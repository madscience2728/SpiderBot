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

SHARED I2C BUS (found 2026-07-24): the ultrasonic sensor, battery ADC, and
all gait servos sit on the same physical I2C bus (robot_hat's Robot HAT V4
address 0x14). The dashboard polls /sensors and /battery continuously in
the background, independent of whatever gait command is in flight -- with
no coordination, that polling can read the bus at the exact same instant
a gait command is writing to it. Two threads racing on one I2C bus without
mutual exclusion is a plausible cause of intermittent stalls that don't
correlate with any specific gait or with battery level (both of which were
ruled out first). Fix: /sensors and /battery now take the same _lock as
gait commands, with a short timeout so a busy bus just means a skipped
poll rather than a blocked request.
"""

import threading
import time

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from picrawler import Picrawler
from robot_hat import Ultrasonic, Pin, ADC

from . import picrawler_fixes
picrawler_fixes.apply()  # fixes turn_right's TURN_X1/TURN_Y1 coordinate typo -- see picrawler_fixes.py

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
HARDWARE_TIMEOUT = 10.0 # seconds to wait for a hardware call before assuming it's stuck

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
# Set when a hardware call doesn't return within HARDWARE_TIMEOUT -- almost
# always means a stuck I2C transaction at the kernel/smbus level (see
# _run_hardware_call below). Once set, we stop trusting the robot's state
# and refuse further commands until the process is restarted -- we cannot
# actually kill or recover a blocked I2C syscall from here.
_hardware_fault = False

class GaitCommand(BaseModel):
    action: str
    speed: int = DEFAULT_SPEED

@app.get("/health")
def health():
    if _hardware_fault:
        return {"status": "hardware_fault", "detail": "restart spider-robot service required"}
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
    # Same physical I2C bus as the gait servos -- must not read concurrently
    # with a gait command mid-flight (see the module docstring note on the
    # shared-bus race, 2026-07-24). Short acquire timeout: this is normally
    # a fast, single transaction, so if the bus is genuinely busy with a
    # gait command it's better to skip this poll than block the request.
    global _hardware_fault
    if _hardware_fault:
        raise HTTPException(status_code=503, detail="hardware fault -- restart required")
    acquired = _lock.acquire(timeout=1.0)
    if not acquired:
        raise HTTPException(status_code=503, detail="robot busy, sensor read skipped this cycle")
    try:
        # Guarded with a timeout, NOT called directly -- an earlier version
        # called ultrasonic.read() unprotected here, and when it hung (no
        # echo returned, or an I2C stall) it held _lock forever, permanently
        # starving every future /sensors and /battery request with "busy"
        # even though nothing was actually executing. See _run_with_timeout.
        ok, distance_cm = _run_with_timeout(ultrasonic.read, SENSOR_TIMEOUT)
        if not ok:
            print(f"[relay] HARDWARE FAULT -- ultrasonic.read() stalled past {SENSOR_TIMEOUT}s")
            _hardware_fault = True
            raise HTTPException(status_code=503, detail="ultrasonic read stalled -- restart required")
    finally:
        _lock.release()
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
    (critical) -- the dashboard's battery chip mirrors these.

    Same shared-I2C-bus lock and stall guard as /sensors above, and for
    the same reason -- see that endpoint's comments."""
    global _hardware_fault
    if _hardware_fault:
        raise HTTPException(status_code=503, detail="hardware fault -- restart required")
    acquired = _lock.acquire(timeout=1.0)
    if not acquired:
        raise HTTPException(status_code=503, detail="robot busy, battery read skipped this cycle")
    try:
        ok, raw = _run_with_timeout(battery_adc.read, SENSOR_TIMEOUT)
        if not ok:
            print(f"[relay] HARDWARE FAULT -- battery_adc.read() stalled past {SENSOR_TIMEOUT}s")
            _hardware_fault = True
            raise HTTPException(status_code=503, detail="battery read stalled -- restart required")
    finally:
        _lock.release()
    voltage = raw * BATTERY_ADC_TO_VOLTS
    return {"voltage": voltage, "raw": raw}

@app.get("/camera/status")
def camera_status():
    return {
        "available": _vilib_available,
        "started": _camera_started,
    }

@app.get("/camera/frame")
def camera_frame():
    """Single JPEG frame, base64-encoded, for the brain's vision calls --
    separate from the always-on MJPEG stream at :9000/mjpg (that's for a
    human watching the dashboard; this is for the LLM to see one frame
    per decision cycle).

    Vilib.img is the same numpy array (BGR, from picam2.capture_array())
    that vilib's own take_photo() writes with cv2.imwrite() -- confirmed
    against vilib's source, not guessed. Before the camera loop has run
    at least once, Vilib.img is still its class-level placeholder
    (Manager().list(range(1)), i.e. not a real frame), so we check
    _camera_started and the array shape before trusting it.

    Camera is on the CSI ribbon, a separate physical bus from the I2C
    servos/sensors -- no need for _lock here.
    """
    if not _vilib_available or not _camera_started:
        raise HTTPException(status_code=503, detail="camera not available/started")

    import base64
    import cv2

    frame = Vilib.img
    if frame is None or not hasattr(frame, "shape"):
        raise HTTPException(status_code=503, detail="no camera frame available yet")

    ok, buf = cv2.imencode(".jpg", frame)
    if not ok:
        raise HTTPException(status_code=500, detail="failed to encode frame as JPEG")

    return {
        "image_base64": base64.b64encode(buf).decode("ascii"),
        "format": "jpeg",
        "timestamp": time.time(),
    }

SENSOR_TIMEOUT = 3.0 # ultrasonic/ADC reads should be near-instant; this is generous

