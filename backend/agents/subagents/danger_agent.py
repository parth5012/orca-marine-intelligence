"""
Danger Watch Agent — Safety Geofence Agent

Owner: M-A (Agents & Orchestration) — EEZ/MPA/cyclone check
Module: backend/agents/danger_agent.py

The Danger Watch agent checks if a recommended fishing zone is:
1. Inside India's Exclusive Economic Zone (EEZ) → legal
2. Outside Marine Protected Areas (MPA) → allowed
3. Outside International Maritime Boundary Line (IMBL) → no conflict (2km buffer)
4. Not under cyclone/lightning warning (IMD data) — W2 stub

Data Sources:
    - EEZ: data/eez.geojson (MarineRegions) + PostGIS eez_boundaries
    - MPA: data/mpa.geojson (WDPA) + PostGIS mpa_boundaries
    - IMBL: data/imbl.geojson (or EEZ boundary as proxy)
    - IMD: Cyclone/lightning alerts (via https://mausam.imd.gov.in) — W2

Safety Rules:
    - If inside MPA → danger (fine risk, strictly banned)
    - If outside EEZ → danger (illegal)
    - If within 2km of EEZ/IMBL boundary → caution (risk of crossing)
    - If cyclone/lightning in area → danger (W2)

Output:
    {is_safe: bool, status: "safe"|"caution"|"danger", warnings: list[str],
     inside_eez: bool, inside_mpa: bool, mpa_name: str | None}

Fallback:
    - Primary: backend.db.postgis.check_geofence(lat, lon) with 10s timeout
    - Fallback: ray-casting polygon checks using local GeoJSON files
"""

import asyncio
import json
import logging
import math
from pathlib import Path
import threading
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
IMBL_BUFFER_KM = 2.0
EEZ_BUFFER_KM = 2.0  # same threshold, spec says 2km proximity warning
TIMEOUT_S = 10.0

# Resolve GeoJSON files relative to project root
_GEOJSON_CANDIDATES_EEZ = [
    Path(__file__).resolve().parents[3] / "data" / "eez.geojson",
    Path(__file__).resolve().parents[2] / "data" / "eez.geojson",
    Path(__file__).resolve().parents[1] / ".." / "data" / "eez.geojson",
    Path.cwd() / "data" / "eez.geojson",
]
_GEOJSON_CANDIDATES_MPA = [
    Path(__file__).resolve().parents[3] / "data" / "mpa.geojson",
    Path(__file__).resolve().parents[2] / "data" / "mpa.geojson",
    Path(__file__).resolve().parents[1] / ".." / "data" / "mpa.geojson",
    Path.cwd() / "data" / "mpa.geojson",
]
_GEOJSON_CANDIDATES_IMBL = [
    Path(__file__).resolve().parents[3] / "data" / "imbl.geojson",
    Path(__file__).resolve().parents[2] / "data" / "imbl.geojson",
    Path(__file__).resolve().parents[1] / ".." / "data" / "imbl.geojson",
    Path.cwd() / "data" / "imbl.geojson",
]

# Simple in-memory cache
_EEZ_CACHE: dict | None = None
_MPA_CACHE: dict | None = None
_IMBL_CACHE: dict | None = None


# ---------------------------------------------------------------------------
# Geometry helpers — haversine, ray-casting, distance to polygon edge
# ---------------------------------------------------------------------------

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return r * 2 * math.asin(math.sqrt(a))


def _point_in_ring(lon: float, lat: float, ring: list) -> bool:
    """Ray-casting point-in-ring. Ring is list of [lon, lat] or [x,y]."""
    if len(ring) < 3:
        return False
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        try:
            xi, yi = float(ring[i][0]), float(ring[i][1])
            xj, yj = float(ring[j][0]), float(ring[j][1])
        except (TypeError, ValueError, IndexError):
            j = i
            continue
        # Check if point is on a horizontal ray
        intersect = ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-12) + xi)
        if intersect:
            inside = not inside
        j = i
    return inside


