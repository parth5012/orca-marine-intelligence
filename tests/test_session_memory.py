"""
Tests for Multi-Turn Session Memory with Structured Context (T10 #126)
"""

import asyncio
import pytest
from unittest.mock import patch, AsyncMock

from backend.db import redis as redis_mod
from backend.agents.planner_service import plan_query
from backend.agents.planner_schema import PlannerOutput, TargetLocation


@pytest.mark.asyncio
async def test_redis_save_session_persists_structured_context():
    """Verify save_session populates last_lat, last_lon, last_zone_id, last_zone_name."""
    sid = "test-session-126-struct"
    data = {
        "lat": 9.93,
        "lon": 76.26,
        "place": "Kochi Offshore",
        "zone_id": "SEC005_Kochi_001",
        "detected_language": "en",
        "turn_history": [{"role": "user", "content": "Fish near Kochi"}],
    }

    await redis_mod.save_session(sid, data)
    retrieved = await redis_mod.get_session(sid)

    assert retrieved is not None
    assert retrieved["last_lat"] == pytest.approx(9.93)
    assert retrieved["last_lon"] == pytest.approx(76.26)
    assert retrieved["last_zone_name"] == "Kochi Offshore"
    assert retrieved["last_zone_id"] == "SEC005_Kochi_001"
    assert retrieved["lat"] == pytest.approx(9.93)
    assert retrieved["lon"] == pytest.approx(76.26)


@pytest.mark.asyncio
async def test_planner_service_reuses_session_location():
    """Query 2 reuses last_lat / last_lon from Redis session when query has no explicit location."""
    sid = "test-session-126-reuse"
    session_data = {
        "lat": 9.93,
        "lon": 76.26,
        "last_lat": 9.93,
        "last_lon": 76.26,
        "last_zone_name": "Kochi",
        "last_zone_id": "SEC005_Kochi_001",
    }
    await redis_mod.save_session(sid, session_data)

    # Mock generate_fn returning plan without explicit coordinates
    mock_raw_json = (
        '{"detected_language": "en", "intents": ["check_weather"], '
        '"target_location": {"port_name": null, "lat": null, "lon": null, "confidence": 0.5}, '
        '"selected_tools": ["check_weather", "check_ocean_state"], '
        '"reasoning_trace": ["SELECT check_weather", "SELECT check_ocean_state"], '
        '"confidence": 0.85}'
    )

    async def mock_generate(prompt):
        return mock_raw_json

    envelope = await plan_query(
        query="Is it safe tomorrow?",
        language="en",
        location=None,  # No explicit location provided in Query 2
        session_id=sid,
        generate_fn=mock_generate,
    )

    assert envelope["status"] == "success"
    plan = envelope["plan"]
    assert plan.target_location.lat == pytest.approx(9.93)
    assert plan.target_location.lon == pytest.approx(76.26)
