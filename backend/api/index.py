"""
ORCA Marine Intelligence — Vercel Serverless Adapter (Backend)

Vercel Python Runtime entry point.
Re-exports the FastAPI `app` from backend/main.py so all routes
(/api/chat, /api/pfz, /api/weather, /api/geofence, /api/tiles, /api/status, /health, /docs)
are served as a single serverless function.

Deployed as a SEPARATE Vercel project with Root Directory = backend/
"""

import sys
import types
from pathlib import Path

# On Vercel, Root Directory = backend/ so /var/task IS backend/.
# The codebase uses `from backend.xxx import ...` in ~100 places,
# but there is no `backend/` folder under /var/task in this layout.
# Fix: alias the `backend` package to the backend dir itself,
# so BOTH `import routers.xxx` and `import backend.routers.xxx` work.
_here = Path(__file__).resolve().parent          # backend/api/
_backend_dir = _here.parent                       # backend/
_project_root = _backend_dir.parent               # repo root (exists locally, not on Vercel)

for p in [str(_backend_dir), str(_project_root)]:
    if p not in sys.path:
        sys.path.insert(0, p)

if "backend" not in sys.modules:
    _pkg = types.ModuleType("backend")
    _pkg.__path__ = [str(_backend_dir)]
    sys.modules["backend"] = _pkg

from main import app  # noqa: E402

# Vercel looks for `app` (ASGI) or `handler`
handler = app
