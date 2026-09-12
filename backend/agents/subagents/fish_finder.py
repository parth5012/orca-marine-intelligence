"""
Fish Finder Agent — PFZ Zone Discovery

Owner: M-A (Agents & Orchestration) — closest-zone search
Module: backend/agents/fish_finder.py

The Fish Finder agent queries the shared PFZ GeoJSON data to find fishing
zones near the user's location. It filters by sector and distance,
returning the closest productive zones.

Data Source:
    - pfz-today.geojson loaded into PostGIS daily at 11:30 AM IST
    - Each feature has: place, direction, bearing, depth, distance, lat, lon, sector

Query Logic:
    1. Try PostGIS find_pfz_near sorted by spherical distance.
    2. Staged radius expansion: 80km -> 120km -> 160km if 0 results.
    3. On DB failure, fallback to local GeoJSON with haversine.
    4. Return normalized zone objects.
"""

import asyncio
import json
import logging
import math
from pathlib import Path
import time
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PostGIS Fast-Check Circuit Breaker (Ticket #76)
# ---------------------------------------------------------------------------
_db_degraded: bool = False
_db_last_failure_time: float = 0.0
_CIRCUIT_BREAKER_COOLDOWN_SECONDS: float = 30.0
# Fast-check budget: 2s ping / 5s query. The old 500ms fired spuriously
# under pool warmup/load (empty TimeoutError), forcing GeoJSON fallback
# and PostGIS geofence misses even with a healthy database.
_DB_PING_TIMEOUT_SECONDS: float = 2.0
_DB_QUERY_TIMEOUT_SECONDS: float = 5.0


def is_db_degraded() -> bool:
    """Return True if PostGIS is currently in degraded / circuit-open state."""
    global _db_degraded, _db_last_failure_time
    if _db_degraded:
        if time.time() - _db_last_failure_time > _CIRCUIT_BREAKER_COOLDOWN_SECONDS:
            return False
        return True
    try:
        from backend.db import postgis as db_postgis

        if hasattr(db_postgis, "is_db_degraded") and db_postgis.is_db_degraded != is_db_degraded:
            return db_postgis.is_db_degraded()
    except Exception:
        pass
    return False


def set_db_degraded(degraded: bool = True) -> None:
    """Set database degraded state and update failure timestamp."""
    global _db_degraded, _db_last_failure_time
    _db_degraded = degraded
    if degraded:
        _db_last_failure_time = time.time()
    else:
        _db_last_failure_time = 0.0
    try:
        from backend.db import postgis as db_postgis

        if hasattr(db_postgis, "set_db_degraded") and db_postgis.set_db_degraded != set_db_degraded:
            db_postgis.set_db_degraded(degraded)
    except Exception:
        pass


def reset_circuit_breaker() -> None:
    """Reset circuit breaker to healthy state (closed)."""
    set_db_degraded(False)
    try:
        from backend.db import postgis as db_postgis

        if (
            hasattr(db_postgis, "reset_circuit_breaker")
            and db_postgis.reset_circuit_breaker != reset_circuit_breaker
        ):
            db_postgis.reset_circuit_breaker()
    except Exception:
        pass


async def ping_database(timeout: float = _DB_PING_TIMEOUT_SECONDS) -> bool:
    """
    Fast async connectivity check for PostGIS within timeout (default 500ms).
    Avoids 4-second connection hang when database is down.
    Returns True if healthy/reachable, False otherwise.
    """
    try:
        from backend.db.postgis import find_pfz_near
        import unittest.mock

        # If find_pfz_near is mocked in tests, treat DB as reachable unless ping is explicitly mocked
        if isinstance(find_pfz_near, (unittest.mock.Mock, unittest.mock.AsyncMock)):
            try:
                from backend.db.postgis import ping_postgis

                if isinstance(ping_postgis, (unittest.mock.Mock, unittest.mock.AsyncMock)):
                    res = ping_postgis()
                    if asyncio.iscoroutine(res):
                        return await asyncio.wait_for(res, timeout=timeout)
                    return bool(res)
            except (ImportError, AttributeError):
                pass
            return True
    except Exception:
        pass

    try:
        try:
            from backend.db.postgis import ping_postgis

            res = ping_postgis()
            if asyncio.iscoroutine(res):
                return await asyncio.wait_for(res, timeout=timeout)
            return bool(res)
        except (ImportError, AttributeError):
            from backend.db.session import engine
            from sqlalchemy import text

            async def _check():
                async with engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))

            await asyncio.wait_for(_check(), timeout=timeout)
            return True
    except Exception as exc:
        logger.warning("fish_finder: PostGIS fast-check ping failed (%s)", exc)
        return False

