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


# ---------------------------------------------------------------------------
# Multilingual Evaluators (T4 #180, Map #182)
# ---------------------------------------------------------------------------

INDIC_UNICODE_RANGES: dict[str, tuple[tuple[int, int], ...]] = {
    "ml": ((0x0D00, 0x0D7F),),
    "ta": ((0x0B80, 0x0BFF),),
    "te": ((0x0C00, 0x0C7F),),
    "hi": ((0x0900, 0x097F),),
    "mr": ((0x0900, 0x097F),),
    "ne": ((0x0900, 0x097F),),
    "sa": ((0x0900, 0x097F),),
    "gom": ((0x0900, 0x097F),),
    "mai": ((0x0900, 0x097F),),
    "brx": ((0x0900, 0x097F),),
    "doi": ((0x0900, 0x097F),),
    "bn": ((0x0980, 0x09FF),),
    "as": ((0x0980, 0x09FF),),
    "mni": ((0x0980, 0x09FF), (0xABC0, 0xABFF)),
    "pa": ((0x0A00, 0x0A7F),),
    "gu": ((0x0A80, 0x0AFF),),
    "or": ((0x0B00, 0x0B7F),),
    "kn": ((0x0C80, 0x0CFF),),
    "ur": ((0x0600, 0x06FF), (0x0750, 0x077F)),
    "ks": ((0x0600, 0x06FF), (0x0750, 0x077F)),
    "sd": ((0x0600, 0x06FF), (0x0750, 0x077F)),
    "sat": ((0x1C50, 0x1C7F),),
}


def _check_native_script(text: str, lang: str) -> bool:
    """Verifies that non-English text contains at least one character in the target script."""
    if lang == "en":
        return True
    ranges = INDIC_UNICODE_RANGES.get(lang)
    if not ranges:
        from backend.agents.lexical_mask import contains_native_script
        return contains_native_script(text, lang)
    return any(any(lo <= ord(ch) <= hi for lo, hi in ranges) for ch in text)


class LanguagePurityEvaluator:
    """
    Evaluates whether generated text is free of mask placeholder leaks
    (__M...__) and contains native script characters when language is non-English.
    """

    def evaluate(
        self,
        run_input_or_output: dict[str, Any],
        run_output: dict[str, Any] | None = None,
        reference: dict[str, Any] | None = None,
        language: str = "en",
    ) -> dict[str, Any]:
        # Handle both evaluate(run_output, reference, ...) and evaluate(run_input, run_output, reference, ...)
        if run_output is None:
            actual_output = run_input_or_output
        else:
            actual_output = run_output

        text = actual_output.get("text") or actual_output.get("advisory_text") or ""
        ref_lang = reference.get("language") if reference else None
        lang = str(actual_output.get("language") or ref_lang or language or "en").lower()

        # 1. Mask placeholder leak (__M[A-Z0-9_]+__)
        if re.search(r"__M[A-Z0-9_]+__", text):
            return {
                "key": "language_purity",
                "score": 0.0,
                "passed": False,
                "reason": "Mask placeholder token leaked into output text.",
            }

        # 2. Native script check for non-English
        if lang != "en":
            if not text.strip():
                return {
                    "key": "language_purity",
                    "score": 0.0,
                    "passed": False,
                    "reason": f"Output text is empty; no native script found for '{lang}'.",
                }
            if not _check_native_script(text, lang):
                return {
                    "key": "language_purity",
                    "score": 0.0,
                    "passed": False,
                    "reason": f"Output does not contain native script for language '{lang}'.",
                }

        return {
            "key": "language_purity",
            "score": 1.0,
            "passed": True,
            "reason": "Clean language purity: no placeholder leaks and valid script.",
        }


class NumeralInvariantEvaluator:
    """
    Enforces Arabic numerals (0-9) only; fails on regional Indic digits (e.g. ൧൨, १२).
    Verifies that expected numerical metrics are preserved in text.
    """

    def evaluate(
        self,
        run_input: dict[str, Any],
        run_output: dict[str, Any],
        reference: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        text = run_output.get("text") or run_output.get("advisory_text") or ""

        from backend.agents.lexical_mask import has_regional_digits, verify_numbers_preserved

        # 1. Check for regional Indic digits (spec violation)
        if has_regional_digits(text):
            return {
                "key": "numeral_invariant",
                "score": 0.0,
                "passed": False,
                "reason": "Contains non-Arabic regional Indic digits.",
                "missing": [],
            }

        # 2. Extract numbers from input/reference metrics
        metrics_dict = run_input.get("metrics") or {}
        if not metrics_dict and reference and "metrics" in reference:
            metrics_dict = reference["metrics"]

        expected_numbers = run_input.get("expected_numbers") or (reference and reference.get("expected_numbers")) or []
        if not expected_numbers and metrics_dict:
            expected_numbers = [
                f"{v:g}" if isinstance(v, float) else str(v)
                for v in metrics_dict.values()
                if isinstance(v, (int, float))
            ]

        missing = verify_numbers_preserved(expected_numbers, text) if expected_numbers else []
        total = len(expected_numbers)
        if total == 0:
            score = 1.0
        else:
            preserved = total - len(missing)
            score = round(preserved / total, 2)

        passed = score == 1.0
        reason = (
            f"Preserved {total - len(missing)}/{total} expected numbers."
            if total > 0
            else "Arabic numerals invariant satisfied."
        )
        if missing:
            reason += f" Missing: {missing}"

        return {
            "key": "numeral_invariant",
            "score": score,
            "passed": passed,
            "reason": reason,
            "missing": missing,
        }


class CrossLangTierEvaluator:
    """
    Evaluates cross-language tier equality across translations of the same scenario.
    All languages for the same location/scenario must yield identical safety_tier
    and identical DO NOT SAIL mandates.
    """

    def evaluate(
        self,
        group_outputs: dict[str, dict[str, Any]],
        reference: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not group_outputs:
            return {
                "key": "cross_lang_tier_equality",
                "score": 1.0,
                "passed": True,
                "reason": "No language outputs to compare.",
                "divergent_langs": [],
            }

        tiers: dict[str, str] = {}
        do_not_sail: dict[str, bool] = {}

        for lang, out in group_outputs.items():
            t = (out.get("safety_tier") or out.get("tier") or "").lower()
            tiers[lang] = t
            text = (out.get("advisory_text") or out.get("text") or "").upper()
            has_dns = "DO NOT SAIL" in text or bool(out.get("mandate_do_not_sail"))
            do_not_sail[lang] = has_dns

        expected_tier = reference.get("expected_safety_tier") if reference else None
        ref_tier = str(expected_tier or next(iter(tiers.values()), "safe")).lower()

        ref_dns = (
            bool(reference.get("mandate_do_not_sail"))
            if (reference and "mandate_do_not_sail" in reference)
            else next(iter(do_not_sail.values()), False)
        )

        divergent = []
        for lang, t in tiers.items():
            tier_match = (t == ref_tier)
            dns_match = (do_not_sail.get(lang, False) == ref_dns)

            if not tier_match or not dns_match:
                divergent.append(lang)

        total = len(group_outputs)
        matching = total - len(divergent)
        score = round(matching / total, 2) if total > 0 else 1.0
        passed = len(divergent) == 0

        reason = (
            "Cross-language tier equality confirmed across all languages."
            if passed
            else f"Divergent safety tiers or DO NOT SAIL status in: {divergent}"
        )

        return {
            "key": "cross_lang_tier_equality",
            "score": score,
            "passed": passed,
            "reason": reason,
            "divergent_langs": divergent,
        }
