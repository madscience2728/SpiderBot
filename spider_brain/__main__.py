"""
Entrypoint for `python3 -m spider_brain`.
Boots the FastAPI orchestrator on 0.0.0.0:9000.

Port 9000 is deliberately different from the robot's 8000, so if you ever
run both on the same machine (e.g. testing) they don't collide.
"""

import uvicorn

from spider_brain.server import app

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9000)
