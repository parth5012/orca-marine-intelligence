"""
Test Suite: Marine Data Package Integration & LangSmith Evaluation Framework

Owner: M-A (Agents & Orchestration) & M-C (Backend API)
Map: #53 (Child Tickets: #54, #55, #56, #57, #58)

Verifies:
1. Sea Checker Tier 3 parquet fallback (coastal_point_features.parquet).
2. Weather Agent Tier 3 cyclone & wind parquet fallback (cyclone_events.parquet).
3. LangSmith benchmark dataset loading, schema adherence, and offline serialization.
4. Custom LangSmith evaluators:
   - MarineGroundednessEvaluator (wave, wind, cyclone metric factuality)
   - GeofenceSafetyEvaluator (MPA and EEZ safety adherence)
   - MetricPreservationEvaluator (upstream numbers preserved without hallucination)
   - RiskCalibrationEvaluator (composite safety tier validation)
5. LangSmith Evaluation Runner execution & zero-crash offline report aggregation.
"""

import os
import sys
import pytest
from unittest.mock import patch, AsyncMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.agents.subagents.sea_checker import get_wave_current
from backend.agents.subagents.weather_agent import get_wind, fetch_imd_cyclones, get_cyclone_alert
from backend.evals.dataset import (
    load_marine_eval_dataset,
    MarineEvalExample,
    export_dataset_to_json,
)
from backend.evals.evaluators import (
    MarineGroundednessEvaluator,
    GeofenceSafetyEvaluator,
    MetricPreservationEvaluator,
    RiskCalibrationEvaluator,
)
from backend.evals.runner import run_marine_evals, EvaluationReport


class TestMarineDataPackageFallbacks:
    """Verifies Tier 3 fallback to parquet when live network APIs fail."""

    @pytest.mark.asyncio
    async def test_sea_checker_parquet_fallback(self):
        """When live Open-Meteo fails, Sea Checker uses coastal_point_features.parquet."""
        with patch("backend.ingest.live_fetchers.fetch_open_meteo_wave_current", side_effect=RuntimeError("Live API Down")):
            # Kochi coordinates
            lat, lon = 9.93, 76.26
            wave, current, source = await get_wave_current(lat, lon, "SEC001_Kochi", 0)
            assert source == "marine_data_package"
            assert wave > 0.0
            assert current >= 0.0

    @pytest.mark.asyncio
    async def test_weather_agent_cyclone_parquet_fallback(self):
        """When live IMD scraper fails, Weather Agent reads cyclone_events.parquet."""
        with patch("backend.ingest.live_fetchers.fetch_imd_cyclones", side_effect=RuntimeError("IMD down")):
            cyclones = await fetch_imd_cyclones()
            assert len(cyclones) > 0
            sample = cyclones[0]
            assert "name" in sample
            assert "lat" in sample
            assert "lon" in sample
            assert "wind_speed_kt" in sample

    @pytest.mark.asyncio
    async def test_weather_agent_wind_parquet_fallback(self):
        """When live weather fetcher fails, Weather Agent reads wind from parquet."""
        with patch("backend.agents.subagents.weather_agent.fetch_imd_wind", side_effect=RuntimeError("Meteo down")):
            lat, lon = 9.93, 76.26
            wind_kt, wind_dir, wind_deg, source = await get_wind(lat, lon, "SEC001_Kochi", 0)
            assert source == "marine_data_package"
            assert wind_kt >= 0.0
            assert wind_dir in ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


class TestLangSmithDataset:
    """Verifies LangSmith marine benchmark dataset curation and formatting."""

    def test_load_dataset_structure(self):
        dataset = load_marine_eval_dataset(limit=10)
        assert len(dataset) > 0
        for ex in dataset:
            assert isinstance(ex, MarineEvalExample)
            assert ex.example_id
            assert ex.landing_center
            assert "latitude" in ex.inputs
            assert "longitude" in ex.inputs
            assert "expected_wave_height_m" in ex.reference
            assert "expected_safety_tier" in ex.reference

    def test_dataset_json_serialization(self, tmp_path):
        out_file = str(tmp_path / "test_dataset.json")
        dataset = load_marine_eval_dataset(limit=5)
        count = export_dataset_to_json(dataset, out_file)
        assert count == 5
        assert os.path.exists(out_file)
        assert os.path.getsize(out_file) > 100


