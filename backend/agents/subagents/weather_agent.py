"""
Weather Agent — Wind, Storm and Cyclone Conditions

Owner: M-A (Agents & Orchestration) — wind/cyclone check
Module: backend/agents/weather_agent.py

The Weather Agent provides atmospheric conditions at PFZ coordinates.
It reports wind speed/direction and cyclone proximity to inform the
Smart Combiner's safety assessment.

Data Sources:
    - W1 (Mock): Deterministic heuristic per point (zone_id/lat/lon hash)
    - W2 (Real): IMD text data from https://mausam.imd.gov.in (extensible wrapper)

Safety Thresholds:
    - Wind < 15kt -> safe
    - Wind 15-25kt -> caution (small craft advisory)
    - Wind > 25kt -> danger
    - Active cyclone within 500km -> danger regardless of wind

Extensible interface:
    - fetch_imd_wind(lat, lon) — W2 real wind fetcher (stub)
    - fetch_imd_cyclones() — W2 real cyclone list (stub, returns [])
    - get_wind(...) / get_cyclone_alert(...) — wrappers with heuristic fallback
"""

import asyncio
import hashlib
import math
import logging
from pathlib import Path
import numpy as np
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
WIND_SAFE_MAX = 15.0  # kt, <15 safe
WIND_CAUTION_MAX = 25.0  # kt, 15-25 caution, >25 danger
CYCLONE_RADIUS_KM = 500.0
_SEVERITY_RANK = {"safe": 0, "caution": 1, "danger": 2}

_COMPASS_8 = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def _classify_wind(wind_kt: float) -> str:
    """Classify wind: <15 safe, 15-25 caution, >25 danger."""
    if wind_kt < WIND_SAFE_MAX:
        return "safe"
    if wind_kt <= WIND_CAUTION_MAX:
        return "caution"
    return "danger"


def _overall_status(wind_status: str, cyclone_danger: bool) -> str:
    """Cyclone within 500km forces danger regardless of wind."""
    if cyclone_danger:
        return "danger"
    return wind_status


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return r * 2 * math.asin(math.sqrt(a))


def _extract_point(point: dict, idx: int) -> tuple[str, float | None, float | None, str]:
    zone_id: str | None = None
    place: str | None = None
    lat: float | None = None
    lon: float | None = None

    props = point.get("properties") if isinstance(point.get("properties"), dict) else None
    source = props if props is not None else point

    zone_id = source.get("zone_id") or point.get("zone_id") or point.get("id")
    place = source.get("place") or point.get("place") or source.get("name") or ""

    geom = point.get("geometry")
    if isinstance(geom, dict):
        coords = geom.get("coordinates")
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            try:
                lon = float(coords[0])
                lat = float(coords[1])
            except (TypeError, ValueError):
                pass

    if lat is None:
        for k in ("lat", "latitude", "y"):
            if point.get(k) is not None:
                try:
                    lat = float(point[k])
                    break
                except (TypeError, ValueError):
                    continue
        if lat is None and props is not None:
            for k in ("lat", "latitude"):
                if props.get(k) is not None:
                    try:
                        lat = float(props[k])
                        break
                    except (TypeError, ValueError):
                        continue

    if lon is None:
        for k in ("lon", "lng", "longitude", "x"):
            if point.get(k) is not None:
                try:
                    lon = float(point[k])
                    break
                except (TypeError, ValueError):
                    continue
        if lon is None and props is not None:
            for k in ("lon", "lng", "longitude"):
                if props.get(k) is not None:
                    try:
                        lon = float(props[k])
                        break
                    except (TypeError, ValueError):
                        continue

    if zone_id is None:
        safe_place = str(place).replace(" ", "_") if place else f"zone_{idx}"
        zone_id = f"SEC000_{safe_place}_{idx}"

    return str(zone_id), lat, lon, str(place) if place else ""


def _stable_int(seed: str) -> int:
    return int(hashlib.md5(seed.encode("utf-8")).hexdigest()[:8], 16)


