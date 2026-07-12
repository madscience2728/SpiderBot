"""
PiCrawler thin-body relay server.

Runs ON the Pi. Contains NO decision-making — it only:
  1. Reports sensor state to the PC
  2. Streams/serves camera frames
  3. Executes gait commands sent by the PC
  4. Auto-stops (watchdog) if the PC goes silent

All "brains" (LLM, agent loop, decision logic) live on the PC and
talk to this server over HTTP.
"""

import threading
import time

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from picrawler import Picrawler
from robot_hat import Ultrasonic, Pin

app = FastAPI()
crawler = Picrawler()
ultrasonic = Ultrasonic(Pin("D2"), Pin("D3"))  # confirm trig/echo pins for your wiring

# --- Config ---
DEFAULT_SPEED = 80
WATCHDOG_TIMEOUT = 30.0  # seconds of silence before auto-sit

# Static poses go through crawler.do_step() — single position, no repeat.
POSE_ACTIONS = {"stand", "sit"}
# Locomotion gaits go through crawler.do_action(name, step_count, speed) —
# step_count=1 below means "do this once," not "repeat N times."
LOCOMOTION_ACTIONS = {"forward", "backward", "turn left", "turn right"}

# NOTE: wave / push up / look-left / look-right / look-up / look-down were
# in an earlier version of this list but have NOT been verified against
# picrawler's actual move_list / do_action vs do_step split. Deliberately
# left out for now rather than guessing again — add back in only after
# checking picrawler/examples/9_preset_actions.py on the Pi to confirm
# which function each one actually needs.
VALID_ACTIONS = POSE_ACTIONS | LOCOMOTION_ACTIONS

_last_command_time = time.time()
_lock = threading.Lock()


class GaitCommand(BaseModel):
    action: str
    speed: int = DEFAULT_SPEED


@app.get("/health")
def health():
    return {"status": "ok"}


@app.on_event("shutdown")
def on_shutdown():
    """Whenever the server stops cleanly (Ctrl+C, systemctl stop, etc.),
    leave the robot in a safe seated position rather than wherever it
    last happened to be."""
    try:
        crawler.do_action("sit", DEFAULT_SPEED)
    except Exception:
        pass


@app.get("/sensors")
def sensors():
    # Only reporting hardware that actually exists on stock PiCrawler.
    # Add accelerometer/gyro/light/sound here once that hardware is added.
    distance_cm = ultrasonic.read()
    return {
        "ultrasonic_cm": distance_cm,
        "timestamp": time.time(),
    }


@app.get("/camera/frame")
def camera_frame():
    # Placeholder — wire up vilib or picamera2 to grab a single JPEG frame.
    # from vilib import Vilib
    # frame_bytes = Vilib.take_photo_bytes()
    # return Response(content=frame_bytes, media_type="image/jpeg")
    raise HTTPException(status_code=501, detail="camera not wired up yet")


def _execute_action(action: str, speed: int):
    """The ONLY place allowed to talk to the servos. Holding _lock for the
    full duration of the physical action prevents the watchdog and a
    /gait request from ever fighting over the hardware at the same time."""
    global _last_command_time
    with _lock:
        if action in POSE_ACTIONS:
            crawler.do_step(action, speed)
        else:
            crawler.do_action(action, 1, speed)  # step_count=1: once, not repeated
        _last_command_time = time.time()  # stamped AFTER completion, not before


@app.post("/gait")
def gait(cmd: GaitCommand):
    if cmd.action not in VALID_ACTIONS:
        raise HTTPException(status_code=400, detail=f"unknown action: {cmd.action}")
    _execute_action(cmd.action, cmd.speed)
    return {"executed": cmd.action}


@app.post("/stop")
def stop():
    _execute_action("sit", DEFAULT_SPEED)
    return {"executed": "sit"}


def _watchdog_loop():
    global _last_command_time
    while True:
        time.sleep(0.5)
        with _lock:
            idle = time.time() - _last_command_time
        if idle > WATCHDOG_TIMEOUT:
            _execute_action("sit", DEFAULT_SPEED)


threading.Thread(target=_watchdog_loop, daemon=True).start()
