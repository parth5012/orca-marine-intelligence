"""
Unit and Integration Tests for FastAPI Application Core and Live Routers

Owner: M-C (Backend API & Platform)
Module: tests/test_main.py
"""

import os
import sys
from unittest.mock import AsyncMock, patch

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from fastapi.testclient import TestClient

from backend.main import app, check_database, check_redis


@pytest.fixture
def client():
    """TestClient fixture managing lifespan cleanly."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_routes_mounted():
    """Verify core routers are mounted under /api prefix (T3 prune applied)."""
    paths = set(app.openapi()["paths"].keys())

    # Core endpoints mounted under /api
    assert "/health" in paths
    assert "/api/chat" in paths
    assert "/api/pfz/today" in paths
    assert "/api/pfz/history" in paths
    assert "/api/weather/current" in paths
    assert "/api/weather/history" in paths
    assert "/api/geofence/status" in paths
    assert "/api/tiles/{z}/{x}/{y}.pbf" in paths
    assert "/api/tiles/config" in paths

    # Unused aliases pruned
    assert "/api/chat/stream" not in paths
    assert "/api/chat/history" not in paths
    assert "/api/geofence/check" not in paths
    assert "/api/geofence/route" not in paths


def test_cors_middleware_defaults(client):
    """Verify CORS middleware responds with correct headers for allowed origins."""
    for origin in ["http://localhost:3000", "https://cron-system.vercel.app"]:
        response = client.get("/health", headers={"Origin": origin})
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == origin
        assert response.headers.get("access-control-allow-credentials") == "true"


def test_health_check_endpoint(client):
    """Verify /health endpoint reports detailed service readiness."""
    response = client.get("/health")
    assert response.status_code == 200

    data = response.json()
    assert "status" in data
    assert data["status"] in ["ok", "degraded"]
    assert data["service"] == "orca-marine-intelligence"
    assert data["version"] == "0.1.0"
    assert isinstance(data["uptime"], (int, float))
    assert data["uptime"] >= 0
    assert data["database"] in ["connected", "disconnected"]
    assert data["redis"] in ["connected", "disconnected"]
    assert data["data_source"] in ["mock", "live"]
    assert "telemetry" in data
    assert "langsmith" in data["telemetry"]
    assert "enabled" in data["telemetry"]["langsmith"]
    assert "project" in data["telemetry"]["langsmith"]


@pytest.mark.asyncio
async def test_health_check_healthy_status():
    """Verify /health reports 'ok' when database and redis are connected."""
    with patch("backend.main.check_database", new_callable=AsyncMock) as mock_db, \
         patch("backend.main.check_redis", new_callable=AsyncMock) as mock_redis:
        mock_db.return_value = "connected"
        mock_redis.return_value = "connected"

        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert data["database"] == "connected"
            assert data["redis"] == "connected"


@pytest.mark.asyncio
async def test_health_check_degraded_status():
    """Verify /health reports 'degraded' when database or redis is disconnected."""
    with patch("backend.main.check_database", new_callable=AsyncMock) as mock_db, \
         patch("backend.main.check_redis", new_callable=AsyncMock) as mock_redis:
        mock_db.return_value = "disconnected"
        mock_redis.return_value = "connected"

    with TestClient(app, raise_server_exceptions=False) as c:
        response = c.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["database"] == "disconnected"


def test_get_telemetry_status_permutations():
    """Verify get_telemetry_status correctly evaluates flags and filters placeholders."""
    from backend.main import get_telemetry_status

    with patch.dict(os.environ, {"LANGCHAIN_TRACING_V2": "false", "LANGCHAIN_API_KEY": ""}, clear=False):
        status = get_telemetry_status()
        assert status["langsmith"]["enabled"] is False

    with patch.dict(os.environ, {"LANGCHAIN_TRACING_V2": "true", "LANGCHAIN_API_KEY": "your_langsmith_api_key_here"}, clear=False):
        status = get_telemetry_status()
        assert status["langsmith"]["enabled"] is False
        assert status["langsmith"]["api_key_configured"] is False

    with patch.dict(os.environ, {"LANGCHAIN_TRACING_V2": "true", "LANGCHAIN_API_KEY": "ls__valid_key_123", "LANGCHAIN_PROJECT": "orca-test"}, clear=False):
        status = get_telemetry_status()
        assert status["langsmith"]["enabled"] is True
        assert status["langsmith"]["api_key_configured"] is True
        assert status["langsmith"]["project"] == "orca-test"