# ---------------------------------------------------------------------------
# W1 deterministic heuristics
# ---------------------------------------------------------------------------

def _heuristic_wind_speed(lat: float | None, lon: float | None, zone_id: str, idx: int) -> float:
    """
    Deterministic mock wind in [4, 32] kt, spread across safe/caution/danger.

    0..279 -> 4.0 .. 31.9 kt
    """
    base_seed = f"wind:{zone_id}:{lat}:{lon}:{idx}"
    h = _stable_int(base_seed)
    wind = 4.0 + (h % 280) / 10.0  # 4.0 .. 31.9
    return round(wind, 1)


def _heuristic_wind_dir(lat: float | None, lon: float | None, zone_id: str, idx: int) -> str:
    base_seed = f"wind_dir:{zone_id}:{lat}:{lon}:{idx}"
    h = _stable_int(base_seed)
    return _COMPASS_8[h % len(_COMPASS_8)]


def _heuristic_wind_deg(wind_dir: str) -> int | None:
    mapping = {"N": 0, "NE": 45, "E": 90, "SE": 135, "S": 180, "SW": 225, "W": 270, "NW": 315}
    return mapping.get(wind_dir)


# ---------------------------------------------------------------------------
# Tier 3 Fallback: Marine Data Package Parquet (cyclones & coastal wind)
# ---------------------------------------------------------------------------

_PARQUET_CYCLONE_CACHE = None
_PARQUET_WIND_CACHE = None

def _get_cyclone_parquet_data() -> list[dict] | None:
    global _PARQUET_CYCLONE_CACHE
    if _PARQUET_CYCLONE_CACHE is not None:
        return _PARQUET_CYCLONE_CACHE
    base = Path(__file__).resolve().parents[3]
    p = base / "data" / "marine_data_package" / "marine-data" / "unified" / "marine_events" / "cyclone_events.parquet"
    if not p.exists():
        return None
    try:
        import pyarrow.parquet as pq
        tbl = pq.read_table(str(p))
        df = tbl.to_pandas()
        cyclones = []
        for _, row in df.tail(15).iterrows():
            min_lat = float(row.get("min_lat", 10.0))
            max_lat = float(row.get("max_lat", 15.0))
            min_lon = float(row.get("min_lon", 75.0))
            max_lon = float(row.get("max_lon", 85.0))
            center_lat = round((min_lat + max_lat) / 2.0, 2)
            center_lon = round((min_lon + max_lon) / 2.0, 2)
            cyclones.append({
                "name": str(row.get("name", "UNKNOWN")),
                "lat": center_lat,
                "lon": center_lon,
                "center": [center_lat, center_lon],
                "wind_speed_kt": float(row.get("max_wind_kt", 45.0)),
                "pressure_hpa": float(row.get("min_pressure_mb", 990.0)),
                "source": "marine_data_package",
            })
        _PARQUET_CYCLONE_CACHE = cyclones
        return _PARQUET_CYCLONE_CACHE
    except Exception as exc:
        logger.debug("Failed reading cyclone_events.parquet: %s", exc)
        return None

def _get_coastal_wind_parquet_data():
    global _PARQUET_WIND_CACHE
    if _PARQUET_WIND_CACHE is not None:
        return _PARQUET_WIND_CACHE
    base = Path(__file__).resolve().parents[3]
    candidates = [
        base / "data" / "marine_data_package" / "marine-data" / "unified" / "marine_features" / "coastal_point_features.parquet",
        base / "data" / "coastal_point_features.parquet",
    ]
    p = next((c for c in candidates if c.exists()), None)
    if not p:
        return None
    try:
        import pyarrow.parquet as pq
        tbl = pq.read_table(str(p), columns=["latitude", "longitude", "wind_speed_10m_kmh", "wind_direction_10m_deg"])
        lats = tbl["latitude"].to_numpy()
        lons = tbl["longitude"].to_numpy()
        speeds = tbl["wind_speed_10m_kmh"].to_numpy()
        dirs = tbl["wind_direction_10m_deg"].to_numpy()
        _PARQUET_WIND_CACHE = (lats, lons, speeds, dirs)
        return _PARQUET_WIND_CACHE
    except Exception as exc:
        logger.debug("Failed reading coastal wind parquet: %s", exc)
        return None

