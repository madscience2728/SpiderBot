"""
robot_client.py — the ONLY place spider_brain talks to the robot.

Reuses the same SPIDER_BOT_HOST env var you already set up for
pc_test_client.py / deploy.py, so no new config needed.
"""

import os

import requests

ROBOT_PORT = int(os.environ.get("SPIDER_BOT_PORT", "8000"))


def _base_url() -> str:
    host = os.environ.get("SPIDER_BOT_HOST")
    if not host:
        raise RuntimeError(
            "SPIDER_BOT_HOST environment variable is not set. "
            "Set it the same way you did for pc_test_client.py."
        )
    return f"http://{host}:{ROBOT_PORT}"


def get_health(timeout: int = 5) -> dict:
    r = requests.get(f"{_base_url()}/health", timeout=timeout)
    r.raise_for_status()
    return r.json()


def get_sensors(timeout: int = 5) -> dict:
    r = requests.get(f"{_base_url()}/sensors", timeout=timeout)
    r.raise_for_status()
    return r.json()


def send_gait(action: str, speed: int = 80, timeout: int = 15) -> dict:
    r = requests.post(
        f"{_base_url()}/gait", json={"action": action, "speed": speed}, timeout=timeout
    )
    r.raise_for_status()
    return r.json()


def send_stop(timeout: int = 15) -> dict:
    r = requests.post(f"{_base_url()}/stop", timeout=timeout)
    r.raise_for_status()
    return r.json()
