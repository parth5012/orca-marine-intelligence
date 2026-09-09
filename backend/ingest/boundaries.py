"""
EEZ, MPA, and IMBL Boundary Ingest and Spatial Validation Layer

Owner: M-B (Data Extractors & Storage) & M-C (Backend API)
Module: backend/ingest/boundaries.py

Loads, caches, and provides high-performance spatial validation against:
- Indian Exclusive Economic Zone (EEZ) boundaries (MarineRegions)
- Marine Protected Areas (MPAs) / Sanctuaries (WDPA)
- International Maritime Boundary Line (IMBL) segments (India-Sri Lanka)

Supports PostGIS upsert when database is connected, with graceful offline fallback.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("orca.boundaries")

# ---------------------------------------------------------------------------
# Constants & Paths
# ---------------------------------------------------------------------------
IMBL_BUFFER_KM = 2.0
IMBL_CAUTION_KM = 5.0
EEZ_CAUTION_KM = 10.0

_BASE_DIR = Path(__file__).resolve().parents[2]

EEZ_CANDIDATES = [
    _BASE_DIR / "data" / "eez.geojson",
    Path.cwd() / "data" / "eez.geojson",
    Path("data/eez.geojson").resolve(),
]

MPA_CANDIDATES = [
    _BASE_DIR / "data" / "mpa.geojson",
    Path.cwd() / "data" / "mpa.geojson",
    Path("data/mpa.geojson").resolve(),
]

IMBL_CANDIDATES = [
    _BASE_DIR / "data" / "imbl.geojson",
    Path.cwd() / "data" / "imbl.geojson",
    Path("data/imbl.geojson").resolve(),
]

# Canonical International Maritime Boundary Line (India-Sri Lanka 1974 & 1976 bilateral agreements)
# Represented as ordered (latitude, longitude) waypoints from Palk Strait south to Gulf of Mannar trijunction
CANONICAL_IMBL_POINTS: List[Tuple[float, float]] = [
    (10.0833, 80.0500),  # Palk Strait Point 1
    (10.0300, 79.9800),  # Point 2
    (9.9500, 79.8800),   # Point 3
    (9.7500, 79.6667),   # Point 4
    (9.6667, 79.5833),   # Point 5
    (9.3667, 79.5333),   # Point 6
    (9.1000, 79.5333),   # Point 7 (Adam's Bridge / Dhanushkodi)
    (9.0000, 79.5167),   # Point 8
    (8.8667, 79.4167),   # Point 9
    (8.4000, 79.0500),   # Point 10
    (8.0000, 78.5000),   # Point 11
    (7.0000, 77.0000),   # Point 12
]


# ---------------------------------------------------------------------------
# Data Models / Segment Wrappers
# ---------------------------------------------------------------------------
class GeoPoint(tuple):
    """Immutable (lat, lon) representation with property and coordinate access."""

    def __new__(cls, lat: float, lon: float):
        return super().__new__(cls, (float(lat), float(lon)))

    @property
    def lat(self) -> float:
        return self[0]

    @property
    def lon(self) -> float:
        return self[1]


class IMBLSegment(tuple):
    """
    Segment between two boundary points (lat1, lon1) and (lat2, lon2).
    Supports tuple unpacking: (p1, p2) or ((lat1, lon1), (lat2, lon2)),
    named attributes (.lat1, .lon1, .lat2, .lon2), and dict-style access.
    """

    def __new__(cls, p1: Any, p2: Any):
        gp1 = p1 if isinstance(p1, GeoPoint) else GeoPoint(p1[0], p1[1])
        gp2 = p2 if isinstance(p2, GeoPoint) else GeoPoint(p2[0], p2[1])
        return super().__new__(cls, (gp1, gp2))

    @property
    def p1(self) -> GeoPoint:
        return self[0]

    @property
    def p2(self) -> GeoPoint:
        return self[1]

    @property
    def lat1(self) -> float:
        return self[0].lat

    @property
    def lon1(self) -> float:
        return self[0].lon

    @property
    def lat2(self) -> float:
        return self[1].lat

    @property
    def lon2(self) -> float:
        return self[1].lon

    @property
    def start(self) -> GeoPoint:
        return self[0]

    @property
    def end(self) -> GeoPoint:
        return self[1]

    def to_dict(self) -> Dict[str, float]:
        return {
            "lat1": self.lat1,
            "lon1": self.lon1,
            "lat2": self.lat2,
            "lon2": self.lon2,
        }

    def __getitem__(self, item: Any) -> Any:
        if isinstance(item, str):
            if item in ("lat1", "lat_1"):
                return self.lat1
            if item in ("lon1", "lon_1"):
                return self.lon1
            if item in ("lat2", "lat_2"):
                return self.lat2
            if item in ("lon2", "lon_2"):
                return self.lon2
            if item in ("p1", "start"):
                return self.p1
            if item in ("p2", "end"):
                return self.p2
            raise KeyError(f"Invalid IMBLSegment key: {item}")
        return super().__getitem__(item)


# In-memory caches for fast sub-millisecond evaluation
_EEZ_CACHE: Optional[List[Dict[str, Any]]] = None
_MPA_CACHE: Optional[List[Dict[str, Any]]] = None
_IMBL_CACHE: Optional[List[IMBLSegment]] = None


def clear_boundaries_cache() -> None:
    """Clear all cached geometries (primarily for testing)."""
    global _EEZ_CACHE, _MPA_CACHE, _IMBL_CACHE
    _EEZ_CACHE = None
    _MPA_CACHE = None
    _IMBL_CACHE = None


# ---------------------------------------------------------------------------
# File Resolution and Parsing Helpers
# ---------------------------------------------------------------------------
def _resolve_candidate(candidates: List[Path]) -> Optional[Path]:
    for cand in candidates:
        try:
            resolved = cand.resolve()
            if resolved.is_file():
                return resolved
        except Exception:
            continue
    return None


def _load_features_from_file(candidates: List[Path]) -> List[Dict[str, Any]]:
    path = _resolve_candidate(candidates)
    if not path:
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            if data.get("type") == "FeatureCollection":
                return data.get("features", [])
            elif data.get("type") == "Feature":
                return [data]
            elif "coordinates" in data:
                return [{"type": "Feature", "properties": {}, "geometry": data}]
        return []
    except Exception as exc:
        logger.warning("Failed to load GeoJSON from %s: %s", path, exc)
        return []


# ---------------------------------------------------------------------------
# Spatial Helper Functions (Ray-casting, Geodesic distance)
# ---------------------------------------------------------------------------
def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great circle distance in kilometers using the Haversine formula."""
    r = 6371.0088
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2.0) ** 2
    )
    return 2.0 * r * math.asin(math.sqrt(min(1.0, a)))