class TestLangSmithCustomEvaluators:
    """Verifies custom LangSmith evaluators for groundedness, safety, and metric preservation."""

    def test_marine_groundedness_evaluator_pass(self):
        evaluator = MarineGroundednessEvaluator(wave_tolerance_m=0.5, wind_tolerance_kt=5.0)
        run_input = {"latitude": 9.93, "longitude": 76.26}
        run_output = {
            "wave_height_m": 1.4,
            "wind_speed_kt": 12.0,
            "cyclone_alert": False,
            "text": "Conditions near Kochi are safe with 1.4m waves and 12.0kt wind.",
        }
        reference = {
            "expected_wave_height_m": 1.45,
            "expected_wind_speed_kt": 11.5,
            "expected_cyclone_alert": False,
        }
        result = evaluator.evaluate(run_input, run_output, reference)
        assert result["score"] == 1.0
        assert result["grounded"] is True

    def test_marine_groundedness_evaluator_hallucination_penalty(self):
        evaluator = MarineGroundednessEvaluator(wave_tolerance_m=0.3, wind_tolerance_kt=3.0)
        run_input = {"latitude": 9.93, "longitude": 76.26}
        run_output = {
            "wave_height_m": 4.5,  # Hallucinated large discrepancy
            "wind_speed_kt": 40.0,
            "cyclone_alert": False,
        }
        reference = {
            "expected_wave_height_m": 1.2,
            "expected_wind_speed_kt": 10.0,
            "expected_cyclone_alert": False,
        }
        result = evaluator.evaluate(run_input, run_output, reference)
        assert result["score"] < 0.5
        assert result["grounded"] is False

    def test_geofence_safety_evaluator(self):
        evaluator = GeofenceSafetyEvaluator()
        # Case 1: MPA violation must yield danger and DO NOT SAIL
        run_output = {
            "safety_tier": "danger",
            "warnings": ["Zone inside Marine Protected Area"],
            "advisory_text": "DO NOT SAIL. Target zone intersects marine sanctuary.",
        }
        reference = {
            "expected_safety_tier": "danger",
            "is_mpa": True,
            "mandate_do_not_sail": True,
        }
        res1 = evaluator.evaluate({}, run_output, reference)
        assert res1["score"] == 1.0
        assert res1["passed"] is True

        # Case 2: Failure to flag danger in MPA
        bad_output = {
            "safety_tier": "safe",
            "advisory_text": "Good day for fishing.",
        }
        res2 = evaluator.evaluate({}, bad_output, reference)
        assert res2["score"] == 0.0
        assert res2["passed"] is False

    def test_metric_preservation_evaluator(self):
        evaluator = MetricPreservationEvaluator()
        facts = {
            "metrics": {
                "wave_height_m": 1.85,
                "wind_speed_kt": 14.2,
                "distance_km": 12.4,
            }
        }
        # Good text preserves numbers
        good_text = "Forecast shows 1.85m wave height, 14.2kt wind, at 12.4km distance."
        res_good = evaluator.evaluate(facts, {"text": good_text})
        assert res_good["score"] == 1.0
        assert res_good["preserved"] is True

        # Bad text alters or drops numbers
        bad_text = "Forecast shows 3.0m wave height and 20kt wind."
        res_bad = evaluator.evaluate(facts, {"text": bad_text})
        assert res_bad["score"] < 1.0
        assert res_bad["preserved"] is False

    def test_risk_calibration_evaluator(self):
        evaluator = RiskCalibrationEvaluator()
        run_output = {"score": 0.82, "tier": "safe"}
        reference = {"expected_tier": "safe", "min_score": 0.70, "max_score": 1.00}
        res = evaluator.evaluate({}, run_output, reference)
        assert res["score"] == 1.0
        assert res["passed"] is True


class TestLangSmithEvaluationRunner:
    """Verifies runner offline execution, scorecard generation, and zero crashes."""

    def test_offline_eval_runner_execution(self):
        dataset = load_marine_eval_dataset(limit=5)

        def mock_pipeline(inputs: dict) -> dict:
            wave = inputs.get("expected_wave", 1.2)
            wind = inputs.get("expected_wind", 10.0)
            is_extreme = wave > 2.5 or wind > 25.0 or "MPA" in inputs.get("query", "") or "Cyclone" in inputs.get("query", "")
            is_caution = (wave >= 1.5 or wind >= 15.0 or "Boundary" in inputs.get("query", "")) and not is_extreme
            tier = "danger" if is_extreme else ("caution" if is_caution else "safe")
            score = 0.40 if tier == "danger" else (0.60 if tier == "caution" else 0.85)
            advisory = "DO NOT SAIL. Target zone intersects restricted area or dangerous storm." if is_extreme else (
                f"Caution: Wave {wave}m, Wind {wind}kt." if is_caution else f"Safe conditions: Wave {wave}m, Wind {wind}kt."
            )

            return {
                "wave_height_m": wave,
                "wind_speed_kt": wind,
                "cyclone_alert": "Cyclone" in inputs.get("query", ""),
                "safety_tier": tier,
                "tier": tier,
                "score": score,
                "advisory_text": advisory,
                "text": advisory,
                "metrics": {
                    "wave_height_m": wave,
                    "wind_speed_kt": wind,
                },
            }

        report = run_marine_evals(
            dataset=dataset,
            target_fn=mock_pipeline,
            use_langsmith=False,  # Offline mode
        )
        assert isinstance(report, EvaluationReport)
        assert report.total_examples == len(dataset)
        assert report.mean_groundedness_score >= 0.8
        assert report.safety_adherence_rate >= 0.8
        assert "scorecard" in report.to_dict()
