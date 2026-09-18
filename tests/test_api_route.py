"""
Tests for Backend Route Safety API (T8 #167)
GET /api/route/safe
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def test_safe_route_direct(client):
    """Kochi offshore safe route returns direct path with valid metrics."""
    # Kochi port (9.9312, 76.2673) to KC-01 (9.9312, 75.8500)
    response = client.get(
        "/api/route/safe",
        params={
            "olat": 9.9312,
            "olon": 76.2673,
            "dlat": 9.9312,
            "dlon": 75.8500,
            "wave_height_m": 1.2,
            "wind_speed_kt": 15.0,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert len(data["waypoints"]) >= 2
    assert data["distance_km"] > 40
    assert data["distance_nm"] > 20
    assert "bearing" in data
    assert data["eta_min"] > 0
    assert data["safety_label"] in ("SAFE", "CAUTION", "AVOID")
    assert "cost_breakdown" in data
    cb = data["cost_breakdown"]
    assert "distance_base" in cb
    assert "wave_penalty" in cb
    assert "wind_penalty" in cb
    assert "total_cost" in cb


def test_safe_route_mpa_detour(client):
    """Route cutting through Vembanad MPA triggers detour waypoint and warning."""
    # South of Vembanad to North of Vembanad
    response = client.get(
        "/api/route/safe",
        params={
            "olat": 9.5500,
            "olon": 76.4500,
            "dlat": 9.7500,
            "dlon": 76.4500,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["waypoints"]) > 2
    assert any("Marine Protected Area" in h for h in data["hazards"])


def test_safe_route_imbl_warning(client):
    """Route near IMBL border (<2km) triggers IMBL hazard warning."""
    response = client.get(
        "/api/route/safe",
        params={
            "olat": 9.0950,
            "olon": 79.5250,
            "dlat": 9.1050,
            "dlon": 79.5400,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert any("International Maritime Boundary Line" in h for h in data["hazards"])


def test_safe_route_invalid_coords(client):
    """Out-of-bounds coordinates return 422 Unprocessable Entity."""
    response = client.get(
        "/api/route/safe",
        params={
            "olat": 199.9312,
            "olon": 76.2673,
            "dlat": 9.9312,
            "dlon": 75.8500,
        },
    )
    assert response.status_code in (400, 422)