def point_in_ring(lon: float, lat: float, ring: List[Any]) -> bool:
    """
    Ray-casting algorithm to determine if point (lon, lat) lies inside ring.
    Ring is a list of [lon, lat] coordinate pairs.
    """
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

        intersect = ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-12) + xi
        )
        if intersect:
            inside = not inside
        j = i
    return inside


def point_in_polygon(lon: float, lat: float, polygon: List[Any]) -> bool:
    """
    Check if point is inside a GeoJSON Polygon: [exterior_ring, hole_1, hole_2, ...].
    Returns True if strictly inside exterior and not inside any hole.
    """
    if not polygon or not isinstance(polygon, list):
        return False

    exterior = polygon[0]
    if not point_in_ring(lon, lat, exterior):
        return False

    # Check holes
    for hole in polygon[1:]:
        if point_in_ring(lon, lat, hole):
            return False

    return True


def point_in_geometry(lon: float, lat: float, geometry: Dict[str, Any]) -> bool:
    """Check if point is inside a GeoJSON Geometry (Polygon or MultiPolygon)."""
    if not geometry or not isinstance(geometry, dict):
        return False
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if not coords:
        return False

    if gtype == "Polygon":
        return point_in_polygon(lon, lat, coords)
    elif gtype == "MultiPolygon":
        for poly in coords:
            if point_in_polygon(lon, lat, poly):
                return True
    return False


def distance_point_to_segment_km(
    plat: float, plon: float, lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """
    Approximate minimum distance from point (plat, plon) to line segment (lat1, lon1)-(lat2, lon2).
    Uses equirectangular projection centered around mean latitude for fast, high-accuracy geodesics.
    """
    if abs(lat1 - lat2) < 1e-9 and abs(lon1 - lon2) < 1e-9:
        return haversine_km(plat, plon, lat1, lon1)

    mean_lat = math.radians((plat + lat1 + lat2) / 3.0)
    cos_lat = math.cos(mean_lat)

    # Convert coordinates to scaled Cartesian plane (degrees * cos_lat for longitude)
    px = plon * cos_lat
    py = plat
    x1 = lon1 * cos_lat
    y1 = lat1
    x2 = lon2 * cos_lat
    y2 = lat2

    dx = x2 - x1
    dy = y2 - y1

    if dx == 0 and dy == 0:
        return haversine_km(plat, plon, lat1, lon1)

    # Projection factor t
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))

    closest_lon = lon1 + t * (lon2 - lon1)
    closest_lat = lat1 + t * (lat2 - lat1)

    return haversine_km(plat, plon, closest_lat, closest_lon)


