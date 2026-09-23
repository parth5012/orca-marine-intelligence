"""
Tests for T5 (#120): Commit valid data/pfz-today.geojson fallback file.
"""

import json
from pathlib import Path
from fastapi.testclient import TestClient

from backend.main import app
from backend.ingest.incois_textdata import load_local_pfz


def test_pfz_today_geojson_exists_and_valid():
    """Verify data/pfz-today.geojson exists, has features, and valid properties."""
    path = Path("data/pfz-today.geojson")
    assert path.is_file(), "data/pfz-today.geojson must exist"

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data.get("type") == "FeatureCollection"
    features = data.get("features", [])
    assert len(features) > 0, "features count must be greater than 0"

    for feat in features:
        assert feat.get("type") == "Feature"
        geom = feat.get("geometry", {})
        assert geom.get("type") == "Point"
        coords = geom.get("coordinates")
        assert isinstance(coords, list) and len(coords) >= 2
        # Lon/lat order: lon is approx 60-95 in Indian waters, lat is 5-30
        assert coords[0] > 40, f"Expected longitude first, got {coords}"

        props = feat.get("properties", {})
        assert "zone_id" in props and props["zone_id"], "Each feature must have zone_id"
        assert "place" in props and props["place"], "Each feature must have place"
        assert "sector" in props and props["sector"], "Each feature must have sector"


def test_load_local_pfz_fallback():
    """Verify load_local_pfz loads features directly from disk."""
    features = load_local_pfz()
    assert len(features) > 0
    assert "zone_id" in features[0]["properties"]
    assert "place" in features[0]["properties"]
    assert "sector" in features[0]["properties"]


def test_api_pfz_today_endpoint_offline():
    """Verify GET /api/pfz/today works without live INCOIS/Redis and returns valid GeoJSON."""
    from unittest.mock import patch, AsyncMock

    with patch("backend.db.redis.get_json", new=AsyncMock(return_value=None)), \
         patch("backend.ingest.incois_textdata.fetch_incois_sectors", side_effect=Exception("INCOIS Offline")):
        client = TestClient(app)
        response = client.get("/api/pfz/today")
        assert response.status_code == 200
        payload = response.json()
        assert payload.get("type") == "FeatureCollection"
        assert len(payload.get("features", [])) > 0
    features = payload.get("features", [])
    assert "zone_id" in features[0]["properties"]
    assert "place" in features[0]["properties"]
    assert "sector" in features[0]["properties"]


import pytest


@pytest.mark.asyncio
async def test_postgis_empty_falls_back_to_geojson():
    """Verify find_fishing_zones falls back to GeoJSON if PostGIS returns 0 zones across all radii."""
    from unittest.mock import patch, AsyncMock
    from backend.agents.subagents import fish_finder

    # Simulate DB alive, but find_pfz_near returns empty list
    with patch.object(fish_finder, "ping_database", new=AsyncMock(return_value=True)), \
         patch("backend.db.postgis.find_pfz_near", new=AsyncMock(return_value=[])):
        zones = await fish_finder.find_fishing_zones(lat=9.93, lon=76.26, radius_km=80.0, limit=5)
    assert len(zones) > 0, "Should fall back to GeoJSON and return zones"
    assert zones[0].get("place")


@pytest.mark.asyncio
async def test_seed_initial_pfz_if_empty():
    """Verify seed_initial_pfz_if_empty calls upsert_pfz_features when table count is 0."""
    from unittest.mock import patch, AsyncMock, MagicMock
    from backend.db.session import seed_initial_pfz_if_empty

    mock_session = AsyncMock()
    mock_res = MagicMock()
    mock_res.scalar.return_value = 0
    mock_session.execute.return_value = mock_res

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__.return_value = mock_session
    mock_session_ctx.__aexit__.return_value = None

    with patch("backend.db.session.AsyncSessionLocal", return_value=mock_session_ctx), \
         patch("backend.db.postgis.upsert_pfz_features", new=AsyncMock(return_value=437)) as mock_upsert:
        upserted = await seed_initial_pfz_if_empty(force=True)
        assert upserted == 437
        assert mock_upsert.called
