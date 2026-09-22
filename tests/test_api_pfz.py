"""
Tests for PFZ Ingestion, Copernicus Fallback, and API Endpoints

Owner: M-B (Data Extractors & Storage) & M-C (Backend API & Platform)
Module: tests/test_api_pfz.py
"""

import os
import sys
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

# Ensure repo root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.db.redis import get_json, set_json
from backend.ingest.copernicus_fallback import fetch_copernicus_fallback
from backend.ingest.incois_textdata import (
    fetch_incois_sectors,
    ingest_textdata,
    load_local_pfz,
    parse_incois_table,
)
from backend.main import app
from scripts.dms_to_decimal import decimal_to_dms, dms_to_decimal


@pytest.fixture
def client():
    """FastAPI TestClient fixture."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ==============================================================================
# 0. Hermetic guard: endpoint tests must never hit the live INCOIS portal nor
#    rewrite the committed data/pfz-today.geojson fallback file.
# ==============================================================================

def _fake_ingest_doc():
    """Deterministic INCOIS-shaped doc (Kerala + Maharashtra, 6 features)."""
    def _feat(place, sector, sector_name, lon, lat, bearing):
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "place": place,
                "sector": sector,
                "sector_name": sector_name,
                "bearing": bearing,
                "distance": "14-19",
                "depth": "55-60",
                "lat_dms": "8 33 18 N",
                "lon_dms": "76 10 02 E",
                "suitability": "high",
                "timestamp": "2026-09-20T06:49:07+00:00",
            },
        }

    features = [
        _feat("Gholvad", "SEC002", "MAHARASHTRA", 72.41083, 20.12083, 315),
        _feat("Dahanu", "SEC002", "MAHARASHTRA", 72.35, 19.95, 300),
        _feat("Versova", "SEC002", "MAHARASHTRA", 72.45, 19.10, 270),
        _feat("Pallithottam", "SEC005", "KERALA", 76.167, 8.555, 232),
        _feat("Kuzhuppilly", "SEC005", "KERALA", 76.05, 10.05, 250),
        _feat("Malipuram", "SEC005", "KERALA", 75.79833, 9.86194, 249),
    ]
    return {
        "type": "FeatureCollection",
        "source": "incois_textdata",
        "sector_count": 2,
        "count": len(features),
        "features": features,
    }


@pytest.fixture(autouse=True)
def _no_live_ingest_no_file_write(monkeypatch):
    """Patch the router's ingest (no portal, no disk write) + restore state.

    GET /api/pfz/today calls the real ingest_textdata() on Redis-miss, which
    scrapes live INCOIS and rewrites data/pfz-today.geojson. The portal's
    sector rotation then breaks every downstream file-reader test in the full
    suite (ports registry, kochi cache, satellite e2e, ...). Serve a fixed doc
    instead and restore the file if anything still touches it. Also snapshot
    the shared in-memory pfz:today key so test_endpoint_serves_from_redis
    cannot leak into the history tests.
    """
    import asyncio
    from pathlib import Path

    import backend.routers.pfz as pfz_router
    from backend.db import redis as redis_mod

    async def _fake_ingest(*args, **kwargs):
        return _fake_ingest_doc()

    monkeypatch.setattr(pfz_router, "ingest_textdata", _fake_ingest)

    repo_path = Path(__file__).resolve().parent.parent / "data" / "pfz-today.geojson"
    backup = repo_path.read_bytes() if repo_path.is_file() else None
    try:
        redis_backup = asyncio.run(redis_mod.get_json("pfz:today"))
    except Exception:
        redis_backup = None
    yield
    # Attempt every cleanup step even if one fails; surface the first error
    # instead of silently leaving polluted state for later tests.
    errors = []
    if backup is not None:
        try:
            repo_path.write_bytes(backup)
        except Exception as exc:
            errors.append(exc)
    try:
        if redis_backup is None:
            # Evict the test-seeded key (in-memory fallback + live Redis).
            redis_mod._memory_store.pop("pfz:today", None)
            redis_mod._memory_expiry.pop("pfz:today", None)
            client = redis_mod._redis_client
            if client is not None:
                asyncio.run(client.delete("pfz:today"))
        else:
            asyncio.run(redis_mod.set_json("pfz:today", redis_backup, ttl_seconds=21600))
    except Exception as exc:
        errors.append(exc)
    if errors:
        raise errors[0]


# ==============================================================================
# 1. Coordinate Conversion Helper Tests
# ==============================================================================

def test_dms_to_decimal_various_formats():
    """Test dms_to_decimal with all required DMS formats and variations."""
    # Degrees Minutes Seconds with symbols
    val = dms_to_decimal("9°55'52\"N")
    assert val is not None
    assert abs(val - 9.931111) < 1e-4

    # Space-separated DMS
    val = dms_to_decimal("9 55 52 N")
    assert val is not None
    assert abs(val - 9.931111) < 1e-4

    # Longitudes
    val = dms_to_decimal("76°16'02\"E")
    assert val is not None
    assert abs(val - 76.267222) < 1e-4

    val = dms_to_decimal("72 18 55 E")
    assert val is not None
    assert abs(val - 72.315278) < 1e-4

    # Letter format (d, m, s)
    val = dms_to_decimal("9d 55m 52s N")
    assert val is not None
    assert abs(val - 9.931111) < 1e-4

    # Pure decimal with direction
    val = dms_to_decimal("9.9311 N")
    assert val is not None
    assert abs(val - 9.9311) < 1e-4

    # Pure decimal without direction
    val = dms_to_decimal("9.9311")
    assert val is not None
    assert abs(val - 9.9311) < 1e-4

    # Direction negation for South and West
    val = dms_to_decimal("9.9311 S")
    assert val is not None
    assert abs(val - (-9.9311)) < 1e-4

    val = dms_to_decimal("9°55'52\"S")
    assert val is not None
    assert abs(val - (-9.931111)) < 1e-4

    val = dms_to_decimal("72 18 55 W")
    assert val is not None
    assert abs(val - (-72.315278)) < 1e-4

    # Leading sign
    val = dms_to_decimal("-72.315278")
    assert val is not None
    assert abs(val - (-72.315278)) < 1e-4


def test_dms_to_decimal_invalid_inputs():
    """Verify that invalid DMS strings return None."""
    assert dms_to_decimal(None) is None
    assert dms_to_decimal("") is None
    assert dms_to_decimal("   ") is None
    assert dms_to_decimal("invalid_coordinate") is None
    assert dms_to_decimal("999 99 99 N") is None  # Out of range lat
    assert dms_to_decimal("9 65 00 N") is None   # Invalid minutes >= 60
    assert dms_to_decimal("9 10 75 N") is None   # Invalid seconds >= 60


def test_decimal_to_dms():
    """Verify decimal_to_dms conversion."""
    dms_lat = decimal_to_dms(9.931111, is_lat=True)
    assert dms_lat.endswith("N")
    assert dms_lat.startswith("9 55")

    dms_south = decimal_to_dms(-9.931111, is_lat=True)
    assert dms_south.endswith("S")

    dms_lon = decimal_to_dms(76.267222, is_lat=False)
    assert dms_lon.endswith("E")
    assert dms_lon.startswith("76 16")


# ==============================================================================
# 2. INCOIS HTML Table Parsing Tests
# ==============================================================================

def test_parse_incois_table():
    """Test parsing HTML table into GeoJSON features with all expected properties."""
    html_content = """
    <html>
      <body>
        <table>
          <tr>
            <th>Landing Centre</th>
            <th>Direction</th>
            <th>Bearing (deg)</th>
            <th>Depth (m)</th>
            <th>Distance (km)</th>
            <th>Latitude (DMS)</th>
            <th>Longitude (DMS)</th>
          </tr>
          <tr>
            <td>Pallithottam</td>
            <td>SW</td>
            <td>232</td>
            <td>55-60</td>
            <td>14-19</td>
            <td>8 33 18 N</td>
            <td>76 10 02 E</td>
          </tr>
          <tr>
            <td>Vypin Bank</td>
            <td>W</td>
            <td>270</td>
            <td>30-40</td>
            <td>20-25</td>
            <td>9°55'52"N</td>
            <td>76°16'02"E</td>
          </tr>
        </table>
      </body>
    </html>
    """
    features = parse_incois_table(html_content, sector="SEC005", sector_name="KERALA")
    assert len(features) == 2

    f1 = features[0]
    assert f1["type"] == "Feature"
    assert f1["geometry"]["type"] == "Point"
    # [lon, lat]
    assert abs(f1["geometry"]["coordinates"][0] - 76.167222) < 1e-3
    assert abs(f1["geometry"]["coordinates"][1] - 8.555) < 1e-3

    props1 = f1["properties"]
    assert props1["place"] == "Pallithottam"
    assert props1["sector"] == "SEC005"
    assert props1["sector_name"] == "KERALA"
    assert props1["bearing"] == 232
    assert props1["distance"] == "14-19"
    assert props1["depth"] == "55-60"
    assert props1["lat_dms"] == "8 33 18 N"
    assert props1["lon_dms"] == "76 10 02 E"
    assert props1["suitability"] == "high"
    assert "timestamp" in props1

    f2 = features[1]
    assert f2["properties"]["place"] == "Vypin Bank"
    assert abs(f2["geometry"]["coordinates"][1] - 9.931111) < 1e-3


# ==============================================================================
# 3. Copernicus Fallback Ingest Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_copernicus_fallback():
    """Test fetch_copernicus_fallback generates calibrated points in Indian EEZ."""
    fallback_doc = await fetch_copernicus_fallback()
    assert fallback_doc["type"] == "FeatureCollection"
    assert fallback_doc["source"] == "copernicus_fallback"
    assert fallback_doc["count"] == len(fallback_doc["features"])
    assert fallback_doc["count"] > 10

    # Verify coverage across Indian EEZ
    sectors = {f["properties"]["sector"] for f in fallback_doc["features"]}
    assert "SEC001" in sectors  # Arabian Sea / Gujarat
    assert "SEC002" in sectors  # Maharashtra
    assert "SEC005" in sectors  # Kerala
    assert "SEC007" in sectors  # Tamil Nadu East / Bay of Bengal
    assert "SEC011" in sectors  # Andaman
    assert "SEC013" in sectors or "SEC014" in sectors  # Lakshadweep

    # Check coordinate bounds for Indian EEZ
    for feat in fallback_doc["features"]:
        lon, lat = feat["geometry"]["coordinates"]
        assert 60.0 <= lon <= 100.0, f"Longitude {lon} out of EEZ range"
        assert 5.0 <= lat <= 26.0, f"Latitude {lat} out of EEZ range"
        assert feat["properties"]["source"] == "copernicus_fallback"
        assert feat["properties"]["suitability"] == "high"


# ==============================================================================
# 4. GET /api/pfz/today Endpoint Tests
# ==============================================================================

def test_get_pfz_today_returns_200_geojson(client):
    """Verify GET /api/pfz/today returns 200 with a valid GeoJSON FeatureCollection."""
    response = client.get("/api/pfz/today")
    assert response.status_code == 200
    data = response.json()

    assert data["type"] == "FeatureCollection"
    assert "valid_until" in data
    assert "source" in data
    assert "sector_count" in data
    assert "features" in data
    assert isinstance(data["features"], list)
    assert len(data["features"]) > 0

    first = data["features"][0]
    assert first["type"] == "Feature"
    assert first["geometry"]["type"] == "Point"
    assert len(first["geometry"]["coordinates"]) == 2

    props = first["properties"]
    assert "place" in props
    assert "sector" in props
    assert "sector_name" in props
    assert "bearing" in props
    assert "distance" in props
    assert "depth" in props
    assert "lat_dms" in props
    assert "lon_dms" in props
    assert "suitability" in props
    assert "timestamp" in props


def test_get_pfz_today_sector_filtering(client):
    """Verify filtering by INCOIS sector code or sector name."""
    response = client.get("/api/pfz/today?sector=SEC002")
    assert response.status_code == 200
    data = response.json()
    assert len(data["features"]) > 0
    for feat in data["features"]:
        assert feat["properties"]["sector"] == "SEC002"

    # Name-based filter
    response_name = client.get("/api/pfz/today?sector=MAHARASHTRA")
    assert response_name.status_code == 200
    data_name = response_name.json()
    assert len(data_name["features"]) > 0
    for feat in data_name["features"]:
        assert feat["properties"]["sector_name"].upper() == "MAHARASHTRA" or feat["properties"]["sector"] == "SEC002"


def test_get_pfz_today_bbox_filtering(client):
    """Verify bounding box filtering (min_lon,min_lat,max_lon,max_lat)."""
    # Maharashtra coast box
    bbox_str = "71.5,18.5,73.5,21.0"
    response = client.get(f"/api/pfz/today?bbox={bbox_str}")
    assert response.status_code == 200
    data = response.json()
    assert len(data["features"]) > 0

    for feat in data["features"]:
        lon, lat = feat["geometry"]["coordinates"]
        assert 71.5 <= lon <= 73.5
        assert 18.5 <= lat <= 21.0

    # Invalid bbox format test
    bad_resp = client.get("/api/pfz/today?bbox=invalid_bbox")
    assert bad_resp.status_code == 400

    # min > max bbox test
    inverted_resp = client.get("/api/pfz/today?bbox=73.5,21.0,72.0,19.0")
    assert inverted_resp.status_code == 400


def test_get_pfz_today_limit(client):
    """Verify limit query parameter limits features returned."""
    response = client.get("/api/pfz/today?limit=5")
    assert response.status_code == 200
    data = response.json()
    assert len(data["features"]) == 5
    assert data["count"] == 5


# ==============================================================================
# 5. Fallback Behavior & Redis Caching Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_fallback_behavior_when_primary_fails():
    """Verify fallback to local geojson or copernicus when primary INCOIS live fails."""
    with patch("httpx.AsyncClient.get", side_effect=Exception("INCOIS portal timeout")):
        features = await fetch_incois_sectors(sectors=["SEC005"])
        assert len(features) > 0
        # Should have loaded from local fallback or copernicus
        assert features[0]["properties"]["sector"] == "SEC005"


@pytest.mark.asyncio
async def test_incois_circuit_breaker_fast_fails():
    """Verify that when circuit breaker is tripped, fetch_incois_sectors returns immediately."""
    import time
    from backend.ingest import incois_textdata

    incois_textdata._INCOIS_CIRCUIT_OPEN_UNTIL = time.time() + 60.0
    try:
        t0 = time.time()
        features = await incois_textdata.fetch_incois_sectors(sectors=["SEC005"])
        elapsed = time.time() - t0
        assert elapsed < 0.2  # Immediate fast-fail, no HTTP attempt
        assert len(features) > 0
    finally:
        incois_textdata._INCOIS_CIRCUIT_OPEN_UNTIL = 0.0


@pytest.mark.asyncio
async def test_redis_caching():
    """Verify Redis caching layer stores and retrieves pfz:today."""
    test_doc = {
        "type": "FeatureCollection",
        "source": "test_redis_source",
        "count": 1,
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [76.25, 9.95]},
                "properties": {
                    "place": "Redis Cache Spot",
                    "sector": "SEC005",
                    "sector_name": "KERALA",
                    "bearing": 250,
                    "distance": "20",
                    "depth": "40",
                    "lat_dms": "9 57 00 N",
                    "lon_dms": "76 15 00 E",
                    "suitability": "high",
                    "timestamp": "2026-09-05T00:00:00Z",
                    "source": "test_redis_source",
                },
            }
        ],
    }

    # Store in Redis
    await set_json("pfz:today", test_doc, ttl_seconds=21600)

    # Retrieve from Redis
    cached = await get_json("pfz:today")
    assert cached is not None
    assert cached["source"] == "test_redis_source"
    assert cached["features"][0]["properties"]["place"] == "Redis Cache Spot"


def test_endpoint_serves_from_redis(client):
    """Verify GET /api/pfz/today uses cached Redis data when available."""
    import asyncio

    test_cached_doc = {
        "type": "FeatureCollection",
        "source": "cached_redis_pfz",
        "count": 1,
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [76.25, 9.95]},
                    "properties": {
                        "zone_id": "SEC005_Cached_Zone_Alpha_001",
                        "place": "Cached Zone Alpha",
                    "sector": "SEC005",
                    "sector_name": "KERALA",
                    "bearing": 240,
                    "distance": "15",
                    "depth": "35",
                    "lat_dms": "9 57 00 N",
                    "lon_dms": "76 15 00 E",
                    "suitability": "high",
                    "timestamp": "2026-09-05T00:00:00Z",
                    "source": "cached_redis_pfz",
                },
            }
        ],
    }

    asyncio.run(set_json("pfz:today", test_cached_doc, ttl_seconds=21600))

    response = client.get("/api/pfz/today")
    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "cached_redis_pfz"
    assert data["features"][0]["properties"]["place"] == "Cached Zone Alpha"


# ==============================================================================
# 6. GET /api/pfz/history Endpoint Tests — 7-Day Sliding Window (#146)
# ==============================================================================

def test_get_pfz_history(client):
    """Verify GET /api/pfz/history returns 7-day sliding window."""
    response = client.get("/api/pfz/history?days=5")
    assert response.status_code == 200
    data = response.json()
    assert "history" in data
    assert data["days"] == 5
    assert len(data["history"]) == 5


def test_get_pfz_history_with_sector(client):
    """Verify historical query with sector filter."""
    response = client.get("/api/pfz/history?days=3&sector=SEC005")
    assert response.status_code == 200
    data = response.json()
    assert "history" in data
    assert data["sector"] == "SEC005"
