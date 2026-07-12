"""
PC-side test client for the spider robot relay server.

Not part of the agent stack — just a manual sanity-check tool to run
right after setup, before wiring up the real LLM/agent loop.

Usage:
    python3 pc_test_client.py <pi-ip>

Requires: requests   (pip install requests)
"""

import sys
import time

import requests

DEFAULT_PORT = 8000


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 pc_test_client.py <pi-ip>")
        sys.exit(1)

    pi_ip = sys.argv[1]
    base_url = f"http://{pi_ip}:{DEFAULT_PORT}"

    print(f"Testing relay at {base_url}\n")

    # 1. Health check
    print("1. Health check...")
    r = requests.get(f"{base_url}/health", timeout=5)
    r.raise_for_status()
    print(f"   OK: {r.json()}\n")

    # 2. Sensors
    print("2. Reading sensors...")
    r = requests.get(f"{base_url}/sensors", timeout=5)
    r.raise_for_status()
    print(f"   {r.json()}\n")

    # 3. Interactive gait menu
    actions = [
        "stand", "sit", "forward", "backward",
        "turn left", "turn right", "wave", "push up",
    ]
    print("3. Interactive gait test.")
    print("   Available actions:", ", ".join(actions))
    print("   Type an action name to send it, 'sensors' to re-read, or 'q' to quit.\n")

    while True:
        cmd = input("> ").strip().lower()
        if cmd == "q":
            break
        if cmd == "sensors":
            r = requests.get(f"{base_url}/sensors", timeout=5)
            print(r.json())
            continue
        if cmd not in actions:
            print(f"   Unknown action. Choose from: {', '.join(actions)}")
            continue
        r = requests.post(f"{base_url}/gait", json={"action": cmd}, timeout=15)
        if r.status_code == 200:
            print(f"   Executed: {r.json()}")
        else:
            print(f"   Error {r.status_code}: {r.text}")
        time.sleep(0.2)

    # Always leave the robot sitting when the test ends
    print("\nSending final stop/sit command...")
    requests.post(f"{base_url}/stop", timeout=5)
    print("Done.")


if __name__ == "__main__":
    main()