def min_distance_to_polygon_km(lat: float, lon: float, polygon: List[Any]) -> float:
    """Calculates the minimum haversine distance from (lat, lon) to any edge of a polygon."""
    if not polygon:
        return float("inf")

    min_dist = float("inf")
    for ring in polygon:
        if len(ring) < 2:
            continue
        for i in range(len(ring) - 1):
            try:
                lon1, lat1 = float(ring[i][0]), float(ring[i][1])
                lon2, lat2 = float(ring[i + 1][0]), float(ring[i + 1][1])
                d = distance_point_to_segment_km(lat, lon, lat1, lon1, lat2, lon2)
                if d < min_dist:
                    min_dist = d
            except (TypeError, ValueError, IndexError):
                continue
        # Close the ring if not explicitly closed
        try:
            lon1, lat1 = float(ring[-1][0]), float(ring[-1][1])
            lon2, lat2 = float(ring[0][0]), float(ring[0][1])
            d = distance_point_to_segment_km(lat, lon, lat1, lon1, lat2, lon2)
            if d < min_dist:
                min_dist = d
        except (TypeError, ValueError, IndexError):
            pass

    return min_dist


def min_distance_to_geometry_km(lat: float, lon: float, geometry: Dict[str, Any]) -> float:
    """Minimum distance from (lat, lon) to edges of GeoJSON Polygon or MultiPolygon."""
    if not geometry or not isinstance(geometry, dict):
        return float("inf")
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if not coords:
        return float("inf")

    if gtype == "Polygon":
        return min_distance_to_polygon_km(lat, lon, coords)
    elif gtype == "MultiPolygon":
        min_dist = float("inf")
        for poly in coords:
            d = min_distance_to_polygon_km(lat, lon, poly)
            if d < min_dist:
                min_dist = d
        return min_dist
    return float("inf")


# ---------------------------------------------------------------------------
# Segments Intersection Helpers for Route Checking
# ---------------------------------------------------------------------------
def _ccw(ax: float, ay: float, bx: float, by: float, cx: float, cy: float) -> bool:
    return (cy - ay) * (bx - ax) > (by - ay) * (cx - ax)


def segments_intersect(
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    q1: Tuple[float, float],
    q2: Tuple[float, float],
) -> bool:
    """
    Checks if 2D segment (p1 -> p2) intersects segment (q1 -> q2).
    Coordinates in (lon, lat) or (x, y).
    """
    ax, ay = p1[0], p1[1]
    bx, by = p2[0], p2[1]
    cx, cy = q1[0], q1[1]
    dx, dy = q2[0], q2[1]

    return (_ccw(ax, ay, cx, cy, dx, dy) != _ccw(bx, by, cx, cy, dx, dy)) and (
        _ccw(ax, ay, bx, by, cx, cy) != _ccw(ax, ay, bx, by, dx, dy)
    )


def route_crosses_polygon(
    segment_start: Tuple[float, float],
    segment_end: Tuple[float, float],
    polygon: List[Any],
) -> bool:
    """
    Determines if a route segment between segment_start (lon, lat) and segment_end (lon, lat)
    crosses any ring boundary of a polygon.
    """
    if not polygon:
        return False
    for ring in polygon:
        if len(ring) < 2:
            continue
        for i in range(len(ring) - 1):
            try:
                q1 = (float(ring[i][0]), float(ring[i][1]))
                q2 = (float(ring[i + 1][0]), float(ring[i + 1][1]))
                if segments_intersect(segment_start, segment_end, q1, q2):
                    return True
            except (TypeError, ValueError, IndexError):
                continue
        # Closing segment
        try:
            q1 = (float(ring[-1][0]), float(ring[-1][1]))
            q2 = (float(ring[0][0]), float(ring[0][1]))
            if segments_intersect(segment_start, segment_end, q1, q2):
                return True
        except (TypeError, ValueError, IndexError):
            pass
    return False


# ---------------------------------------------------------------------------
# Boundary Getters & Boundary Checks
# ---------------------------------------------------------------------------
def get_eez_boundaries() -> List[Dict[str, Any]]:
    """Get list of loaded EEZ GeoJSON features."""
    global _EEZ_CACHE
    if _EEZ_CACHE is None:
        _EEZ_CACHE = _load_features_from_file(EEZ_CANDIDATES)
    return _EEZ_CACHE


