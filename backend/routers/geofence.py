"""
Geofence Check Router

Owner: M-C (Backend API & Platform) & M-B (Data Extractors & Storage)
Module: backend/routers/geofence.py

Provides real-time maritime boundary validation and safety alerts against:
- Sovereign Exclusive Economic Zone (EEZ) boundaries
- Marine Protected Areas (MPAs) / Sanctuaries (WDPA)
- International Maritime Boundary Line (IMBL) buffer zones (2km / 5km)

Endpoints:
- GET /api/geofence/check   : Geofence safety check via query parameters
- POST /api/geofence/check  : Geofence safety check via JSON request body
- GET /api/geofence/status  : Active sanctuaries, EEZ zones, and protection thresholds
- POST /api/geofence/route  : Multi-waypoint route and segment safety validation
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any, Dict, List, Optional, Union, Tuple

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field

from backend.ingest.boundaries import (
    EEZ_CAUTION_KM,
    IMBL_BUFFER_KM,
    IMBL_CAUTION_KM,
    check_point_in_eez,
    check_point_in_mpa,
    distance_point_to_segment_km,
    distance_to_imbl_km,
    get_eez_boundaries,
    get_imbl_segments,
    get_mpa_boundaries,
    route_crosses_polygon,
)

logger = logging.getLogger("orca.geofence")

router = APIRouter(tags=["geofence"])


# ---------------------------------------------------------------------------
# Pydantic Request & Response Models
# ---------------------------------------------------------------------------
class GeofenceCheckRequest(BaseModel):
    lat: float = Field(..., description="Latitude in degrees [-90, 90]")
    lon: float = Field(..., description="Longitude in degrees [-180, 180]")
    heading_deg: Optional[float] = Field(None, description="Vessel heading in degrees [0, 360]")
    speed_kt: Optional[float] = Field(None, description="Vessel speed in knots")


class GeofenceCheckResponse(BaseModel):
    lat: float
    lon: float
    inside_eez: bool
    distance_to_eez_border_km: float
    inside_mpa: bool
    nearest_mpa_name: Optional[str] = None
    mpa_name: Optional[str] = None
    distance_to_imbl_km: float
    near_imbl: bool
    safety_status: str  # "safe" | "caution" | "danger_violation"
    alerts: List[str]
    latency_ms: float
    heading_deg: Optional[float] = None
    speed_kt: Optional[float] = None


class GeofenceStatusResponse(BaseModel):
    status: str = "ok"
    active_mpas: List[str]
    eez_zones: List[str]
    imbl_buffer_km: float = 2.0
    imbl_caution_threshold_km: float = 5.0
    eez_caution_threshold_km: float = 10.0
    count_protected_boundaries: int
    protected_boundaries_count: int
    boundary_counts: Dict[str, int]


class GeofenceRouteRequest(BaseModel):
    coordinates: List[Any] = Field(
        ...,
        description="List of waypoints formatted as GeoJSON [[lon, lat], ...] or [{'lat': ..., 'lon': ...}, ...]",
    )


class GeofenceRouteResponse(BaseModel):
    safe: bool
    violations: List[str]
    waypoint_checks: List[Dict[str, Any]]
    min_distance_to_imbl_km: float


# ---------------------------------------------------------------------------
# Core Evaluation Logic
# ---------------------------------------------------------------------------
def _validate_coords(lat: float, lon: float) -> None:
    """Validate latitude and longitude ranges."""
    if math.isnan(lat) or math.isnan(lon) or not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        raise HTTPException(
            status_code=400,
            detail="Invalid coordinates: lat must be between -90 and 90, lon between -180 and 180",
        )


def _evaluate_point(
    lat: float,
    lon: float,
    heading_deg: Optional[float] = None,
    speed_kt: Optional[float] = None,
) -> GeofenceCheckResponse:
    """Core in-memory geofence evaluation logic."""
    t0 = time.perf_counter()
    _validate_coords(lat, lon)

    # 1. EEZ Check
    inside_eez, dist_eez = check_point_in_eez(lat, lon)

    # 2. MPA Check
    inside_mpa, nearest_mpa_name, dist_mpa = check_point_in_mpa(lat, lon)

    # 3. IMBL Distance
    dist_imbl = distance_to_imbl_km(lat, lon)
    near_imbl = dist_imbl <= IMBL_BUFFER_KM

    # 4. Determine Safety Status & Safety Alerts
    alerts: List[str] = []
    if inside_mpa:
        safety_status = "danger_violation"
        alerts.append(f"Inside Marine Protected Area: {nearest_mpa_name or 'Sanctuary'}")
    elif near_imbl:
        safety_status = "danger_violation"
        alerts.append(f"Approaching International Maritime Boundary Line (<2km: {dist_imbl:.2f}km)")
    elif not inside_eez:
        safety_status = "danger_violation"
        alerts.append("Outside sovereign Exclusive Economic Zone (EEZ)")
    elif dist_imbl <= IMBL_CAUTION_KM or dist_eez <= EEZ_CAUTION_KM:
        safety_status = "caution"
        if dist_imbl <= IMBL_CAUTION_KM:
            alerts.append(f"Approaching International Maritime Boundary Line (<5km: {dist_imbl:.2f}km)")
        if dist_eez <= EEZ_CAUTION_KM:
            alerts.append(f"Approaching EEZ boundary (<10km: {dist_eez:.2f}km)")
    else:
        safety_status = "safe"

    latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)

    return GeofenceCheckResponse(
        lat=lat,
        lon=lon,
        inside_eez=inside_eez,
        distance_to_eez_border_km=dist_eez,
        inside_mpa=inside_mpa,
        nearest_mpa_name=nearest_mpa_name,
        mpa_name=nearest_mpa_name if inside_mpa else None,
        distance_to_imbl_km=dist_imbl,
        near_imbl=near_imbl,
        safety_status=safety_status,
        alerts=alerts,
        latency_ms=latency_ms,
        heading_deg=heading_deg,
        speed_kt=speed_kt,
    )


# ---------------------------------------------------------------------------
# Router Endpoints
# ---------------------------------------------------------------------------
@router.get("/geofence/check", response_model=GeofenceCheckResponse)
async def check_geofence_get(
    lat: float = Query(..., description="Latitude [-90, 90]"),
    lon: float = Query(..., description="Longitude [-180, 180]"),
    heading_deg: Optional[float] = Query(None, description="Vessel heading in degrees"),
    speed_kt: Optional[float] = Query(None, description="Vessel speed in knots"),
) -> GeofenceCheckResponse:
    """Check whether a coordinate point falls within EEZ, MPA, or approaches IMBL via GET query parameters."""
    return _evaluate_point(lat=lat, lon=lon, heading_deg=heading_deg, speed_kt=speed_kt)


@router.post("/geofence/check", response_model=GeofenceCheckResponse)
async def check_geofence_post(
    body: Optional[GeofenceCheckRequest] = Body(None),
    lat: Optional[float] = Query(None),
    lon: Optional[float] = Query(None),
    heading_deg: Optional[float] = Query(None),
    speed_kt: Optional[float] = Query(None),
) -> GeofenceCheckResponse:
    """Check whether a coordinate point falls within EEZ, MPA, or approaches IMBL via JSON body or query params."""
    if body is not None:
        target_lat = body.lat
        target_lon = body.lon
        target_heading = body.heading_deg
        target_speed = body.speed_kt
    elif lat is not None and lon is not None:
        target_lat = lat
        target_lon = lon
        target_heading = heading_deg
        target_speed = speed_kt
    else:
        raise HTTPException(
            status_code=400,
            detail="Missing required coordinate fields: lat and lon must be provided.",
        )

    return _evaluate_point(
        lat=target_lat,
        lon=target_lon,
        heading_deg=target_heading,
        speed_kt=target_speed,
    )


@router.get("/geofence/status", response_model=GeofenceStatusResponse)
async def get_geofence_status() -> GeofenceStatusResponse:
    """
    Returns active Marine Protected Areas (MPAs), sovereign EEZ zones,
    IMBL buffer protection rules, and total count of active boundary layers.
    """
    eez_features = get_eez_boundaries()
    mpa_features = get_mpa_boundaries()

    eez_zones = [
        f.get("properties", {}).get("boundary_name", f"EEZ Zone {idx}")
        for idx, f in enumerate(eez_features)
    ]
    active_mpas = [
        f.get("properties", {}).get("mpa_name")
        or f.get("properties", {}).get("name")
        or f"MPA {idx}"
        for idx, f in enumerate(mpa_features)
    ]

    total_count = len(eez_zones) + len(active_mpas)

    return GeofenceStatusResponse(
        status="ok",
        active_mpas=active_mpas,
        eez_zones=eez_zones,
        imbl_buffer_km=IMBL_BUFFER_KM,
        imbl_caution_threshold_km=IMBL_CAUTION_KM,
        eez_caution_threshold_km=EEZ_CAUTION_KM,
        count_protected_boundaries=total_count,
        protected_boundaries_count=total_count,
        boundary_counts={
            "eez": len(eez_zones),
            "mpa": len(active_mpas),
            "total": total_count,
        },
    )


@router.post("/geofence/route", response_model=GeofenceRouteResponse)
async def check_route_geofence(
    body: GeofenceRouteRequest,
) -> GeofenceRouteResponse:
    """
    Validates a planned navigational route and its constituent line segments
    against sovereign EEZ limits, Marine Protected Areas, and IMBL boundaries.
    """
    raw_coords = body.coordinates
    if not raw_coords:
        raise HTTPException(status_code=400, detail="Route coordinates must contain at least one waypoint.")
    if len(raw_coords) > 500:
        raise HTTPException(status_code=400, detail=f"Route coordinates exceed maximum of 500 waypoints (got {len(raw_coords)}).")

    # Parse waypoints to standard (lat, lon) tuples
    waypoints: List[Tuple[float, float]] = []
    for idx, item in enumerate(raw_coords):
        if isinstance(item, dict):
            lat_val = item.get("lat") if item.get("lat") is not None else item.get("latitude")
            lon_val = item.get("lon") if item.get("lon") is not None else (item.get("lng") if item.get("lng") is not None else item.get("longitude"))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            # GeoJSON coordinates standard: [longitude, latitude]
            lon_val = item[0]
            lat_val = item[1]
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Waypoint {idx} format invalid: expected [lon, lat] or {{'lat': ..., 'lon': ...}}",
            )

        if lat_val is None or lon_val is None:
            raise HTTPException(
                status_code=400,
                detail=f"Waypoint {idx} contains missing coordinates: lat={lat_val}, lon={lon_val}",
            )

        try:
            flat = float(lat_val)
            flon = float(lon_val)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=400,
                detail=f"Waypoint {idx} contains non-numeric coordinates: lat={lat_val}, lon={lon_val}",
            )

        _validate_coords(flat, flon)
        waypoints.append((flat, flon))

    violations: List[str] = []
    waypoint_checks: List[Dict[str, Any]] = []
    min_dist_imbl = float("inf")

    # 1. Check each waypoint
    for idx, (wlat, wlon) in enumerate(waypoints):
        check = _evaluate_point(wlat, wlon)
        min_dist_imbl = min(min_dist_imbl, check.distance_to_imbl_km)

        if check.safety_status == "danger_violation":
            for alert in check.alerts:
                violations.append(f"Waypoint {idx + 1} ({wlat:.3f}, {wlon:.3f}): {alert}")

        waypoint_checks.append(
            {
                "waypoint_index": idx,
                "lat": wlat,
                "lon": wlon,
                "inside_eez": check.inside_eez,
                "distance_to_eez_border_km": check.distance_to_eez_border_km,
                "inside_mpa": check.inside_mpa,
                "nearest_mpa_name": check.nearest_mpa_name,
                "distance_to_imbl_km": check.distance_to_imbl_km,
                "near_imbl": check.near_imbl,
                "safety_status": check.safety_status,
                "alerts": check.alerts,
            }
        )

    # 2. Check route segments between consecutive waypoints
    mpa_features = get_mpa_boundaries()
    imbl_segments = get_imbl_segments()

    for i in range(len(waypoints) - 1):
        lat_a, lon_a = waypoints[i]
        lat_b, lon_b = waypoints[i + 1]

        # Check direct polygon boundary intersection with MPAs
        # Note: route_crosses_polygon uses (lon, lat) GeoJSON point order
        p_start = (lon_a, lat_a)
        p_end = (lon_b, lat_b)

        for mpa_feat in mpa_features:
            geom = mpa_feat.get("geometry", {})
            props = mpa_feat.get("properties", {})
            mname = props.get("mpa_name") or props.get("name") or "Marine Protected Area"
            gtype = geom.get("type")
            coords = geom.get("coordinates", [])

            crosses = False
            if gtype == "Polygon":
                crosses = route_crosses_polygon(p_start, p_end, coords)
            elif gtype == "MultiPolygon":
                for poly in coords:
                    if route_crosses_polygon(p_start, p_end, poly):
                        crosses = True
                        break

            if crosses:
                violations.append(
                    f"Route segment {i + 1} -> {i + 2} crosses boundary of Marine Protected Area: {mname}"
                )

        # Sample intermediate points along the segment for IMBL proximity and MPA penetration
        num_samples = 5
        for s in range(1, num_samples):
            frac = s / float(num_samples)
            sample_lat = lat_a + frac * (lat_b - lat_a)
            sample_lon = lon_a + frac * (lon_b - lon_a)

            # Check IMBL distance along the segment
            s_imbl_dist = distance_to_imbl_km(sample_lat, sample_lon)
            min_dist_imbl = min(min_dist_imbl, s_imbl_dist)
            if s_imbl_dist <= IMBL_BUFFER_KM:
                violations.append(
                    f"Route segment {i + 1} -> {i + 2} approaches IMBL (<2km buffer: {s_imbl_dist:.2f}km)"
                )

            # Check MPA containment along the segment
            s_inside_mpa, s_mpa_name, _ = check_point_in_mpa(sample_lat, sample_lon)
            if s_inside_mpa:
                violations.append(
                    f"Route segment {i + 1} -> {i + 2} penetrates Marine Protected Area: {s_mpa_name}"
                )

    # Deduplicate violations while preserving order
    unique_violations = list(dict.fromkeys(violations))
    is_safe = len(unique_violations) == 0

    return GeofenceRouteResponse(
        safe=is_safe,
        violations=unique_violations,
        waypoint_checks=waypoint_checks,
        min_distance_to_imbl_km=round(min_dist_imbl, 2) if min_dist_imbl != float("inf") else 0.0,
    )
