"""
main.py — single entry point for local dev.

Before this: deploy the Pi separately, then start spider_brain, then
separately serve/open the frontend. That last step was never actually
necessary — spider_brain/server.py already mounts the dashboard at /ui
on the same FastAPI app (see app.mount("/ui", ...)). So "start the
server" and "start the frontend" have always been the same step; this
script just makes that obvious and adds the couple of things that were
still manual.

Usage:
    python3 main.py                # start the brain + open the dashboard
    python3 main.py --deploy       # also push spider_robot/ to the Pi first
    python3 main.py --no-browser   # don't auto-open a browser tab

What this does NOT do:
    - Does not touch the Pi's systemd service unless --deploy is passed.
      spider-robot.service is expected to already be running persistently
      on the Pi (that's the whole point of the systemd setup).
    - Does not start the llama.cpp Docker container. That's a GPU-heavy,
      host-specific process not worth babysitting from here — this script
      just health-checks it and prints the exact `docker run` command
      (same one llm_adapter.py already builds) if it's not up.
"""

import argparse
import os
import sys
import threading
import time
import webbrowser

import uvicorn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BRAIN_HOST = "0.0.0.0"
BRAIN_PORT = 9000
DASHBOARD_URL = f"http://localhost:{BRAIN_PORT}/ui/"


def _run_deploy():
    print("== Deploying spider_robot/ to the Pi ==")
    from scripts.deploy import main as deploy_main
    deploy_main()
    print()


def _check_robot():
    from spider_brain import robot_client
    try:
        robot_client.get_health()
        print("[main] Robot relay: reachable")
    except Exception as e:
        print(
            f"[main] WARNING: robot relay not reachable ({e}). "
            "The dashboard will still load; robot/sensor calls will fail "
            "until the relay is up and SPIDER_BOT_HOST is set correctly."
        )


def _check_llm():
    from spider_brain.llm_adapter import LLMAdapter
    adapter = LLMAdapter()
    if adapter.health_check():
        print("[main] LLM server: reachable")
    else:
        print(adapter._not_running_message())
        print(
            "[main] Continuing without it — manual dashboard controls and "
            "/step (mock brain) work fine; /llm_step will fail until the "
            "LLM container is running.\n"
        )


def _open_browser_later(delay: float = 1.5):
    def _open():
        time.sleep(delay)
        webbrowser.open(DASHBOARD_URL)

    threading.Thread(target=_open, daemon=True).start()


def main():
    parser = argparse.ArgumentParser(description="Start the SpiderBot brain + dashboard")
    parser.add_argument(
        "--deploy",
        action="store_true",
        help="push spider_robot/ to the Pi and restart its service before starting",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="don't auto-open the dashboard in a browser",
    )
    args = parser.parse_args()

    if args.deploy:
        _run_deploy()

    _check_robot()
    _check_llm()

    if not args.no_browser:
        _open_browser_later()

    print(f"[main] Starting spider_brain on http://{BRAIN_HOST}:{BRAIN_PORT}")
    print(f"[main] Dashboard: {DASHBOARD_URL}\n")

    from spider_brain.server import app

    uvicorn.run(app, host=BRAIN_HOST, port=BRAIN_PORT)


if __name__ == "__main__":
    main()
