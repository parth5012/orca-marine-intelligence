"""
E2E Telemetry & CARTO Basemap Verification Suite

Owner: Cross-Lane Verification (M-A, M-C, M-D)
Module: tests/test_telemetry.py
Ticket: #52 (Wayfinder Map: #47)

Verifies:
1. LangSmith environment detection & telemetry reporting in /health.
2. RunnableConfig injection with run_name, tags, and sanitized metadata.
3. Offline zero-crash fallback when LangSmith is unconfigured.
4. /api/tiles/config layer metadata & caching headers.
5. /api/tiles/{z}/{x}/{y}.pbf bounds checking & MVT response.
"""

import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from starlette.testclient import TestClient
from backend.main import app, get_telemetry_status
from backend.agents.graph import orchestrate_via_graph, orchestrate_stream_via_graph, get_orca_graph


@pytest.fixture
def client():
    """TestClient fixture for FastAPI application."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestLangSmithTelemetryConfig:
    """Test environment variable detection and health payload reporting."""

    def test_telemetry_status_unconfigured(self):
        """When keys are absent, telemetry is disabled with zero error."""
        with patch.dict(os.environ, {"LANGCHAIN_TRACING_V2": "", "LANGCHAIN_API_KEY": ""}, clear=False):
            status = get_telemetry_status()
            assert status["langsmith"]["enabled"] is False
            assert status["langsmith"]["api_key_configured"] is False

    @pytest.mark.parametrize(
        "placeholder_key",
        [
            "your_langsmith_api_key_here",
            "YOUR_LANGSMITH_API_KEY_HERE",
            "Your_Key_123",
        ],
    )
    def test_telemetry_status_placeholder_key(self, placeholder_key):
        """Placeholder keys in .env.example are detected (case-insensitive) and not treated as enabled."""
        with patch.dict(
            os.environ,
            {
                "LANGCHAIN_TRACING_V2": "true",
                "LANGCHAIN_API_KEY": placeholder_key,
            },
            clear=False,
        ):
            status = get_telemetry_status()
            assert status["langsmith"]["enabled"] is False
            assert status["langsmith"]["api_key_configured"] is False

    def test_telemetry_status_authenticated(self):
        """Valid API key enables telemetry status with correct project."""
        with patch.dict(
            os.environ,
            {
                "LANGCHAIN_TRACING_V2": "true",
                "LANGCHAIN_API_KEY": "lsv2_pt_1234567890abcdef",
                "LANGCHAIN_PROJECT": "orca-test-project",
            },
            clear=False,
        ):
            status = get_telemetry_status()
            assert status["langsmith"]["enabled"] is True
            assert status["langsmith"]["tracing_v2"] is True
            assert status["langsmith"]["api_key_configured"] is True
            assert status["langsmith"]["project"] == "orca-test-project"

    def test_health_endpoint_telemetry_payload(self, client):
        """GET /health reports telemetry metadata in response."""
        res = client.get("/health")
        assert res.status_code == 200
        data = res.json()
        assert "telemetry" in data
        assert "langsmith" in data["telemetry"]
        ls = data["telemetry"]["langsmith"]
        assert "enabled" in ls
        assert "tracing_v2" in ls
        assert "api_key_configured" in ls
        assert "project" in ls
        assert "endpoint" in ls


class TestLangGraphRunnableConfigPropagation:
    """Test RunnableConfig metadata, tags, and run_name propagation into LangGraph."""

    @pytest.mark.asyncio
    async def test_orchestrate_via_graph_passes_runnable_config(self):
        """Verify orchestrate_via_graph passes typed RunnableConfig to graph.ainvoke."""
        graph = get_orca_graph()
        assert graph is not None

        captured_config = {}

        async def mock_ainvoke(state, config=None):
            nonlocal captured_config
            captured_config = config or {}
            return {
                "query": state.get("query"),
                "status": "success",
                "needs_clarification": False,
                "ranked_zones": [],
                "best_zone": None,
                "synthesized_reply": "Advisory ready",
                "session_id": state.get("session_id"),
                "reasoning_trace": ["Step 1: Test verified"],
            }

        with patch.object(graph, "ainvoke", side_effect=mock_ainvoke):
            result = await orchestrate_via_graph(
                query="find fishing zones near Kochi",
                language="ml",
                location={"lat": 9.9312, "lon": 76.2673, "port": "Kochi"},
                session_id="test-session-telemetry-01",
            )

            assert result is not None
            assert captured_config.get("run_name") == "orca_agentic_supervisor"
            assert "orca" in captured_config.get("tags", [])
            assert "ml" in captured_config.get("tags", [])
            assert "sih26176" in captured_config.get("tags", [])

            meta = captured_config.get("metadata", {})
            assert meta.get("session_id") == "test-session-telemetry-01"
            assert meta.get("language") == "ml"
            assert meta.get("location", {}).get("has_coords") is True
            assert meta.get("location", {}).get("port") == "Kochi"

    @pytest.mark.asyncio
    async def test_offline_zero_crash_execution(self):
        """Ensure orchestrate_via_graph completes cleanly when keys are absent."""
        with patch.dict(os.environ, {"LANGCHAIN_API_KEY": "", "LANGCHAIN_TRACING_V2": "false"}, clear=False):
            result = await orchestrate_via_graph(
                query="safe fishing zones",
                language="en",
                location={"lat": 9.93, "lon": 76.26},
            )
            assert isinstance(result, dict)
            assert "reply" in result or "status" in result


class TestTileServiceConfiguration:
    """Test /api/tiles/config and /api/tiles/{z}/{x}/{y}.pbf endpoints."""

    def test_tile_config_endpoint_structure_and_caching(self, client):
        """GET /api/tiles/config returns basemap metadata with 1h public cache header."""
        res = client.get("/api/tiles/config")
        assert res.status_code == 200
        assert res.headers.get("cache-control") == "public, max-age=3600"

        data = res.json()
        assert data["status"] == "success"
        assert "default_style" in data
        assert "carto_key_configured" in data
        assert "layers" in data

        layers = data["layers"]
        for expected_id in ["carto_dark", "carto_voyager", "carto_positron", "osm"]:
            assert expected_id in layers
            layer = layers[expected_id]
            assert "url" in layer
            assert "attribution" in layer
            assert "min_zoom" in layer
            assert "max_zoom" in layer
            # Ensure server secret key is never leaked into public URL templates
            assert "your_carto_api_key" not in layer["url"]

    def test_tile_pbf_endpoint_valid_coordinates(self, client):
        """GET /api/tiles/{z}/{x}/{y}.pbf serves protobuf tile with cache header."""
        res = client.get("/api/tiles/0/0/0.pbf?layer=pfz")
        assert res.status_code == 200
        assert res.headers.get("content-type") == "application/x-protobuf"
        assert res.headers.get("cache-control") == "public, max-age=3600"
        assert res.headers.get("x-tile-layer") == "pfz"
        assert res.headers.get("x-tile-coords") == "0/0/0"
        assert res.content == b""

    def test_tile_pbf_endpoint_bounds_validation(self, client):
        """GET /api/tiles/{z}/{x}/{y}.pbf rejects invalid Web Mercator bounds."""
        # Invalid zoom
        assert client.get("/api/tiles/-1/0/0.pbf").status_code == 400
        assert client.get("/api/tiles/25/0/0.pbf").status_code == 400

        # Out-of-bounds coordinate for zoom level 1 (valid range is 0..1)
        assert client.get("/api/tiles/1/2/0.pbf").status_code == 400
        assert client.get("/api/tiles/1/0/2.pbf").status_code == 400

    def test_tile_pbf_header_injection_guard(self, client):
        """Untrusted layer parameters are sanitized to safe whitelist default."""
        res = client.get("/api/tiles/0/0/0.pbf?layer=malicious_header_payload")
        assert res.status_code == 200
        assert res.headers.get("x-tile-layer") == "pfz"
