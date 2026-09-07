"""
Vector Tile Server Router & Basemap Configuration Provider

Owner: M-C (Backend API & Platform) — GET /api/tiles/config, GET /api/tiles/{z}/{x}/{y}.pbf
Module: backend/routers/tiles.py

Serves basemap tile configuration metadata and vector tile endpoints for Leaflet / MapLibre.
"""

import json
import os
from typing import Any, Dict
from fastapi import APIRouter, Response

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
    has_carto_key = bool(raw_key and not raw_key.lower().startswith("your_"))

    config = {
        "status": "success",
        "default_style": os.getenv("NEXT_PUBLIC_CARTO_BASEMAP_STYLE", "dark_all"),
        "carto_key_configured": has_carto_key,
        "layers": {
            "carto_dark": {
                "id": "carto_dark",
                "name": "CARTO Dark Matter",
                "type": "raster",
                "url": "https://{s}.basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}{r}.png",
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
                "url": "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png",
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
                "url": "https://{s}.basemaps.cartocdn.com/rastertiles/light_all/{z}/{x}/{y}{r}.png",
                "subdomains": ["a", "b", "c", "d"],
                "attribution": '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
                "min_zoom": 0,
                "max_zoom": 19,
                "theme": "high_contrast",
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
    Returns an empty MVT (Mapbox Vector Tile) byte sequence with 3600s caching
    when dynamic PostGIS ST_AsMVT generation is in fallback/mock mode.
    """
    if z < 0 or z > 24:
        return Response(status_code=400, content="Invalid zoom level")

    max_coord = 2**z
    if x < 0 or x >= max_coord or y < 0 or y >= max_coord:
        return Response(status_code=400, content="Invalid tile coordinates")

    safe_layer = layer.strip().lower() if layer else "pfz"
    if safe_layer not in ALLOWED_LAYERS:
        safe_layer = "pfz"

    return Response(
        content=EMPTY_MVT_BYTES,
        media_type="application/x-protobuf",
        headers={
            "Content-Type": "application/x-protobuf",
            "Cache-Control": "public, max-age=3600",
            "X-Tile-Layer": safe_layer,
            "X-Tile-Coords": f"{z}/{x}/{y}",
        },
    )
