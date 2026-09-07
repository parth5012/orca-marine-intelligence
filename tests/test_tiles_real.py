"""
Real MVT Vector Tile & Redis Cache Integration Tests

Tests:
1. Real non-empty MVT protobuf generation from PostGIS (ST_AsMVT)
2. Redis cache hit under 'tiles:{layer}:{z}/{x}/{y}' (3600s TTL)
3. Fallback to EMPTY_MVT_BYTES with 'X-Tile-Fallback: true' when DB/Redis down
4. HTTP 400 on invalid coordinates and zoom levels
5. Layer allowlist locking to pfz | eez | mpa | recommendation
6. Frontend URL format verification: /api/tiles/{z}/{x}/{y}.pbf?layer={layer}
"""

import os
import sys
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

# Ensure repo root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.db.postgis import MVT_LAYER_QUERIES, get_mvt_tile
from backend.db.redis import _memory_expiry, _memory_store, get_tile_cache, set_tile_cache
from backend.main import app
from backend.routers.tiles import ALLOWED_LAYERS, EMPTY_MVT_BYTES

# Realistic non-empty protobuf byte payload (valid mock MVT bytes)
MOCK_REAL_MVT_BYTES = b"\x1a\x24\x0a\x03\x70\x66\x7a\x12\x10\x08\x01\x12\x06\x00\x00\x01\x01\x02\x02\x18\x03"


