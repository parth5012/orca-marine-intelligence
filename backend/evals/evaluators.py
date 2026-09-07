"""
Custom LangSmith Evaluators for ORCA Marine Intelligence (PS 26176).

Owner: M-A (Agents & Orchestration)
Ticket: #57 (Wayfinder Map: #53)

Implements domain-specific evaluators:
1. MarineGroundednessEvaluator: Oceanographic factuality against physical ground truth.
2. GeofenceSafetyEvaluator: Maritime boundary safety adherence & "DO NOT SAIL" enforcement.
3. MetricPreservationEvaluator: LLM synthesizer numerical preservation without hallucination.
4. RiskCalibrationEvaluator: Smart Combiner composite score & tier calibration.
"""

from __future__ import annotations

import re
from typing import Any


class MarineGroundednessEvaluator:
    """
    Evaluates factual grounding of predicted marine metrics against verified ground truth.
    Penalizes hallucinations in wave height, wind speed, and cyclone alert status.
    """

    def __init__(self, wave_tolerance_m: float = 0.5, wind_tolerance_kt: float = 5.0):
        self.wave_tolerance_m = wave_tolerance_m
        self.wind_tolerance_kt = wind_tolerance_kt

    def evaluate(
        self,
        run_input: dict[str, Any],
        run_output: dict[str, Any],
        reference: dict[str, Any],
    ) -> dict[str, Any]:
        penalties = 0.0
        checks = 0
        details = {}

        # 1. Wave height verification
        if "expected_wave_height_m" in reference:
            checks += 1
            ref_wave = float(reference["expected_wave_height_m"])
            pred_wave = run_output.get("wave_height_m")
            if pred_wave is None:
                # Try parsing from text
                m = re.search(r"(\d+(?:\.\d+)?)\s*m(?:eters?)?\s*(?:wave|height)?", run_output.get("text", ""))
                pred_wave = float(m.group(1)) if m else None

            if pred_wave is not None:
                diff = abs(float(pred_wave) - ref_wave)
                details["wave_diff_m"] = round(diff, 2)
                if diff > self.wave_tolerance_m:
                    excess = min(diff - self.wave_tolerance_m, 2.0)
                    penalties += 0.4 * (excess / 2.0)
            else:
                penalties += 0.4
                details["wave_missing"] = True

        # 2. Wind speed verification
        if "expected_wind_speed_kt" in reference:
            checks += 1
            ref_wind = float(reference["expected_wind_speed_kt"])
            pred_wind = run_output.get("wind_speed_kt")
            if pred_wind is None:
                m = re.search(r"(\d+(?:\.\d+)?)\s*k(?:ts?|nots?)", run_output.get("text", ""))
                pred_wind = float(m.group(1)) if m else None

            if pred_wind is not None:
                diff = abs(float(pred_wind) - ref_wind)
                details["wind_diff_kt"] = round(diff, 2)
                if diff > self.wind_tolerance_kt:
                    excess = min(diff - self.wind_tolerance_kt, 20.0)
                    penalties += 0.4 * (excess / 20.0)
            else:
                penalties += 0.4
                details["wind_missing"] = True

        # 3. Cyclone alert status
        if "expected_cyclone_alert" in reference:
            checks += 1
            ref_alert = bool(reference["expected_cyclone_alert"])
            pred_alert = bool(run_output.get("cyclone_alert", False))
            details["cyclone_alert_match"] = ref_alert == pred_alert
            if ref_alert != pred_alert:
                penalties += 0.5  # Heavy penalty on cyclone miss or false alarm

        score = max(0.0, round(1.0 - penalties, 2))
        grounded = score >= 0.80

        reasoning = (
            f"Groundedness score: {score:.2f} ({checks} metric checks). "
            f"{'Accurately grounded' if grounded else 'Hallucinations or out-of-tolerance metrics detected'}."
        )

        return {
            "key": "marine_groundedness",
            "score": score,
            "grounded": grounded,
            "reasoning": reasoning,
            "details": details,
        }


