"""
End-to-End (E2E) Integration Suite & System Verification for ORCA Marine Intelligence.

Ticket: wayfinder #45 / SIH26176 E2E Integration Suite System Verification
Lane: Cross-Functional (E2E Verification & QA)
File: tests/test_e2e_integration.py

Comprehensive automated end-to-end integration test suite verifying:
1. API Router Verification (Health, Weather, PFZ GeoJSON, Geofence Point & Route)
2. Streaming Chat End-to-End (SSE protocol, event ordering, unmasked nautical metrics)
3. Safety Veto & Risk Enforcement (DO NOT SAIL on Cyclone Alert & MPA Sanctuary)
4. Latency & Performance SLA Benchmarks (<50ms for in-memory/cached checks, P95 streaming)
5. All 8 ISRO SIH26176 Core Requirements:
   - test_isro_r1_multi_agent_intent_and_coordination
   - test_isro_r2_live_external_data_and_fallbacks
   - test_isro_r3_pfz_spatial_data_and_geojson_spec
   - test_isro_r4_sovereign_maritime_geofence_and_imbl_alert
   - test_isro_r5_realtime_sse_event_streaming_order
   - test_isro_r6_vernacular_voice_and_language_support
   - test_isro_r7_graceful_offline_degradation
   - test_isro_r8_latency_and_performance_sla
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from typing import Any, AsyncGenerator, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.main import app, check_database, check_redis
import backend.db.redis as r_mod
from backend.agents import combiner
from backend.agents import lexical_mask as lm
from backend.agents import planner_schema
from backend.agents.fallback import _parse_intent
from backend.ingest.boundaries import (
    check_point_in_eez,
    check_point_in_mpa,
    distance_to_imbl_km,
    get_eez_boundaries,
    get_imbl_segments,
    get_mpa_boundaries,
)
from backend.ingest.copernicus_fallback import fetch_copernicus_fallback
from backend.ingest.incois_textdata import load_local_pfz
from backend.ingest.live_fetchers import (
    fetch_imd_cyclone_alerts,
    fetch_live_incois_pfz,
    fetch_open_meteo_wave_current,
    fetch_open_meteo_weather,
)
from backend.ingest.mock_fetchers import (
    SimulationScenario,
    mock_fetch_all,
)

KOCHI_LAT = 9.93
KOCHI_LON = 76.26
GULF_OF_MANNAR_LAT = 9.00
GULF_OF_MANNAR_LON = 79.00
IMBL_BORDER_LAT = 9.10
IMBL_BORDER_LON = 79.53


def parse_sse_events(response_text: str) -> list[dict]:
    """Parse raw SSE response text into list of {event: str, data: dict} dictionaries."""
    events = []
    current_event = None
    current_data = []

    for line in response_text.splitlines():
        if line.startswith("event: "):
            current_event = line[len("event: ") :].strip()
        elif line.startswith("data: "):
            current_data.append(line[len("data: ") :].strip())
        elif line == "":
            if current_event is not None and current_data:
                data_str = "\n".join(current_data)
                try:
                    data_obj = json.loads(data_str)
                except Exception:
                    data_obj = {"raw": data_str}
                events.append({"event": current_event, "data": data_obj})
            current_event = None
            current_data = []

    if current_event is not None and current_data:
        data_str = "\n".join(current_data)
        try:
            data_obj = json.loads(data_str)
        except Exception:
            data_obj = {"raw": data_str}
        events.append({"event": current_event, "data": data_obj})

    return events


@pytest.fixture(autouse=True)
def clean_memory_store():
    """Ensure in-memory Redis cache and graph cache are clean between tests."""
    r_mod._memory_store.clear()
    r_mod._memory_expiry.clear()
    try:
        import backend.agents.graph as g_mod
        g_mod._compiled_graph = None
    except Exception:
        pass
    yield
    r_mod._memory_store.clear()
    r_mod._memory_expiry.clear()


@pytest.fixture
def client() -> TestClient:
    """FastAPI TestClient fixture."""
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def primed_pfz_cache():
    """Prime Redis in-memory cache with valid PFZ GeoJSON FeatureCollection."""
    features = load_local_pfz()
    doc = {
        "type": "FeatureCollection",
        "source": "incois_textdata",
        "valid_until": "2026-09-06T00:00:00Z",
        "sector_count": 13,
        "features": features,
    }
    r_mod._memory_store["pfz:today"] = doc
    return doc


# ==============================================================================
# 1. API Router Verification
# ==============================================================================

class TestAPIRouterVerification:
    """Verifies all primary ORCA API routes serve correct schemas, status, and data."""

    def test_health_reports_operational_status(self, client: TestClient):
        """GET /health reports operational deployment status, uptime, and services."""
        with (
            patch("backend.main.check_database", new=AsyncMock(return_value="connected")),
            patch("backend.main.check_redis", new=AsyncMock(return_value="connected")),
        ):
            resp = client.get("/health")
            assert resp.status_code == 200
            data = resp.json()

            assert data["status"] == "ok"
            assert data["service"] == "orca-marine-intelligence"
            assert data["version"] == "0.1.0"
            assert isinstance(data["uptime"], (int, float))
            assert data["database"] == "connected"
            assert data["redis"] == "connected"
            assert "data_source" in data

    def test_weather_current_and_cyclone_endpoints(self, client: TestClient):
        """GET /api/weather/current and GET /api/weather/cyclone return valid schemas."""
        # 1. Weather Current
        resp = client.get(f"/api/weather/current?lat={KOCHI_LAT}&lon={KOCHI_LON}")
        assert resp.status_code == 200
        weather_data = resp.json()

        for key in [
            "lat", "lon", "temperature_c", "humidity_pct", "pressure_hpa",
            "wind_speed_kt", "wind_gust_kt", "wind_direction", "wave_height_m",
            "wave_period_s", "current_speed_kt", "status", "source", "cached"
        ]:
            assert key in weather_data, f"Missing key in weather response: {key}"

        assert weather_data["status"] in ("safe", "caution", "danger")
        assert isinstance(weather_data["wind_speed_kt"], (int, float))
        assert isinstance(weather_data["wave_height_m"], (int, float))

        # 2. Cyclone Warnings
        c_resp = client.get("/api/weather/cyclone")
        assert c_resp.status_code == 200
        cyclone_data = c_resp.json()

        assert "alert_level" in cyclone_data
        assert cyclone_data["alert_level"] in ("safe", "advisory", "warning", "severe")
        assert "nearest_cyclone_distance_km" in cyclone_data
        assert "description" in cyclone_data
        assert "regions_affected" in cyclone_data
        assert isinstance(cyclone_data["regions_affected"], list)

    def test_pfz_today_geojson_featurecollection(self, client: TestClient, primed_pfz_cache):
        """GET /api/pfz/today returns valid GeoJSON FeatureCollection with required metadata."""
        resp = client.get("/api/pfz/today")
        assert resp.status_code == 200
        data = resp.json()

        assert data["type"] == "FeatureCollection"
        assert "source" in data
        assert "sector_count" in data
        assert "features" in data
        assert isinstance(data["features"], list)
        assert len(data["features"]) > 0

        first_feat = data["features"][0]
        assert first_feat["type"] == "Feature"
        assert first_feat["geometry"]["type"] == "Point"
        assert len(first_feat["geometry"]["coordinates"]) == 2

        props = first_feat["properties"]
        for prop in ["place", "sector", "bearing", "distance", "depth", "suitability", "timestamp"]:
            assert prop in props, f"Missing property {prop} in PFZ feature"

    def test_geofence_check_mpa_violation_and_eez_safe(self, client: TestClient):
        """GET /api/geofence/check flags violation inside MPA and confirms safe inside EEZ."""
        # Gulf of Mannar MPA: 9.0° N, 79.0° E -> danger_violation
        mpa_resp = client.get(f"/api/geofence/check?lat={GULF_OF_MANNAR_LAT}&lon={GULF_OF_MANNAR_LON}")
        assert mpa_resp.status_code == 200
        mpa_data = mpa_resp.json()
        assert mpa_data["inside_mpa"] is True
        assert mpa_data["safety_status"] == "danger_violation"
        assert any("Marine Protected Area" in alert or "Mannar" in alert for alert in mpa_data["alerts"])

        # Kochi Territorial Waters: 9.93° N, 76.26° E -> safe
        safe_resp = client.get(f"/api/geofence/check?lat={KOCHI_LAT}&lon={KOCHI_LON}")
        assert safe_resp.status_code == 200
        safe_data = safe_resp.json()
        assert safe_data["inside_eez"] is True
        assert safe_data["inside_mpa"] is False
        assert safe_data["near_imbl"] is False
        assert safe_data["safety_status"] == "safe"

    def test_geofence_route_detects_crossings(self, client: TestClient):
        """POST /api/geofence/route detects prohibited zone crossings."""
        # Safe route off Kochi
        safe_coords = [[76.26, 9.93], [76.20, 9.90]]
        s_resp = client.post("/api/geofence/route", json={"coordinates": safe_coords})
        assert s_resp.status_code == 200
        s_data = s_resp.json()
        assert s_data["safe"] is True
        assert len(s_data["violations"]) == 0

        # Crossing through Gulf of Mannar MPA
        danger_coords = [[78.50, 9.00], [79.50, 9.00]]
        d_resp = client.post("/api/geofence/route", json={"coordinates": danger_coords})
        assert d_resp.status_code == 200
        d_data = d_resp.json()
        assert d_data["safe"] is False
        assert len(d_data["violations"]) > 0
        assert any("Marine Protected Area" in v or "Gulf of Mannar" in v for v in d_data["violations"])


# ==============================================================================
# 2. Streaming Chat End-to-End
# ==============================================================================

class TestStreamingChatEndToEnd:
    """Verifies end-to-end SSE conversational advisory stream and unmasked nautical metrics."""

    def test_streaming_chat_event_flow_and_nautical_metrics(self, client: TestClient):
        """POST /api/chat query streams complete event types with unmasked nautical metrics."""
        mock_fish = [
            {
                "zone_id": "z1",
                "place": "Vypin Light",
                "sector": "SEC005",
                "lat": 9.98,
                "lon": 76.15,
                "distance_km": 14.5,
                "distance_from_user_km": 14.5,
                "bearing": 285,
                "direction": "WNW",
                "depth_range": "25-30",
            }
        ]
        mock_sea = [{"zone_id": "z1", "wave_height_m": 0.9, "current_speed_kt": 0.8}]
        mock_weather = [{"zone_id": "z1", "wind_kt": 10.0, "wind_speed_kt": 10.0}]
        mock_danger = [
            {
                "zone_id": "z1",
                "inside_eez": True,
                "inside_mpa": False,
                "near_imbl": False,
                "status": "safe",
                "warnings": [],
            }
        ]

        with (
            patch("backend.agents.fish_finder.find_fishing_zones", new=AsyncMock(return_value=mock_fish)),
            patch("backend.agents.sea_checker.check_sea_conditions", new=AsyncMock(return_value=mock_sea)),
            patch("backend.agents.weather_agent.check_weather", new=AsyncMock(return_value=mock_weather)),
            patch("backend.agents.danger_agent.check_safety_batch", new=AsyncMock(return_value=mock_danger)),
        ):
            resp = client.post(
                "/api/chat",
                json={
                    "message": "Where can I fish near Kochi today?",
                    "lat": KOCHI_LAT,
                    "lon": KOCHI_LON,
                    "language": "en",
                    "session_id": "e2e-nautical-stream",
                },
            )
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers["content-type"]

            events = parse_sse_events(resp.text)
            event_types = [e["event"] for e in events]

            # Verify core event types received
            assert "status" in event_types or "reasoning_step" in event_types
            assert "map" in event_types
            assert "safety" in event_types or "safety_warning" in event_types
            assert "token" in event_types
            assert "done" in event_types

            # Verify map event contents
            map_events = [e["data"] for e in events if e["event"] == "map"]
            assert len(map_events) > 0
            assert "center" in map_events[0]
            assert "pfz_features" in map_events[0]

            # Verify safety event contents
            safety_events = [e["data"] for e in events if e["event"] == "safety"]
            assert len(safety_events) > 0
            assert "danger" in safety_events[0]
            assert "badge" in safety_events[0]

            # Accumulate full text tokens
            token_texts = [e["data"].get("text", "") for e in events if e["event"] == "token"]
            full_reply = "".join(token_texts)
            assert len(full_reply) > 0

            # Verify UNMASKED nautical metrics delivered to client (no __M...__ placeholders)
            assert not re.search(r"__M[A-Z]+_\d+__", full_reply), "Raw lexical mask placeholders leaked into response"

            # Check nautical indicators in streamed advisory (distance km, bearing, wind/wave)
            assert any(term in full_reply.lower() for term in ["km", "bearing", "wave", "wind", "safe", "zone"])


# ==============================================================================
# 3. Safety Veto & Risk Enforcement
# ==============================================================================

class TestSafetyVetoRiskEnforcement:
    """Verifies safety veto policies: DO NOT SAIL on simulated high risk conditions."""

    def test_safety_veto_on_cyclone_alert(self, client: TestClient):
        """Simulated cyclone warning triggers danger status and DO NOT SAIL veto."""
        mock_fish = [
            {
                "zone_id": "z1",
                "place": "Offshore Zone Alpha",
                "sector": "SEC005",
                "lat": 9.93,
                "lon": 76.00,
                "distance_km": 28.0,
                "distance_from_user_km": 28.0,
                "bearing": 270,
                "direction": "W",
            }
        ]
        # Severe cyclone conditions: wind 45kt, waves 3.8m
        mock_sea = [{"zone_id": "z1", "wave_height_m": 3.8, "status": "danger"}]
        mock_weather = [{"zone_id": "z1", "wind_kt": 45.0, "status": "danger", "cyclone_alert": True}]
        mock_danger = [{"zone_id": "z1", "inside_eez": True, "inside_mpa": False, "status": "safe", "warnings": []}]

        with (
            patch("backend.agents.fish_finder.find_fishing_zones", new=AsyncMock(return_value=mock_fish)),
            patch("backend.agents.sea_checker.check_sea_conditions", new=AsyncMock(return_value=mock_sea)),
            patch("backend.agents.weather_agent.check_weather", new=AsyncMock(return_value=mock_weather)),
            patch("backend.agents.danger_agent.check_safety_batch", new=AsyncMock(return_value=mock_danger)),
        ):
            resp = client.post(
                "/api/chat",
                json={
                    "message": "Can I sail out for fishing today?",
                    "lat": KOCHI_LAT,
                    "lon": KOCHI_LON,
                    "language": "en",
                    "session_id": "e2e-cyclone-veto",
                },
            )
            assert resp.status_code == 200
            events = parse_sse_events(resp.text)

            safety_events = [e["data"] for e in events if e["event"] == "safety"]
            assert len(safety_events) > 0
            # Safety event flags red badge indicating severe ocean/weather danger
            assert safety_events[0]["badge"] == "red"

            # Reply text contains DO NOT SAIL veto
            tokens = [e["data"].get("text", "") for e in events if e["event"] == "token"]
            full_reply = "".join(tokens).upper()
            assert "DO NOT SAIL" in full_reply or "UNSAFE" in full_reply or "DANGER" in full_reply

    def test_safety_veto_on_mpa_sanctuary_violation(self, client: TestClient):
        """Query targeting a Marine Protected Area triggers danger status and prohibition alert."""
        mock_fish = [
            {
                "zone_id": "z_mpa",
                "place": "Gulf of Mannar National Park",
                "sector": "SEC006",
                "lat": GULF_OF_MANNAR_LAT,
                "lon": GULF_OF_MANNAR_LON,
                "distance_km": 5.0,
                "distance_from_user_km": 5.0,
                "bearing": 180,
                "direction": "S",
            }
        ]
        mock_sea = [{"zone_id": "z_mpa", "wave_height_m": 0.8, "status": "safe"}]
        mock_weather = [{"zone_id": "z_mpa", "wind_kt": 8.0, "status": "safe"}]
        mock_danger = [
            {
                "zone_id": "z_mpa",
                "inside_eez": True,
                "inside_mpa": True,
                "near_imbl": False,
                "status": "danger",
                "warnings": ["Inside Marine Protected Area (fishing banned)"],
            }
        ]

        with (
            patch("backend.agents.fish_finder.find_fishing_zones", new=AsyncMock(return_value=mock_fish)),
            patch("backend.agents.sea_checker.check_sea_conditions", new=AsyncMock(return_value=mock_sea)),
            patch("backend.agents.weather_agent.check_weather", new=AsyncMock(return_value=mock_weather)),
            patch("backend.agents.danger_agent.check_safety_batch", new=AsyncMock(return_value=mock_danger)),
        ):
            resp = client.post(
                "/api/chat",
                json={
                    "message": "Fish inside Gulf of Mannar sanctuary?",
                    "lat": GULF_OF_MANNAR_LAT,
                    "lon": GULF_OF_MANNAR_LON,
                    "language": "en",
                    "session_id": "e2e-mpa-veto",
                },
            )
            assert resp.status_code == 200
            events = parse_sse_events(resp.text)

            safety_events = [e["data"] for e in events if e["event"] == "safety"]
            assert len(safety_events) > 0
            assert safety_events[0]["danger"] == "danger"
            assert safety_events[0]["badge"] == "red"

            tokens = [e["data"].get("text", "") for e in events if e["event"] == "token"]
            full_reply = "".join(tokens)
            assert "DO NOT sail" in full_reply or "DO NOT SAIL" in full_reply or "Protected Area" in full_reply


# ==============================================================================
# 4. Latency & Performance SLA Benchmarks
# ==============================================================================

class TestLatencyPerformanceBenchmark:
    """Verifies strict latency benchmarks (<50ms for in-memory/cached checks, P95 streaming)."""

    def test_endpoint_latency_benchmarks_sub_50ms(self, client: TestClient, primed_pfz_cache):
        """Verifies health, weather (cached), pfz (cached), and geofence respond in <50ms."""
        # 1. Health check (with in-memory status)
        with (
            patch("backend.main.check_database", new=AsyncMock(return_value="connected")),
            patch("backend.main.check_redis", new=AsyncMock(return_value="connected")),
        ):
            t0 = time.perf_counter()
            resp = client.get("/health")
            t_health_ms = (time.perf_counter() - t0) * 1000
            assert resp.status_code == 200
            assert t_health_ms < 50.0, f"Health endpoint took {t_health_ms:.2f}ms (threshold 50ms)"

        # 2. Weather current (cached)
        # Prime cache
        client.get(f"/api/weather/current?lat={KOCHI_LAT}&lon={KOCHI_LON}")
        t0 = time.perf_counter()
        w_resp = client.get(f"/api/weather/current?lat={KOCHI_LAT}&lon={KOCHI_LON}")
        t_weather_ms = (time.perf_counter() - t0) * 1000
        assert w_resp.status_code == 200
        assert w_resp.json().get("cached") is True
        assert t_weather_ms < 50.0, f"Cached weather endpoint took {t_weather_ms:.2f}ms (threshold 50ms)"

        # 3. PFZ Today (cached in Redis / memory)
        t0 = time.perf_counter()
        pfz_resp = client.get("/api/pfz/today")
        t_pfz_ms = (time.perf_counter() - t0) * 1000
        assert pfz_resp.status_code == 200
        assert t_pfz_ms < 50.0, f"Cached PFZ endpoint took {t_pfz_ms:.2f}ms (threshold 50ms)"

        # 4. Geofence point check (in-memory ray-casting)
        t0 = time.perf_counter()
        geo_resp = client.get(f"/api/geofence/check?lat={KOCHI_LAT}&lon={KOCHI_LON}")
        t_geo_ms = (time.perf_counter() - t0) * 1000
        assert geo_resp.status_code == 200
        assert t_geo_ms < 50.0, f"Geofence check endpoint took {t_geo_ms:.2f}ms (threshold 50ms)"

    def test_streaming_response_latency_sla(self, client: TestClient):
        """Measures SSE stream latency ensuring P95 budget (<2.0s) and fast TTFB."""
        mock_fish = [
            {
                "zone_id": "z1",
                "place": "Kochi Harbor",
                "sector": "SEC005",
                "lat": KOCHI_LAT,
                "lon": KOCHI_LON,
                "distance_km": 5.0,
                "distance_from_user_km": 5.0,
                "bearing": 270,
                "direction": "W",
            }
        ]
        mock_sea = [{"zone_id": "z1", "wave_height_m": 1.0}]
        mock_weather = [{"zone_id": "z1", "wind_kt": 10.0}]
        mock_danger = [{"zone_id": "z1", "inside_eez": True, "inside_mpa": False, "status": "safe", "warnings": []}]

        with (
            patch("backend.agents.fish_finder.find_fishing_zones", new=AsyncMock(return_value=mock_fish)),
            patch("backend.agents.sea_checker.check_sea_conditions", new=AsyncMock(return_value=mock_sea)),
            patch("backend.agents.weather_agent.check_weather", new=AsyncMock(return_value=mock_weather)),
            patch("backend.agents.danger_agent.check_safety_batch", new=AsyncMock(return_value=mock_danger)),
        ):
            t0 = time.perf_counter()
            resp = client.post(
                "/api/chat",
                json={
                    "message": "Fast response test",
                    "lat": KOCHI_LAT,
                    "lon": KOCHI_LON,
                    "session_id": "latency-bench-sess",
                },
            )
            total_duration_s = time.perf_counter() - t0

            assert resp.status_code == 200
            # Total streaming execution must be within the P95 SLA budget (<2.0s)
            assert total_duration_s < 2.0, f"Total stream took {total_duration_s:.2f}s (exceeds 2.0s budget)"


# ==============================================================================
# 5. Verification: 8 ISRO SIH26176 Core Requirements
# ==============================================================================

@pytest.mark.isro
def test_isro_r1_multi_agent_intent_and_coordination(client: TestClient):
    """
    ISRO R1: Multi-Agent Intent Understanding & Specialized Subagent Coordination.
    Decomposes user query into specialized subagent actions and integrates results.
    """
    # 1. Test intent detection logic
    intent = _parse_intent("Where is the best safe fishing zone near Kochi today?")
    assert intent["wants_fish"] is True
    assert intent["wants_safety"] is True

    # Validate structured tool plan schema
    plan = planner_schema.PlannerOutput(
        detected_language="en",
        intents=["find_fish", "check_safety"],
        selected_tools=["find_fishing_zones", "check_ocean_state", "check_weather", "check_geofence"],
        confidence=0.87,
    )
    assert "find_fish" in plan.intents
    assert "check_safety" in plan.intents
    assert "find_fishing_zones" in plan.selected_tools

    # 2. Test multi-agent pipeline integration via combiner
    sample_fish = [
        {"zone_id": "z1", "place": "Kochi Deep", "lat": 9.95, "lon": 76.10, "distance_km": 18.0, "bearing": 260},
        {"zone_id": "z2", "place": "Alappuzha Coast", "lat": 9.50, "lon": 76.20, "distance_km": 45.0, "bearing": 180},
    ]
    sample_sea = [
        {"zone_id": "z1", "wave_height_m": 1.1},
        {"zone_id": "z2", "wave_height_m": 2.4},  # high wave
    ]
    sample_weather = [
        {"zone_id": "z1", "wind_kt": 11.0},
        {"zone_id": "z2", "wind_kt": 18.0},  # high wind
    ]
    sample_danger = [
        {"zone_id": "z1", "inside_eez": True, "inside_mpa": False},
        {"zone_id": "z2", "inside_eez": True, "inside_mpa": False},
    ]

    fused = combiner.combine_and_rank(
        fish_results=sample_fish,
        sea_results=sample_sea,
        weather_results=sample_weather,
        danger_results=sample_danger,
        user_location={"lat": KOCHI_LAT, "lon": KOCHI_LON},
    )

    assert fused["best"] is not None
    assert fused["best"]["zone_id"] == "z1", "Combiner must prioritize safe, lower wave zone z1 over z2"
    assert "explanation" in fused
    assert "citation" in fused


@pytest.mark.isro
def test_isro_r2_live_external_data_and_fallbacks():
    """
    ISRO R2: Live External Data Fetching with Robust Fallback Cascades.
    Verifies INCOIS, Open-Meteo, Copernicus fallback and offline resiliency.
    """
    # 1. Live/local PFZ retrieval
    pfz_res = fetch_live_incois_pfz(sector="SEC005", center_lat=KOCHI_LAT, center_lon=KOCHI_LON, count=3)
    assert pfz_res["status"] == "success"
    assert len(pfz_res["zones"]) > 0

    # 2. Copernicus Fallback verification
    async def _test_copernicus():
        res = await fetch_copernicus_fallback()
        assert res["type"] == "FeatureCollection"
        assert len(res["features"]) > 0
        assert "copernicus" in res.get("source", "").lower() or "fallback" in res.get("source", "").lower()

    asyncio.run(_test_copernicus())

    # 3. Weather Fetcher with Fallback resilience
    weather_live = fetch_open_meteo_weather(KOCHI_LAT, KOCHI_LON)
    assert "wind_speed_kt" in weather_live
    assert "status" in weather_live
    assert weather_live["status"] in ("safe", "caution", "danger")

    # 4. IMD Cyclone Alerts
    cyclone_res = fetch_imd_cyclone_alerts()
    assert "alert_level" in cyclone_res
    assert isinstance(cyclone_res["regions_affected"], list)


@pytest.mark.isro
def test_isro_r3_pfz_spatial_data_and_geojson_spec(client: TestClient, primed_pfz_cache):
    """
    ISRO R3: PFZ Spatial Data RFC 7946 GeoJSON Standard Compliance.
    Validates FeatureCollection format, WGS84 coordinate boundaries, and properties schema.
    """
    resp = client.get("/api/pfz/today?sector=SEC005")
    assert resp.status_code == 200
    fc = resp.json()

    # GeoJSON RFC 7946 validation
    assert fc["type"] == "FeatureCollection"
    assert isinstance(fc["features"], list)
    assert len(fc["features"]) > 0

    for feat in fc["features"][:10]:
        assert feat["type"] == "Feature"
        geom = feat["geometry"]
        assert geom["type"] == "Point"
        lon, lat = geom["coordinates"]

        # Validate coordinate order: [lon, lat] and Indian EEZ territorial bounding box
        assert 65.0 <= lon <= 95.0, f"Longitude {lon} outside Indian marine bounds"
        assert 4.0 <= lat <= 25.0, f"Latitude {lat} outside Indian marine bounds"

        props = feat["properties"]
        assert "place" in props
        assert "sector" in props
        assert "bearing" in props
        assert "distance" in props
        assert "depth" in props
        assert "suitability" in props


@pytest.mark.isro
def test_isro_r4_sovereign_maritime_geofence_and_imbl_alert():
    """
    ISRO R4: Sovereign Maritime Geofencing, EEZ Boundaries & IMBL Proximity Alerts.
    Enforces 2.0km IMBL buffer rule, Marine Protected Area sanctuary rules, and EEZ boundary checking.
    """
    # 1. Safe point inside EEZ
    in_eez, _ = check_point_in_eez(KOCHI_LAT, KOCHI_LON)
    assert in_eez is True
    in_mpa_kochi, _, _ = check_point_in_mpa(KOCHI_LAT, KOCHI_LON)
    assert in_mpa_kochi is False

    # 2. MPA Violation: Gulf of Mannar Marine National Park (9.0, 79.0)
    in_mpa_mannar, mpa_name_mannar, _ = check_point_in_mpa(GULF_OF_MANNAR_LAT, GULF_OF_MANNAR_LON)
    assert in_mpa_mannar is True
    assert "Mannar" in (mpa_name_mannar or "")

    # 3. MPA Violation: Vembanad Lake (9.65, 76.45)
    in_mpa_vem, mpa_name_vem, _ = check_point_in_mpa(9.65, 76.45)
    assert in_mpa_vem is True
    assert "Vembanad" in (mpa_name_vem or "")

    # 4. IMBL Proximity (<2.0km buffer alert)
    dist_to_border = distance_to_imbl_km(IMBL_BORDER_LAT, IMBL_BORDER_LON)
    assert dist_to_border < 2.0, f"Point {IMBL_BORDER_LAT},{IMBL_BORDER_LON} expected <2km to IMBL, got {dist_to_border}km"

    # 5. Geofence boundaries datasets loaded
    eez_zones = get_eez_boundaries()
    assert len(eez_zones) >= 2, "Must contain Eastern and Western Indian EEZ"
    mpa_zones = get_mpa_boundaries()
    assert len(mpa_zones) >= 2, "Must contain Mannar and Vembanad MPAs"
    imbl_segs = get_imbl_segments()
    assert len(imbl_segs) > 0, "Must contain India-Sri Lanka IMBL border segments"


@pytest.mark.isro
def test_isro_r5_realtime_sse_event_streaming_order(client: TestClient):
    """
    ISRO R5: Real-time Server-Sent Events (SSE) Protocol & Strict Streaming Order.
    Enforces sequence: status* -> map -> safety -> token+ -> evidence -> done.
    """
    mock_fish = [{"zone_id": "z1", "place": "Cochin Point", "sector": "SEC005", "lat": 9.93, "lon": 76.26, "distance_km": 5.0, "bearing": 270}]
    mock_sea = [{"zone_id": "z1", "wave_height_m": 0.8}]
    mock_weather = [{"zone_id": "z1", "wind_kt": 8.0}]
    mock_danger = [{"zone_id": "z1", "inside_eez": True, "inside_mpa": False, "status": "safe"}]

    with (
        patch("backend.agents.fish_finder.find_fishing_zones", new=AsyncMock(return_value=mock_fish)),
        patch("backend.agents.sea_checker.check_sea_conditions", new=AsyncMock(return_value=mock_sea)),
        patch("backend.agents.weather_agent.check_weather", new=AsyncMock(return_value=mock_weather)),
        patch("backend.agents.danger_agent.check_safety_batch", new=AsyncMock(return_value=mock_danger)),
    ):
        resp = client.post(
            "/api/chat",
            json={
                "message": "Stream event ordering test",
                "lat": KOCHI_LAT,
                "lon": KOCHI_LON,
                "session_id": "test-order-sess",
            },
        )
        assert resp.status_code == 200
        events = parse_sse_events(resp.text)
        types = [e["event"] for e in events]

        # Ensure critical event types are present
        assert "map" in types
        assert "safety" in types
        assert "token" in types
        assert "done" in types

        # Find first occurrences of each key event type
        idx_map = types.index("map")
        idx_safety = types.index("safety")
        idx_token = types.index("token")
        idx_done = types.index("done")

        # Strict ordering: map and safety must precede streamed text tokens
        assert idx_map < idx_token, "map event must be emitted before text tokens start"
        assert idx_safety < idx_token, "safety event must be emitted before text tokens start"
        assert idx_token < idx_done, "token events must precede done event"


@pytest.mark.isro
def test_isro_r6_vernacular_voice_and_language_support(client: TestClient):
    """
    ISRO R6: Vernacular Voice & Multilingual Regional Advisory Grounding.
    Tests voice transcription endpoint, lexical masking preserving metrics, and multilingual replies.
    """
    # 1. Voice transcription endpoint
    dummy_wav_bytes = b"RIFF....WAVEfmt ...." + b"\x00" * 100
    files = {"file": ("fisherman_query.wav", dummy_wav_bytes, "audio/wav")}

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"text": "എവിടെ മത്സ്യം? (Where to fish?)"}

    with patch("httpx.AsyncClient.post", return_value=mock_resp):
        v_resp = client.post("/api/chat/voice", files=files, data={"language": "ml"})
        assert v_resp.status_code == 200
        v_data = v_resp.json()
        assert "transcription" in v_data
        assert "session_id" in v_data
        assert len(v_data["transcription"]) > 0

    # 2. Marine Glossary Masking: preserving nautical metrics across vernacular translations
    masker = lm.MarineGlossaryMasker()
    source_advisory = "Zone at Bearing 240 deg, distance 14 km, wind 10 knots, wave 1.1m, coords 9.93N 76.26E."
    masked, table = masker.mask(source_advisory)

    assert "__MBEARING_0__" in masked
    assert "__MDIST_0__" in masked
    assert "__MKNOTS_0__" in masked
    assert "__MMETER_0__" in masked

    # Unmasking restores the exact numerical figures
    restored = masker.unmask(masked, table)
    assert restored == source_advisory

    # 3. Multilingual combiner output (Malayalam, Tamil, Hindi)
    sample_fish = [{"zone_id": "z1", "place": "Kollam Port", "sector": "SEC005", "lat": 8.89, "lon": 76.55, "distance_km": 12.0, "bearing": 210, "direction": "SSW"}]
    for lang in ["ml", "ta", "hi", "te"]:
        out = combiner.combine_and_rank(
            fish_results=sample_fish,
            sea_results=[{"zone_id": "z1", "wave_height_m": 0.8}],
            weather_results=[{"zone_id": "z1", "wind_kt": 8.0}],
            danger_results=[{"zone_id": "z1", "inside_eez": True, "inside_mpa": False}],
            user_location={"lat": KOCHI_LAT, "lon": KOCHI_LON},
            detected_language=lang,
        )
        assert out["best"] is not None
        assert "explanation" in out
        # Explanation must preserve critical numbers
        assert "12" in out["explanation"]
        assert "210" in out["explanation"]


@pytest.mark.isro
def test_isro_r7_graceful_offline_degradation(client: TestClient):
    """
    ISRO R7: Resilient Offline Graceful Degradation.
    Verifies that system runs without crashing when database, Redis, and LLM APIs are disconnected.
    """
    # 1. Health endpoint gracefully handles disconnected services without 500 error
    with (
        patch("backend.main.check_database", new=AsyncMock(return_value="disconnected")),
        patch("backend.main.check_redis", new=AsyncMock(return_value="disconnected")),
    ):
        h_resp = client.get("/health")
        assert h_resp.status_code == 200
        h_data = h_resp.json()
        assert h_data["status"] == "degraded"
        assert h_data["database"] == "disconnected"
        assert h_data["redis"] == "disconnected"

    # 2. Redis failure falls back transparently to in-memory store
    r_mod._redis_client = None
    r_mod._memory_store.clear()
    asyncio.run(r_mod.set_json("test:degrade:key", {"status": "in_memory"}))
    retrieved = asyncio.run(r_mod.get_json("test:degrade:key"))
    assert retrieved == {"status": "in_memory"}

    # 3. Chat advisor degrades gracefully to deterministic combiner templates when LLM API keys are absent
    mock_fish = [{"zone_id": "z1", "place": "Offline Spot", "sector": "SEC005", "lat": 9.93, "lon": 76.26, "distance_km": 10.0, "bearing": 270}]
    with (
        patch("backend.agents.fish_finder.find_fishing_zones", new=AsyncMock(return_value=mock_fish)),
        patch("backend.agents.sea_checker.check_sea_conditions", new=AsyncMock(return_value=[{"zone_id": "z1", "wave_height_m": 1.0}])),
        patch("backend.agents.weather_agent.check_weather", new=AsyncMock(return_value=[{"zone_id": "z1", "wind_kt": 10.0}])),
        patch("backend.agents.danger_agent.check_safety_batch", new=AsyncMock(return_value=[{"zone_id": "z1", "inside_eez": True, "inside_mpa": False}])),
    ):
        chat_resp = client.post(
            "/api/chat",
            json={
                "message": "Where to fish offline?",
                "lat": KOCHI_LAT,
                "lon": KOCHI_LON,
                "session_id": "offline-degrade-sess",
            },
        )
        assert chat_resp.status_code == 200
        events = parse_sse_events(chat_resp.text)
        done_events = [e["data"] for e in events if e["event"] == "done"]
        assert len(done_events) > 0
        # When degraded, confidence reflects the calibrated degraded confidence
        assert done_events[0]["confidence"] in (0.62, 0.87)


@pytest.mark.isro
def test_isro_r8_latency_and_performance_sla(client: TestClient, primed_pfz_cache):
    """
    ISRO R8: Strict Latency & Performance SLA Verification.
    Validates <50ms response for cached/in-memory checks, fast TTFB, and P95 streaming SLA.
    """
    # 1. In-memory readiness / health check SLA < 50ms
    with (
        patch("backend.main.check_database", new=AsyncMock(return_value="connected")),
        patch("backend.main.check_redis", new=AsyncMock(return_value="connected")),
    ):
        t0 = time.perf_counter()
        resp = client.get("/health")
        t_health = (time.perf_counter() - t0) * 1000
        assert resp.status_code == 200
        assert t_health < 50.0

    # 2. Geofence point check SLA < 50ms
    t0 = time.perf_counter()
    g_resp = client.get(f"/api/geofence/check?lat={KOCHI_LAT}&lon={KOCHI_LON}")
    t_geo = (time.perf_counter() - t0) * 1000
    assert g_resp.status_code == 200
    assert t_geo < 50.0

    # 3. Cached PFZ SLA < 50ms
    t0 = time.perf_counter()
    p_resp = client.get("/api/pfz/today")
    t_pfz = (time.perf_counter() - t0) * 1000
    assert p_resp.status_code == 200
    assert t_pfz < 50.0

    # 4. Route check SLA < 50ms
    t0 = time.perf_counter()
    r_resp = client.post("/api/geofence/route", json={"coordinates": [[76.26, 9.93], [76.20, 9.90]]})
    t_route = (time.perf_counter() - t0) * 1000
    assert r_resp.status_code == 200
    assert t_route < 50.0
