"""
Geofence Check Router

Owner: M-D (Platform) — moved from M-B to balance load (Platform owns API surface)
Module: backend/routers/geofence.py

Checks if a given point or route falls within restricted zones:
    - EEZ (Exclusive Economic Zone) boundaries
    - MPA (Marine Protected Area) zones
    - Active cyclone danger zones

Endpoints:
    POST /api/geofence/check — Check if a point is in a restricted zone
    POST /api/geofence/route — Check if a route crosses restricted zones

Dependencies:
    - PostGIS for ST_Contains spatial queries
    - Pre-loaded boundary data (see backend/ingest/boundaries.py)

TODO:
    - [ ] Implement POST /api/geofence/check with lat/lon
    - [ ] Implement POST /api/geofence/route with GeoJSON LineString
    - [ ] Add ST_Contains and ST_Intersects queries
    - [ ] Return detailed zone information on match
"""

from fastapi import APIRouter

router = APIRouter(tags=["geofence"])


@router.post("/geofence/check")
async def check_geofence():
    """Check if a point falls within any restricted zone."""
    # TODO: Implement geofence point check
    raise NotImplementedError("Geofence check not yet implemented")


@router.post("/geofence/route")
async def check_route_geofence():
    """Check if a route crosses any restricted zones."""
    # TODO: Implement geofence route check
    raise NotImplementedError("Geofence route check not yet implemented")