class GeofenceSafetyEvaluator:
    """
    Evaluates strict compliance with maritime boundary rules, MPA non-fishing mandates,
    and the mandatory 'DO NOT SAIL' safety directive.
    """

    def evaluate(
        self,
        run_input: dict[str, Any],
        run_output: dict[str, Any],
        reference: dict[str, Any],
    ) -> dict[str, Any]:
        pred_tier = (run_output.get("safety_tier") or run_output.get("tier") or "").lower()
        expected_tier = (reference.get("expected_safety_tier") or "").lower()
        is_mpa = reference.get("is_mpa", False)
        mandate_dns = reference.get("mandate_do_not_sail", False)
        text = (run_output.get("advisory_text") or run_output.get("text") or "").upper()

        reasons: list[str] = []
        score = 1.0

        # Tier matching
        if expected_tier and pred_tier != expected_tier:
            # Danger downgraded to safe is a catastrophic failure
            if expected_tier == "danger" and pred_tier == "safe":
                score = 0.0
                reasons.append(f"Catastrophic failure: Expected danger but got '{pred_tier}'.")
            else:
                score -= 0.4
                reasons.append(f"Tier mismatch: Expected '{expected_tier}', got '{pred_tier}'.")

        # MPA violation checking
        if is_mpa and pred_tier != "danger":
            score = 0.0
            reasons.append("Zone inside MPA must be classified as danger.")

        # Mandatory 'DO NOT SAIL' directive checking
        if mandate_dns:
            if "DO NOT SAIL" not in text:
                score = max(0.0, score - 0.5)
                reasons.append("Mandatory directive 'DO NOT SAIL' missing from advisory text.")
            else:
                reasons.append("Mandatory directive 'DO NOT SAIL' confirmed present.")

        passed = score >= 0.85
        reasoning = " | ".join(reasons) if reasons else "Full safety adherence verified."

        return {
            "key": "geofence_safety",
            "score": score,
            "passed": passed,
            "reasoning": reasoning,
        }


class MetricPreservationEvaluator:
    """
    Evaluates whether numbers and units from upstream agent facts were preserved
    verbatim by the synthesizer without corruption or masking token leaks.
    """

    def evaluate(
        self,
        run_input: dict[str, Any],
        run_output: dict[str, Any],
        reference: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        text = run_output.get("advisory_text") or run_output.get("text") or ""

        # Check for placeholder leaks (__M*__)
        if re.search(r"__M[A-Z0-9_]+__", text):
            return {
                "key": "metric_preservation",
                "score": 0.0,
                "preserved": False,
                "reasoning": "Mask placeholder token leaked into final synthesized response.",
                "missing": [],
            }

        # Check metrics in run_input
        metrics_dict = run_input.get("metrics") or {}
        if not metrics_dict and reference and "metrics" in reference:
            metrics_dict = reference["metrics"]

        if not metrics_dict:
            return {
                "key": "metric_preservation",
                "score": 1.0,
                "preserved": True,
                "reasoning": "No specific numerical metrics specified in input.",
                "missing": [],
            }

        missing = []
        for key, val in metrics_dict.items():
            if isinstance(val, (int, float)):
                v_exact = str(val)
                v_f1 = f"{val:.1f}" if isinstance(val, float) else str(val)
                v_f2 = f"{val:.2f}" if isinstance(val, float) else str(val)
                # Look for number bordered by non-digits (handles 1.85m, 14.2kt, etc.)
                pattern = rf"(?<![\d.])(?:{re.escape(v_exact)}|{re.escape(v_f1)}|{re.escape(v_f2)})(?![\d.])"
                if not re.search(pattern, text):
                    missing.append(f"{key}={val}")

        total = len(metrics_dict)
        preserved_count = total - len(missing)
        score = round(preserved_count / total, 2) if total > 0 else 1.0
        preserved = score == 1.0

        return {
            "key": "metric_preservation",
            "score": score,
            "preserved": preserved,
            "reasoning": f"Preserved {preserved_count}/{total} numerical metrics."
            + (f" Missing: {missing}" if missing else ""),
            "missing": missing,
        }


class RiskCalibrationEvaluator:
    """
    Evaluates whether the composite safety risk score and classification
    fall within expected calibrated bounds.
    """

    def evaluate(
        self,
        run_input: dict[str, Any],
        run_output: dict[str, Any],
        reference: dict[str, Any],
    ) -> dict[str, Any]:
        score_val = run_output.get("score")
        tier = (run_output.get("tier") or run_output.get("safety_tier") or "").lower()

        expected_tier = (reference.get("expected_tier") or reference.get("expected_safety_tier") or "").lower()
        min_score = reference.get("min_score", 0.0)
        max_score = reference.get("max_score", 1.0)

        penalties = 0.0
        reasons = []

        if score_val is not None:
            if not (min_score <= float(score_val) <= max_score):
                penalties += 0.4
                reasons.append(f"Score {score_val} outside expected range [{min_score}, {max_score}].")

        if expected_tier and tier != expected_tier:
            penalties += 0.6
            reasons.append(f"Tier '{tier}' does not match expected '{expected_tier}'.")

        final_score = max(0.0, round(1.0 - penalties, 2))
        passed = final_score >= 0.90

        return {
            "key": "risk_calibration",
            "score": final_score,
            "passed": passed,
            "reasoning": " | ".join(reasons) if reasons else "Risk score and tier properly calibrated.",
        }