def _deg_to_compass(deg: float) -> str:
    val = int((deg / 45.0) + 0.5) % 8
    return _COMPASS_8[val]

def _fetch_parquet_wind(lat: float, lon: float) -> tuple[float, str, int] | None:
    data = _get_coastal_wind_parquet_data()
    if not data:
        return None
    lats, lons, speeds, dirs = data
    dist_sq = (lats - lat) ** 2 + (lons - lon) ** 2
    idx = int(dist_sq.argmin())
    speed_kmh = float(speeds[idx]) if not (np.isnan(speeds[idx]) if hasattr(speeds, "dtype") else False) else 15.0
    wind_kt = round(speed_kmh * 0.539957, 1)
    deg = int(dirs[idx]) if not (np.isnan(dirs[idx]) if hasattr(dirs, "dtype") else False) else 0
    compass = _deg_to_compass(deg)
    return wind_kt, compass, deg


# ---------------------------------------------------------------------------
# W2 extensible interface — IMD scraping
# ---------------------------------------------------------------------------

async def fetch_imd_wind(lat: float, lon: float) -> tuple[float, str]:
    """
    Live real wind fetcher: single-try Open-Meteo 3.5s (fail-fast).
    Avoids fetch_live_weather 6+3+6=15s double-retry chain that blew the 8/12s budget.
    Offloaded via to_thread — sync httpx must not block event loop.
    """
    try:
        from backend.ingest.live_fetchers import fetch_open_meteo_weather
        data = await asyncio.to_thread(
            fetch_open_meteo_weather, lat, lon, None, 3.5
        )
        return float(data["wind_speed_kt"]), str(data["wind_direction"])
    except Exception as exc:
        logger.debug("Live wind fetch failed for (%s, %s): %s", lat, lon, exc)
        raise NotImplementedError("Live wind fetch unavailable") from exc


async def fetch_imd_cyclones() -> list[dict]:
    """
    Real fetcher: active cyclone list from IMD / live coastal fetcher.
    Falls back to Marine Data Package (cyclone_events.parquet) if live is unavailable.
    """
    try:
        from backend.ingest.live_fetchers import fetch_imd_cyclones as live_cyclones
        res = live_cyclones()
        if res:
            return res
    except Exception as exc:
        logger.debug("IMD cyclone fetch error: %s", exc)

    # Tier 3 fallback: Marine Data Package
    fallback = _get_cyclone_parquet_data()
    if fallback:
        return fallback

    return []


async def get_wind(
    lat: float | None,
    lon: float | None,
    zone_id: str,
    idx: int,
) -> tuple[float, str, int | None, str]:
    """
    Wrapper: try IMD real wind, fall back to Marine Data Package parquet, then heuristic.

    Returns:
        (wind_kt, wind_dir, wind_deg, source)
    """
    if lat is not None and lon is not None:
        try:
            wind_kt, wind_dir = await fetch_imd_wind(lat, lon)
            deg = _heuristic_wind_deg(wind_dir)
            return round(float(wind_kt), 1), str(wind_dir), deg, "open_meteo_live"
        except NotImplementedError:
            pass
        except Exception as exc:
            logger.debug("weather_agent: IMD wind fetch failed for %s (%s, %s): %s", zone_id, lat, lon, exc)

        # Tier 3 fallback: Marine Data Package
        parquet_fallback = _fetch_parquet_wind(lat, lon)
        if parquet_fallback is not None:
            return parquet_fallback[0], parquet_fallback[1], parquet_fallback[2], "marine_data_package"

    wind_kt = _heuristic_wind_speed(lat, lon, zone_id, idx)
    wind_dir = _heuristic_wind_dir(lat, lon, zone_id, idx)
    wind_deg = _heuristic_wind_deg(wind_dir)
    return wind_kt, wind_dir, wind_deg, "mock_heuristic"


