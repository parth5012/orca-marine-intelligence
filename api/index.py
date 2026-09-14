"""
ORCA Marine Intelligence — Vercel Serverless Entry Point (Backend)

Deployed as a Vercel project with Root Directory = repository root.
`backend/`, `scripts/` and `data/` are real directories under /var/task,
so all absolute imports (`backend.*`, `scripts.*`) and relative data paths
resolve exactly as they do locally and in Docker. No path shims needed.
"""

from backend.main import app

# Vercel Python runtime looks for `app` (ASGI) or `handler`
handler = app
