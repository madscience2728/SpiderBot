"""
web_routes.py -- new endpoints to support the SpiderBot web dashboard.

Verified against the public repo (github.com/madscience2728/SpiderBot,
master) on 2026-07-13. Reuses spider_brain.robot_client for all robot
communication, per that module's own docstring: "the ONLY place
spider_brain talks to the robot." Handlers are plain sync `def` (not
`async def`) to match the style already used in spider_brain/server.py --
FastAPI runs sync handlers in a threadpool, so robot_client's blocking
`requests` calls are safe here without any extra async plumbing.

Where this goes: drop into spider_brain/web_routes.py (needs to live
inside the spider_brain package so `from spider_brain import robot_client`
resolves) and wire it into spider_brain/server.py -- see the wiring
snippet at the bottom of this file.

Why a proxy instead of calling the relay straight from the browser: the
dashboard is served from the brain (port 9000); the relay lives on the Pi
(port 8000). Proxying through the brain avoids CORS and keeps the browser
talking to a single origin.
"""

import os

import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from spider_brain import robot_client

router = APIRouter(prefix="/manual", tags=["manual-dashboard"])

# Matches VALID_ACTIONS in spider_robot/relay_server.py exactly. Note the
# two turn actions use a space, not an underscore -- confirmed directly
# from relay_server.py's LOCOMOTION_ACTIONS set.
ALLOWED_GAITS = {"stand", "sit", "forward", "backward", "turn left", "turn right"}

DEFAULT_SPEED = 80  # mirrors relay_server.py's DEFAULT_SPEED / robot_client.send_gait default


class GaitRequest(BaseModel):
    action: str
    speed: int = DEFAULT_SPEED


def _relay_http_error(e: requests.exceptions.HTTPError) -> HTTPException:
    """Preserve the relay's actual status code (e.g. 409 busy) instead of
    flattening everything to a generic 502."""
    status = e.response.status_code if e.response is not None else 502
    detail = None
    if e.response is not None:
        try:
            detail = e.response.json().get("detail")
        except ValueError:
            detail = e.response.text
    return HTTPException(status_code=status, detail=detail or str(e))


@router.get("/health")
def manual_health():
    """Proxies the relay's /health ({"status": "ok"}) via robot_client."""
    try:
        return robot_client.get_health()
    except requests.exceptions.HTTPError as e:
        raise _relay_http_error(e)
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Relay unreachable: {e}")


@router.get("/sensors")
def manual_sensors():
    """Proxies the relay's /sensors -- returns
    {"ultrasonic_cm": <float>, "timestamp": <float>}. That's the only
    sensor wired up right now (confirmed in relay_server.py)."""
    try:
        return robot_client.get_sensors()
    except requests.exceptions.HTTPError as e:
        raise _relay_http_error(e)
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Relay unreachable: {e}")


@router.get("/battery")
def manual_battery():
    """Proxies the relay's /battery -- returns {"voltage": <float>, "raw": <int>}.
    Reads Robot HAT V4's ADC channel A4 (dedicated battery-sense pin, wired
    through a 20K/10K divider per SunFounder's own docs); the frontend
    applies the board's own LED-equivalent thresholds (>7.6V healthy,
    7.15-7.6V getting low, <7.15V critical)."""
    try:
        return robot_client.get_battery()
    except requests.exceptions.HTTPError as e:
        raise _relay_http_error(e)
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Relay unreachable: {e}")


@router.get("/camera")
def manual_camera():
    """
    Live camera feed lives OUTSIDE this proxy on purpose: vilib runs its own
    embedded MJPEG server directly on the Pi (port 9000, path /mjpg) once
    Vilib.camera_start() + Vilib.display(web=True) have been called -- see
    patches/spider_robot/relay_server.py. Proxying continuous multipart
    JPEG frames through this FastAPI app would add real complexity for no
    benefit when the browser can just point an <img> straight at the Pi.

    This endpoint only tells the dashboard WHERE to point that <img> tag,
    and asks the relay (via robot_client.get_camera_status(), added
    alongside the camera patch) whether the stream is actually running.
    """
    host = os.environ.get("SPIDER_BOT_HOST")
    if not host:
        raise HTTPException(status_code=502, detail="SPIDER_BOT_HOST not set")

    stream_url = f"http://{host}:9000/mjpg"

    try:
        status = robot_client.get_camera_status()
    except AttributeError:
        # robot_client.py hasn't been patched with get_camera_status() yet
        # (that's a separate step -- see patches/spider_brain/robot_client.py).
        # Degrade gracefully instead of a 500 until that patch is applied.
        return {
            "stream_url": stream_url,
            "available": False,
            "started": False,
            "error": "robot_client.get_camera_status() not present yet -- camera patch not applied",
        }
    except requests.exceptions.RequestException as e:
        # Relay's main API (port 8000) is unreachable -- report that, but
        # still hand back the stream URL in case the caller wants to try it
        # directly anyway.
        return {"stream_url": stream_url, "available": False, "started": False, "error": str(e)}

    return {"stream_url": stream_url, **status}


@router.post("/gait")
def manual_gait(req: GaitRequest):
    if req.action not in ALLOWED_GAITS:
        raise HTTPException(status_code=400, detail=f"Unknown action '{req.action}'")
    try:
        return robot_client.send_gait(req.action, speed=req.speed)
    except requests.exceptions.HTTPError as e:
        # A 409 here means the relay's own busy-lock rejected the command
        # (e.g. an autonomous loop step is mid-execution) -- surfaced as-is
        # so the dashboard can show "robot busy" rather than a generic error.
        raise _relay_http_error(e)
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Relay unreachable: {e}")