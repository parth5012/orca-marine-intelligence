"""
Tests for detailed eval logging (offline-first, no network).

Verifies that the eval harness emits useful log records:
- run_marine_evals logs start + completion summaries
- LLM judges log verdicts when a (fake) client is injected
- provider failures log a warning before falling through to skipped-neutral
"""

import logging

import backend.evals.llm_judge as llm_judge
from backend.evals.dataset import load_marine_eval_dataset
from backend.evals.llm_judge import fake_client_for_tests
from backend.evals.runner import run_marine_evals


def test_judge_logs_verdict_on_fake_client(caplog):
    with caplog.at_level(logging.INFO, logger="backend.evals.llm_judge"):
        res = llm_judge.LLMAdvisoryQualityJudge().evaluate(
            {}, {"advisory_text": "Safe.", "safety_tier": "safe"},
            {"expected_safety_tier": "safe"}, client=fake_client_for_tests,
        )
    assert res["skipped"] is False
    assert any("Quality judge verdict" in r.message for r in caplog.records)


def test_runner_logs_start_and_complete(caplog):
    ds = load_marine_eval_dataset(limit=2)
    with caplog.at_level(logging.INFO, logger="backend.evals.runner"):
        report = run_marine_evals(dataset=ds, use_langsmith=False)
    msgs = [r.message for r in caplog.records]
    assert any("Starting marine evals" in m for m in msgs)
    assert any("Evaluation complete" in m for m in msgs)
    assert report.total_examples == 2


def test_provider_failure_logs_warning_before_skip(caplog, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_testkey1234567890")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr(
        llm_judge, "_call_groq",
        lambda p, s: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with caplog.at_level(logging.DEBUG, logger="backend.evals.llm_judge"):
        res = llm_judge.LLMSafetyJudge().evaluate(
            {}, {"safety_tier": "safe", "advisory_text": "Safe."},
            {"expected_safety_tier": "safe"}, client=None,
        )
    assert res["skipped"] is True
    assert any("failed" in r.message for r in caplog.records)
