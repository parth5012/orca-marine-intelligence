"""
Tests for the evals HTML dashboard (reports/evals/).

Ticket: evals-html-dashboard
"""

import json
from pathlib import Path

from backend.evals.dataset import load_marine_eval_dataset
from backend.evals.report_html import write_html_report
from backend.evals.runner import run_marine_evals


def _small_report():
    dataset = load_marine_eval_dataset(limit=6)
    return run_marine_evals(dataset=dataset, use_langsmith=False)


def test_runner_results_carry_detail_fields():
    report = _small_report()
    assert report.results, "expected per-case results"
    for r in report.results:
        for key in ("language", "bucket", "query", "inputs", "reference", "advisory_text"):
            assert key in r, f"result missing {key}"


def test_write_html_report_creates_dashboard_cases_and_detail_pages(tmp_path: Path):
    report = _small_report()
    out = tmp_path / "evals"
    paths = write_html_report(report, out_dir=out)

    assert Path(paths["dashboard"]).exists()
    assert Path(paths["cases"]).exists()
    assert Path(paths["json"]).exists()
    assert int(paths["pages"]) == len(report.results) == 6

    dashboard = (out / "index.html").read_text(encoding="utf-8")
    for needle in (
        "Eval dashboard",
        "Groundedness",
        "Language purity",
        "Bucket × language matrix",
        "Top failures",
    ):
        assert needle in dashboard

    cases_html = (out / "cases.html").read_text(encoding="utf-8")
    for r in report.results:
        eid = r["example_id"]
        assert eid in cases_html
        assert f"case/{eid}.html" in cases_html

    # Every case page shows judge scores + reasoning.
    for r in report.results:
        page = (out / "case" / f"{r['example_id']}.html").read_text(encoding="utf-8")
        assert r["example_id"] in page
        assert "Judge reasoning" in page
        assert "Judge scores" in page
        assert "advisory" in page.lower() or "Model output" in page

    payload = json.loads((out / "evals_latest.json").read_text(encoding="utf-8"))
    assert payload["total_examples"] == 6
    assert len(payload["results"]) == 6


def test_case_page_escapes_html_injection(tmp_path: Path):
    report = _small_report()
    report.results[0]["query"] = "<script>alert(1)</script>"
    report.results[0]["advisory_text"] = "<b>bold</b>"
    out = tmp_path / "evals"
    write_html_report(report, out_dir=out)
    page = (out / "case" / f"{report.results[0]['example_id']}.html").read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page
