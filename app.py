"""
ORCA Marine Intelligence — Vercel framework entrypoint.

Vercel auto-discovers FastAPI apps in root-level app.py / index.py /
server.py / main.py. This module re-exports the application instance
built in backend/main.py (routers, lifespan, middleware all live there),
so local, Docker and Vercel all serve the same object.
"""

from backend.main import app

__all__ = ["app"]
