"""
Tests for T3 (#118): Wire SST and chlorophyll data to agent pipeline for hotspot queries.
"""

from unittest.mock import patch
import pytest

from backend.agents.subagents import fish_finder
from backend.agents.planner_schema import PlannerOutput
from backend.agents.fallback import _parse_intent
from backend.agents.combiner import combine_and_rank


def test_enrich_with_satellite_data_present():
    """Zone coords near Kochi should attach sst_c and chlorophyll_mg_m3."""
    zones = [{"zone_id": "z1", "place": "Kochi Offshore", "lat": 9.93, "lon": 76.26}]
    enriched = fish_finder._enrich_with_satellite_data(zones, lat=9.93, lon=76.26)
    assert len(enriched) == 1
    assert "sst_c" in enriched[0]
    assert "chlorophyll_mg_m3" in enriched[0]
    assert enriched[0]["sst_c"] is not None
    assert enriched[0]["chlorophyll_mg_m3"] is not None
    assert isinstance(enriched[0]["sst_c"], (float, int))
    assert isinstance(enriched[0]["chlorophyll_mg_m3"], (float, int))


def test_enrich_with_missing_parquet():
    """Missing parquet file must degrade gracefully without crashing."""
    zones = [{"zone_id": "z1", "place": "Kochi", "lat": 9.93, "lon": 76.26}]
    with patch("backend.agents.subagents.fish_finder._find_parquet_features_file", return_value=None):
        if hasattr(fish_finder, "_clear_satellite_cache"):
            fish_finder._clear_satellite_cache()
        enriched = fish_finder._enrich_with_satellite_data(zones, lat=9.93, lon=76.26)
        assert len(enriched) == 1
        assert enriched[0]["zone_id"] == "z1"
    if hasattr(fish_finder, "_clear_satellite_cache"):
        fish_finder._clear_satellite_cache()


def test_enrich_empty_zones():
    """Empty zones list returns empty list."""
    enriched = fish_finder._enrich_with_satellite_data([], lat=9.93, lon=76.26)
    assert enriched == []


def test_planner_schema_satellite_flags():
    """PlannerOutput must support wants_sst and wants_chlorophyll booleans."""
    plan = PlannerOutput(
        detected_language="en",
        intents=["find_fish", "wants_sst", "wants_chlorophyll"],
        wants_sst=True,
        wants_chlorophyll=True,
        confidence=0.9,
    )
    assert plan.wants_sst is True
    assert plan.wants_chlorophyll is True


def test_fallback_intent_detection_sst_hotspots():
    """_parse_intent should detect SST and chlorophyll keywords."""
    res_sst = _parse_intent("Show me SST hotspots near Kochi")
    assert res_sst.get("wants_sst") is True
    assert res_sst.get("wants_fish") is True

    res_chlo = _parse_intent("Find chlorophyll and phytoplankton productivity near Munambam")
    assert res_chlo.get("wants_chlorophyll") is True
    assert res_chlo.get("wants_fish") is True


def test_combiner_advisory_includes_sst_and_chlorophyll():
    """When SST and chlorophyll data are present on best zone, explanation includes advisory."""
    fish_results = [
        {
            "zone_id": "z1",
            "place": "Pallithottam",
            "sector": "KERALA",
            "lat": 9.0,
            "lon": 76.5,
            "distance_km": 12.0,
            "sst_c": 28.5,
            "chlorophyll_mg_m3": 0.6,
        }
    ]
    sea_results = [{"wave_height_m": 1.0}]
    weather_results = [{"wind_speed_kt": 10.0}]
    danger_results = [{"inside_eez": True, "inside_mpa": False}]

    res = combine_and_rank(
        fish_results=fish_results,
        sea_results=sea_results,
        weather_results=weather_results,
        danger_results=danger_results,
        user_location={"lat": 9.0, "lon": 76.5},
    )

    best = res.get("best")
    assert best is not None
    assert best.get("sst_c") == 28.5
    assert best.get("chlorophyll_mg_m3") == 0.6

    explanation = res.get("explanation", "")
    assert "SST: 28.5C" in explanation
    assert "Chlorophyll: 0.6 mg/m3" in explanation
    assert "productive waters." in explanation


@pytest.mark.asyncio
async def test_graph_sst_query_e2e():
    """End-to-end query for SST hotspots through graph returns advisory with SST values."""
    from backend.agents.graph import orchestrate_via_graph

    try:
        res = await orchestrate_via_graph(
            query="Where are the SST hotspots near Kochi today?",
            location={"lat": 9.93, "lon": 76.26},
        )
        assert res is not None
        reply = res.get("reply", "") or res.get("explanation", "")
        assert "SST:" in reply
        assert "C" in reply
    finally:
        fish_finder.set_db_degraded(False)