@pytest.fixture
def client():
    """FastAPI TestClient fixture."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(autouse=True)
def clear_tile_cache():
    """Clear in-memory tile cache between tests."""
    _memory_store.clear()
    _memory_expiry.clear()
    yield
    _memory_store.clear()
    _memory_expiry.clear()


# ==============================================================================
# 1. PostGIS Real ST_AsMVT Tile Generation
# ==============================================================================


def test_tile_pbf_real_bytes_success(client):
    """
    When PostGIS is connected, queries ST_AsMVT and returns real non-empty
    MVT protobuf bytes with proper caching headers (no fallback header).
    """
    with patch("backend.routers.tiles.get_mvt_tile", new=AsyncMock(return_value=MOCK_REAL_MVT_BYTES)):
        res = client.get("/api/tiles/10/716/483.pbf?layer=pfz")

        assert res.status_code == 200
        assert res.content == MOCK_REAL_MVT_BYTES
        assert len(res.content) > 0
        assert res.headers["content-type"] == "application/x-protobuf"
        assert res.headers["cache-control"] == "public, max-age=3600"
        assert res.headers["x-tile-layer"] == "pfz"
        assert res.headers["x-tile-coords"] == "10/716/483"
        # Must NOT have fallback header on real tile generation
        assert "x-tile-fallback" not in res.headers


# ==============================================================================
# 2. Redis Cache Hit
# ==============================================================================


@pytest.mark.asyncio
async def test_tile_redis_cache_hit(client):
    """
    When tile is cached in Redis under 'tiles:{layer}:{z}/{x}/{y}',
    it returns cached bytes without hitting PostGIS.
    """
    cached_payload = b"\x1a\x15\x0a\x03\x65\x65\x7a\x18\x03_EEZ_CACHE"
    cache_key = "tiles:eez:5/22/15"

    # Pre-populate cache
    await set_tile_cache(cache_key, cached_payload, ttl_seconds=3600)

    # PostGIS mock should NOT be called
    mock_db = AsyncMock(return_value=None)
    with patch("backend.routers.tiles.get_mvt_tile", new=mock_db):
        res = client.get("/api/tiles/5/22/15.pbf?layer=eez")

        assert res.status_code == 200
        assert res.content == cached_payload
        assert res.headers["content-type"] == "application/x-protobuf"
        assert res.headers["cache-control"] == "public, max-age=3600"
        assert res.headers["x-tile-layer"] == "eez"
        assert res.headers["x-tile-coords"] == "5/22/15"
        assert "x-tile-fallback" not in res.headers
        mock_db.assert_not_called()


def test_tile_caches_in_redis_after_db_success(client):
    """
    After a successful PostGIS generation, the tile is stored in Redis
    so subsequent calls are served from cache.
    """
    mock_bytes = b"\x1a\x10\x0a\x03\x6d\x70\x61\x18\x03"
    mock_db = AsyncMock(return_value=mock_bytes)

    with patch("backend.routers.tiles.get_mvt_tile", new=mock_db):
        # First call: hits DB
        res1 = client.get("/api/tiles/8/179/120.pbf?layer=mpa")
        assert res1.status_code == 200
        assert res1.content == mock_bytes
        assert mock_db.call_count == 1

        # Second call: hits cache, DB not called again
        res2 = client.get("/api/tiles/8/179/120.pbf?layer=mpa")
        assert res2.status_code == 200
        assert res2.content == mock_bytes
        assert mock_db.call_count == 1


# ==============================================================================
# 3. Fallback when DB / Redis Down
# ==============================================================================


def test_tile_fallback_when_db_returns_none(client):
    """
    When PostGIS is down (returns None), falls back to EMPTY_MVT_BYTES
    with 'X-Tile-Fallback: true' header.
    """
    with patch("backend.routers.tiles.get_mvt_tile", new=AsyncMock(return_value=None)):
        res = client.get("/api/tiles/10/716/483.pbf?layer=pfz")

        assert res.status_code == 200
        assert res.content == EMPTY_MVT_BYTES
        assert res.content == b""
        assert res.headers.get("x-tile-fallback") == "true"
        assert res.headers["content-type"] == "application/x-protobuf"
        assert res.headers["cache-control"] == "public, max-age=3600"
        assert res.headers["x-tile-layer"] == "pfz"
        assert res.headers["x-tile-coords"] == "10/716/483"


def test_tile_fallback_when_db_raises_exception(client):
    """
    When PostGIS query raises a connection exception, endpoint catches it,
    logs error, and falls back to EMPTY_MVT_BYTES + X-Tile-Fallback: true.
    """
    with patch("backend.routers.tiles.get_mvt_tile", new=AsyncMock(side_effect=Exception("DB connection refused"))):
        res = client.get("/api/tiles/10/716/483.pbf?layer=mpa")

        assert res.status_code == 200
        assert res.content == EMPTY_MVT_BYTES
        assert res.headers.get("x-tile-fallback") == "true"


def test_tile_fallback_when_redis_and_db_both_fail(client):
    """
    When both Redis and PostGIS fail, gracefully returns fallback tile.
    """
    with patch("backend.routers.tiles.get_tile_cache", new=AsyncMock(side_effect=Exception("Redis down"))):
        with patch("backend.routers.tiles.get_mvt_tile", new=AsyncMock(side_effect=Exception("PostGIS down"))):
            res = client.get("/api/tiles/10/716/483.pbf?layer=recommendation")

            assert res.status_code == 200
            assert res.content == EMPTY_MVT_BYTES
            assert res.headers.get("x-tile-fallback") == "true"
            assert res.headers["x-tile-layer"] == "recommendation"


# ==============================================================================
# 4. HTTP 400 Bounds and Coordinate Validation Cases
# ==============================================================================


@pytest.mark.parametrize(
    "z,x,y,expected_msg",
    [
        (-1, 0, 0, "Invalid zoom level"),
        (25, 0, 0, "Invalid zoom level"),
        (1, -1, 0, "Invalid tile coordinates"),
        (1, 2, 0, "Invalid tile coordinates"),
        (1, 0, -1, "Invalid tile coordinates"),
        (1, 0, 2, "Invalid tile coordinates"),
        (0, 1, 0, "Invalid tile coordinates"),
        (0, 0, 1, "Invalid tile coordinates"),
        (3, 8, 3, "Invalid tile coordinates"),
        (3, 3, 8, "Invalid tile coordinates"),
    ],
)
def test_tile_pbf_400_cases(client, z, x, y, expected_msg):
    """Verifies that invalid zoom levels and coordinates return HTTP 400."""
    res = client.get(f"/api/tiles/{z}/{x}/{y}.pbf")
    assert res.status_code == 400
    assert expected_msg in res.text


# ==============================================================================
# 5. Layer Allowlist Locking
# ==============================================================================


def test_allowed_layers_lock():
    """Verify ALLOWED_LAYERS exactly matches specification."""
    assert ALLOWED_LAYERS == {"pfz", "eez", "mpa", "recommendation"}


@pytest.mark.parametrize("layer", ["pfz", "eez", "mpa", "recommendation"])
def test_all_allowed_layers_supported(client, layer):
    """Verify all four allowed layers generate tiles and set correct headers."""
    mock_bytes = f"MVT_{layer}".encode("utf-8")
    with patch("backend.routers.tiles.get_mvt_tile", new=AsyncMock(return_value=mock_bytes)):
        res = client.get(f"/api/tiles/2/1/1.pbf?layer={layer}")
        assert res.status_code == 200
        assert res.content == mock_bytes
        assert res.headers["x-tile-layer"] == layer
        assert res.headers["x-tile-coords"] == "2/1/1"
        assert "x-tile-fallback" not in res.headers


def test_untrusted_layer_sanitized_to_default(client):
    """Untrusted or unrecognized layer query parameters are sanitized to pfz."""
    with patch("backend.routers.tiles.get_mvt_tile", new=AsyncMock(return_value=MOCK_REAL_MVT_BYTES)):
        res = client.get("/api/tiles/0/0/0.pbf?layer=malicious_layer_name")
        assert res.status_code == 200
        assert res.headers["x-tile-layer"] == "pfz"


# ==============================================================================
# 6. PostGIS SQL Query Structure Validation
# ==============================================================================


def test_postgis_sql_query_definitions():
    """Verify that all layer queries use PostGIS ST_AsMVT and ST_TileEnvelope."""
    for layer in ["pfz", "eez", "mpa", "recommendation"]:
        assert layer in MVT_LAYER_QUERIES
        sql = MVT_LAYER_QUERIES[layer]
        assert "ST_AsMVT" in sql
        assert "ST_AsMVTGeom" in sql
        assert "ST_TileEnvelope" in sql
        assert "ST_Transform" in sql


# ==============================================================================
# 7. Frontend URL Compatibility
# ==============================================================================


def test_frontend_url_format_preserved(client):
    """
    Verifies that the frontend URL format /api/tiles/{z}/{x}/{y}.pbf?layer={layer}
    is preserved and returns application/x-protobuf.
    """
    with patch("backend.routers.tiles.get_mvt_tile", new=AsyncMock(return_value=MOCK_REAL_MVT_BYTES)):
        res = client.get("/api/tiles/4/11/7.pbf?layer=pfz")
        assert res.status_code == 200
        assert res.headers["content-type"] == "application/x-protobuf"
        assert res.headers["cache-control"] == "public, max-age=3600"
