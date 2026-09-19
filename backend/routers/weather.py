"""
Weather Data Router

Owner: M-C (Backend API & Platform) — GET /api/weather
Module: backend/routers/weather.py

Serves live weather data for marine advisory: wind speed, wave height,
tide information, barometric pressure, ocean currents, and cyclone alerts.
Powered by OpenWeatherMap API, Open-Meteo Marine API, and IMD cyclone checks,
with Redis 30-minute caching.

Endpoints:
  GET /api/weather/current   Current weather at point (lat, lon)
  GET /api/weather/cyclone   Active cyclone warnings and pressure anomalies
"""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

try:
    from backend.db.redis import get_json, set_json
    from backend.ingest.live_fetchers import (
        fetch_live_weather,
        fetch_open_meteo_marine,
        fetch_imd_cyclone_alerts,
    )
except ImportError:
    from db.redis import get_json, set_json  # type: ignore
    from ingest.live_fetchers import (  # type: ignore
        fetch_live_weather,
        fetch_open_meteo_marine,
        fetch_imd_cyclone_alerts,
    )

logger = logging.getLogger("orca.weather")

router = APIRouter(tags=["weather"])


class CurrentWeatherResponse(BaseModel):
    lat: float
    lon: float
    temperature_c: float
    humidity_pct: float
    pressure_hpa: float
    wind_speed_kt: float
    wind_gust_kt: float
    wind_direction: str
    wave_height_m: float
    wave_period_s: float
    current_speed_kt: float
    status: str
    source: str
    cached: bool
    # Backward compatibility / optional fields
    wind_speed_kts: Optional[float] = None
    swell_wave_height_m: Optional[float] = None
    swell_wave_period_s: Optional[float] = None
    # Tide (T2 #117): nulls + unknown when data unavailable
    tide_range_m: Optional[float] = None
    tidal_state: Optional[str] = None
    next_high_tide_utc: Optional[str] = None
    next_low_tide_utc: Optional[str] = None


class CycloneWarningResponse(BaseModel):
    alert_level: str
    nearest_cyclone_distance_km: Optional[float] = None
    max_wind_speed_kt: Optional[float] = None
    description: str
    regions_affected: List[str] = Field(default_factory=list)
    last_updated: str
    active: Optional[bool] = None
    nearest_cyclone_km: Optional[float] = None


