"""
Vector Tile Server Router & Basemap Configuration Provider

Owner: M-C (Backend API & Platform) — GET /api/tiles/config, GET /api/tiles/{z}/{x}/{y}.pbf
Module: backend/routers/tiles.py

Serves basemap tile configuration metadata and vector tile endpoints for Leaflet / MapLibre.
"""

import json
import logging
import os
from typing import Any, Dict
from fastapi import APIRouter, Response

from backend.db.postgis import get_mvt_tile
from backend.db.redis import get_tile_cache, set_tile_cache

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tiles"])

# Standard Empty MVT vector tile payload (empty bytes is valid empty protobuf tile)
EMPTY_MVT_BYTES = b""


ALLOWED_LAYERS = {"pfz", "eez", "mpa", "recommendation"}


@router.get("/tiles/config")
async def get_tiles_config() -> Response:
    """
    Return available basemap layer configurations, tile URL templates,
    and metadata for map clients.
    """
    raw_key = (
        os.getenv("CARTO_API_KEY")
        or os.getenv("NEXT_PUBLIC_CARTO_API_KEY")
        or ""
    ).strip()
    normalized = raw_key.lower()
    # Keyless CARTO CDN works when blank; treat common placeholders as unconfigured.
    has_carto_key = bool(
        raw_key
        and normalized not in ("", "undefined", "null", "none")
        and normalized != "your_carto_api_key_here"
        and not normalized.startswith("your_")
    )

    def _carto_url(template: str) -> str:
        # Only append ?api_key when a real key is configured; otherwise keyless CDN.
        if has_carto_key:
            return f"{template}?api_key={raw_key}"
        return template

    config = {
        "status": "success",
        "default_style": os.getenv("NEXT_PUBLIC_CARTO_BASEMAP_STYLE", "dark_all"),
        "carto_key_configured": has_carto_key,
        "layers": {
            "carto_dark": {
                "id": "carto_dark",
                "name": "CARTO Dark Matter",
                "type": "raster",
                "url": _carto_url("https://{s}.basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}{r}.png"),
                "subdomains": ["a", "b", "c", "d"],
                "attribution": '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
                "min_zoom": 0,
                "max_zoom": 19,
                "theme": "night_tactical",
            },
            "carto_voyager": {
                "id": "carto_voyager",
                "name": "CARTO Voyager",
                "type": "raster",
                "url": _carto_url("https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png"),
                "subdomains": ["a", "b", "c", "d"],
                "attribution": '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
                "min_zoom": 0,
                "max_zoom": 19,
                "theme": "day_nautical",
            },
            "carto_positron": {
                "id": "carto_positron",
                "name": "CARTO Positron",
                "type": "raster",
                "url": _carto_url("https://{s}.basemaps.cartocdn.com/rastertiles/light_all/{z}/{x}/{y}{r}.png"),
                "subdomains": ["a", "b", "c", "d"],
                "attribution": '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
                "min_zoom": 0,
                "max_zoom": 19,
                "theme": "high_contrast",
            },
            "esri_ocean": {
                "id": "esri_ocean",
                "name": "Esri Ocean Basemap",
                "type": "raster",
                "url": "https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean/MapServer/tile/{z}/{y}/{x}",
                "attribution": '&copy; <a href="https://www.esri.com/">Esri</a> &mdash; Sources: GEBCO, NOAA, CHS, OSU, UNH, CSUMB, National Geographic, DeLorme, NAVTEQ, and Esri',
                "min_zoom": 0,
                "max_native_zoom": 13,
                "max_zoom": 18,
                "theme": "ocean",
            },
            "esri_dark": {
                "id": "esri_dark",
                "name": "Esri Dark Gray",
                "type": "raster",
                "url": "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
                "attribution": '&copy; <a href="https://www.esri.com/">Esri</a> &mdash; Esri, DeLorme, NAVTEQ',
                "min_zoom": 0,
                "max_native_zoom": 16,
                "max_zoom": 18,
                "theme": "night_tactical",
            },
            "osm": {
                "id": "osm",
                "name": "OpenStreetMap",
                "type": "raster",
                "url": "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
                "subdomains": ["a", "b", "c"],
                "attribution": '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
                "min_zoom": 0,
                "max_zoom": 19,
                "theme": "community",
            },
        },
        "cache": {
            "max_age_seconds": 3600,
        },
    }

    return Response(
        content=json.dumps(config),
        media_type="application/json",
        headers={
            "Cache-Control": "public, max-age=3600",
        },
    )


@router.get("/tiles/{z}/{x}/{y}.pbf")
async def get_tile(z: int, x: int, y: int, layer: str = "pfz") -> Response:
    """
    Serve vector tile for coordinate (z, x, y).
    Queries PostGIS ST_AsMVT per layer when connected;
    Caches in Redis under 'tiles:{layer}:{z}/{x}/{y}' for 3600s;
    Returns 503 with 'X-Tile-Fallback: true' header when DB/Redis is down (no empty-tile caching).
    """
    if not (0 <= z <= 24):
        return Response(status_code=400, content="Invalid zoom level")

    max_coord = 2**z
    if not (0 <= x < max_coord and 0 <= y < max_coord):
        return Response(status_code=400, content="Invalid tile coordinates")

    safe_layer = layer.strip().lower() if layer else "pfz"
    if safe_layer not in ALLOWED_LAYERS:
        safe_layer = "pfz"

    cache_key = f"tiles:{safe_layer}:{z}/{x}/{y}"

    # 1. Check Redis cache
    cached_tile = None
    try:
        cached_tile = await get_tile_cache(cache_key)
    except Exception as e:
        logger.warning("Redis cache read error for %s: %s", cache_key, e)

    if cached_tile is not None:
        return Response(
            content=cached_tile,
            media_type="application/x-protobuf",
            headers={
                "Content-Type": "application/x-protobuf",
                "Cache-Control": "public, max-age=3600",
                "X-Tile-Layer": safe_layer,
                "X-Tile-Coords": f"{z}/{x}/{y}",
            },
        )

    # 2. Query PostGIS ST_AsMVT per layer
    tile_bytes = None
    try:
        tile_bytes = await get_mvt_tile(safe_layer, z, x, y)
    except Exception as e:
        logger.warning("PostGIS ST_AsMVT error for %s: %s", cache_key, e)

    # 3. If DB connected & returned tile, cache in Redis and return
    if tile_bytes is not None:
        try:
            await set_tile_cache(cache_key, tile_bytes, ttl_seconds=3600)
        except Exception as e:
            logger.warning("Redis set_tile_cache failed for %s: %s", cache_key, e)

        return Response(
            content=tile_bytes,
            media_type="application/x-protobuf",
            headers={
                "Content-Type": "application/x-protobuf",
                "Cache-Control": "public, max-age=3600",
                "X-Tile-Layer": safe_layer,
                "X-Tile-Coords": f"{z}/{x}/{y}",
            },
        )

    # 4. No empty-tile fallback: surface DB outage as 503 (never cache emptiness)
    return Response(
        content="Tile unavailable: PostGIS offline",
        status_code=503,
        media_type="text/plain",
        headers={
            "Cache-Control": "no-store",
            "X-Tile-Layer": safe_layer,
            "X-Tile-Coords": f"{z}/{x}/{y}",
            "X-Tile-Fallback": "true",
        },
    )