async def get_cyclone_alert(
    lat: float | None,
    lon: float | None,
    cyclones: list[dict] | None = None,
) -> tuple[bool, float | None, str | None, dict | None]:
    """
    Determine if any active cyclone is within 500km of (lat, lon).

    Args:
        lat, lon: point to check (None -> no alert)
        cyclones: optional pre-fetched cyclone list; if None, calls fetch_imd_cyclones().

    Returns:
        (cyclone_alert: bool, nearest_cyclone_km: float|None, cyclone_name: str|None, nearest_cyclone: dict|None)
    """
    if lat is None or lon is None:
        return False, None, None, None

    if cyclones is None:
        try:
            cyclones = await fetch_imd_cyclones()
        except Exception as exc:
            logger.debug("weather_agent: IMD cyclone fetch failed: %s", exc)
            cyclones = []

    if not cyclones:
        return False, None, None, None

    nearest = None
    nearest_km: float | None = None
    for c in cyclones:
        # Support both {center:[lat,lon]} and {lat,lon} and {center:[lat,lon]} shapes
        c_lat: float | None = None
        c_lon: float | None = None
        if "center" in c and isinstance(c["center"], (list, tuple)) and len(c["center"]) >= 2:
            # center may be [lat, lon] or [lon, lat] — IMD convention is [lat, lon] but handle both
            # Heuristic: if first value > 30 it's likely lon? Simpler: assume [lat, lon] per spec
            try:
                c_lat = float(c["center"][0])
                c_lon = float(c["center"][1])
            except (TypeError, ValueError):
                continue
        else:
            try:
                if c.get("lat") is not None and c.get("lon") is not None:
                    c_lat = float(c["lat"])
                    c_lon = float(c["lon"])
            except (TypeError, ValueError):
                continue
        if c_lat is None or c_lon is None:
            continue
        try:
            dist = _haversine_km(lat, lon, c_lat, c_lon)
        except Exception:
            continue
        if nearest_km is None or dist < nearest_km:
            nearest_km = dist
            nearest = c

    if nearest_km is not None and nearest_km <= CYCLONE_RADIUS_KM:
        name = None
        if nearest is not None:
            name = nearest.get("name") or nearest.get("cyclone_name")
        return True, round(nearest_km, 1), str(name) if name else None, nearest

    # No cyclone within 500km — still report nearest distance for transparency if any
    if nearest_km is not None:
        return False, round(nearest_km, 1), None, nearest
    return False, None, None, None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def check_weather(points: list[dict]) -> list[dict]:
    """
    Evaluate wind speed and cyclone alerts per zone.

    Classification:
        wind < 15kt -> safe, 15-25kt -> caution, > 25kt -> danger.
        Active cyclone within 500km -> danger regardless of wind.

    Args:
        points: List of dicts, each representing a PFZ zone. Accepted shapes:
            - Flat: {"zone_id": str, "place": str, "lat": float, "lon": float}
            - GeoJSON Feature: {"properties": {...}, "geometry": {"coordinates":[lon,lat]}}
            Order is preserved.

    Returns:
        List of dicts in the SAME order as input, each containing:
            {
              "zone_id": str,
              "place": str,
              "lat": float|None,
              "lon": float|None,
              "wind_kt": float,              # alias: wind_speed_kt
              "wind_speed_kt": float,
              "wind_dir": str,               # N/NE/E/SE/S/SW/W/NW
              "wind_direction": str,
              "wind_deg": int|None,          # 0/45/...315
              "wind_status": "safe"|"caution"|"danger",
              "cyclone_alert": bool,
              "nearest_cyclone_km": float|None,
              "cyclone_name": str|None,
              "status": "safe"|"caution"|"danger",  # overall (cyclone forces danger)
              "reason": str,
              "source": "mock_heuristic"|"imd"
            }
        Empty input -> [].
    """
    if not points:
        return []

    # Fetch cyclones once for all points (efficient, extensible)
    try:
        cyclones = await fetch_imd_cyclones()
    except Exception as exc:
        logger.debug("weather_agent: cyclone fetch failed: %s", exc)
        cyclones = []

    async def _one(idx: int, pt: dict) -> dict:
        if not isinstance(pt, dict):
            return {
                "zone_id": f"unknown_{idx}",
                "place": "",
                "lat": None,
                "lon": None,
                "wind_kt": 0.0,
                "wind_speed_kt": 0.0,
                "wind_dir": "N",
                "wind_direction": "N",
                "wind_deg": 0,
                "wind_status": "danger",
                "cyclone_alert": False,
                "nearest_cyclone_km": None,
                "cyclone_name": None,
                "status": "danger",
                "reason": "invalid point — unknown location treated as danger",
                "source": "mock_heuristic",
            }
        zone_id, lat, lon, place = _extract_point(pt, idx)
        wind_kt, wind_dir, wind_deg, source = await get_wind(lat, lon, zone_id, idx)
        wind_status = _classify_wind(wind_kt)

        # Tide (T2 #117): lazy import to avoid cycles; never breaks the agent.
        tide_range_m: float | None = None
        tidal_state: str = "unknown"
        next_high_tide_utc: str | None = None
        next_low_tide_utc: str | None = None
        try:
            if lat is not None and lon is not None:
                try:
                    from backend.ingest.tides import get_tide as _get_tide
                except ImportError:
                    from ingest.tides import get_tide as _get_tide  # type: ignore
                _tide = await asyncio.to_thread(_get_tide, lat, lon) or {}
                tide_range_m = _tide.get("tide_range_m")
                try:
                    tide_range_m = float(tide_range_m) if tide_range_m is not None else None
                except (TypeError, ValueError):
                    tide_range_m = None
                tidal_state = str(_tide.get("tidal_state") or "unknown")
                if tidal_state not in ("rising", "falling", "slack", "unknown"):
                    tidal_state = "unknown"
                next_high_tide_utc = _tide.get("next_high_tide_utc")
                next_low_tide_utc = _tide.get("next_low_tide_utc")
        except Exception as exc:
            logger.debug("weather_agent: tide lookup failed for %s (%s, %s): %s", zone_id, lat, lon, exc)
            tide_range_m, tidal_state = None, "unknown"
            next_high_tide_utc, next_low_tide_utc = None, None

        cyclone_alert, nearest_km, cyclone_name, _nearest = await get_cyclone_alert(lat, lon, cyclones)
        status = _overall_status(wind_status, cyclone_alert)

        if cyclone_alert:
            reason = f"cyclone {cyclone_name or 'alert'} within {nearest_km}km (<=500km) -> danger"
        elif status == "danger":
            reason = f"wind {wind_kt}kt danger (>25kt) dir {wind_dir}"
        elif status == "caution":
            reason = f"wind {wind_kt}kt caution (15-25kt) dir {wind_dir}"
        else:
            reason = f"wind {wind_kt}kt safe dir {wind_dir}"

        return {
            "zone_id": zone_id,
            "place": place,
            "lat": lat,
            "lon": lon,
            "wind_kt": wind_kt,
            "wind_speed_kt": wind_kt,
            "wind_dir": wind_dir,
            "wind_direction": wind_dir,
            "wind_deg": wind_deg,
            "wind_status": wind_status,
            "cyclone_alert": cyclone_alert,
            "nearest_cyclone_km": nearest_km,
            "cyclone_name": cyclone_name,
            "tide_range_m": tide_range_m,
            "tidal_state": tidal_state,
            "next_high_tide_utc": next_high_tide_utc,
            "next_low_tide_utc": next_low_tide_utc,
            "status": status,
            "reason": reason,
            "source": source,
        }

    # Parallel per-zone: gather preserves order, ~6s total not 5x6s sequential.
    return list(await asyncio.gather(*(_one(idx, pt) for idx, pt in enumerate(points))))