@router.get("/weather/current", response_model=CurrentWeatherResponse)
async def get_current_weather(
    lat: float = Query(..., description="Latitude in degrees (-90 to 90)"),
    lon: float = Query(..., description="Longitude in degrees (-180 to 180)"),
):
    """
    Return current live weather conditions for a marine point.
    Combines OpenWeatherMap API / Open-Meteo Weather with Open-Meteo Marine API,
    cached in Redis with 30-minute TTL.
    """
    if math.isnan(lat) or math.isnan(lon) or not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        raise HTTPException(
            status_code=400,
            detail="Invalid coordinates: lat must be in [-90, 90] and lon in [-180, 180].",
        )

    cache_key = f"weather:current:{round(lat, 2)}:{round(lon, 2)}"
    try:
        cached_data = await get_json(cache_key)
        if cached_data is not None:
            cached_data["cached"] = True
            return cached_data
    except Exception as exc:
        logger.warning("Redis cache read error for %s: %s", cache_key, exc)

    try:
        try:
            from backend.ingest.tides import get_tide as _get_tide
        except ImportError:
            from ingest.tides import get_tide as _get_tide  # type: ignore
        # Run upstream providers concurrently: total latency = max(), not sum().
        # Tide is local disk/parse — also off the event loop via to_thread.
        weather_data, marine_data, tide_info = await asyncio.gather(
            asyncio.to_thread(fetch_live_weather, lat, lon),
            asyncio.to_thread(fetch_open_meteo_marine, lat, lon),
            asyncio.to_thread(_get_tide, lat, lon),
        )
        if not isinstance(tide_info, dict):
            tide_info = {"tide_range_m": None, "next_high_tide_utc": None, "next_low_tide_utc": None, "tidal_state": "unknown"}

        wind_speed_kt = float(weather_data.get("wind_speed_kt", 10.0))
        wind_gust_kt = float(
            weather_data.get("wind_gust_kt", weather_data.get("wind_gusts_kt", wind_speed_kt * 1.3))
        )
        pressure_hpa = float(
            weather_data.get("pressure_hpa", weather_data.get("surface_pressure_hpa", 1012.0))
        )
        wave_height_m = float(marine_data.get("wave_height_m", 1.2))
        wave_period_s = float(marine_data.get("wave_period_s", 7.0))
        current_speed_kt = float(marine_data.get("current_speed_kt", 1.0))

        # Composite safety status classification — canonical bands from
        # backend/agents/safety_thresholds.py (wayfinder #196):
        # wind 15/25kt, wave 1.5/2.5m, current 1.5/2.5kt, pressure 995/1005hPa.
        from backend.agents.safety_thresholds import (
            CURRENT_DANGER_MIN_KT as _CUR_D,
        )
        from backend.agents.safety_thresholds import (
            CURRENT_SAFE_MAX_KT as _CUR_S,
        )
        from backend.agents.safety_thresholds import (
            PRESSURE_CAUTION_HPA as _P_C,
        )
        from backend.agents.safety_thresholds import (
            PRESSURE_DANGER_HPA as _P_D,
        )
        from backend.agents.safety_thresholds import (
            WAVE_DANGER_MIN_M as _WAV_D,
        )
        from backend.agents.safety_thresholds import (
            WAVE_SAFE_MAX_M as _WAV_S,
        )
        from backend.agents.safety_thresholds import (
            WIND_DANGER_MIN_KT as _WND_D,
        )
        from backend.agents.safety_thresholds import (
            WIND_SAFE_MAX_KT as _WND_S,
        )

        if wind_speed_kt > _WND_D or wave_height_m > _WAV_D or current_speed_kt > _CUR_D or pressure_hpa < _P_D:
            status = "danger"
        elif wind_speed_kt > _WND_S or wave_height_m > _WAV_S or current_speed_kt > _CUR_S or pressure_hpa < _P_C:
            status = "caution"
        else:
            status = "safe"

        source = f"{weather_data.get('source', 'live')}+{marine_data.get('source', 'live')}"

        result = {
            "lat": round(lat, 4),
            "lon": round(lon, 4),
            "temperature_c": float(weather_data.get("temperature_c", 28.0)),
            "humidity_pct": float(weather_data.get("humidity_pct", 75.0)),
            "pressure_hpa": pressure_hpa,
            "wind_speed_kt": wind_speed_kt,
            "wind_speed_kts": wind_speed_kt,
            "wind_gust_kt": wind_gust_kt,
            "wind_direction": str(weather_data.get("wind_direction", "N")),
            "wave_height_m": wave_height_m,
            "wave_period_s": wave_period_s,
            "swell_wave_height_m": float(marine_data.get("swell_wave_height_m", 0.8)),
            "swell_wave_period_s": float(marine_data.get("swell_wave_period_s", 6.5)),
            "current_speed_kt": current_speed_kt,
            "status": status,
            "source": source,
            "cached": False,
            "tide_range_m": tide_info.get("tide_range_m"),
            "tidal_state": tide_info.get("tidal_state", "unknown"),
            "next_high_tide_utc": tide_info.get("next_high_tide_utc"),
            "next_low_tide_utc": tide_info.get("next_low_tide_utc"),
        }

        # Cache in Redis with 30-minute TTL (1800 seconds)
        try:
            await set_json(cache_key, result, ttl_seconds=1800)
        except Exception as exc:
            logger.warning("Redis cache write error for %s: %s", cache_key, exc)

        return result

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed fetching live weather for (%s, %s): %s", lat, lon, exc, exc_info=True)
        raise HTTPException(
            status_code=502,
            detail=f"Live weather fetch failed: upstream providers unavailable after retries ({exc}).",
        )


