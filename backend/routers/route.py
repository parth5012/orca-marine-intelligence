"""
Safe Marine Routing API Endpoint (T8 #167)
GET /api/route/safe

Owner: M-C (Backend API)
Provides safe marine route calculation between origin and destination coordinates,
avoiding Marine Protected Areas (MPAs) and warning on IMBL proximity with cost-breakdown.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.ingest.boundaries import (
    CANONICAL_IMBL_POINTS,
    IMBL_BUFFER_KM,
    get_mpa_boundaries,
    haversine_km,
)

logger = logging.getLogger("orca.route")

router = APIRouter(tags=["route"])

# Standard fishing vessel cruise speed (km/h)
CRUISE_KMH = 25.0
KM_TO_NM = 1.852


class CostBreakdown(BaseModel):
    distance_base: float
    wave_penalty: float
    wind_penalty: float
    forbidden_penalty: float
    total_cost: float


class SafeRouteResponse(BaseModel):
    status: str = "ok"
    waypoints: List[List[float]] = Field(
        ..., description="List of [latitude, longitude] route coordinates"
    )
    distance_km: float
    distance_nm: float
    bearing: str
    bearing_deg: float
    eta_min: int
    safety_index: int
    safety_label: str
    hazards: List[str]
    cost_breakdown: CostBreakdown


def calculate_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> Tuple[float, str]:
    """Calculates compass bearing in degrees and 16-point cardinal label."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_lambda = math.radians(lon2 - lon1)

    y = math.sin(delta_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(delta_lambda)

    deg = (math.degrees(math.atan2(y, x)) + 360.0) % 360.0
    deg = round(deg, 1)

    directions = [
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
    ]
    idx = int((deg + 11.25) / 22.5) % 16
    cardinal = directions[idx]
    label = f"{cardinal} {int(round(deg)):03d}°"
    return deg, label


def _ccw(a: Tuple[float, float], b: Tuple[float, float], c: Tuple[float, float]) -> bool:
    return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])


def _segments_intersect(
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    p3: Tuple[float, float],
    p4: Tuple[float, float],
) -> bool:
    return _ccw(p1, p3, p4) != _ccw(p2, p3, p4) and _ccw(p1, p2, p3) != _ccw(p1, p2, p4)


