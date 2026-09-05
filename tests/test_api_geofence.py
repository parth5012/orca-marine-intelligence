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
# 1. Geofence Point Check Endpoint Tests (GET & POST)
# ---------------------------------------------------------------------------
class TestGeofenceCheckEndpoint:
    """Tests for /api/geofence/check (GET & POST)."""

    def test_safe_point_kochi_get(self, client):
        """Safe point test (Kochi 9.93, 76.26): inside sovereign EEZ, clear of MPAs and IMBL."""
        resp = client.get("/api/geofence/check", params={"lat": 9.93, "lon": 76.26})
        assert resp.status_code == 200
        data = resp.json()

        assert data["inside_eez"] is True
        assert data["inside_mpa"] is False
        assert data["near_imbl"] is False
        assert data["safety_status"] == "safe"
        assert data["alerts"] == []
        assert data["distance_to_imbl_km"] > 5.0
        assert data["distance_to_eez_border_km"] > 10.0
        assert data["latency_ms"] < 50.0

    def test_safe_point_kochi_post(self, client):
        """POST /api/geofence/check produces identical result for Kochi coordinate."""
        resp = client.post(
            "/api/geofence/check",
            json={"lat": 9.93, "lon": 76.26, "heading_deg": 180.0, "speed_kt": 8.5},
        )
        assert resp.status_code == 200
        data = resp.json()

        assert data["inside_eez"] is True
        assert data["inside_mpa"] is False
        assert data["near_imbl"] is False
        assert data["safety_status"] == "safe"
        assert data["heading_deg"] == 180.0
        assert data["speed_kt"] == 8.5

    def test_mpa_violation_gulf_of_mannar(self, client):
        """MPA violation test: Gulf of Mannar (9.0, 79.0) inside MPA sanctuary -> danger_violation."""
        resp = client.post("/api/geofence/check", json={"lat": 9.0, "lon": 79.0})
        assert resp.status_code == 200
        data = resp.json()

        assert data["inside_mpa"] is True
        assert data["safety_status"] == "danger_violation"
        assert "Mannar" in (data["nearest_mpa_name"] or "")
        assert any("Inside Marine Protected Area" in alert for alert in data["alerts"])

    def test_mpa_violation_vembanad(self, client):
        """MPA violation test: Vembanad sanctuary (9.65, 76.45) inside MPA -> danger_violation."""
        resp = client.get("/api/geofence/check", params={"lat": 9.65, "lon": 76.45})
        assert resp.status_code == 200
        data = resp.json()

        assert data["inside_mpa"] is True
        assert data["safety_status"] == "danger_violation"
        assert "Vembanad" in (data["nearest_mpa_name"] or "")
        assert any("Inside Marine Protected Area" in alert for alert in data["alerts"])

    def test_near_imbl_violation(self, client):
        """Near IMBL test (<2km to international border, e.g. 9.10, 79.53) -> near_imbl=True, danger_violation."""
        resp = client.get("/api/geofence/check", params={"lat": 9.10, "lon": 79.53})
        assert resp.status_code == 200
        data = resp.json()

        assert data["distance_to_imbl_km"] <= 2.0
        assert data["near_imbl"] is True
        assert data["safety_status"] == "danger_violation"
        assert any("Approaching International Maritime Boundary Line" in alert for alert in data["alerts"])

    def test_caution_approaching_eez_border(self, client):
        """Caution status when inside EEZ but within 10km of border (9.0, 77.45)."""
        resp = client.get("/api/geofence/check", params={"lat": 9.0, "lon": 77.45})
        assert resp.status_code == 200
        data = resp.json()

        assert data["inside_eez"] is True
        assert data["inside_mpa"] is False
        assert data["distance_to_eez_border_km"] <= 10.0
        assert data["safety_status"] == "caution"
        assert any("Approaching EEZ boundary" in alert for alert in data["alerts"])

    def test_outside_eez_violation(self, client):
        """Outside sovereign EEZ (2.0, 60.0 in international waters) -> danger_violation."""
        resp = client.get("/api/geofence/check", params={"lat": 2.0, "lon": 60.0})
        assert resp.status_code == 200
        data = resp.json()

        assert data["inside_eez"] is False
        assert data["safety_status"] == "danger_violation"
        assert any("Outside sovereign Exclusive Economic Zone" in alert for alert in data["alerts"])

    def test_coordinate_validation_out_of_range(self, client):
        """Invalid latitude (>90 or <-90) and longitude (>180 or <-180) return HTTP 400."""
        resp1 = client.get("/api/geofence/check", params={"lat": 95.0, "lon": 76.0})
        assert resp1.status_code == 400

        resp2 = client.post("/api/geofence/check", json={"lat": 9.93, "lon": 185.0})
        assert resp2.status_code == 400

    def test_missing_coordinates_returns_400(self, client):
        """Empty POST body returns HTTP 400."""
        resp = client.post("/api/geofence/check", json={})
        assert resp.status_code in (400, 422)


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
# 3. Geofence Route Endpoint Tests
# ---------------------------------------------------------------------------
class TestGeofenceRouteEndpoint:
    """Tests for POST /api/geofence/route."""

    def test_safe_route_in_kochi_waters(self, client):
        """A planned route entirely within safe Kochi waters returns safe=True, zero violations."""
        route_coords = [[76.26, 9.93], [76.20, 9.90]]
        resp = client.post("/api/geofence/route", json={"coordinates": route_coords})
        assert resp.status_code == 200
        data = resp.json()

        assert data["safe"] is True
        assert data["violations"] == []
        assert len(data["waypoint_checks"]) == 2
        assert data["min_distance_to_imbl_km"] > 10.0

    def test_route_crossing_marine_protected_area(self, client):
        """A route passing through the Gulf of Mannar MPA returns safe=False with violation."""
        route_coords = [[78.50, 9.00], [79.50, 9.00]]
        resp = client.post("/api/geofence/route", json={"coordinates": route_coords})
        assert resp.status_code == 200
        data = resp.json()

        assert data["safe"] is False
        assert len(data["violations"]) > 0
        assert any("Gulf Mannar" in v or "Marine Protected Area" in v for v in data["violations"])

    def test_route_approaching_imbl_boundary(self, client):
        """A route waypoint within 2km of IMBL triggers near_imbl violation."""
        route_coords = [[79.50, 9.10], [79.53, 9.10]]
        resp = client.post("/api/geofence/route", json={"coordinates": route_coords})
        assert resp.status_code == 200
        data = resp.json()

        assert data["safe"] is False
        assert data["min_distance_to_imbl_km"] <= 2.0
        assert any("International Maritime Boundary Line" in v for v in data["violations"])

    def test_route_dict_waypoint_format(self, client):
        """Accepts dict-style waypoints [{'lat': ..., 'lon': ...}] transparently."""
        dict_waypoints = [{"lat": 9.93, "lon": 76.26}, {"lat": 9.90, "lon": 76.20}]
        resp = client.post("/api/geofence/route", json={"coordinates": dict_waypoints})
        assert resp.status_code == 200
        data = resp.json()

        assert data["safe"] is True
        assert len(data["waypoint_checks"]) == 2

    def test_route_empty_coordinates_fails(self, client):
        """Empty route array raises HTTP 400 Bad Request."""
        resp = client.post("/api/geofence/route", json={"coordinates": []})
        assert resp.status_code == 400


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
