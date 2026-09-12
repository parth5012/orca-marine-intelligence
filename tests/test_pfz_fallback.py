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
