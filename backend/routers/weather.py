"""
Weather Data Router

Owner: M2 (Data)
Module: backend/routers/weather.py

Serves weather data for marine advisory: wind speed, wave height,
tide information, and cyclone alerts from IMD.

Endpoints:
    GET /api/weather/current — Current weather at a point
    GET /api/weather/cyclone — Active cyclone warnings

Dependencies:
    - IMD API (real data, Week 2+)
    - Redis for caching (30min TTL)

TODO:
    - [ ] Implement GET /api/weather/current with lat/lon params
    - [ ] Implement GET /api/weather/cyclone for active warnings
    - [ ] Add IMD API integration (Week 2+)
    - [ ] Return mock data for MVP development
"""

from fastapi import APIRouter

router = APIRouter(tags=["weather"])


@router.get("/weather/current")
async def get_current_weather(lat: float, lon: float):
    """Return current weather conditions at a marine point."""
    # TODO: Implement weather data retrieval
    raise NotImplementedError("Weather endpoint not yet implemented")


@router.get("/weather/cyclone")
async def get_cyclone_warnings():
    """Return active cyclone warnings for Indian coast."""
    # TODO: Implement cyclone warning retrieval
    raise NotImplementedError("Cyclone endpoint not yet implemented")