async def check_forecast(lat: float, lon: float, hours_ahead: int = 24) -> dict[str, Any]:
    """
    Evaluate departure window forecast for coordinates over next 6-24 hours.
    Queries Open-Meteo hourly forecast via live_fetchers.
    Returns:
      {
        "departure_safe": bool | str,
        "best_window_utc": str,
        "forecast_summary": str,
        "wind_kts_6h": float | None,
        "wave_m_6h": float | None,
      }
    """
    try:
        import asyncio as _aio
        from datetime import datetime, timezone, timedelta
        try:
            from backend.ingest import live_fetchers
        except ImportError:
            from ingest import live_fetchers  # type: ignore

        _ist = timezone(timedelta(hours=5, minutes=30))
        now_utc = datetime.now(timezone.utc)
        target_dt = (now_utc + timedelta(hours=6)).astimezone(_ist)

        # 1. Fetch 6h ahead weather + marine (non-blocking, correct keys)
        wind_6h = None
        wave_6h = None
        try:
            w_6h = await _aio.to_thread(live_fetchers.fetch_open_meteo_weather, lat, lon, target_dt)
            wind_6h = w_6h.get("wind_speed_kt")
            if wind_6h is None:
                try:
                    wind_6h = (w_6h.get("trip_window_6h") or {}).get("max_wind_kt")
                except Exception:
                    wind_6h = None
        except Exception:
            w_6h = {}
        try:
            m_6h = await _aio.to_thread(live_fetchers.fetch_open_meteo_marine, lat, lon, target_dt)
            wave_6h = m_6h.get("wave_height_m") or m_6h.get("wave_height")
            if wave_6h is None:
                wave_6h = m_6h.get("max_wave_6h")
            if wave_6h is None:
                try:
                    wave_6h = (m_6h.get("trip_window_6h") or {}).get("max_wave_m")
                except Exception:
                    wave_6h = None
        except Exception:
            m_6h = {}

        # 2. Compute 24h departure advisory if available
        advisory_info: dict[str, Any] = {}
        try:
            advisory_info = await _aio.to_thread(live_fetchers.compute_departure_window_advisory, lat, lon, hours_ahead)
        except Exception:
            pass

        best_window = advisory_info.get("departure_window") or f"{target_dt.strftime('%H:00')} IST"
        dep_safe = advisory_info.get("is_safe_to_depart")
        if dep_safe is None:
            # derive from wind/wave thresholds only when BOTH metrics known;
            # missing data must read as unknown, never safe.
            try:
                if wind_6h is not None and wave_6h is not None:
                    dep_safe = bool(float(wind_6h) < 15.0 and float(wave_6h) < 1.5)
                else:
                    dep_safe = "unknown"
            except Exception:
                dep_safe = "unknown"

        if advisory_info.get("bulletin_text"):
            summary = advisory_info["bulletin_text"]
        elif wind_6h is not None and wave_6h is not None:
            safe_str = "safe to depart" if dep_safe is True else ("conditions unsafe / caution" if dep_safe is False else "conditions uncertain")
            summary = f"Tomorrow morning ({best_window}): wind {wind_6h} kt, waves {wave_6h}m - {safe_str}."
        elif wind_6h is not None:
            safe_str = "safe to depart" if dep_safe is True else ("conditions unsafe / caution" if dep_safe is False else "conditions uncertain")
            summary = f"Tomorrow morning ({best_window}): wind {wind_6h} kt - {safe_str}."
        elif dep_safe == "unknown":
            summary = "Forecast unavailable"
        else:
            summary = "Forecast advisory available."

        return {
            "departure_safe": dep_safe,
            "best_window_utc": str(best_window),
            "forecast_summary": summary,
            "wind_kts_6h": float(wind_6h) if wind_6h is not None else None,
            "wave_m_6h": float(wave_6h) if wave_6h is not None else None,
        }
    except Exception as exc:
        logger.warning("weather_agent.check_forecast error for (%s, %s): %s", lat, lon, exc)
        return {
            "departure_safe": "unknown",
            "best_window_utc": "",
            "forecast_summary": "Forecast unavailable",
            "wind_kts_6h": None,
            "wave_m_6h": None,
        }
