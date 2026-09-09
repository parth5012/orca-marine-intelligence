"""
PostGIS Spatial Query Helpers & Ingestion Utilities
Owner: M-B (Data Extractors & Storage)
Module: backend/db/postgis.py

Provides spatial database queries for:
1. Nearest PFZ fishing zones (ST_DWithin & ST_Distance)
2. Geofencing checks (EEZ international boundaries & Marine Protected Areas)
3. Bulk upsert of daily INCOIS GeoJSON features
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import date
from sqlalchemy import select, func, cast, text
from sqlalchemy.dialects.postgresql import insert
from geoalchemy2 import Geometry
from geoalchemy2.functions import ST_DWithin, ST_Distance, ST_Contains, ST_MakePoint, ST_SetSRID

from backend.db.session import AsyncSessionLocal, engine, init_db
from backend.db.models import PFZZone, EEZBoundary, MPABoundary, CoastalPort

logger = logging.getLogger(__name__)


async def upsert_pfz_features(features: List[Dict[str, Any]], valid_date: Optional[date] = None) -> int:
    """
    Upsert daily INCOIS PFZ GeoJSON Point features into PostGIS.
    Uses PostgreSQL ON CONFLICT (zone_id) DO UPDATE.
    """
    if not features:
        return 0

    if valid_date is None:
        valid_date = date.today()

    rows = []
    for idx, feat in enumerate(features):
        props = feat.get("properties", {})
        geom = feat.get("geometry", {})
        coords = geom.get("coordinates", [0.0, 0.0])
        lon, lat = coords[0], coords[1]

        base_zone_id = props.get("zone_id") or f"{props.get('sector', 'SEC')}_{props.get('place', 'zone')}_{idx}"
        date_str = str(valid_date)
        if date_str not in base_zone_id:
            zone_id = f"{base_zone_id}_{date_str}"
        else:
            zone_id = base_zone_id
        zone_id = zone_id[:64]
        bearing_val = props.get("bearing")
        try:
            bearing_int = int(bearing_val) if bearing_val is not None else None
        except (ValueError, TypeError):
            bearing_int = None

        dist_val = props.get("distance_km") or props.get("distance")
        try:
            # Handle distance ranges like "14-19" or single floats
            if isinstance(dist_val, str) and "-" in dist_val:
                parts = dist_val.split("-")
                dist_float = (float(parts[0]) + float(parts[1])) / 2.0
            else:
                dist_float = float(dist_val) if dist_val is not None else None
        except (ValueError, TypeError):
            dist_float = None

        rows.append({
            "zone_id": zone_id,
            "place": props.get("place", "Unknown"),
            "sector": props.get("sector", "SEC000"),
            "sector_name": props.get("sector_name", "COASTAL"),
            "direction": props.get("dir") or props.get("direction"),
            "bearing": bearing_int,
            "depth_range": str(props.get("depth", "")),
            "distance_km": dist_float,
            "lat": lat,
            "lon": lon,
            "geom": f"SRID=4326;POINT({lon} {lat})",
            "intensity": props.get("intensity", "medium"),
            "source": props.get("source", "incois_textdata"),
            "valid_date": valid_date,
        })

    async with AsyncSessionLocal() as session:
        stmt = insert(PFZZone).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[PFZZone.zone_id],
            set_={
                "bearing": stmt.excluded.bearing,
                "direction": stmt.excluded.direction,
                "depth_range": stmt.excluded.depth_range,
                "distance_km": stmt.excluded.distance_km,
                "lat": stmt.excluded.lat,
                "lon": stmt.excluded.lon,
                "geom": stmt.excluded.geom,
                "valid_date": stmt.excluded.valid_date,
            }
        )
        result = await session.execute(stmt)
        await session.commit()
    return len(rows)


# ---------------------------------------------------------------------------
# PostGIS Fast-Check Circuit Breaker & Health State (Ticket #76)
# ---------------------------------------------------------------------------
_db_degraded: bool = False
_db_last_failure_time: float = 0.0
_CIRCUIT_BREAKER_COOLDOWN_SECONDS: float = 30.0


def is_db_degraded() -> bool:
    """Return True if PostGIS database is currently in degraded state."""
    global _db_degraded, _db_last_failure_time
    if _db_degraded:
        import time

        if time.time() - _db_last_failure_time > _CIRCUIT_BREAKER_COOLDOWN_SECONDS:
            _db_degraded = False
            return False
        return True
    return False


def set_db_degraded(degraded: bool = True) -> None:
    """Set PostGIS database degraded state."""
    global _db_degraded, _db_last_failure_time
    _db_degraded = degraded
    if degraded:
        import time

        _db_last_failure_time = time.time()
    else:
        _db_last_failure_time = 0.0


def reset_circuit_breaker() -> None:
    """Reset PostGIS circuit breaker to healthy state."""
    set_db_degraded(False)


async def ping_postgis(timeout: float = 0.5) -> bool:
    """Fast health check for PostGIS database connection with timeout."""
    import asyncio

    try:
        async def _check():
            async with AsyncSessionLocal() as session:
                await session.execute(text("SELECT 1"))
                return True

        res = await asyncio.wait_for(_check(), timeout=timeout)
        set_db_degraded(False)
        return bool(res)
    except Exception as exc:
        set_db_degraded(True)
        logger.warning("ping_postgis: database unreachable or timed out (%s)", exc)
        return False


async def find_pfz_near(
    lat: float,
    lon: float,
    radius_km: float = 80.0,
    limit: int = 5
) -> List[Dict[str, Any]]:
    """
    Find nearest Potential Fishing Zones within radius_km using PostGIS spatial indexes.
    Calculates exact spherical distance on Earth ellipsoid.
    """
    async with AsyncSessionLocal() as session:
        # Create user reference point in WGS84
        user_point = func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326)
        user_geog = cast(user_point, Geometry(geometry_type="GEOGRAPHY"))
        zone_geog = cast(PFZZone.geom, Geometry(geometry_type="GEOGRAPHY"))

        radius_meters = radius_km * 1000.0

        query = (
            select(
                PFZZone,
                func.ST_Distance(zone_geog, user_geog).label("distance_meters")
            )
            .where(func.ST_DWithin(zone_geog, user_geog, radius_meters))
            .order_by("distance_meters")
            .limit(limit)
        )

        result = await session.execute(query)
        spots = []
        for zone, dist_m in result.all():
            spots.append({
                "zone_id": zone.zone_id,
                "place": zone.place,
                "sector": zone.sector_name,
                "bearing": zone.bearing,
                "direction": zone.direction,
                "depth_range": zone.depth_range,
                "lat": zone.lat,
                "lon": zone.lon,
                "distance_from_user_km": round(dist_m / 1000.0, 1),
            })
        return spots


async def check_geofence(lat: float, lon: float) -> Dict[str, Any]:
    """
    Check if a boat or fishing point falls within safety zones:
    1. Is it inside India's Exclusive Economic Zone (EEZ)?
    2. How close is it to the nearest international border?
    3. Is it inside any Marine Protected Area (MPA) where fishing is forbidden?
    """
    async with AsyncSessionLocal() as session:
        boat_point = func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326)
        boat_geog = cast(boat_point, Geometry(geometry_type="GEOGRAPHY"))

        # 1. Check EEZ containment
        eez_query = select(EEZBoundary).where(
            EEZBoundary.country == "India",
            func.ST_Contains(EEZBoundary.geom, boat_point)
        ).limit(1)
        eez_result = await session.execute(eez_query)
        inside_eez = eez_result.scalar_one_or_none() is not None

        # 2. Check MPA containment
        mpa_query = select(MPABoundary).where(
            func.ST_Contains(MPABoundary.geom, boat_point)
        ).limit(1)
        mpa_result = await session.execute(mpa_query)
        mpa = mpa_result.scalar_one_or_none()
        inside_mpa = mpa is not None
        mpa_name = mpa.mpa_name if mpa else None

        # Determine safety status
        if not inside_eez or inside_mpa:
            status = "danger"
            reason = f"Inside forbidden zone: {mpa_name}" if inside_mpa else "Outside Indian Exclusive Economic Zone!"
        else:
            status = "safe"
            reason = "Inside safe Indian territorial waters (no MPA violation)"

        return {
            "inside_eez": inside_eez,
            "inside_mpa": inside_mpa,
            "mpa_name": mpa_name,
            "status": status,
            "reason": reason,
        }


MVT_LAYER_QUERIES: Dict[str, str] = {
    "pfz": """
        WITH mvtgeom AS (
            SELECT
                ST_AsMVTGeom(
                    ST_Transform(geom, 3857),
                    ST_TileEnvelope(:z, :x, :y),
                    4096,
                    64,
                    true
                ) AS geom,
                zone_id,
                place,
                sector,
                sector_name,
                direction,
                bearing,
                depth_range,
                distance_km,
                lat,
                lon,
                intensity,
                source,
                CAST(valid_date AS TEXT) AS valid_date
            FROM pfz_zones
            WHERE geom && ST_Transform(ST_TileEnvelope(:z, :x, :y), 4326)
        )
        SELECT ST_AsMVT(mvtgeom.*, :layer, 4096, 'geom') FROM mvtgeom;
    """,
    "eez": """
        WITH mvtgeom AS (
            SELECT
                ST_AsMVTGeom(
                    ST_Transform(geom, 3857),
                    ST_TileEnvelope(:z, :x, :y),
                    4096,
                    64,
                    true
                ) AS geom,
                id,
                country,
                boundary_name,
                boundary_type
            FROM eez_boundaries
            WHERE geom && ST_Transform(ST_TileEnvelope(:z, :x, :y), 4326)
        )
        SELECT ST_AsMVT(mvtgeom.*, :layer, 4096, 'geom') FROM mvtgeom;
    """,
    "mpa": """
        WITH mvtgeom AS (
            SELECT
                ST_AsMVTGeom(
                    ST_Transform(geom, 3857),
                    ST_TileEnvelope(:z, :x, :y),
                    4096,
                    64,
                    true
                ) AS geom,
                id,
                mpa_name,
                state,
                restriction_level
            FROM mpa_boundaries
            WHERE geom && ST_Transform(ST_TileEnvelope(:z, :x, :y), 4326)
        )
        SELECT ST_AsMVT(mvtgeom.*, :layer, 4096, 'geom') FROM mvtgeom;
    """,
    "recommendation": """
        WITH mvtgeom AS (
            SELECT
                ST_AsMVTGeom(
                    ST_Transform(geom, 3857),
                    ST_TileEnvelope(:z, :x, :y),
                    4096,
                    64,
                    true
                ) AS geom,
                zone_id,
                place,
                sector,
                sector_name,
                direction,
                bearing,
                depth_range,
                distance_km,
                lat,
                lon,
                intensity,
                source,
                CAST(valid_date AS TEXT) AS valid_date
            FROM pfz_zones
            WHERE geom && ST_Transform(ST_TileEnvelope(:z, :x, :y), 4326)
              AND intensity IN ('high', 'medium', 'recommended')
        )
        SELECT ST_AsMVT(mvtgeom.*, :layer, 4096, 'geom') FROM mvtgeom;
    """,
}


async def get_mvt_tile(layer: str, z: int, x: int, y: int) -> Optional[bytes]:
    """
    Generate Mapbox Vector Tile (MVT) binary protobuf for a given layer and tile coordinate.
    Queries PostGIS using ST_TileEnvelope and ST_AsMVT.
    Returns bytes (empty b"" if no features exist in tile), or None on database error.
    """
    sql = MVT_LAYER_QUERIES.get(layer)
    if not sql:
        return None
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text(sql),
                {"z": z, "x": x, "y": y, "layer": layer},
            )
            raw = result.scalar()
            if raw is None:
                return b""
            if isinstance(raw, bytes):
                return raw
            if isinstance(raw, (bytearray, memoryview)):
                return bytes(raw)
            if isinstance(raw, str):
                return raw.encode("latin1")
            return b""
    except Exception as e:
        logger.warning("PostGIS ST_AsMVT query failed for %s (%d/%d/%d): %s", layer, z, x, y, e)
        return None
