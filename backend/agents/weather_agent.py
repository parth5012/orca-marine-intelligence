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

import hashlib
import math
import logging
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
# W2 extensible interface — IMD scraping
# ---------------------------------------------------------------------------

async def fetch_imd_wind(lat: float, lon: float) -> tuple[float, str]:
    """
    W2 real fetcher: IMD wind from https://mausam.imd.gov.in.

    Would scrape/parse IMD marine bulletins or GFS wind grids and return
    (wind_speed_kt, wind_direction_compass). Stub raises NotImplementedError.
    """
    raise NotImplementedError("IMD wind fetch not configured — use heuristic fallback")


async def fetch_imd_cyclones() -> list[dict]:
    """
    W2 real fetcher: active cyclone list from IMD.

    Returns list of {"name": str, "lat": float, "lon": float, "center": [lat, lon]}
    Stub returns [] (no active cyclones) so heuristic path is deterministic.
    In W2 this would scrape https://mausam.imd.gov.in/responsive/cycloneinformation.php
    or use IMD API.
    """
    # Intentionally return empty — no active cyclones in W1 mock
    return []


async def get_wind(
    lat: float | None,
    lon: float | None,
    zone_id: str,
    idx: int,
) -> tuple[float, str, int | None, str]:
    """
    Wrapper: try IMD real wind, fall back to heuristic.

    Returns:
        (wind_kt, wind_dir, wind_deg, source)
    """
    if lat is not None and lon is not None:
        try:
            wind_kt, wind_dir = await fetch_imd_wind(lat, lon)
            deg = _heuristic_wind_deg(wind_dir)
            return round(float(wind_kt), 1), str(wind_dir), deg, "imd"
        except NotImplementedError:
            pass
        except Exception as exc:
            logger.debug("weather_agent: IMD wind fetch failed for %s (%s,%s): %s", zone_id, lat, lon, exc)

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

    results: list[dict] = []
    for idx, pt in enumerate(points):
        if not isinstance(pt, dict):
            results.append({
                "zone_id": f"unknown_{idx}",
                "place": "",
                "lat": None,
                "lon": None,
                "wind_kt": 0.0,
                "wind_speed_kt": 0.0,
                "wind_dir": "N",
                "wind_direction": "N",
                "wind_deg": 0,
                "wind_status": "safe",
                "cyclone_alert": False,
                "nearest_cyclone_km": None,
                "cyclone_name": None,
                "status": "safe",
                "reason": "invalid point — skipped",
                "source": "mock_heuristic",
            })
            continue

        zone_id, lat, lon, place = _extract_point(pt, idx)
        wind_kt, wind_dir, wind_deg, source = await get_wind(lat, lon, zone_id, idx)
        wind_status = _classify_wind(wind_kt)

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

        results.append({
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
            "status": status,
            "reason": reason,
            "source": source,
        })

    return results
