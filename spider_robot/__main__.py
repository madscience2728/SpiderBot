"""
Entrypoint for `python3 -m spider_robot`.
Boots the FastAPI relay server on 0.0.0.0:8000.
"""

import uvicorn

from spider_robot.relay_server import app

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
