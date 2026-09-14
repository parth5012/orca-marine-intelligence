"""
Tests for /api/status endpoint and status monitoring.
"""

import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from fastapi.testclient import TestClient
from backend.main import app

@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c

def test_api_status_endpoint_returns_ok_when_services_connected(client):
    """Verify /api/status returns 200 with service health dictionary."""
    with patch("backend.routers.status.check_database", new_callable=AsyncMock) as mock_db, \
         patch("backend.routers.status.check_redis", new_callable=AsyncMock) as mock_redis:
        mock_db.return_value = "connected"
        mock_redis.return_value = "connected"

        response = client.get("/api/status")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "services" in data
        services = data["services"]
        assert services["weather"] is True
        assert services["pfz"] is True
        assert services["geofence"] is True
        assert services["tiles"] is True
        assert services["chat"] is True

def test_api_status_endpoint_reports_degraded_when_db_down(client):
    """Verify /api/status returns degraded when database is disconnected."""
    with patch("backend.routers.status.check_database", new_callable=AsyncMock) as mock_db, \
         patch("backend.routers.status.check_redis", new_callable=AsyncMock) as mock_redis:
        mock_db.return_value = "disconnected"
        mock_redis.return_value = "connected"

        response = client.get("/api/status")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert "services" in data
