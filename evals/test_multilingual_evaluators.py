"""
Tests for T4 M-A: 3 multilingual evaluators + 14x22 matrix in runner.
Ticket: #180
"""

import pytest
from backend.evals.evaluators import (
    LanguagePurityEvaluator,
    NumeralInvariantEvaluator,
    CrossLangTierEvaluator,
)
from backend.evals.dataset import load_golden_v1
from backend.evals.runner import run_marine_evals


def test_language_purity_evaluator_placeholder_leak():
    evaluator = LanguagePurityEvaluator()
    # Mask placeholder token leak must fail with score 0.0
    output = {"advisory_text": "Safe fishing near __MKNOTS_0__ wind."}
    res = evaluator.evaluate(output, language="en")
    assert res["score"] == 0.0
    assert res["passed"] is False
    assert "placeholder" in res["reason"].lower()


def test_language_purity_evaluator_empty_text():
    evaluator = LanguagePurityEvaluator()
    # Non-English empty text must fail language purity
    res = evaluator.evaluate({"advisory_text": ""}, language="ml")
    assert res["score"] == 0.0
    assert res["passed"] is False


def test_cross_lang_tier_evaluator_unreferenced_divergence():
    evaluator = CrossLangTierEvaluator()
    # Without reference, if one language has DO NOT SAIL and another does not, it must flag divergence
    group_outputs = {
        "en": {"safety_tier": "safe", "advisory_text": "Safe conditions."},
        "ta": {"safety_tier": "safe", "advisory_text": "DO NOT SAIL. Danger."},
    }
    res = evaluator.evaluate(group_outputs, reference=None)
    assert res["passed"] is False
    assert len(res["divergent_langs"]) > 0
    evaluator = LanguagePurityEvaluator()
    # Mask placeholder token leak must fail with score 0.0
    output = {"advisory_text": "Safe fishing near __MKNOTS_0__ wind."}
    res = evaluator.evaluate(output, language="en")
    assert res["score"] == 0.0
    assert res["passed"] is False
    assert "placeholder" in res["reason"].lower()


def test_language_purity_evaluator_native_script():
    evaluator = LanguagePurityEvaluator()
    # Malayalam output with native script passes
    ml_output = {"advisory_text": "കൊച്ചിയിൽ ഇന്ന് കടൽ ശാന്തമാണ്."}
    res = evaluator.evaluate(ml_output, language="ml")
    assert res["score"] == 1.0
    assert res["passed"] is True

    # Non-English without native script (pure English text for ml) fails
    en_only_output = {"advisory_text": "Sea is safe near Kochi."}
    res = evaluator.evaluate(en_only_output, language="ml")
    assert res["score"] == 0.0
    assert res["passed"] is False


def test_numeral_invariant_regional_digits_fails():
    evaluator = NumeralInvariantEvaluator()
    # Malayalam digits ൧൨ (12) must fail
    res = evaluator.evaluate(
        run_input={},
        run_output={"advisory_text": "കാറ്റിന്റെ വേഗത ൧൨ knots."},
    )
    assert res["score"] == 0.0
    assert res["passed"] is False
    assert "regional" in res["reason"].lower() or "non-arabic" in res["reason"].lower()


def test_numeral_invariant_arabic_digits_passes():
    evaluator = NumeralInvariantEvaluator()
    # Arabic digits 12 must pass
    res = evaluator.evaluate(
        run_input={"expected_numbers": ["12", "1.4"]},
        run_output={"advisory_text": "Wind speed is 12 knots, wave height is 1.4m."},
    )
    assert res["score"] == 1.0
    assert res["passed"] is True
    assert res["missing"] == []


def test_cross_lang_tier_evaluator_tier_mismatch():
    evaluator = CrossLangTierEvaluator()
    # en says safe, ta says danger
    group_outputs = {
        "en": {"safety_tier": "safe", "advisory_text": "Safe to sail."},
        "ml": {"safety_tier": "safe", "advisory_text": "കടൽ ശാന്തമാണ്."},
        "ta": {"safety_tier": "danger", "advisory_text": "DO NOT SAIL."},
    }
    reference = {"expected_safety_tier": "safe", "mandate_do_not_sail": False}
    res = evaluator.evaluate(group_outputs, reference=reference)
    assert res["passed"] is False
    assert "ta" in res["divergent_langs"]


def test_cross_lang_tier_evaluator_matching():
    evaluator = CrossLangTierEvaluator()
    group_outputs = {
        "en": {"safety_tier": "safe", "advisory_text": "Safe to sail."},
        "ml": {"safety_tier": "safe", "advisory_text": "കടൽ ശാന്തമാണ്."},
        "ta": {"safety_tier": "safe", "advisory_text": "பாதுகாப்பானது."},
    }
    reference = {"expected_safety_tier": "safe", "mandate_do_not_sail": False}
    res = evaluator.evaluate(group_outputs, reference=reference)
    assert res["passed"] is True
    assert res["divergent_langs"] == []


def test_run_marine_evals_on_golden_dataset_offline():
    dataset = load_golden_v1("data/golden_v1.json")
    assert len(dataset) == 66

    report = run_marine_evals(dataset=dataset, use_langsmith=False)
    assert report.total_examples == 66
    scorecard = report.generate_scorecard()
    assert "LANGSMITH EVAL SCORECARD" in scorecard
    assert "Language Purity" in scorecard
    assert "Numeral Invariant" in scorecard
    assert "14x23" in scorecard or "Matrix" in scorecard