def get_mpa_boundaries() -> List[Dict[str, Any]]:
    """Get list of loaded MPA GeoJSON features."""
    global _MPA_CACHE
    if _MPA_CACHE is None:
        _MPA_CACHE = _load_features_from_file(MPA_CANDIDATES)
    return _MPA_CACHE


def get_imbl_segments() -> List[IMBLSegment]:
    """
    Get list of International Maritime Boundary Line segments.
    Loads from data/imbl.geojson if present; otherwise generates canonical
    India-Sri Lanka IMBL segments.
    """
    global _IMBL_CACHE
    if _IMBL_CACHE is not None:
        return _IMBL_CACHE

    segments: List[IMBLSegment] = []
    # Check if a custom imbl.geojson exists
    imbl_features = _load_features_from_file(IMBL_CANDIDATES)
    if imbl_features:
        for feat in imbl_features:
            geom = feat.get("geometry", {})
            gtype = geom.get("type")
            coords = geom.get("coordinates", [])
            if gtype == "LineString" and len(coords) >= 2:
                for i in range(len(coords) - 1):
                    # In GeoJSON: coords are [lon, lat]
                    lon1, lat1 = coords[i][0], coords[i][1]
                    lon2, lat2 = coords[i + 1][0], coords[i + 1][1]
                    segments.append(IMBLSegment((lat1, lon1), (lat2, lon2)))
            elif gtype == "MultiLineString":
                for line in coords:
                    for i in range(len(line) - 1):
                        lon1, lat1 = line[i][0], line[i][1]
                        lon2, lat2 = line[i + 1][0], line[i + 1][1]
                        segments.append(IMBLSegment((lat1, lon1), (lat2, lon2)))

    # If no file found or empty, load canonical bilateral points
    if not segments:
        for i in range(len(CANONICAL_IMBL_POINTS) - 1):
            p1 = CANONICAL_IMBL_POINTS[i]
            p2 = CANONICAL_IMBL_POINTS[i + 1]
            segments.append(IMBLSegment(p1, p2))

    _IMBL_CACHE = segments
    return _IMBL_CACHE


def distance_to_imbl_km(lat: float, lon: float) -> float:
    """Compute distance in kilometers from (lat, lon) to nearest IMBL segment."""
    segments = get_imbl_segments()
    if not segments:
        return float("inf")

    min_dist = float("inf")
    for seg in segments:
        d = distance_point_to_segment_km(lat, lon, seg.lat1, seg.lon1, seg.lat2, seg.lon2)
        if d < min_dist:
            min_dist = d

    return round(float(min_dist), 2) if min_dist != float("inf") else float("inf")


def distance_to_eez_border_km(lat: float, lon: float) -> float:
    """Compute minimum distance in kilometers from (lat, lon) to sovereign EEZ border."""
    eez_features = get_eez_boundaries()
    if not eez_features:
        return float("inf")

    min_dist = float("inf")
    for feat in eez_features:
        geom = feat.get("geometry", {})
        d = min_distance_to_geometry_km(lat, lon, geom)
        if d < min_dist:
            min_dist = d

    return round(float(min_dist), 2) if min_dist != float("inf") else float("inf")


def check_point_in_eez(lat: float, lon: float) -> Tuple[bool, float]:
    """
    Check if point (lat, lon) is inside India's Exclusive Economic Zone.
    Returns: (inside_eez: bool, distance_to_eez_border_km: float)
    """
    eez_features = get_eez_boundaries()
    if not eez_features:
        # No EEZ data: fail-closed as unknown (never assume inside)
        return False, float("inf")

    inside = False
    for feat in eez_features:
        geom = feat.get("geometry", {})
        if point_in_geometry(lon, lat, geom):
            inside = True
            break

    border_dist = distance_to_eez_border_km(lat, lon)
    return inside, border_dist


