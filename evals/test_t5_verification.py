"""
Tests for T5 Verify: LangSmith sync + full offline eval + scorecard report.
Ticket: #181
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from backend.evals.dataset import load_golden_v1, load_marine_eval_dataset, sync_dataset_to_langsmith
from backend.evals.runner import run_marine_evals
from scripts.freeze_golden import verify_golden_file


def test_golden_dataset_and_english_seed_counts():
    golden = load_golden_v1("data/golden_v1.json")
    assert len(golden) == 66

    english = load_marine_eval_dataset()
    assert len(english) >= 80


def test_freeze_golden_check_mode():
    valid, err = verify_golden_file("data/golden_v1.json")
    assert valid is True
    assert err == ""


def test_langsmith_sync_offline_skip(monkeypatch):
    # Ensure LANGCHAIN_API_KEY is unset/mocked empty
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    res = sync_dataset_to_langsmith(dataset_name="orca-golden-v1")
    assert res is None


def test_reports_scorecard_file_exists():
    report_file = Path("reports/golden_v1_scorecard.md")
    assert report_file.exists()
    content = report_file.read_text(encoding="utf-8")
    assert "LANGSMITH EVAL SCORECARD" in content
    assert "14x23 Evaluation Matrix" in content
    assert "Top Failures & Degradation Cases" in content


def test_full_offline_eval_no_network(monkeypatch):
    # Block network requests completely
    import socket

    def guard(*args, **kwargs):
        raise RuntimeError("Network call attempted during offline evaluation!")

    monkeypatch.setattr(socket, "socket", guard)

    combined_ds = load_golden_v1("data/golden_v1.json") + load_marine_eval_dataset()
    assert len(combined_ds) >= 146

    report = run_marine_evals(dataset=combined_ds, use_langsmith=False)
    assert report.total_examples >= 146
    assert report.execution_time_s >= 0.0
    assert report.mean_groundedness_score == 1.0
    assert report.safety_adherence_rate == 1.0
    assert report.numeral_invariant_rate == 1.0
    assert report.risk_calibration_rate == 1.0
    assert report.cross_lang_tier_equality_rate == 1.0


def test_langsmith_sync_mocked(monkeypatch):
    monkeypatch.setenv("LANGCHAIN_API_KEY", "lsv2_pt_testkey12345")

    from unittest.mock import MagicMock
    mock_client_inst = MagicMock()
    mock_client_inst.read_dataset.side_effect = Exception("Not found")
    mock_ds = MagicMock()
    mock_ds.id = "mock-dataset-id-123"
    mock_client_inst.create_dataset.return_value = mock_ds

    with patch("langsmith.Client", return_value=mock_client_inst):
        res = sync_dataset_to_langsmith(
            dataset_name="orca-golden-v1",
            dataset=load_golden_v1("data/golden_v1.json")[:2],
        )

    assert res == "mock-dataset-id-123"
    assert mock_client_inst.create_dataset.called
    assert mock_client_inst.create_example.call_count == 2