def _run_with_timeout(func, timeout: float):
    """Run func() in a dedicated thread and wait up to `timeout` seconds.

    Returns (True, result) on success, (False, None) if func() didn't
    return in time. We can't kill a thread blocked inside a C-level I2C
    syscall -- Python has no safe way to do that -- so a timed-out call
    means that thread may still be running (and could still eventually
    touch the bus later, unsupervised). What this DOES buy us: the caller
    stops waiting and can free _lock instead of holding it forever, which
    is what actually happened on 2026-07-24 when a bare, unguarded
    ultrasonic.read() hung and starved every future /sensors and /battery
    request with a permanent "busy," even though nothing was actually
    executing.
    """
    result = {}

    def _call():
        result["value"] = func()
        result["done"] = True

    t = threading.Thread(target=_call, daemon=True)
    t.start()
    t.join(timeout=timeout)
    if t.is_alive():
        return False, None
    return True, result.get("value")


def _run_hardware_call(action: str, speed: float) -> bool:
    """Run the actual (potentially blocking) picrawler/robot_hat gait call
    with a hard timeout -- see _run_with_timeout above for the mechanism.

    Why a timeout is needed at all: crawler.do_step()/do_action() are
    themselves bounded pure-Python loops (see robot_hat.Robot.servo_move
    -- fixed step count, small sleeps). What ISN'T bounded is the I2C
    write underneath each servo update: robot_hat's I2C retry wrapper (5
    retries, no backoff) sits on top of a raw smbus2/kernel call that can
    itself block for a long time if the bus is in a bad state. A single
    stuck transaction during a gait with dozens of servo writes (e.g.
    turn right's 7 sub-steps) can easily add up past any reasonable
    request timeout.

    If it does time out, we mark a hardware fault and stop trusting the
    robot's state entirely -- see _hardware_fault.
    """
    global _last_command_time, _hardware_fault

    def _do():
        if action in POSE_ACTIONS:
            crawler.do_step(action, speed)
        else:
            crawler.do_action(action, 1, speed)

    ok, _ = _run_with_timeout(_do, HARDWARE_TIMEOUT)
    if not ok:
        print(
            f"[relay] HARDWARE FAULT -- action={action!r} did not return within "
            f"{HARDWARE_TIMEOUT}s. Likely a stuck I2C transaction. Refusing "
            f"further commands until restart."
        )
        _hardware_fault = True
        return False

    _last_command_time = time.time()
    return True


def _try_execute_action(action: str, speed: int) -> str:
    """Returns 'ok', 'busy', or 'fault'."""
    if _hardware_fault:
        return "fault"
    acquired = _lock.acquire(blocking=False)
    if not acquired:
        print(f"[relay] BUSY -- rejected action={action!r}")
        return "busy"
    try:
        print(f"[relay] Executing action={action!r} speed={speed}")
        if not _run_hardware_call(action, speed):
            return "fault"
        print(f"[relay] Completed action={action!r}")
        return "ok"
    finally:
        _lock.release()

def _force_safe_sit() -> str:
    """Returns 'ok', 'busy', or 'fault'."""
    if _hardware_fault:
        return "fault"
    acquired = _lock.acquire(timeout=5)
    if not acquired:
        return "busy"
    try:
        if not _run_hardware_call("sit", DEFAULT_SPEED):
            return "fault"
        return "ok"
    finally:
        _lock.release()

@app.post("/gait")
def gait(cmd: GaitCommand):
    if cmd.action not in VALID_ACTIONS:
        raise HTTPException(status_code=400, detail=f"unknown action: {cmd.action}")
    result = _try_execute_action(cmd.action, cmd.speed)
    if result == "busy":
        raise HTTPException(status_code=409, detail="robot busy executing a previous action")
    if result == "fault":
        raise HTTPException(
            status_code=503,
            detail=(
                f"hardware fault: a previous action didn't respond within "
                f"{HARDWARE_TIMEOUT}s (likely a stuck I2C bus). The relay "
                f"service needs a restart (sudo systemctl restart spider-robot) "
                f"and the robot should be physically checked before resuming."
            ),
        )
    return {"executed": cmd.action}

@app.post("/stop")
def stop():
    result = _force_safe_sit()
    if result == "busy":
        raise HTTPException(status_code=503, detail="robot unresponsive, could not acquire control")
    if result == "fault":
        raise HTTPException(
            status_code=503,
            detail=(
                f"hardware fault: sit didn't respond within {HARDWARE_TIMEOUT}s "
                f"(likely a stuck I2C bus). Restart the relay service and check "
                f"the robot physically."
            ),
        )
    return {"executed": "sit"}

def _watchdog_loop():
    while True:
        time.sleep(0.5)
        # NOTE: deliberately not holding _lock here. _force_safe_sit()
        # acquires _lock itself; since threading.Lock is not reentrant,
        # holding it here too would make that inner acquire block for its
        # full 5s timeout on every idle cycle, starving real /gait calls
        # with false 409s AND silently defeating the auto-sit itself.
        # Reading _last_command_time without the lock is fine -- it's a
        # single float read/write, atomic in CPython, and worst case we
        # act on a value that's a few hundred ms stale.
        if _hardware_fault:
            continue  # already known broken -- retrying won't help, needs a restart
        idle = time.time() - _last_command_time
        if idle > WATCHDOG_TIMEOUT:
            print(f"[relay] WATCHDOG: idle {idle:.1f}s > {WATCHDOG_TIMEOUT}s, forcing safe sit")
            _force_safe_sit()

threading.Thread(target=_watchdog_loop, daemon=True).start()