def _point_in_polygon(lon: float, lat: float, polygon: list) -> bool:
    """
    Polygon is list of rings: [exterior, hole1, hole2, ...].
    Returns True if inside exterior and not inside any hole.
    """
    if not polygon:
        return False
    exterior = polygon[0]
    if not _point_in_ring(lon, lat, exterior):
        return False
    # Check holes — if inside a hole, it's outside polygon
    for hole in polygon[1:]:
        if _point_in_ring(lon, lat, hole):
            return False
    return True


def _point_in_multipolygon(lon: float, lat: float, multipolygon: list) -> bool:
    """Multipolygon is list of polygons. True if inside any polygon."""
    for polygon in multipolygon:
        if _point_in_polygon(lon, lat, polygon):
            return True
    return False


def _distance_point_to_segment_km(
    plat: float, plon: float, lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """
    Approximate distance from point (plat, plon) to segment (lat1,lon1)-(lat2,lon2)
    using equirectangular projection around mean latitude, then haversine to
    closest point. Accurate to <1% for segments <~100km.
    """
    # Degenerate segment
    if abs(lat1 - lat2) < 1e-9 and abs(lon1 - lon2) < 1e-9:
        return _haversine_km(plat, plon, lat1, lon1)

    # Use equirectangular projection for parameter t
    # Convert to radians for better scaling
    mean_lat = math.radians((plat + lat1 + lat2) / 3.0)
    cos_lat = math.cos(mean_lat)
    # Scale lon by cos(lat)
    # Work in degrees scaled
    px = plon * cos_lat
    py = plat
    x1 = lon1 * cos_lat
    y1 = lat1
    x2 = lon2 * cos_lat
    y2 = lat2

    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return _haversine_km(plat, plon, lat1, lon1)
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    closest_lon = lon1 + t * (lon2 - lon1)
    closest_lat = lat1 + t * (lat2 - lat1)
    return _haversine_km(plat, plon, closest_lat, closest_lon)


def _distance_to_polygon_km(lat: float, lon: float, polygon: list) -> float:
    """Min haversine distance from point to any edge of polygon (including holes)."""
    min_dist = float("inf")
    for ring in polygon:
        if len(ring) < 2:
            continue
        for i in range(len(ring) - 1):
            try:
                lon1, lat1 = float(ring[i][0]), float(ring[i][1])
                lon2, lat2 = float(ring[i + 1][0]), float(ring[i + 1][1])
            except (TypeError, ValueError, IndexError):
                continue
            d = _distance_point_to_segment_km(lat, lon, lat1, lon1, lat2, lon2)
            if d < min_dist:
                min_dist = d
        # Close ring if not already closed
        if len(ring) >= 3:
            try:
                lon1, lat1 = float(ring[-1][0]), float(ring[-1][1])
                lon2, lat2 = float(ring[0][0]), float(ring[0][1])
                d = _distance_point_to_segment_km(lat, lon, lat1, lon1, lat2, lon2)
                if d < min_dist:
                    min_dist = d
            except (TypeError, ValueError, IndexError):
                pass
    return min_dist if min_dist != float("inf") else float("inf")


def _distance_to_multipolygon_km(lat: float, lon: float, multipolygon: list) -> float:
    min_dist = float("inf")
    for polygon in multipolygon:
        d = _distance_to_polygon_km(lat, lon, polygon)
        if d < min_dist:
            min_dist = d
    return min_dist


# ---------------------------------------------------------------------------
# GeoJSON loading & normalization
# ---------------------------------------------------------------------------

def _resolve_geojson_path(candidates: list[Path]) -> Path | None:
    for p in candidates:
        try:
            resolved = p.resolve()
        except Exception:
            resolved = p
        if resolved.is_file():
            return resolved
    return None


def _extract_multipolygons(geojson_data: dict) -> tuple[list, list[dict]]:
    """
    Normalize GeoJSON into list of multipolygons and raw features for MPA names.
    Supports FeatureCollection, Feature, or raw Geometry.
    Returns (multipolygons, features_with_props).
    Each multipolygon is list[polygon] where polygon is list[ring] where ring is list[[lon,lat]].
    """
    multipolygons: list = []
    features: list[dict] = []

    if not isinstance(geojson_data, dict):
        return multipolygons, features

    raw_features: list[dict] = []
    gtype = geojson_data.get("type")
    if gtype == "FeatureCollection":
        raw_features = geojson_data.get("features", []) or []
    elif gtype == "Feature":
        raw_features = [geojson_data]
    elif gtype in ("Polygon", "MultiPolygon"):
        raw_features = [{"type": "Feature", "properties": {}, "geometry": geojson_data}]
    else:
        raw_features = geojson_data.get("features", []) or []

    for feat in raw_features:
        if not isinstance(feat, dict):
            continue
        geom = feat.get("geometry") or feat.get("geom")
        if not isinstance(geom, dict):
            continue
        geom_type = geom.get("type")
        coords = geom.get("coordinates")
        if coords is None:
            continue
        props = feat.get("properties") or {}

        normalized: list | None = None
        if geom_type == "Polygon":
            # coords is list[ring]
            normalized = [coords]  # single polygon → multipolygon with 1 polygon
        elif geom_type == "MultiPolygon":
            # coords is list[polygon]
            normalized = coords
        else:
            # Ignore Point/LineString for boundary checks
            continue

        if normalized is not None:
            multipolygons.append(normalized)
            features.append({"multipolygon": normalized, "properties": props, "geometry": geom})
        else:
            features.append({"multipolygon": [], "properties": props, "geometry": geom})

    return multipolygons, features


def _load_cached_geojson(cache_name: str, candidates: list[Path]) -> tuple[list, list[dict]]:
    """Load and cache GeoJSON. Returns (multipolygons, features). Missing file → ([], [])."""
    global _EEZ_CACHE, _MPA_CACHE, _IMBL_CACHE
    cache_map = {"eez": "_EEZ_CACHE", "mpa": "_MPA_CACHE", "imbl": "_IMBL_CACHE"}
    # Use globals for simple caching
    cache_val = None
    if cache_name == "eez":
        cache_val = _EEZ_CACHE
    elif cache_name == "mpa":
        cache_val = _MPA_CACHE
    elif cache_name == "imbl":
        cache_val = _IMBL_CACHE

    if cache_val is not None:
        return cache_val  # type: ignore

    path = _resolve_geojson_path(candidates)
    if path is None:
        result: tuple[list, list[dict]] = ([], [])
        if cache_name == "eez":
            _EEZ_CACHE = result  # type: ignore
        elif cache_name == "mpa":
            _MPA_CACHE = result  # type: ignore
        elif cache_name == "imbl":
            _IMBL_CACHE = result  # type: ignore
        return result

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        multipolygons, features = _extract_multipolygons(data)
        result = (multipolygons, features)
        if cache_name == "eez":
            _EEZ_CACHE = result  # type: ignore
        elif cache_name == "mpa":
            _MPA_CACHE = result  # type: ignore
        elif cache_name == "imbl":
            _IMBL_CACHE = result  # type: ignore
        logger.info("danger_agent: loaded %s %s polygons from %s", len(multipolygons), cache_name, path)
        return result
    except Exception as exc:
        logger.warning("danger_agent: failed to load %s GeoJSON %s: %s", cache_name, path, exc)
        result = ([], [])
        if cache_name == "eez":
            _EEZ_CACHE = result  # type: ignore
        elif cache_name == "mpa":
            _MPA_CACHE = result  # type: ignore
        elif cache_name == "imbl":
            _IMBL_CACHE = result  # type: ignore
        return result


def _clear_geojson_cache() -> None:
    """Clear cached GeoJSON — useful for tests."""
    global _EEZ_CACHE, _MPA_CACHE, _IMBL_CACHE
    _EEZ_CACHE = None
    _MPA_CACHE = None
    _IMBL_CACHE = None


# ---------------------------------------------------------------------------
# Fallback ray-casting checks
# ---------------------------------------------------------------------------

def _fallback_check_eez(lat: float, lon: float) -> tuple[bool, float | None]:
    """
    Returns (inside_eez, distance_to_boundary_km).
    If no EEZ data available, returns (False, None) fail-closed with warning handled by caller.
    """
    multipolygons, _ = _load_cached_geojson("eez", _GEOJSON_CANDIDATES_EEZ)
    if not multipolygons:
        # Also try IMBL as fallback for EEZ if EEZ missing
        multipolygons_imbl, _ = _load_cached_geojson("imbl", _GEOJSON_CANDIDATES_IMBL)
        if multipolygons_imbl:
            multipolygons = multipolygons_imbl
        else:
            return False, None

    inside = False
    min_dist = float("inf")
    for mp in multipolygons:
        # mp is multipolygon: list[polygon]
        if _point_in_multipolygon(lon, lat, mp):
            inside = True
        d = _distance_to_multipolygon_km(lat, lon, mp)
        if d < min_dist:
            min_dist = d

    dist = None if min_dist == float("inf") else round(float(min_dist), 2)
    # If multipolygon empty, inside stays False but we treat as True above
    return inside, dist


def _fallback_check_mpa(lat: float, lon: float) -> tuple[bool, str | None]:
    multipolygons, features = _load_cached_geojson("mpa", _GEOJSON_CANDIDATES_MPA)
    if not multipolygons:
        return False, None
    for idx, feat in enumerate(features):
        mp = feat.get("multipolygon") or []
        if not mp:
            continue
        if _point_in_multipolygon(lon, lat, mp):
            props = feat.get("properties") or {}
            name = (
                props.get("mpa_name")
                or props.get("name")
                or props.get("NAME")
                or props.get("Name")
                or props.get("mpaName")
                or f"MPA_{idx}"
            )
            return True, str(name)
    return False, None


def _fallback_distance_to_imbl(lat: float, lon: float) -> float | None:
    """
    Distance to IMBL or EEZ boundary. Tries IMBL file first, then EEZ.
    Returns None if no data.
    """
    multipolygons, _ = _load_cached_geojson("imbl", _GEOJSON_CANDIDATES_IMBL)
    if multipolygons:
        min_dist = float("inf")
        for mp in multipolygons:
            md = _distance_to_multipolygon_km(lat, lon, mp)
            if md < min_dist:
                min_dist = md
        if min_dist != float("inf"):
            return round(float(min_dist), 2)
    # Fallback to EEZ boundary distance
    _, dist = _fallback_check_eez(lat, lon)
    return dist


# ---------------------------------------------------------------------------
# W2 extensible stubs — IMD cyclone/lightning
# ---------------------------------------------------------------------------

async def fetch_imd_cyclone_alert(lat: float, lon: float) -> dict | None:
    """
    Live real fetcher: IMD cyclone data and coastal pressure anomalies via live_fetchers.
    Returns {"active": bool, "name": str, "distance_km": float} or None.
    """
    try:
        from backend.ingest.live_fetchers import fetch_cyclone_alert_for_point
        return fetch_cyclone_alert_for_point(lat, lon)
    except Exception as exc:
        logger.debug("danger_agent: live cyclone check failed: %s", exc)
        return {"active": False}


_PARQUET_LIGHTNING_CACHE = None
_PARQUET_LIGHTNING_LOCK = threading.Lock()


def _get_coastal_parquet_lightning_data() -> dict | None:
    global _PARQUET_LIGHTNING_CACHE
    if _PARQUET_LIGHTNING_CACHE is not None:
        return _PARQUET_LIGHTNING_CACHE
    with _PARQUET_LIGHTNING_LOCK:
        if _PARQUET_LIGHTNING_CACHE is not None:
            return _PARQUET_LIGHTNING_CACHE
        base = Path(__file__).resolve().parents[3]
        candidates = [
            base / "data" / "marine_data_package" / "marine-data" / "unified" / "marine_features" / "coastal_point_features.parquet",
            base / "data" / "coastal_point_features.parquet",
            Path("data/coastal_point_features.parquet"),
            Path.cwd() / "data" / "coastal_point_features.parquet",
        ]
        target_path = None
        for p in candidates:
            try:
                if p.is_file():
                    target_path = p.resolve()
                    break
            except Exception:
                continue
        if not target_path:
            return None
        try:
            import pyarrow.parquet as pq

            tbl = pq.read_table(
                str(target_path),
                columns=["latitude", "longitude", "olr_wm2", "convective_favorable_derived"],
            )
            _PARQUET_LIGHTNING_CACHE = {
                "lats": tbl["latitude"].to_numpy(),
                "lons": tbl["longitude"].to_numpy(),
                "olrs": tbl["olr_wm2"].to_numpy(),
                "conv": tbl["convective_favorable_derived"].to_numpy(),
            }
            return _PARQUET_LIGHTNING_CACHE
        except Exception as exc:
            logger.debug("danger_agent: failed loading lightning parquet: %s", exc)
            return None


async def fetch_imd_lightning_alert(lat: float, lon: float) -> dict | None:
    """Fetch IMD convective cloud / lightning risk proxy data (T8 #124)."""
    data = _get_coastal_parquet_lightning_data()
    if not data:
        return None
    try:
        import numpy as np

        lats = data["lats"]
        lons = data["lons"]
        olrs = data["olrs"]
        conv = data["conv"]
        dists = (lats - lat) ** 2 + (lons - lon) ** 2
        idx = int(np.argmin(dists))
        min_dist_deg = float(np.sqrt(dists[idx]))
        min_dist_km = min_dist_deg * 111.0
        if min_dist_km > 200.0:
            return None

        olr_val = float(olrs[idx]) if not np.isnan(olrs[idx]) else None
        is_conv = (
            bool(conv[idx])
            if conv[idx] is not None and not (isinstance(conv[idx], float) and np.isnan(conv[idx]))
            else False
        )

        if olr_val is not None:
            if olr_val < 180.0 or (olr_val < 210.0 and is_conv):
                risk = "high"
                desc = f"High convective activity (OLR: {round(olr_val, 1)} W/m²). Severe lightning risk."
            elif olr_val < 240.0 or is_conv:
                risk = "moderate"
                desc = f"Moderate convective clouds (OLR: {round(olr_val, 1)} W/m²). Scattered lightning possible."
            else:
                risk = "low"
                desc = f"Low convective clouds (OLR: {round(olr_val, 1)} W/m²). Minimal lightning risk."
        elif is_conv:
            risk = "moderate"
            desc = "Convective cloud formation detected. Moderate lightning risk."
        else:
            risk = "low"
            desc = "Normal conditions. Lightning risk is low."

        active = risk == "high"
        return {
            "active": active,
            "lightning_risk": risk,
            "description": desc,
            "olr_wm2": olr_val,
            "distance_km": round(min_dist_km, 1),
        }
    except Exception as exc:
        logger.debug("danger_agent: lightning query error: %s", exc)
        return None


async def _check_imd_safe(lat: float, lon: float) -> tuple[bool, list[str]]:
    """
    W2 IMD check wrapper. Returns (is_safe, warnings).
    Falls back to safe if IMD not configured.
    """
    warnings: list[str] = []
    is_safe = True
    try:
        cyclone = await fetch_imd_cyclone_alert(lat, lon)
        if cyclone and cyclone.get("active"):
            is_safe = False
            warnings.append(f"Cyclone warning: {cyclone.get('name','unknown')} within {cyclone.get('distance_km','?')}km")
    except NotImplementedError:
        pass
    except Exception as exc:
        logger.debug("danger_agent: IMD cyclone check failed: %s", exc)

    try:
        lightning = await fetch_imd_lightning_alert(lat, lon)
        if lightning and lightning.get("active"):
            is_safe = False
            warnings.append("Lightning warning active in area")
    except NotImplementedError:
        pass
    except Exception as exc:
        logger.debug("danger_agent: IMD lightning check failed: %s", exc)

    return is_safe, warnings


# ---------------------------------------------------------------------------
# Public API — check_safety + batch
# ---------------------------------------------------------------------------

async def check_safety(
    lat: float,
    lon: float,
    check_eez: bool = True,
    check_mpa: bool = True,
    check_imbl: bool = True,
    check_imd: bool = False,
) -> dict:
    """
    Check if a point is safe for fishing based on geofences and weather alerts.

    Integrate with backend.db.postgis.check_geofence(lat, lon) with 10s timeout
    and fallback to ray-casting polygon checks using local GeoJSON files
    (data/eez.geojson, data/mpa.geojson).

    Args:
        lat: Latitude of the point (WGS84).
        lon: Longitude of the point (WGS84).
        check_eez: Verify EEZ containment. Outside EEZ → danger.
        check_mpa: Check if inside Marine Protected Area. Inside MPA → danger (banned).
        check_imbl: Check 2km proximity to IMBL/EEZ boundary. Within 2km → caution.
        check_imd: Check for IMD cyclone/lightning alerts (W2 stub, default False).

    Returns:
        {
          "is_safe": bool,              # True only if status == "safe"
          "status": "safe"|"caution"|"danger",
          "warnings": list[str],        # human-readable warnings
          "inside_eez": bool,
          "inside_mpa": bool,
          "mpa_name": str | None
        }
        On fallback or missing data, includes warning note but never raises.

    Notes:
        - Per-agent 10s timeout enforced on PostGIS call.
        - Fishing in MPA is strictly banned → status "danger".
        - 2km buffer for IMBL/border limits → status "caution" (unless already danger).
        - Extensible stubs for W2 IMD integration (fetch_imd_cyclone_alert).
    """
    warnings: list[str] = []
    inside_eez: bool = True
    inside_mpa: bool = False
    mpa_name: str | None = None
    distance_to_boundary: float | None = None
    postgis_ok = False

    # Validate inputs — non-numeric or out-of-range is treated as danger
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return {
            "is_safe": False,
            "status": "danger",
            "warnings": ["Invalid coordinates — cannot verify safety"],
            "inside_eez": False,
            "inside_mpa": False,
            "mpa_name": None,
        }

    if not (-90 <= lat_f <= 90 and -180 <= lon_f <= 180):
        return {
            "is_safe": False,
            "status": "danger",
            "warnings": ["Coordinates out of range — outside valid WGS84 bounds"],
            "inside_eez": False,
            "inside_mpa": False,
            "mpa_name": None,
        }

    # ------------------------------------------------------------------
    # 1. Try PostGIS primary path with timeout
    # ------------------------------------------------------------------
    if check_eez or check_mpa:
        try:
            from backend.db.postgis import check_geofence as pg_check_geofence

            try:
                result = await asyncio.wait_for(pg_check_geofence(lat_f, lon_f), timeout=TIMEOUT_S)
            except asyncio.TimeoutError:
                raise TimeoutError(f"PostGIS check_geofence timed out after {TIMEOUT_S}s")

            # PostGIS succeeded
            postgis_ok = True
            inside_eez = bool(result.get("inside_eez", True))
            inside_mpa = bool(result.get("inside_mpa", False))
            mpa_name = result.get("mpa_name")
            # If PostGIS result has no distance, compute via fallback for IMBL buffer
            if check_imbl:
                # Try to compute distance via local file even when PostGIS ok
                try:
                    distance_to_boundary = _fallback_distance_to_imbl(lat_f, lon_f)
                except Exception:
                    distance_to_boundary = None

        except Exception as exc:
            # PostGIS offline or timed out — fall back to ray-casting
            logger.warning("danger_agent: PostGIS check_geofence failed (%s), using ray-casting fallback", exc)
            postgis_ok = False
            # Fallback will be handled below
        except BaseException as exc:
            logger.warning("danger_agent: PostGIS unexpected error %s, fallback", exc)
            postgis_ok = False

    # ------------------------------------------------------------------
    # 2. Fallback ray-casting if PostGIS failed or was skipped
    # ------------------------------------------------------------------
    if not postgis_ok:
        # Always populate inside_eez/inside_mpa/distance for accurate reporting,
        # even when flags are False (classification later respects flags).
        try:
            fb_inside_eez, fb_dist = _fallback_check_eez(lat_f, lon_f)
            multipolygons_eez, _ = _load_cached_geojson("eez", _GEOJSON_CANDIDATES_EEZ)
            multipolygons_imbl, _ = _load_cached_geojson("imbl", _GEOJSON_CANDIDATES_IMBL)
            has_boundary_data = bool(multipolygons_eez or multipolygons_imbl)
            if has_boundary_data:
                inside_eez = fb_inside_eez
                distance_to_boundary = fb_dist
            else:
                if check_eez:
                    warnings.append("EEZ boundary data unavailable — containment check skipped")
                distance_to_boundary = None
        except Exception as exc:
            logger.warning("danger_agent: EEZ fallback failed: %s", exc)
            if check_eez:
                warnings.append("EEZ check unavailable")

        try:
            fb_inside_mpa, fb_mpa_name = _fallback_check_mpa(lat_f, lon_f)
            multipolygons_mpa, _ = _load_cached_geojson("mpa", _GEOJSON_CANDIDATES_MPA)
            has_mpa_data = bool(multipolygons_mpa)
            if has_mpa_data:
                inside_mpa = fb_inside_mpa
                mpa_name = fb_mpa_name
        except Exception as exc:
            logger.warning("danger_agent: MPA fallback failed: %s", exc)
            if check_mpa:
                warnings.append("MPA check unavailable")

        if check_imbl and distance_to_boundary is None:
            try:
                distance_to_boundary = _fallback_distance_to_imbl(lat_f, lon_f)
            except Exception:
                distance_to_boundary = None
    else:
        # PostGIS succeeded — still ensure IMBL distance if not already set and check_imbl
        if check_imbl and distance_to_boundary is None:
            try:
                distance_to_boundary = _fallback_distance_to_imbl(lat_f, lon_f)
            except Exception:
                distance_to_boundary = None
        # If PostGIS succeeded but we didn't get MPA/EEZ due to flags, still fallback for those flags?
        # e.g., check_mpa True but PostGIS was called — already handled. If check_eez False, inside_eez stays True.

    # ------------------------------------------------------------------
    # 3. Apply check_* flags and classify status
    # ------------------------------------------------------------------
    # Respect flags: if flag is False, ignore that check for danger classification
    # but still report inside_eez/inside_mpa fields as detected.

    status = "safe"

    # Priority 1: MPA → danger (strictly banned)
    if check_mpa and inside_mpa:
        status = "danger"
        name_str = mpa_name or "Protected Area"
        warnings.append(f"Inside Marine Protected Area: {name_str} — fishing strictly banned")

    # Priority 2: Outside EEZ → danger
    elif check_eez and not inside_eez:
        status = "danger"
        warnings.append("Outside Indian Exclusive Economic Zone — fishing not permitted")

    # Priority 3: IMBL 2km buffer → caution (only if not already danger)
    if status != "danger" and check_imbl and distance_to_boundary is not None:
        if distance_to_boundary <= IMBL_BUFFER_KM:
            # Only caution if inside EEZ; outside already danger
            if inside_eez or not check_eez:
                status = "caution"
                warnings.append(f"Within {IMBL_BUFFER_KM:.0f}km of International Maritime Boundary Line — risk of crossing ({distance_to_boundary:.1f}km to boundary)")

    # ------------------------------------------------------------------
    # 4. Lightning & Convective Check (T8 #124)
    # ------------------------------------------------------------------
    lightning_info = None
    try:
        lightning_info = await fetch_imd_lightning_alert(lat_f, lon_f)
    except Exception as exc:
        logger.debug("danger_agent: fetch_imd_lightning_alert error: %s", exc)

    if lightning_info:
        l_risk = lightning_info.get("lightning_risk")
        if l_risk == "high" or lightning_info.get("active"):
            warnings.append(f"Lightning warning: {lightning_info.get('description', 'High convective activity; severe lightning likely')}")
            status = "danger"

    # ------------------------------------------------------------------
    # 5. W2 IMD extensible stub (cyclone)
    # ------------------------------------------------------------------
    if check_imd:
        try:
            imd_safe, imd_warnings = await _check_imd_safe(lat_f, lon_f)
            if imd_warnings:
                warnings.extend(imd_warnings)
            if not imd_safe:
                status = "danger"
        except Exception as exc:
            logger.debug("danger_agent: IMD check error: %s", exc)

    is_safe = (status == "safe")

    return {
        "is_safe": is_safe,
        "status": status,
        "warnings": warnings,
        "inside_eez": bool(inside_eez),
        "inside_mpa": bool(inside_mpa),
        "mpa_name": mpa_name,
        "lightning_risk": lightning_info.get("lightning_risk") if lightning_info else None,
        "lightning_description": lightning_info.get("description") if lightning_info else None,
    }


async def check_safety_batch(
    points: list[dict | tuple | list],
    check_eez: bool = True,
    check_mpa: bool = True,
    check_imbl: bool = True,
    check_imd: bool = False,
) -> list[dict]:
    """
    Batch verification helper for orchestrator — checks multiple points concurrently.

    Args:
        points: List of points, each as:
            - dict with "lat"/"lon" or "latitude"/"longitude" or GeoJSON Feature
            - tuple/list [lat, lon] or [lon, lat] (detects GeoJSON order via magnitude? expects [lat,lon] if first |value| <=90)
        check_eez/check_mpa/check_imbl/check_imd: forwarded to check_safety.

    Returns:
        List of danger_agent result dicts in SAME order as input.
        Each dict has {is_safe, status, warnings, inside_eez, inside_mpa, mpa_name}
        plus {"lat": float|None, "lon": float|None} for traceability.
    """
    if not points:
        return []

    async def _check_one(idx: int, pt: Any) -> dict:
        lat: float | None = None
        lon: float | None = None
        try:
            if isinstance(pt, dict):
                # GeoJSON Feature?
                geom = pt.get("geometry")
                if isinstance(geom, dict) and isinstance(geom.get("coordinates"), (list, tuple)):
                    coords = geom["coordinates"]
                    if len(coords) >= 2:
                        # GeoJSON is [lon, lat]
                        lon = float(coords[0])
                        lat = float(coords[1])
                    # Also check properties for lat/lon override
                if lat is None:
                    for k in ("lat", "latitude", "y"):
                        if pt.get(k) is not None:
                            lat = float(pt[k])
                            break
                    if lat is None:
                        props = pt.get("properties") if isinstance(pt.get("properties"), dict) else None
                        if props:
                            for k in ("lat", "latitude"):
                                if props.get(k) is not None:
                                    lat = float(props[k])
                                    break
                if lon is None:
                    for k in ("lon", "lng", "longitude", "x"):
                        if pt.get(k) is not None:
                            lon = float(pt[k])
                            break
                    if lon is None:
                        props = pt.get("properties") if isinstance(pt.get("properties"), dict) else None
                        if props:
                            for k in ("lon", "lng", "longitude"):
                                if props.get(k) is not None:
                                    lon = float(props[k])
                                    break
            elif isinstance(pt, (list, tuple)) and len(pt) >= 2:
                # Heuristic: assume [lat, lon] if first value looks like lat (|lat|<=90)
                # Otherwise treat as [lon, lat] for GeoJSON compat
                # Default to [lat, lon] per spec
                try:
                    a, b = float(pt[0]), float(pt[1])
                    # If a is plausible lat and b plausible lon, assume [lat, lon]
                    # This is the common caller convention
                    lat, lon = a, b
                except (TypeError, ValueError):
                    lat, lon = None, None
            else:
                lat, lon = None, None
        except Exception:
            lat, lon = None, None

        if lat is None or lon is None:
            return {
                "is_safe": False,
                "status": "danger",
                "warnings": ["Invalid point — missing lat/lon"],
                "inside_eez": False,
                "inside_mpa": False,
                "mpa_name": None,
                "lat": lat,
                "lon": lon,
            }

        try:
            res = await asyncio.wait_for(
                check_safety(lat, lon, check_eez=check_eez, check_mpa=check_mpa, check_imbl=check_imbl, check_imd=check_imd),
                timeout=TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            res = {
                "is_safe": False,
                "status": "danger",
                "warnings": [f"Danger check timed out after {TIMEOUT_S}s — treat as danger (fail-closed)"],
                "inside_eez": False,
                "inside_mpa": False,
                "mpa_name": None,
            }
        except Exception as exc:
            res = {
                "is_safe": False,
                "status": "danger",
                "warnings": [f"Danger check error: {exc} — treat as danger (fail-closed)"],
                "inside_eez": False,
                "inside_mpa": False,
                "mpa_name": None,
            }
        # Attach coordinates for traceability
        res["lat"] = lat
        res["lon"] = lon
        return res

    tasks = [_check_one(idx, pt) for idx, pt in enumerate(points)]
    # asyncio.gather with per-task timeout already, use gather without global timeout
    results = await asyncio.gather(*tasks)
    return list(results)


# ---------------------------------------------------------------------------
# Legacy alias for router compatibility
# ---------------------------------------------------------------------------

async def check_geofence(lat: float, lon: float) -> dict:
    """Alias to check_safety for backend/routers/geofence.py compatibility."""
    return await check_safety(lat, lon)
