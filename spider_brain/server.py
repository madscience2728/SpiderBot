"""
server.py — the PC-side orchestrator API.

Exposes one core operation: /step, which runs a single
observe (sensors) -> decide (brain) -> act (gait command) cycle.

Deliberately step-by-step rather than a continuous autonomous loop for now —
easier to test, and safer while brain.py is still a mock / not yet an LLM
you fully trust to run unsupervised.
"""

from typing import List
import threading

from fastapi import FastAPI, HTTPException

from spider_brain import robot_client
from spider_brain.brain import decide_next_action
from spider_brain.llm_brain import decide_and_act

app = FastAPI()

from fastapi.staticfiles import StaticFiles
from spider_brain.web_routes import router as web_router

app.include_router(web_router)
app.mount("/ui", StaticFiles(directory="frontend", html=True), name="ui")

_history: List[str] = []
_last_sensors: dict = {}
_step_lock = threading.Lock()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/status")
def status():
    return {
        "last_sensors": _last_sensors,
        "history": _history[-10:],
    }


@app.post("/step")
def step():
    """One full cycle: pull sensors from the robot, ask the brain for the
    next action, send it, record it. Rejects overlapping calls outright
    (409) rather than letting two steps race to hit the robot at once."""
    global _last_sensors

    if not _step_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="a step is already in progress")

    try:
        try:
            sensors = robot_client.get_sensors()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"couldn't reach robot sensors: {e}")

        _last_sensors = sensors
        action = decide_next_action(sensors, _history)

        try:
            result = robot_client.send_gait(action)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"couldn't send gait to robot: {e}")

        _history.append(action)
        return {"sensors": sensors, "action": action, "robot_response": result}
    finally:
        _step_lock.release()


@app.post("/llm_step")
def llm_step():
    """One real LLM-driven cycle: observe -> decide (via LLM tool call)
    -> act. Same busy-rejection as /step — never overlaps a robot command."""
    global _last_sensors

    if not _step_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="a step is already in progress")

    try:
        try:
            sensors = robot_client.get_sensors()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"couldn't reach robot sensors: {e}")

        _last_sensors = sensors

        try:
            result = decide_and_act(sensors)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"LLM/tool execution failed: {e}")

        if result.get("tool_chosen"):
            _history.append(result["tool_chosen"])
        return {"sensors": sensors, **result}
    finally:
        _step_lock.release()


@app.post("/stop")
def stop():
    try:
        result = robot_client.send_stop()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"couldn't stop robot: {e}")
    return result
