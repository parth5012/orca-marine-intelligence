"""
Tests for LLM-as-judge evaluators (Groq primary, Gemini fallback).

Policy: offline-first, measure-only, never a CI gate.
- Default pytest runs use injected fake clients (no network).
- Real LLM calls only when ORCA_ENABLE_LLM_JUDGE=1 + keys present.
- Socket-guard test proves offline-skip never dials out.
"""

import json
import os
import socket

import pytest

from backend.evals.dataset import load_marine_eval_dataset
from backend.evals.runner import run_marine_evals


def _fake_client_ok(prompt: str) -> str:
    return json.dumps({
        "score": 0.9,
        "passed": True,
        "reasoning": "Fake judge: advisory is clear, actionable, tier matches.",
    })


def _fake_client_fail(prompt: str) -> str:
    return json.dumps({
        "score": 0.2,
        "passed": False,
        "reasoning": "Fake judge: safety downgrade, DO NOT SAIL missing.",
    })


def test_llm_judge_module_importable():
    from backend.evals import llm_judge  # noqa: F401
    assert hasattr(llm_judge, "LLMAdvisoryQualityJudge")
    assert hasattr(llm_judge, "LLMSafetyJudge")
    assert hasattr(llm_judge, "is_llm_judge_available")


def test_quality_judge_fake_client_pass():
    from backend.evals.llm_judge import LLMAdvisoryQualityJudge
    j = LLMAdvisoryQualityJudge()
    out = {"safety_tier": "safe", "advisory_text": "Safe fishing near Kochi. Wave 1.2m, wind 10kt."}
    ref = {"expected_safety_tier": "safe", "mandate_do_not_sail": False}
    res = j.evaluate({}, out, ref, client=_fake_client_ok)
    assert res["key"] == "llm_advisory_quality"
    assert res["score"] == pytest.approx(0.9)
    assert res["passed"] is True
    assert "reasoning" in res and res["reasoning"]
    assert res.get("skipped") is False


def test_safety_judge_fake_client_fail():
    from backend.evals.llm_judge import LLMSafetyJudge
    j = LLMSafetyJudge()
    out = {"safety_tier": "safe", "advisory_text": "Good day for fishing."}
    ref = {"expected_safety_tier": "danger", "mandate_do_not_sail": True}
    res = j.evaluate({}, out, ref, client=_fake_client_fail)
    assert res["key"] == "llm_safety"
    assert res["score"] == pytest.approx(0.2)
    assert res["passed"] is False


def test_judge_graceful_skip_without_keys(monkeypatch):
    """No keys + no injected client -> skipped verdict, never raises, never fails gate."""
    from backend.evals.llm_judge import LLMAdvisoryQualityJudge
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    j = LLMAdvisoryQualityJudge()
    res = j.evaluate({}, {"advisory_text": "hi"}, {}, client=None)
    assert res["skipped"] is True
    assert res["passed"] is True  # neutral: measure-only sidecar must not fail offline suite
    assert res["score"] == 1.0


def test_judge_malformed_llm_output_never_crashes():
    from backend.evals.llm_judge import LLMAdvisoryQualityJudge
    j = LLMAdvisoryQualityJudge()
    res = j.evaluate({}, {"advisory_text": "Safe."}, {}, client=lambda p: "not json {{{")
    assert res["skipped"] is True or "reasoning" in res
    assert 0.0 <= res["score"] <= 1.0


def test_judge_offline_proof_no_socket(monkeypatch):
    """Injected fake client path must not touch the network."""
    from backend.evals.llm_judge import LLMSafetyJudge

    def guard(*a, **k):
        raise AssertionError("network dial attempted in offline judge path")

    monkeypatch.setattr(socket, "socket", guard)
    j = LLMSafetyJudge()
    res = j.evaluate(
        {}, {"safety_tier": "safe", "advisory_text": "Safe."},
        {"expected_safety_tier": "safe"}, client=_fake_client_ok,
    )
    assert res["passed"] is True


def test_runner_llm_sidecar_opt_in_with_fake_client():
    from backend.evals.llm_judge import fake_client_for_tests  # test helper
    dataset = load_marine_eval_dataset(limit=3)
    report = run_marine_evals(
        dataset=dataset, use_langsmith=False,
        use_llm_judge=True, llm_judge_client=fake_client_for_tests,
    )
    assert report.total_examples == 3
    # sidecar fields exist on every result, deterministic gate unchanged
    for r in report.results:
        assert "llm_quality" in r and "llm_safety" in r
        assert 0.0 <= r["llm_quality"]["score"] <= 1.0
    assert 0.0 <= report.llm_quality_rate <= 1.0
    assert 0.0 <= report.llm_safety_rate <= 1.0
    assert "LLM" in report.generate_scorecard()


def test_runner_llm_disabled_by_default_offline():
    dataset = load_marine_eval_dataset(limit=2)
    report = run_marine_evals(dataset=dataset, use_langsmith=False)
    for r in report.results:
        assert r["llm_quality"]["skipped"] is True
        assert r["llm_safety"]["skipped"] is True
