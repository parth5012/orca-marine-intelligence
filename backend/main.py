"""
ORCA Agentic Marine Intelligence — FastAPI Application Entry Point

Owner: M6 (Platform)
Module: backend/main.py

This is the main FastAPI application that serves the ORCA backend API.
It configures CORS middleware, mounts all routers, and starts the server.

Routers:
    - /api/pfz      → PFZ data proxy (pfz.py)
    - /api/tiles     → Vector tile server (tiles.py)
    - /api/chat      → Chat endpoint for ORCA brain (chat.py)
    - /api/weather   → Weather data endpoint (weather.py)
    - /api/geofence  → Geofence check endpoint (geofence.py)

Usage:
    uvicorn backend.main:app --reload --port 8000

TODO:
    - [ ] Configure CORS with ALLOWED_ORIGINS from .env
    - [ ] Mount all routers
    - [ ] Add health check endpoint GET /health
    - [ ] Add startup event to verify PostGIS and Redis connections
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# TODO: Import routers
# from backend.routers import pfz, tiles, chat, weather, geofence

app = FastAPI(
    title="ORCA Agentic Marine Intelligence",
    description="Multi-agent marine advisory system for Indian fishermen (SIH26176)",
    version="0.1.0",
)

# TODO: Configure CORS from environment
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(","),
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# TODO: Include routers
# app.include_router(pfz.router, prefix="/api")
# app.include_router(tiles.router, prefix="/api")
# app.include_router(chat.router, prefix="/api")
# app.include_router(weather.router, prefix="/api")
# app.include_router(geofence.router, prefix="/api")


@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring and deployment verification."""
    # TODO: Check PostGIS and Redis connectivity
    return {"status": "ok", "service": "orca-marine-intelligence"}
