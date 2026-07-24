"""
PiCrawler thin-body relay server.

Runs ON the Pi. Contains NO decision-making -- it only:
1. Reports sensor state to the PC
2. Streams/serves camera frames
3. Executes gait commands sent by the PC
4. Auto-stops (watchdog) if the PC goes silent

All "brains" (LLM, agent loop, decision logic) live on the PC and
talk to this server over HTTP.

CAMERA (confirmed working on the real Pi, 2026-07-13): vilib runs its own
embedded MJPEG server directly on this Pi at http://<this-pi>:9000/mjpg
(started below, in the FastAPI startup hook) -- it does NOT go through this
FastAPI app or port 8000. This endpoint set only starts that stream and
reports whether it's running; the actual video bytes never touch this file.

This Pi is on Debian 13 (trixie), which only works with vilib's `picamera2`
branch (github.com/sunfounder/vilib, branch picamera2) -- the `master`
branch's legacy `picamera` library does not work on this camera stack.
Installed via that branch's own install.py, which handles the apt/pip
dependency list and the externally-managed-environment restriction itself.

Import is wrapped in try/except so a missing/broken vilib install disables
the camera feature without taking down gait control, sensors, or anything
else this relay does.

CAMERA TUNING: the raw feed came out dark and orange-tinted under normal
indoor lighting, so a couple of Picamera2 controls are set right after
camera_start() -- see the comment in start_camera() below for specifics
and what to adjust if it still doesn't look right.

BATTERY: reads Robot HAT V4's ADC channel A4, which the board wires to the
battery through a 20K/10K voltage divider (confirmed against SunFounder's
official Robot HAT V4 docs, not guessed). See /battery below for the exact
formula and the LED-equivalent thresholds it's based on.
"""

import threading
import time

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from picrawler import Picrawler
from robot_hat import Ultrasonic, Pin, ADC

try:
    from vilib import Vilib
    _vilib_available = True
except Exception as e:  # broad on purpose -- vilib's own imports can fail
    # in several ways (missing model files under /opt/vilib, missing
    # picamera2, etc.), and none of those should take down the relay.
    print(f"[relay] vilib not available, camera feed disabled: {e}")
    Vilib = None
    _vilib_available = False

app = FastAPI()
crawler = Picrawler()
ultrasonic = Ultrasonic(Pin("D2"), Pin("D3")) # confirm trig/echo pins for your wiring
battery_adc = ADC("A4")  # Robot HAT V4's dedicated battery-sense channel

# --- Config ---
DEFAULT_SPEED = 80
WATCHDOG_TIMEOUT = 30.0 # seconds of silence before auto-sit

# Robot HAT V4's ADC->voltage conversion, per SunFounder's own docs:
# Va4 = raw / 4095.0 * 3.3 (ADC reference voltage)
# Vbat = Va4 * 3 (the board's 20K/10K divider steps battery voltage down by 3x)
BATTERY_ADC_TO_VOLTS = 3.3 / 4095.0 * 3

# Static poses go through crawler.do_step() -- single position, no repeat.
POSE_ACTIONS = {"stand", "sit"}
# Locomotion gaits go through crawler.do_action(name, step_count, speed) --
# step_count=1 below means "do this once," not "repeat N times."
LOCOMOTION_ACTIONS = {"forward", "backward", "turn left", "turn right"}

VALID_ACTIONS = POSE_ACTIONS | LOCOMOTION_ACTIONS

_last_command_time = time.time()
_lock = threading.Lock()
_camera_started = False

class GaitCommand(BaseModel):
    action: str
    speed: int = DEFAULT_SPEED

@app.get("/health")
def health():
    return {"status": "ok"}

@app.on_event("startup")
def start_camera():
    global _camera_started
    if not _vilib_available:
        return
    try:
        Vilib.camera_start(vflip=False, hflip=False)

        Vilib.set_controls({
            "ExposureValue": 1.5,
            "AwbMode": 4,
        })

        Vilib.display(local=False, web=True)
        _camera_started = True
        print("[relay] camera stream started -- http://<this-pi>:9000/mjpg")
    except Exception as e:
        print(f"[relay] camera failed to start: {e}")

@app.on_event("shutdown")
def on_shutdown():
    try:
        crawler.do_action("sit", DEFAULT_SPEED)
    except Exception:
        pass
    if _vilib_available and _camera_started:
        try:
            Vilib.camera_close()
        except Exception:
            pass

@app.get("/sensors")
def sensors():
    distance_cm = ultrasonic.read()
    return {
        "ultrasonic_cm": distance_cm,
        "timestamp": time.time(),
    }

@app.get("/battery")
def battery():
    """Reads battery voltage via ADC channel A4 (Robot HAT V4's dedicated
    battery-sense pin, wired through a 20K/10K divider -- see
    BATTERY_ADC_TO_VOLTS above). For reference, the board's own LED
    indicator uses these same voltage bands: both LEDs on above 7.6V
    (healthy), one LED on 7.15-7.6V (getting low), both off below 7.15V
    (critical) -- the dashboard's battery chip mirrors these."""
    raw = battery_adc.read()
    voltage = raw * BATTERY_ADC_TO_VOLTS
    return {"voltage": voltage, "raw": raw}

@app.get("/camera/status")
def camera_status():
    return {
        "available": _vilib_available,
        "started": _camera_started,
    }

def _try_execute_action(action: str, speed: int) -> bool:
    global _last_command_time
    acquired = _lock.acquire(blocking=False)
    if not acquired:
        print(f"[relay] BUSY -- rejected action={action!r}")
        return False
    try:
        print(f"[relay] Executing action={action!r} speed={speed}")
        if action in POSE_ACTIONS:
            crawler.do_step(action, speed)
        else:
            crawler.do_action(action, 1, speed)
        _last_command_time = time.time()
        print(f"[relay] Completed action={action!r}")
        return True
    finally:
        _lock.release()

def _force_safe_sit():
    global _last_command_time
    acquired = _lock.acquire(timeout=5)
    if not acquired:
        return False
    try:
        crawler.do_step("sit", DEFAULT_SPEED)
        _last_command_time = time.time()
        return True
    finally:
        _lock.release()

@app.post("/gait")
def gait(cmd: GaitCommand):
    if cmd.action not in VALID_ACTIONS:
        raise HTTPException(status_code=400, detail=f"unknown action: {cmd.action}")
    if not _try_execute_action(cmd.action, cmd.speed):
        raise HTTPException(status_code=409, detail="robot busy executing a previous action")
    return {"executed": cmd.action}

@app.post("/stop")
def stop():
    if not _force_safe_sit():
        raise HTTPException(status_code=503, detail="robot unresponsive, could not acquire control")
    return {"executed": "sit"}

def _watchdog_loop():
    global _last_command_time
    while True:
        time.sleep(0.5)
        with _lock:
            idle = time.time() - _last_command_time
            if idle > WATCHDOG_TIMEOUT:
                print(f"[relay] WATCHDOG: idle {idle:.1f}s > {WATCHDOG_TIMEOUT}s, forcing safe sit")
                _force_safe_sit()

threading.Thread(target=_watchdog_loop, daemon=True).start()