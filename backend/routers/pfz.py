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
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Query

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


@router.post("/pfz/refresh")
async def refresh_pfz(
    authorization: Optional[str] = Header(None, description="Bearer <CRON_SECRET>"),
) -> Dict[str, Any]:
    """
    Cron-triggered PFZ refresh.

    Called by: Vercel Cron (frontend/app/api/cron/pfz), Render Cron Job,
    or OS cron via `curl -X POST .../api/pfz/refresh -H "Authorization: Bearer $CRON_SECRET"`.

    Runs backend.ingest.incois_textdata.ingest_textdata() which rewrites
    data/pfz-today.geojson, upserts PostGIS, and refreshes Redis (6h TTL).
    Returns AGENTS.md §3.2 observable envelope.

    Auth fails closed: CRON_SECRET must be set in every environment except
    explicit local dev (ALLOW_UNAUTHENTICATED_REFRESH=true). Without either,
    the endpoint refuses with 503 instead of exposing an unauthenticated
    scrape-and-write trigger.
    """
    expected = os.getenv("CRON_SECRET", "").strip()
    allow_local = os.getenv("ALLOW_UNAUTHENTICATED_REFRESH", "").strip().lower() in (
        "true",
        "1",
        "yes",
    )
    if expected:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing Bearer CRON_SECRET")
        if authorization[len("Bearer "):].strip() != expected:
            raise HTTPException(status_code=403, detail="Invalid CRON_SECRET")
    elif not allow_local:
        raise HTTPException(
            status_code=503,
            detail="PFZ refresh not configured: set CRON_SECRET "
            "(or ALLOW_UNAUTHENTICATED_REFRESH=true for local dev only)",
        )

    try:
        doc = await ingest_textdata()
    except Exception as exc:
        logger.exception("PFZ cron refresh failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"PFZ refresh failed: {exc}") from exc

    features = doc.get("features", [])
    source = doc.get("source", "incois_textdata")
    status = "success" if features else "warning"
    summary = (
        f"PFZ refresh {status}: {len(features)} features via {source}"
        if features
        else "PFZ refresh warning: 0 features; yesterday file retained"
    )
    return {
        "status": status,
        "summary": summary,
        "next_actions": ["serve /api/pfz/today", "verify map renders"],
        # Only sinks ingest_textdata actually persisted (file/PostGIS/Redis).
        "artifacts": doc.get("artifacts", []),
        "count": len(features),
        "source": source,
        "sector_count": doc.get("sector_count", 0),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
