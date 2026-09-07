"""
PFZ Data Proxy Router

Owner: M-C (Backend API & Platform) — GET /api/pfz/today, GET /api/pfz/history
Module: backend/routers/pfz.py

Serves latest and historical PFZ GeoJSON data for frontend map and agent workflows.
Caches live INCOIS data in Redis (6h TTL) with automatic Copernicus Marine fallback.
"""

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from backend.db.redis import get_json, set_json
from backend.ingest.copernicus_fallback import fetch_copernicus_fallback
from backend.ingest.incois_textdata import ingest_textdata, load_local_pfz

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


@router.get("/pfz/history")
async def get_pfz_history(
    days: int = Query(7, ge=1, le=30, description="Number of historical days to return (1-30)"),
    sector: Optional[str] = Query(None, description="Optional INCOIS sector code filter"),
    limit: int = Query(500, ge=1, le=5000, description="Max number of historical features to return"),
) -> Dict[str, Any]:
    """
    Return historical PFZ data for the last `days` days.
    Queries PostGIS if connected; otherwise constructs historical snapshots from local / fallback data.
    """
    history_features: List[Dict[str, Any]] = []
    is_db_result = False
    today_date = date.today()
    sec_up = sector.strip().upper() if sector and sector.strip() else None

    # 1. Attempt PostGIS query if database is connected
    try:
        from sqlalchemy import func, select
        from backend.db.models import PFZZone
        from backend.db.session import AsyncSessionLocal

        start_date = today_date - timedelta(days=days)
        async with AsyncSessionLocal() as session:
            stmt = select(PFZZone).where(PFZZone.valid_date >= start_date)
            if sec_up:
                stmt = stmt.where(
                    (func.upper(PFZZone.sector) == sec_up) | (func.upper(PFZZone.sector_name) == sec_up)
                )
            stmt = stmt.order_by(PFZZone.valid_date.desc(), PFZZone.id.asc()).limit(limit)
            res = await session.execute(stmt)
            zones = res.scalars().all()

            if zones:
                is_db_result = True
                for z in zones:
                    history_features.append(
                        {
                            "type": "Feature",
                            "geometry": {"type": "Point", "coordinates": [z.lon, z.lat]},
                            "properties": {
                                "zone_id": z.zone_id,
                                "place": z.place,
                                "sector": z.sector,
                                "sector_name": z.sector_name,
                                "dir": z.direction,
                                "direction": z.direction,
                                "bearing": z.bearing,
                                "distance": z.distance_km,
                                "depth": z.depth_range,
                                "valid_date": str(z.valid_date),
                                "source": z.source or "incois_textdata",
                            },
                        }
                    )
    except Exception as db_exc:
        logger.debug("Database historical query skipped: %s", db_exc)

    # 2. If no database records found, construct historical snapshots from fallback
    snapshots: List[Dict[str, Any]] = []

    if not is_db_result:
        # DB-empty fallback clearly flagged: source: synthetic-duplicate + warning field
        source = "synthetic-duplicate"
        warning = "No historical records found in database; returning synthetic duplicate snapshots."

        base_feats = load_local_pfz(sectors=[sec_up] if sec_up else None)
        if not base_feats:
            cop_data = await fetch_copernicus_fallback(sector=sec_up)
            base_feats = cop_data.get("features", [])

        for d in range(days):
            hist_date = (today_date - timedelta(days=d)).isoformat()
            day_features = []
            for feat in base_feats:
                if len(history_features) >= limit:
                    break
                feat_copy = json.loads(json.dumps(feat))
                props = feat_copy.setdefault("properties", {})
                props["valid_date"] = hist_date
                props["timestamp"] = f"{hist_date}T11:30:00Z"
                props["source"] = "synthetic-duplicate"
                day_features.append(feat_copy)
                history_features.append(feat_copy)

            if day_features:
                snapshots.append(
                    {
                        "date": hist_date,
                        "count": len(day_features),
                        "features": day_features,
                    }
                )
    else:
        source = "postgis"
        warning = None

        # Group database records into snapshots by valid_date
        date_groups: Dict[str, List[Dict[str, Any]]] = {}
        for feat in history_features:
            v_date = feat.get("properties", {}).get("valid_date", str(today_date))
            date_groups.setdefault(v_date, []).append(feat)

        for v_date, feats in sorted(date_groups.items(), reverse=True):
            snapshots.append(
                {
                    "date": v_date,
                    "count": len(feats),
                    "features": feats,
                }
            )

    response: Dict[str, Any] = {
        "type": "FeatureCollection",
        "days": days,
        "sector": sector,
        "start_date": (today_date - timedelta(days=days)).isoformat(),
        "end_date": today_date.isoformat(),
        "source": source,
        "snapshots": snapshots,
        "features": history_features,
        "count": len(history_features),
    }
    if warning:
        response["warning"] = warning

    return response
