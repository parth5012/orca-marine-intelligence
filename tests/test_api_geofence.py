"""
Unit and Integration Tests for Geofence Boundary Router & Ingest Layer

Tests:
1. Safe point check (Kochi 9.93, 76.26 -> inside_eez=True, inside_mpa=False, near_imbl=False, safety_status='safe')
2. MPA violation check (Gulf of Mannar 9.0, 79.0 -> inside_mpa=True, safety_status='danger_violation')
3. MPA violation check (Vembanad 9.65, 76.45 -> inside_mpa=True, safety_status='danger_violation')
4. Near IMBL check (<2km to IMBL -> near_imbl=True, safety_status='danger_violation')
5. Caution zone near EEZ border (<10km -> caution)
6. Route validation: safe route vs route crossing MPA / IMBL buffer
7. Geofence status endpoint (active MPAs, EEZ zones, 2.0km IMBL buffer rule)
8. Coordinate bounds validation and error handling
9. Boundary ingestion and spatial geometry helper functions
"""

from __future__ import annotations

import os
import sys

# Ensure repository root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.ingest.boundaries import (
    ingest_boundaries,
    get_eez_boundaries,
    get_mpa_boundaries,
    get_imbl_segments,
    check_point_in_eez,
    check_point_in_mpa,
    distance_to_imbl_km,
    haversine_km,
    distance_point_to_segment_km,
    point_in_polygon,
)


@pytest.fixture
def client():
    """TestClient fixture managing lifespan cleanly."""
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# 1. Geofence Point Check Endpoints REMOVED (T3 prune, Wayfinder map #92)
# ---------------------------------------------------------------------------
class TestGeofenceCheckEndpoint:
    """T3 prune: GET+POST /api/geofence/check deleted — must 404."""

    def test_check_get_gone(self, client):
        resp = client.get("/api/geofence/check", params={"lat": 9.93, "lon": 76.26})
        assert resp.status_code == 404

    def test_check_post_gone(self, client):
        resp = client.post("/api/geofence/check", json={"lat": 9.93, "lon": 76.26})
        assert resp.status_code == 404
# ---------------------------------------------------------------------------
# 2. Geofence Status Endpoint Tests
# ---------------------------------------------------------------------------
class TestGeofenceStatusEndpoint:
    """Tests for GET /api/geofence/status."""

    def test_geofence_status_returns_expected_metadata(self, client):
        """Status endpoint returns active MPAs, EEZ zones, 2km threshold, and boundary counts."""
        resp = client.get("/api/geofence/status")
        assert resp.status_code == 200
        data = resp.json()

        assert data["status"] == "ok"
        assert "active_mpas" in data
        assert any("Vembanad" in mpa for mpa in data["active_mpas"])
        assert any("Mannar" in mpa for mpa in data["active_mpas"])

        assert "eez_zones" in data
        assert any("West" in zone for zone in data["eez_zones"])
        assert any("East" in zone for zone in data["eez_zones"])

        assert data["imbl_buffer_km"] == 2.0
        assert data["imbl_caution_threshold_km"] == 5.0
        assert data["eez_caution_threshold_km"] == 10.0
        assert data["count_protected_boundaries"] >= 4
        assert data["protected_boundaries_count"] >= 4


# ---------------------------------------------------------------------------
# 3. Geofence Route Endpoint REMOVED (T3 prune, Wayfinder map #92)
# ---------------------------------------------------------------------------
class TestGeofenceRouteEndpoint:
    """T3 prune: POST /api/geofence/route deleted — must 404."""

    def test_route_gone(self, client):
        resp = client.post(
            "/api/geofence/route",
            json={"coordinates": [[76.26, 9.93], [76.20, 9.90]]},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 4. Ingest Layer & Geometry Helper Unit Tests
# ---------------------------------------------------------------------------
class TestBoundariesIngestLayer:
    """Unit tests for backend/ingest/boundaries.py."""

    @pytest.mark.asyncio
    async def test_ingest_boundaries_loads_features(self):
        """Verify boundary ingest loads EEZ and MPA features gracefully."""
        res = await ingest_boundaries()
        assert isinstance(res, dict)
        assert res["eez_count"] >= 2
        assert res["mpa_count"] >= 2
        assert res["status"] == "loaded"

    def test_get_boundaries_getters(self):
        """Verify boundary getter functions return non-empty collections."""
        eez = get_eez_boundaries()
        mpa = get_mpa_boundaries()
        imbl = get_imbl_segments()

        assert len(eez) >= 2
        assert len(mpa) >= 2
        assert len(imbl) >= 10

        # Verify IMBLSegment attributes and unpacking
        seg = imbl[0]
        p1, p2 = seg
        assert hasattr(seg, "lat1")
        assert hasattr(seg, "lon1")
        assert seg["lat2"] == p2.lat
        assert seg["lon2"] == p2.lon

    def test_haversine_and_segment_distance(self):
        """Verify geodetic calculation helpers."""
        # Distance between identical points is 0
        assert haversine_km(9.93, 76.26, 9.93, 76.26) == 0.0

        # Distance from point (9.05, 79.52) to segment (9.10, 79.5333)-(9.00, 79.5167) < 2km
        d = distance_point_to_segment_km(9.05, 79.52, 9.10, 79.5333, 9.00, 79.5167)
        assert d < 2.0

    def test_ray_casting_point_in_polygon(self):
        """Verify ray-casting containment helper."""
        # Simple square: [lon, lat]
        square = [[[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0], [0.0, 0.0]]]
        assert point_in_polygon(1.0, 1.0, square) is True
        assert point_in_polygon(3.0, 3.0, square) is False

    def test_check_point_in_eez_and_mpa(self):
        """Direct check of Kochi and Gulf of Mannar in boundary helpers."""
        inside_eez, dist_eez = check_point_in_eez(9.93, 76.26)
        assert inside_eez is True
        assert dist_eez > 10.0

        inside_mpa, mpa_name, _ = check_point_in_mpa(9.0, 79.0)
        assert inside_mpa is True
        assert "Mannar" in (mpa_name or "")