def check_point_in_mpa(lat: float, lon: float) -> Tuple[bool, Optional[str], float]:
    """
    Check if point (lat, lon) is inside any Marine Protected Area.
    Returns: (inside_mpa: bool, nearest_mpa_name: Optional[str], distance_to_nearest_mpa_km: float)
    """
    mpa_features = get_mpa_boundaries()
    if not mpa_features:
        return False, None, float("inf")

    inside = False
    containing_mpa_name: Optional[str] = None
    nearest_mpa_name: Optional[str] = None
    min_dist = float("inf")

    for feat in mpa_features:
        geom = feat.get("geometry", {})
        props = feat.get("properties", {})
        name = (
            props.get("mpa_name")
            or props.get("NAME")
            or props.get("name")
            or props.get("Name")
            or "Protected Marine Sanctuary"
        )

        # Check containment
        if point_in_geometry(lon, lat, geom):
            inside = True
            containing_mpa_name = str(name)

        # Measure distance to border
        d = min_distance_to_geometry_km(lat, lon, geom)
        if d < min_dist:
            min_dist = d
            nearest_mpa_name = str(name)

    chosen_name = containing_mpa_name if inside else nearest_mpa_name
    return inside, chosen_name, round(float(min_dist), 2)


# ---------------------------------------------------------------------------
# Ingestion Task (Upsert into PostGIS if DB connected)
# ---------------------------------------------------------------------------
async def ingest_boundaries() -> Dict[str, Any]:
    """
    Ingests EEZ and MPA boundary datasets from GeoJSON files into memory cache,
    computes feature counts, validates geometries, and attempts upserting into
    PostGIS (eez_boundaries, mpa_boundaries) if database connection is available.
    Gracefully skips database insertion if database is offline.

    Returns:
        dict: {"eez_count": int, "mpa_count": int, "status": str, "db_synced": bool}
    """
    clear_boundaries_cache()
    eez_features = get_eez_boundaries()
    mpa_features = get_mpa_boundaries()

    eez_count = len(eez_features)
    mpa_count = len(mpa_features)
    logger.info("Boundaries loaded from GeoJSON: %d EEZ, %d MPA", eez_count, mpa_count)

    db_synced = False
    try:
        from backend.db.session import AsyncSessionLocal, engine
        from sqlalchemy import text

        # Quick probe to see if DB is responsive (0.5s timeout)
        async def _check_db() -> bool:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True

        is_connected = await asyncio.wait_for(_check_db(), timeout=0.8)
        if is_connected:
            async with AsyncSessionLocal() as session:
                # Upsert EEZ Boundaries
                for feat in eez_features:
                    props = feat.get("properties", {})
                    geom = feat.get("geometry", {})
                    bname = props.get("boundary_name", "India EEZ")
                    country = props.get("country", "India")
                    btype = props.get("boundary_type", "EEZ")

                    # Normalize geometry to MultiPolygon for PostGIS schema
                    gtype = geom.get("type")
                    if gtype == "Polygon":
                        mp_geom = {"type": "MultiPolygon", "coordinates": [geom.get("coordinates", [])]}
                    else:
                        mp_geom = geom

                    stmt = text(
                        """
                        INSERT INTO eez_boundaries (country, boundary_name, boundary_type, geom)
                        VALUES (:country, :bname, :btype, ST_SetSRID(ST_GeomFromGeoJSON(:geom), 4326))
                        ON CONFLICT DO NOTHING;
                        """
                    )
                    await session.execute(
                        stmt,
                        {
                            "country": country,
                            "bname": bname,
                            "btype": btype,
                            "geom": json.dumps(mp_geom),
                        },
                    )

                # Upsert MPA Boundaries
                for feat in mpa_features:
                    props = feat.get("properties", {})
                    geom = feat.get("geometry", {})
                    mpa_name = props.get("mpa_name") or props.get("name") or "Marine Sanctuary"
                    state = props.get("state", "India Coastal")
                    restriction = props.get("restriction_level", "no-take")

                    gtype = geom.get("type")
                    if gtype == "Polygon":
                        mp_geom = {"type": "MultiPolygon", "coordinates": [geom.get("coordinates", [])]}
                    else:
                        mp_geom = geom

                    stmt = text(
                        """
                        INSERT INTO mpa_boundaries (mpa_name, state, restriction_level, geom)
                        VALUES (:mpa_name, :state, :restriction, ST_SetSRID(ST_GeomFromGeoJSON(:geom), 4326))
                        ON CONFLICT DO NOTHING;
                        """
                    )
                    await session.execute(
                        stmt,
                        {
                            "mpa_name": mpa_name,
                            "state": state,
                            "restriction": restriction,
                            "geom": json.dumps(mp_geom),
                        },
                    )

                await session.commit()
                db_synced = True
                logger.info("Boundaries successfully upserted into PostGIS tables.")
    except Exception as exc:
        logger.debug("Database boundary upsert skipped (offline/degraded): %s", exc)
        db_synced = False

    return {
        "eez_count": eez_count,
        "mpa_count": mpa_count,
        "status": "loaded",
        "db_synced": db_synced,
    }
