"""
test_suite.py — reliability stress test for the spider_brain orchestrator.

Two modes:
  sequential — fire /step repeatedly, one at a time, waiting for each
               response. Confirms the robot holds up under sustained,
               well-behaved repeated use (the normal LLM-driving-it case).
  burst      — fire several /step calls at the EXACT same moment
               (concurrently, not waiting for responses). Confirms the
               busy-rejection logic actually works: exactly one call
               should succeed and the rest should get a clean 409,
               never silently queue or corrupt state.

Usage:
    python3 test_suite.py sequential 10
    python3 test_suite.py burst 5

Requires: requests
"""

import sys
import threading
import time

import requests

BRAIN_URL = "http://localhost:9000"


def run_sequential(n: int):
    print(f"Running {n} sequential /step calls...\n")
    ok = 0
    for i in range(n):
        start = time.time()
        try:
            r = requests.post(f"{BRAIN_URL}/step", timeout=20)
            elapsed = time.time() - start
            if r.status_code == 200:
                data = r.json()
                print(f"  [{i+1}/{n}] OK  ({elapsed:.1f}s)  action={data['action']}")
                ok += 1
            else:
                print(f"  [{i+1}/{n}] UNEXPECTED status {r.status_code}: {r.text}")
        except requests.exceptions.RequestException as e:
            print(f"  [{i+1}/{n}] FAILED: {e}")

    print(f"\nSequential test complete: {ok}/{n} succeeded cleanly.")


def run_burst(n: int):
    print(f"Firing {n} concurrent /step calls at the same instant...\n")
    results = [None] * n

    def worker(i):
        try:
            r = requests.post(f"{BRAIN_URL}/step", timeout=20)
            results[i] = r.status_code
        except requests.exceptions.RequestException as e:
            results[i] = f"error: {e}"

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ok_count = results.count(200)
    busy_count = results.count(409)
    other = n - ok_count - busy_count

    print(f"Results: {results}")
    print(f"  200 OK: {ok_count}   409 busy: {busy_count}   other: {other}\n")

    if ok_count == 1 and busy_count == n - 1:
        print("PASS — exactly one call executed, the rest were cleanly rejected.")
    else:
        print("UNEXPECTED — check relay/orchestrator locking logic.")


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("sequential", "burst"):
        print("Usage: python3 test_suite.py [sequential|burst] <count>")
        sys.exit(1)

    mode = sys.argv[1]
    count = int(sys.argv[2])

    if mode == "sequential":
        run_sequential(count)
    else:
        run_burst(count)


if __name__ == "__main__":
    main()
