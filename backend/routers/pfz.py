"""
PFZ Data Proxy Router

Owner: M-C (Backend API & Platform) — GET /api/pfz/today
Module: backend/routers/pfz.py

Serves latest PFZ GeoJSON data for frontend map and agent workflows.
Caches live INCOIS data in Redis (6h TTL) with automatic Copernicus Marine fallback.

Wayfinder T3 (map #92): GET /api/pfz/history deleted per human grill
decision (post-MVP slider deferred) — today endpoint only.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from backend.db.redis import get_json, set_json
from backend.ingest.copernicus_fallback import fetch_copernicus_fallback
from backend.ingest.incois_textdata import ingest_textdata

logger = logging.getLogger(__name__)

router = APIRouter(tags=["pfz"])


@router.get("/pfz/today")
async def get_today_pfz(
    sector: Optional[str] = Query(None, description="Optional INCOIS sector code (e.g. SEC005 or KERALA)"),
    bbox: Optional[str] = Query(None, description="Bounding box filter: min_lon,min_lat,max_lon,max_lat"),
    limit: int = Query(1000, ge=1, le=5000, description="Max number of features to return"),
) -> Dict[str, Any]:
    """
    Return today's PFZ GeoJSON FeatureCollection.
    Checks Redis cache (6h TTL), loads live INCOIS data, falls back to Copernicus Marine when needed.
    """
    # 1. Check Redis cache for 'pfz:today'
    base_data: Optional[Dict[str, Any]] = None
    try:
        base_data = await get_json("pfz:today")
    except Exception as cache_err:
        logger.debug("Redis cache read error for pfz:today: %s", cache_err)

    # 2. If not cached, fetch live INCOIS or fallback
    if not base_data or not base_data.get("features"):
        try:
            base_data = await ingest_textdata()
        except Exception as ingest_err:
            logger.warning("INCOIS live ingest failed: %s; invoking Copernicus fallback", ingest_err)
            base_data = await fetch_copernicus_fallback()

        # Cache base dataset in Redis with 6-hour TTL
        if base_data and base_data.get("features"):
            try:
                await set_json("pfz:today", base_data, ttl_seconds=21600)
            except Exception as set_err:
                logger.debug("Redis cache write failed: %s", set_err)

    features: List[Dict[str, Any]] = list(base_data.get("features", [])) if base_data else []

    # 3. Apply sector filter if requested
    if sector:
        target_sec = sector.strip().upper()
        features = [
            f
            for f in features
            if f.get("properties", {}).get("sector", "").upper() == target_sec
            or f.get("properties", {}).get("sector_name", "").upper() == target_sec
        ]

    # 4. Apply bbox filter if requested (min_lon,min_lat,max_lon,max_lat)
    if bbox:
        try:
            coords_split = [float(x.strip()) for x in bbox.split(",")]
            if len(coords_split) != 4:
                raise ValueError("Expected 4 numbers")
            min_lon, min_lat, max_lon, max_lat = coords_split
            if min_lon > max_lon or min_lat > max_lat:
                raise ValueError("Invalid bounding coordinates: min must be <= max")

            filtered = []
            for f in features:
                pt = f.get("geometry", {}).get("coordinates", [])
                if len(pt) >= 2:
                    lon, lat = pt[0], pt[1]
                    if min_lon <= lon <= max_lon and min_lat <= lat <= max_lat:
                        filtered.append(f)
            features = filtered
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid bbox parameter '{bbox}'. Expected format: min_lon,min_lat,max_lon,max_lat.",
            ) from exc

    # 5. Apply limit
    limited_features = features[:limit]

    # 6. Build response with metadata
    source = base_data.get("source", "incois_textdata") if base_data else "incois_textdata"
    valid_until = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()
    sector_count = len(
        {
            f.get("properties", {}).get("sector")
            for f in limited_features
            if f.get("properties", {}).get("sector")
        }
    )

    return {
        "type": "FeatureCollection",
        "valid_until": valid_until,
        "source": source,
        "sector_count": sector_count,
        "count": len(limited_features),
        "metadata": {
            "valid_until": valid_until,
            "source": source,
            "sector_count": sector_count,
            "count": len(limited_features),
        },
        "features": limited_features,
    }
