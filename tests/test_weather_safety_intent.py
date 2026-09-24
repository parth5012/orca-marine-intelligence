"""
Tests for pure weather / cyclone / safety queries without fish intent.

Verifies:
1. combiner.combine_and_rank produces a marine weather advisory (NOT fishing zones)
   when intent['wants_fish'] is False.
2. Cyclone alerts are explicitly highlighted in the advisory text.
3. pfz_features on map remain empty for weather/safety-only queries.
4. Deterministic intent parsing correctly tags weather/cyclone as wants_fish=False.
5. Deterministic fallback in graph does not select find_fishing_zones when wants_fish=False.
"""

import pytest
from unittest.mock import AsyncMock, patch

from backend.agents.combiner import combine_and_rank
from backend.agents.fallback import _parse_intent


def test_intent_parsing_pure_weather_cyclone():
    """Unambiguous weather/cyclone queries must have wants_fish=False, wants_safety=True."""
    # Pure weather
    res_weather = _parse_intent("What is the weather in Kochi today?")
    assert res_weather["wants_safety"] is True
    assert res_weather["wants_fish"] is False

    # Cyclone query
    res_cyclone = _parse_intent("Is there any cyclone warning near Munambam?")
    assert res_cyclone["wants_safety"] is True
    assert res_cyclone["wants_fish"] is False

    # Safe to sail
    res_safe = _parse_intent("Is it safe to sail from Beypore?")
    assert res_safe["wants_safety"] is True
    assert res_safe["wants_fish"] is False

    # Fish query should still have wants_fish=True
    res_fish = _parse_intent("Where can I find fish near Kochi?")
    assert res_fish["wants_fish"] is True


def test_combiner_weather_only_advisory_no_fishing_zones_mentioned():
    """When intent['wants_fish'] is False, explanation must not mention fishing zones or catch."""
    sea = [{"zone_id": "loc", "place": "Kochi", "wave_height_m": 1.2, "status": "safe"}]
    weather = [{"zone_id": "loc", "place": "Kochi", "wind_kt": 12.0, "status": "safe"}]
    danger = [{"zone_id": "loc", "inside_eez": True, "inside_mpa": False}]
    user_loc = {"lat": 9.93, "lon": 76.26}

    # Pass synthetic fish anchor as fish_results (what graph.py currently does)
    fish = [{"id": "current_loc", "name": "Current Location", "lat": 9.93, "lon": 76.26, "source": "synthetic_safety_anchor"}]

    res = combine_and_rank(
        fish_results=fish,
        sea_results=sea,
        weather_results=weather,
        danger_results=danger,
        user_location=user_loc,
        detected_language="en",
        intent={"wants_fish": False, "wants_safety": True},
    )

    explanation = res["explanation"].lower()
    # Must NOT mention fishing zone recommendations or catch
    assert "fishing zone" not in explanation
    assert "best fishing zone" not in explanation
    assert "expected catch" not in explanation
    assert "no fishing zones found" not in explanation

    # Must contain weather/sea information
    assert "wave" in explanation or "wind" in explanation
    assert res["ranked_zones"] == []  # No fake fishing zones displayed


def test_combiner_cyclone_alert_in_weather_advisory():
    """When a cyclone alert is present, the advisory must prominently warn of the cyclone."""
    sea = [{"zone_id": "loc", "place": "Kochi", "wave_height_m": 2.5, "status": "danger"}]
    weather = [{
        "zone_id": "loc",
        "place": "Kochi",
        "wind_kt": 35.0,
        "status": "danger",
        "cyclone_alert": True,
        "cyclone_name": "Cyclone Ockhi",
        "nearest_cyclone_km": 150.0,
    }]
    danger = [{"zone_id": "loc", "inside_eez": True, "inside_mpa": False}]
    user_loc = {"lat": 9.93, "lon": 76.26}

    res = combine_and_rank(
        fish_results=[],
        sea_results=sea,
        weather_results=weather,
        danger_results=danger,
        user_location=user_loc,
        detected_language="en",
        intent={"wants_fish": False, "wants_safety": True},
    )

    explanation = res["explanation"]
    assert "cyclone" in explanation.lower()
    assert "do not sail" in explanation.lower() or "unsafe" in explanation.lower() or "danger" in explanation.lower()


@pytest.mark.asyncio
async def test_graph_weather_query_skips_pfz_and_renders_weather_reply():
    """Full graph execution for weather query must not recommend fishing zones."""
    from backend.agents import graph as g

    # Patch redis & live fetchers
    with patch("backend.db.redis.get_session", new=AsyncMock(return_value=None)), \
         patch("backend.db.redis.save_session", new=AsyncMock(return_value=None)), \
         patch("backend.agents.sea_checker.check_sea_conditions", new=AsyncMock(return_value=[{
             "zone_id": "current_location", "place": "Kochi", "wave_height_m": 1.1, "status": "safe", "source": "mock"
         }])), \
         patch("backend.agents.weather_agent.check_weather", new=AsyncMock(return_value=[{
             "zone_id": "current_location", "place": "Kochi", "wind_kt": 11.0, "status": "safe", "source": "mock"
         }])), \
         patch("backend.agents.danger_agent.check_safety_batch", new=AsyncMock(return_value=[{
             "zone_id": "current_location", "inside_eez": True, "inside_mpa": False, "status": "safe"
         }])):

        res = await g.orchestrate_via_graph(
            query="What is the weather and sea condition in Kochi?",
            language="en",
            location={"lat": 9.93, "lon": 76.26},
            session_id="test-weather-pure",
        )

        assert "find_fishing_zones" not in (res.get("selected_tools") or [])
        assert res.get("map", {}).get("pfz_features") == []
        reply = (res.get("reply") or res.get("explanation") or "").lower()
        assert "best fishing zone" not in reply
        assert "no fishing zones found" not in reply