def _point_in_polygon(point: Tuple[float, float], polygon: List[Tuple[float, float]]) -> bool:
    lat, lon = point
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if (yi > lon) != (yj > lon) and (lat < ((xj - xi) * (lon - yi)) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _segment_crosses_polygon(
    p1: Tuple[float, float], p2: Tuple[float, float], polygon: List[Tuple[float, float]]
) -> bool:
    if len(polygon) < 3:
        return False
    for i in range(len(polygon)):
        next_i = (i + 1) % len(polygon)
        if _segments_intersect(p1, p2, polygon[i], polygon[next_i]):
            return True
    mid = ((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0)
    return _point_in_polygon(p1, polygon) or _point_in_polygon(p2, polygon) or _point_in_polygon(mid, polygon)


def _point_to_segment_distance_km(
    pt: Tuple[float, float], s1: Tuple[float, float], s2: Tuple[float, float]
) -> float:
    denom = (s2[0] - s1[0]) ** 2 + (s2[1] - s1[1]) ** 2
    if denom == 0:
        return haversine_km(pt[0], pt[1], s1[0], s1[1])
    t = max(
        0.0,
        min(
            1.0,
            ((pt[0] - s1[0]) * (s2[0] - s1[0]) + (pt[1] - s1[1]) * (s2[1] - s1[1])) / denom,
        ),
    )
    proj_lat = s1[0] + t * (s2[0] - s1[0])
    proj_lon = s1[1] + t * (s2[1] - s1[1])
    return haversine_km(pt[0], pt[1], proj_lat, proj_lon)


def _point_to_polyline_distance_km(
    pt: Tuple[float, float], polyline: List[Tuple[float, float]]
) -> float:
    min_dist = float("inf")
    for i in range(len(polyline) - 1):
        d = _point_to_segment_distance_km(pt, polyline[i], polyline[i + 1])
        if d < min_dist:
            min_dist = d
    return min_dist


@router.get("/route/safe", response_model=SafeRouteResponse)
async def get_safe_route(
    olat: float = Query(..., ge=-90.0, le=90.0, description="Origin latitude"),
    olon: float = Query(..., ge=-180.0, le=180.0, description="Origin longitude"),
    dlat: float = Query(..., ge=-90.0, le=90.0, description="Destination latitude"),
    dlon: float = Query(..., ge=-180.0, le=180.0, description="Destination longitude"),
    wave_height_m: float = Query(1.0, ge=0.0, le=20.0, description="Significant wave height (m)"),
    wind_speed_kt: float = Query(15.0, ge=0.0, le=120.0, description="Wind speed (knots)"),
) -> SafeRouteResponse:
    """
    Computes a safe marine route avoiding MPAs and warning on IMBL proximity.
    Returns waypoints, distance, bearing, ETA, safety classification, and cost breakdown.
    """
    start_pt = (olat, olon)
    end_pt = (dlat, dlon)

    mpa_features = get_mpa_boundaries()
    hazards: List[str] = []
    detour_occurred = False
    detour_wp: Optional[Tuple[float, float]] = None
    crossed_mpa_name: Optional[str] = None

    # 1. MPA intersection check
    for feat in mpa_features:
        geom = feat.get("geometry", {})
        if geom.get("type") != "Polygon":
            continue
        coords = geom.get("coordinates", [])
        if not coords or not isinstance(coords[0], list):
            continue
        # GeoJSON is [lon, lat] -> convert to (lat, lon)
        poly = [(pt[1], pt[0]) for pt in coords[0] if len(pt) >= 2]
        if _segment_crosses_polygon(start_pt, end_pt, poly):
            detour_occurred = True
            crossed_mpa_name = (
                feat.get("properties", {}).get("mpa_name")
                or feat.get("properties", {}).get("name")
                or "Marine Protected Area"
            )

            # Calculate detour tangent waypoint (+0.02 deg ~ 2.2 km buffer)
            min_lat = min(p[0] for p in poly)
            max_lat = max(p[0] for p in poly)
            min_lon = min(p[1] for p in poly)
            max_lon = max(p[1] for p in poly)
            buf = 0.02

            c1 = (round((min_lat + max_lat) / 2.0, 4), round(min_lon - buf, 4))
            c2 = (round((min_lat + max_lat) / 2.0, 4), round(max_lon + buf, 4))

            d1 = haversine_km(olat, olon, c1[0], c1[1]) + haversine_km(c1[0], c1[1], dlat, dlon)
            d2 = haversine_km(olat, olon, c2[0], c2[1]) + haversine_km(c2[0], c2[1], dlat, dlon)
            detour_wp = c1 if d1 <= d2 else c2
            break

    waypoints: List[List[float]] = [[olat, olon]]
    if detour_occurred and detour_wp and crossed_mpa_name:
        waypoints.append([detour_wp[0], detour_wp[1]])
        hazards.append(
            f"Route passes through Marine Protected Area: {crossed_mpa_name}. Detour applied around protected zone."
        )
    else:
        # Standard midpoint
        waypoints.append([round((olat + dlat) / 2.0, 4), round((olon + dlon) / 2.0, 4)])
    waypoints.append([dlat, dlon])

    # 2. IMBL proximity check
    min_imbl_dist = float("inf")
    pts_to_check = [start_pt, end_pt] + ([detour_wp] if detour_wp else [])
    for pt in pts_to_check:
        d = _point_to_polyline_distance_km(pt, CANONICAL_IMBL_POINTS)
        if d < min_imbl_dist:
            min_imbl_dist = d

    near_imbl = min_imbl_dist <= IMBL_BUFFER_KM
    if near_imbl:
        hazards.append(
            f"Warning: Proximity to International Maritime Boundary Line (<{IMBL_BUFFER_KM}km). Risk of border crossing."
        )

    # 3. Calculate total route distance
    total_dist_km = 0.0
    for i in range(len(waypoints) - 1):
        total_dist_km += haversine_km(
            waypoints[i][0], waypoints[i][1], waypoints[i + 1][0], waypoints[i + 1][1]
        )
    total_dist_km = round(total_dist_km, 1)
    total_dist_nm = round(total_dist_km / KM_TO_NM, 1)

    bearing_deg, bearing_label = calculate_bearing(olat, olon, dlat, dlon)
    eta_min = max(5, int(round((total_dist_km / CRUISE_KMH) * 60)))

    # Safety index and label
    safety_label = "SAFE"
    safety_index = 85
    if near_imbl:
        safety_label = "CAUTION"
        safety_index = 50
    elif detour_occurred:
        safety_label = "CAUTION"
        safety_index = 68

    # 4. Cost model per T3 lock: distance * (1.0 + wave*0.5 + wind*0.3 + forbidden_penalty)
    wave_penalty = round(wave_height_m * 0.5, 3)
    wind_penalty = round((wind_speed_kt / 50.0) * 0.3, 3)
    forbidden_penalty = 1000.0 if (detour_occurred or near_imbl) else 0.0
    total_cost = round(
        total_dist_km * (1.0 + wave_penalty + wind_penalty + forbidden_penalty), 2
    )

    cost_breakdown = CostBreakdown(
        distance_base=total_dist_km,
        wave_penalty=wave_penalty,
        wind_penalty=wind_penalty,
        forbidden_penalty=forbidden_penalty,
        total_cost=total_cost,
    )

    return SafeRouteResponse(
        status="ok",
        waypoints=waypoints,
        distance_km=total_dist_km,
        distance_nm=total_dist_nm,
        bearing=bearing_label,
        bearing_deg=bearing_deg,
        eta_min=eta_min,
        safety_index=safety_index,
        safety_label=safety_label,
        hazards=hazards,
        cost_breakdown=cost_breakdown,
    )
