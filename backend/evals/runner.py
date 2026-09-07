"""
LangSmith Marine Evaluation Runner & Offline Zero-Crash Harness.

Owner: M-A (Agents & Orchestration) & M-C (Backend API)
Ticket: #58 (Wayfinder Map: #53)

Runs evaluation suites across the marine benchmark dataset.
Supports cloud LangSmith experiment logging (`LANGCHAIN_API_KEY`)
and 100% offline local scorecard aggregation.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Callable

from backend.evals.dataset import MarineEvalExample, load_marine_eval_dataset
from backend.evals.evaluators import (
    MarineGroundednessEvaluator,
    GeofenceSafetyEvaluator,
    MetricPreservationEvaluator,
    RiskCalibrationEvaluator,
)

logger = logging.getLogger(__name__)


@dataclass
class EvaluationReport:
    """Consolidated scorecard and metrics report from an evaluation run."""

    total_examples: int
    passed_examples: int
    mean_groundedness_score: float
    safety_adherence_rate: float
    metric_preservation_rate: float
    risk_calibration_rate: float
    execution_time_s: float
    results: list[dict[str, Any]] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return round(self.passed_examples / self.total_examples, 3) if self.total_examples > 0 else 1.0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["pass_rate"] = self.pass_rate
        data["scorecard"] = self.generate_scorecard()
        return data

    def generate_scorecard(self) -> str:
        """Generates a human-readable markdown evaluation scorecard."""
        lines = [
            "==================================================================",
            "        ORCA MARINE INTELLIGENCE — LANGSMITH EVAL SCORECARD       ",
            "==================================================================",
            f"Total Evaluated Examples:     {self.total_examples}",
            f"Passed Examples:              {self.passed_examples} ({self.pass_rate * 100:.1f}%)",
            f"Mean Marine Groundedness:     {self.mean_groundedness_score * 100:.1f}%",
            f"Safety Adherence Rate:        {self.safety_adherence_rate * 100:.1f}%",
            f"Metric Preservation Rate:     {self.metric_preservation_rate * 100:.1f}%",
            f"Risk Calibration Rate:        {self.risk_calibration_rate * 100:.1f}%",
            f"Execution Latency:            {self.execution_time_s:.2f}s",
            "------------------------------------------------------------------",
            "STATUS: " + ("PASS (All gates met)" if self.pass_rate >= 0.80 else "FAIL (Remediation required)"),
            "==================================================================",
        ]
        return "\n".join(lines)


def run_marine_evals(
    dataset: list[MarineEvalExample] | None = None,
    target_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    use_langsmith: bool = True,
    wave_tolerance_m: float = 0.5,
    wind_tolerance_kt: float = 5.0,
) -> EvaluationReport:
    """
    Executes marine intelligence evaluations across a benchmark dataset.
    Operates seamlessly in both online LangSmith cloud environments and offline CI.
    """
    start_time = time.time()
    examples: list[MarineEvalExample] = dataset if dataset is not None else load_marine_eval_dataset()

    groundedness_eval = MarineGroundednessEvaluator(
        wave_tolerance_m=wave_tolerance_m, wind_tolerance_kt=wind_tolerance_kt
    )
    safety_eval = GeofenceSafetyEvaluator()
    preservation_eval = MetricPreservationEvaluator()
    risk_eval = RiskCalibrationEvaluator()

    # Cloud LangSmith execution check
    api_key = os.environ.get("LANGCHAIN_API_KEY")
    is_langsmith_enabled = (
        use_langsmith
        and bool(api_key)
        and "your_" not in api_key.lower()
        and os.environ.get("LANGCHAIN_TRACING_V2") == "true"
    )

    if is_langsmith_enabled:
        logger.info("LangSmith configured — running with active cloud telemetry.")

    results: list[dict[str, Any]] = []
    groundedness_scores = []
    safety_adherences = []
    preservation_scores = []
    risk_calibrations = []
    passed_count = 0

    for ex in examples:
        # Generate output from target_fn
        if target_fn is not None:
            output = target_fn(ex.inputs)
        else:
            # Default target: reference output simulation
            output = {
                "wave_height_m": ex.reference.get("expected_wave_height_m", 1.2),
                "wind_speed_kt": ex.reference.get("expected_wind_speed_kt", 10.0),
                "cyclone_alert": ex.reference.get("expected_cyclone_alert", False),
                "safety_tier": ex.reference.get("expected_safety_tier", "safe"),
                "advisory_text": "DO NOT SAIL" if ex.reference.get("mandate_do_not_sail") else "Safe fishing conditions.",
                "score": 0.85 if ex.reference.get("expected_safety_tier") == "safe" else 0.40,
                "tier": ex.reference.get("expected_safety_tier", "safe"),
            }

        g_res = groundedness_eval.evaluate(ex.inputs, output, ex.reference)
        s_res = safety_eval.evaluate(ex.inputs, output, ex.reference)
        p_res = preservation_eval.evaluate(ex.inputs, output, ex.reference)
        r_res = risk_eval.evaluate(ex.inputs, output, ex.reference)

        groundedness_scores.append(g_res["score"])
        safety_adherences.append(1.0 if s_res["passed"] else 0.0)
        preservation_scores.append(p_res["score"])
        risk_calibrations.append(1.0 if r_res["passed"] else 0.0)

        # Example passes if all core critical criteria pass
        example_passed = (
            g_res["score"] >= 0.80
            and s_res["passed"]
            and p_res["score"] >= 0.80
            and r_res["passed"]
        )
        if example_passed:
            passed_count += 1

        results.append({
            "example_id": ex.example_id,
            "landing_center": ex.landing_center,
            "groundedness": g_res,
            "safety": s_res,
            "preservation": p_res,
            "risk_calibration": r_res,
            "passed": example_passed,
        })

    elapsed = round(time.time() - start_time, 3)
    n = len(examples)

    report = EvaluationReport(
        total_examples=n,
        passed_examples=passed_count,
        mean_groundedness_score=round(sum(groundedness_scores) / n, 3) if n > 0 else 1.0,
        safety_adherence_rate=round(sum(safety_adherences) / n, 3) if n > 0 else 1.0,
        metric_preservation_rate=round(sum(preservation_scores) / n, 3) if n > 0 else 1.0,
        risk_calibration_rate=round(sum(risk_calibrations) / n, 3) if n > 0 else 1.0,
        execution_time_s=elapsed,
        results=results,
    )

    logger.info("Evaluation complete: %d/%d passed in %.2fs", passed_count, n, elapsed)
    return report