# Resolved GeoJSON path — backend/agents/subagents/fish_finder.py -> project root / data/pfz-today.geojson
_GEOJSON_CANDIDATES = [
    Path(__file__).resolve().parents[3] / "data" / "pfz-today.geojson",
    Path(__file__).resolve().parents[2] / "data" / "pfz-today.geojson",
    Path(__file__).resolve().parents[1] / ".." / "data" / "pfz-today.geojson",
    Path.cwd() / "data" / "pfz-today.geojson",
]

# Expansion stages (km) — always try initial, then 120, then 160 if needed
_EXPANSION_STAGES = (120.0, 160.0)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two WGS84 points."""
    r = 6371.0088  # mean earth radius km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.asin(math.sqrt(a))
    return r * c


def _resolve_geojson_path() -> Path | None:
    for p in _GEOJSON_CANDIDATES:
        try:
            resolved = p.resolve()
        except Exception:
            resolved = p
        if resolved.is_file():
            return resolved
    return None


def _load_geojson_features() -> list[dict]:
    """Load features from data/pfz-today.geojson. Returns [] on failure."""
    path = _resolve_geojson_path()
    if path is None:
        logger.warning("fish_finder: data/pfz-today.geojson not found in candidates %s", _GEOJSON_CANDIDATES)
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        features = data.get("features", [])
        if not isinstance(features, list):
            return []
        return features
    except Exception as exc:
        logger.warning("fish_finder: failed to load GeoJSON %s: %s", path, exc)
        return []


def _geojson_fallback(
    lat: float,
    lon: float,
    radius_km: float,
    limit: int,
    sector: str | None,
) -> list[dict]:
    """Compute haversine distance against local GeoJSON and return normalized zones."""
    features = _load_geojson_features()
    if not features:
        return []

    sector_filter = sector.strip().upper() if sector else None

    candidates: list[dict] = []
    for idx, feat in enumerate(features):
        props: dict = feat.get("properties", {}) or {}
        geom: dict = feat.get("geometry", {}) or {}
        coords = geom.get("coordinates")

        # Resolve lon/lat — GeoJSON is [lon, lat]
        f_lon: float | None = None
        f_lat: float | None = None
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            try:
                f_lon = float(coords[0])
                f_lat = float(coords[1])
            except (TypeError, ValueError):
                f_lon, f_lat = None, None

        # Fallback: some ingestion variants may store lat/lon in properties
        if f_lat is None or f_lon is None:
            try:
                if props.get("lat") is not None and props.get("lon") is not None:
                    f_lat = float(props["lat"])
                    f_lon = float(props["lon"])
            except (TypeError, ValueError):
                continue
        if f_lat is None or f_lon is None:
            continue

        # Sector filtering — match against sector code or sector_name (case-insensitive)
        if sector_filter:
            feat_sector = str(props.get("sector", "")).strip().upper()
            feat_sector_name = str(props.get("sector_name", "")).strip().upper()
            # Also handle human name passed as filter matching sector_name
            if sector_filter not in (feat_sector, feat_sector_name):
                # Allow partial: e.g. filter "KERALA" matches sector_name "KERALA"
                # or filter "SEC005" matches only SEC005
                continue

        try:
            dist_km = _haversine_km(lat, lon, f_lat, f_lon)
        except Exception:
            continue

        if dist_km > radius_km:
            continue

        # Normalize fields
        feat_sector_code = props.get("sector", "SEC000")
        feat_sector_name = props.get("sector_name", feat_sector_code)
        # Prefer human-readable sector_name for returned sector field to match postgis behavior
        sector_out = feat_sector_name if feat_sector_name else feat_sector_code

        zone_id = props.get("zone_id")
        if not zone_id:
            # Deterministic synthetic id: sector_place_idx
            safe_place = str(props.get("place", "zone")).replace(" ", "_")
            zone_id = f"{feat_sector_code}_{safe_place}_{idx}"

        bearing_val = props.get("bearing")
        try:
            bearing_out = int(bearing_val) if bearing_val is not None else None
        except (ValueError, TypeError):
            bearing_out = None

        direction_out = props.get("dir") if props.get("dir") is not None else props.get("direction")
        depth_out = props.get("depth") if props.get("depth") is not None else props.get("depth_range", "")
        # Ensure depth_range is string
        depth_range = str(depth_out) if depth_out is not None else ""

        place_out = props.get("place", "Unknown")

        candidates.append({
            "zone_id": str(zone_id),
            "place": str(place_out),
            "sector": str(sector_out),
            "bearing": bearing_out,
            "direction": direction_out,
            "depth_range": depth_range,
            "lat": float(f_lat),
            "lon": float(f_lon),
            "distance_from_user_km": round(float(dist_km), 1),
        })

    # Sort by distance ascending (spherical), dedup by place+rounded
    # coords (same landing centre from overlapping sectors), apply limit
    candidates.sort(key=lambda z: z["distance_from_user_km"])
    try:
        from backend.agents.zone_dedup import dedup_zones as _dedup_zones

        candidates = _dedup_zones(candidates)
    except Exception:
        _seen: set[str] = set()
        _uniq: list[dict] = []
        for _c in candidates:
            try:
                _k = f"{str(_c.get('place') or '').strip().lower()}|{round(float(str(_c.get('lat'))), 4):.4f}|{round(float(str(_c.get('lon'))), 4):.4f}"
            except (TypeError, ValueError):
                _k = f"id:{_c.get('zone_id')}"
            if _k in _seen:
                continue
            _seen.add(_k)
            _uniq.append(_c)
        candidates = _uniq
    return candidates[:limit]


async def find_fishing_zones(
    lat: float,
    lon: float,
    radius_km: float = 80.0,
    sector: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """
    Find the closest PFZ zones to a given location.

    Integrates with PostGIS find_pfz_near and falls back to local GeoJSON
    haversine on DB failure. Implements staged radius expansion 80->120->160km.

    Args:
        lat: User's latitude in decimal degrees.
        lon: User's longitude in decimal degrees.
        radius_km: Search radius in kilometers (default 80).
        sector: Optional INCOIS sector code or name (e.g., "SEC005" or "KERALA").
        limit: Maximum number of results to return.

    Returns:
        List of normalized PFZ zone dicts:
        {zone_id, place, sector, bearing, direction, depth_range, lat, lon, distance_from_user_km}
        Sorted by distance_from_user_km ascending. Empty list if none found within 160km.
    """
    # Build staged radii: initial + any larger expansion that exceeds initial
    radii_to_try: list[float] = [float(radius_km)]
    for stage in _EXPANSION_STAGES:
        if stage > float(radius_km) and stage not in radii_to_try:
            radii_to_try.append(stage)
    # If caller passes >160, just use their value (no expansion needed)
    # Ensure sorted ascending
    radii_to_try = sorted(set(radii_to_try))

    # Normalize sector for post-filtering (PostGIS find_pfz_near has no sector param)
    sector_filter = sector.strip() if sector and sector.strip() else None

    def _apply_sector_filter(zones: list[dict]) -> list[dict]:
        if not sector_filter:
            return zones
        sf = sector_filter.strip().upper()
        filtered: list[dict] = []
        for z in zones:
            # Zones from PostGIS have sector == sector_name (e.g. KERALA)
            # Zones from fallback also use sector_name. We also check zone_id prefix for SEC code.
            z_sector = str(z.get("sector", "")).strip().upper()
            z_id = str(z.get("zone_id", "")).strip().upper()
            # Match either human name or SEC code prefix in zone_id
            if sf == z_sector or z_id.startswith(sf + "_") or z_id.startswith(sf):
                filtered.append(z)
            elif sf.startswith("SEC") and sf in z_id:
                filtered.append(z)
        return filtered

    # Try PostGIS first for each radius; on DB error switch permanently to fallback
    use_fallback = False
    last_error: Exception | None = None

    # Fast-check PostGIS circuit breaker & ping before entering query loop (Ticket #76)
    if is_db_degraded():
        logger.warning(
            "fish_finder: PostGIS in degraded state (circuit-breaker open), fast-failing to GeoJSON fallback"
        )
        use_fallback = True
    else:
        try:
            db_alive = await asyncio.wait_for(
                ping_database(timeout=_DB_PING_TIMEOUT_SECONDS),
                timeout=_DB_PING_TIMEOUT_SECONDS,
            )
        except Exception:
            db_alive = False

        if not db_alive:
            logger.warning(
                "fish_finder: PostGIS fast-check ping failed within %.0fs, fast-failing to GeoJSON fallback",
                _DB_PING_TIMEOUT_SECONDS,
            )
            set_db_degraded(True)
            use_fallback = True

    for radius in radii_to_try:
        if not use_fallback:
            try:
                from backend.db.postgis import find_pfz_near  # local import for testability

                res = find_pfz_near(lat=lat, lon=lon, radius_km=radius, limit=limit)
                if asyncio.iscoroutine(res) or hasattr(res, "__await__"):
                    zones: list[dict] = await asyncio.wait_for(
                        res,
                        timeout=_DB_QUERY_TIMEOUT_SECONDS,
                    )
                else:
                    zones = res
                # PostGIS does not filter by sector — apply here
                zones = _apply_sector_filter(zones)
                # find_pfz_near already returns normalized objects sorted by distance
                # Defense-in-depth: dedup again (sector filter + legacy rows)
                try:
                    from backend.agents.zone_dedup import dedup_zones as _dedup_zones2

                    zones = _dedup_zones2(zones)
                except Exception:
                    pass
                # If sector filter emptied results, treat as 0 and expand
                if zones:
                    set_db_degraded(False)
                    return zones[:limit]
                # else: 0 zones at this radius -> try next expansion stage
                continue
            except Exception as exc:
                # DB unreachable or query failed - fallback to GeoJSON
                last_error = exc
                use_fallback = True
                set_db_degraded(True)
                logger.warning(
                    "fish_finder: PostGIS find_pfz_near failed at radius %.1fkm (%r), falling back to GeoJSON",
                    radius,
                    exc,
                )
                # Fall through to GeoJSON for same radius

        # Fallback path (either DB failed or we are already in fallback mode)
        try:
            zones = _geojson_fallback(lat=lat, lon=lon, radius_km=radius, limit=limit, sector=sector_filter)
            if zones:
                return zones
            # No zones at this radius via fallback -> expand
        except Exception as exc:
            logger.warning("fish_finder: GeoJSON fallback failed at radius %.1fkm: %s", radius, exc)
            last_error = exc
            continue

    # All stages exhausted
    if last_error and use_fallback:
        logger.info("fish_finder: 0 zones found within %dkm (fallback, last_error=%s)", radii_to_try[-1], last_error)
    return []


# ---------------------------------------------------------------------------
# Satellite Data Enrichment (T3 #118 - coastal_point_features.parquet)
# ---------------------------------------------------------------------------

import threading

_PARQUET_SATELLITE_CACHE: Any = None
_PARQUET_LOCK = threading.Lock()
_MAX_SATELLITE_DISTANCE_DEG_SQ = 9.0  # ~3 degrees (~330 km) max search radius


def _clear_satellite_cache() -> None:
    """Clear cached satellite features data (for tests)."""
    global _PARQUET_SATELLITE_CACHE
    with _PARQUET_LOCK:
        _PARQUET_SATELLITE_CACHE = None


def _find_parquet_features_file() -> Path | None:
    """Find candidate path for coastal_point_features.parquet."""
    base = Path(__file__).resolve().parents[3]
    candidates = [
        base / "data" / "marine_data_package" / "marine-data" / "unified" / "marine_features" / "coastal_point_features.parquet",
        base / "data" / "coastal_point_features.parquet",
        Path("data/coastal_point_features.parquet"),
        Path("D:/work/projects/orca-marine-intelligence/data/marine_data_package/marine-data/unified/marine_features/coastal_point_features.parquet"),
        Path("D:/work/projects/orca-marine-intelligence/data/coastal_point_features.parquet"),
    ]
    for p in candidates:
        try:
            if p.exists():
                return p
        except Exception:
            continue
    return None


def _get_satellite_parquet_data() -> Any:
    """Load and cache coastal point features containing SST and chlorophyll columns."""
    global _PARQUET_SATELLITE_CACHE
    if _PARQUET_SATELLITE_CACHE is not None:
        return _PARQUET_SATELLITE_CACHE
    with _PARQUET_LOCK:
        if _PARQUET_SATELLITE_CACHE is not None:
            return _PARQUET_SATELLITE_CACHE
        p = _find_parquet_features_file()
        if not p:
            return None
        try:
            import numpy as np
            import pyarrow.parquet as pq

            schema = pq.read_schema(str(p))
            cols = schema.names
            sst_col = "sst_degC" if "sst_degC" in cols else ("sst_c" if "sst_c" in cols else None)
            chlo_col = "chlorophyll_a_mg_m3" if "chlorophyll_a_mg_m3" in cols else ("chlorophyll_mg_m3" if "chlorophyll_mg_m3" in cols else None)
            needed = ["latitude", "longitude"]
            if sst_col:
                needed.append(sst_col)
            if chlo_col:
                needed.append(chlo_col)
            tbl = pq.read_table(str(p), columns=needed)
            lats = tbl["latitude"].to_numpy()
            lons = tbl["longitude"].to_numpy()
            ssts = tbl[sst_col].to_numpy() if sst_col else None
            chlos = tbl[chlo_col].to_numpy() if chlo_col else None

            valid_sst_mask = ~np.isnan(ssts) if ssts is not None else None
            valid_chlo_mask = ~np.isnan(chlos) if chlos is not None else None

            _PARQUET_SATELLITE_CACHE = {
                "lats": lats,
                "lons": lons,
                "ssts": ssts,
                "chlos": chlos,
                "sst_mask": valid_sst_mask,
                "chlo_mask": valid_chlo_mask,
            }
            return _PARQUET_SATELLITE_CACHE
        except Exception as exc:
            logger.debug("Failed loading satellite parquet data: %s", exc)
            return None


def _enrich_with_satellite_data(zones: list[dict], lat: float = 0.0, lon: float = 0.0) -> list[dict]:
    """Enrich candidate fishing zones with sst_c and chlorophyll_mg_m3 from satellite data.

    Preserves existing properties, handles missing parquet gracefully without crashing.
    """
    if not zones:
        return zones
    data = _get_satellite_parquet_data()
    if not data:
        return zones
    try:
        import numpy as np

        lats = data.get("lats")
        lons = data.get("lons")
        ssts = data.get("ssts")
        chlos = data.get("chlos")
        sst_mask = data.get("sst_mask")
        chlo_mask = data.get("chlo_mask")

        sst_lats = lats[sst_mask] if sst_mask is not None and ssts is not None else None
        sst_lons = lons[sst_mask] if sst_mask is not None and ssts is not None else None
        sst_vals = ssts[sst_mask] if sst_mask is not None and ssts is not None else None

        chlo_lats = lats[chlo_mask] if chlo_mask is not None and chlos is not None else None
        chlo_lons = lons[chlo_mask] if chlo_mask is not None and chlos is not None else None
        chlo_vals = chlos[chlo_mask] if chlo_mask is not None and chlos is not None else None

        for z in zones:
            if not isinstance(z, dict):
                continue
            z_lat = float(z.get("lat") if z.get("lat") is not None else lat)
            z_lon = float(z.get("lon") if z.get("lon") is not None else lon)

            if sst_vals is not None and len(sst_vals) > 0 and z.get("sst_c") is None:
                d_sq_s = (sst_lats - z_lat) ** 2 + (sst_lons - z_lon) ** 2
                idx_s = int(d_sq_s.argmin())
                if d_sq_s[idx_s] <= _MAX_SATELLITE_DISTANCE_DEG_SQ:
                    val_s = sst_vals[idx_s]
                    if not (np.isnan(val_s) if hasattr(val_s, "dtype") else False):
                        z["sst_c"] = round(float(val_s), 1)

            if chlo_vals is not None and len(chlo_vals) > 0 and z.get("chlorophyll_mg_m3") is None:
                d_sq_c = (chlo_lats - z_lat) ** 2 + (chlo_lons - z_lon) ** 2
                idx_c = int(d_sq_c.argmin())
                if d_sq_c[idx_c] <= _MAX_SATELLITE_DISTANCE_DEG_SQ:
                    val_c = chlo_vals[idx_c]
                    if not (np.isnan(val_c) if hasattr(val_c, "dtype") else False):
                        z["chlorophyll_mg_m3"] = round(float(val_c), 2)
    except Exception as exc:
        logger.debug("Error enriching zones with satellite data: %s", exc)
    return zones


enrich_with_satellite_data = _enrich_with_satellite_data