@router.get("/weather/cyclone", response_model=CycloneWarningResponse)
async def get_cyclone_warnings(
    lat: Optional[float] = Query(None, description="Optional latitude for point-specific cyclone evaluation"),
    lon: Optional[float] = Query(None, description="Optional longitude for point-specific cyclone evaluation"),
):
    """
    Return active cyclone warnings and coastal barometric pressure anomalies.
    Evaluates IMD bulletins and coastal pressure thresholds (<995 hPa).
    """
    if lat is not None and lon is not None:
        if math.isnan(lat) or math.isnan(lon) or not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            raise HTTPException(
                status_code=400,
                detail="Invalid coordinates: lat must be in [-90, 90] and lon in [-180, 180].",
            )
    elif (lat is None and lon is not None) or (lat is not None and lon is None):
        raise HTTPException(
            status_code=400,
            detail="Both lat and lon must be provided together if checking a specific location.",
        )

    cache_key = (
        f"weather:cyclone:{round(lat, 2)}:{round(lon, 2)}"
        if lat is not None and lon is not None
        else "weather:cyclone:coastal"
    )

    try:
        cached_data = await get_json(cache_key)
        if cached_data is not None:
            return cached_data
    except Exception as exc:
        logger.warning("Redis cache read error for %s: %s", cache_key, exc)

    try:
        alerts = await asyncio.to_thread(fetch_imd_cyclone_alerts, lat=lat, lon=lon)

        alerts["active"] = alerts.get("alert_level") in ("warning", "severe")
        alerts["nearest_cyclone_km"] = alerts.get("nearest_cyclone_distance_km")

        try:
            await set_json(cache_key, alerts, ttl_seconds=1800)
        except Exception as exc:
            logger.warning("Redis cache write error %s: %s", cache_key, exc)

        return alerts

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed fetching cyclone warnings: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=502,
            detail="Failed retrieving cyclone warnings from upstream providers.",
        )


@router.get("/weather/history")
async def get_weather_history(
    lat: float = Query(..., description="Latitude in degrees (-90 to 90)"),
    lon: float = Query(..., description="Longitude in degrees (-180 to 180)"),
    days: int = Query(7, ge=1, le=30, description="Sliding window size in days (1-30, default 7)"),
) -> Dict[str, Any]:
    """
    Return sliding window historical weather and ocean conditions for a marine point.
    Reads daily snapshots from Redis cache (weather:history:{lat}:{lon}:{YYYY-MM-DD}) or current estimates.
    """
    if math.isnan(lat) or math.isnan(lon) or not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        raise HTTPException(
            status_code=400,
            detail="Invalid coordinates: lat must be in [-90, 90] and lon in [-180, 180].",
        )

    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    rounded_lat = round(lat, 2)
    rounded_lon = round(lon, 2)
    history_entries: List[Dict[str, Any]] = []

    # Get current weather as baseline if needed
    current_baseline = None
    try:
        current_baseline = await get_json(f"weather:current:{rounded_lat}:{rounded_lon}")
    except Exception:
        pass

    for day_offset in range(days):
        day_dt = now - timedelta(days=day_offset)
        date_str = day_dt.strftime("%Y-%m-%d")
        cache_key = f"weather:history:{rounded_lat}:{rounded_lon}:{date_str}"

        day_data = None
        try:
            day_data = await get_json(cache_key)
        except Exception:
            pass

        if not day_data:
            # Baseline estimation from current data or standard seasonal model
            base_temp = current_baseline.get("temperature_c", 28.4) if current_baseline else 28.4
            base_wind = current_baseline.get("wind_speed_kt", 12.0) if current_baseline else 12.0
            base_wave = current_baseline.get("wave_height_m", 0.9) if current_baseline else 0.9
            base_current = current_baseline.get("current_speed_kt", 1.0) if current_baseline else 1.0

            # Deterministic variation by date offset
            day_temp = round(base_temp - (day_offset * 0.1), 1)
            day_wind = round(max(5.0, base_wind + (day_offset % 3 - 1) * 1.5), 1)
            day_wave = round(max(0.4, base_wave + (day_offset % 2 - 0.5) * 0.2), 1)
            day_current = round(max(0.3, base_current + (day_offset % 2 - 0.5) * 0.1), 1)

            # Safety determination — canonical bands via
            # derive_safety_tier (#196): wave 1.5/2.5m, wind 15/25kt,
            # current 1.5/2.5kt. Uppercase tier lowered to keep the
            # lowercase history API contract.
            from backend.agents.safety_thresholds import derive_safety_tier

            safety = derive_safety_tier(day_wave, day_wind, current_kt=day_current).lower()

            day_data = {
                "date": date_str,
                "temperature_c": day_temp,
                "wind_speed_kt": day_wind,
                "wave_height_m": day_wave,
                "current_speed_kt": day_current,
                "safety": safety,
            }

        history_entries.append(day_data)

    return {
        "lat": rounded_lat,
        "lon": rounded_lon,
        "days": days,
        "history": history_entries,
    }
