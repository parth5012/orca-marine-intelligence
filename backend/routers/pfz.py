"""
PFZ Data Proxy Router

Owner: M2 (Data)
Module: backend/routers/pfz.py

Serves the latest PFZ GeoJSON data to the frontend map.
Provides endpoints for today's PFZ snapshot and historical data.

Endpoints:
    GET /api/pfz/today  — Current day's PFZ GeoJSON FeatureCollection
    GET /api/pfz/history — Historical PFZ data (last N days)

Dependencies:
    - PostGIS for spatial queries
    - Redis for caching (6h TTL)

TODO:
    - [ ] Implement GET /api/pfz/today with Redis cache layer
    - [ ] Implement GET /api/pfz/history with pagination
    - [ ] Add bounding box filter query parameter
    - [ ] Return proper GeoJSON content-type headers
"""

from fastapi import APIRouter

router = APIRouter(tags=["pfz"])


@router.get("/pfz/today")
async def get_today_pfz():
    """Return today's PFZ GeoJSON FeatureCollection."""
    # TODO: Implement PFZ data retrieval
    raise NotImplementedError("PFZ endpoint not yet implemented")


@router.get("/pfz/history")
async def get_pfz_history(days: int = 7):
    """Return historical PFZ data for the last N days."""
    # TODO: Implement historical PFZ retrieval
    raise NotImplementedError("PFZ history endpoint not yet implemented")
