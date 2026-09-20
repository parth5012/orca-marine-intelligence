import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def pytest_configure(config):
    """Register the eval marker for LangSmith quality evaluations."""
    config.addinivalue_line(
        "markers", "eval: marks test as an LLM-quality evaluation (measure-only, not a CI gate)"
    )


def pytest_sessionfinish(session, exitstatus):
    """Regenerate reports/evals/ HTML dashboard after every evals suite run.

    Re-runs the full offline eval (golden + English seed, no network) and
    rewrites index.html / cases.html / case/*.html / evals_latest.json so the
    template is always in sync with the latest results. Set
    ORCA_SKIP_EVAL_HTML=1 to opt out (e.g. in unit tests for report_html).
    """
    import os

    if os.environ.get("ORCA_SKIP_EVAL_HTML") == "1":
        return
    # Only fire for runs that actually collected evals tests.
    try:
        collected = getattr(session, "testscollected", 0)
    except Exception:
        collected = 1
    if not collected:
        return
    try:
        from backend.evals.dataset import load_golden_v1, load_marine_eval_dataset
        from backend.evals.report_html import write_html_report
        from backend.evals.runner import run_marine_evals

        dataset = load_golden_v1() + load_marine_eval_dataset()
        report = run_marine_evals(dataset=dataset, use_langsmith=False)
        paths = write_html_report(report)
        print(f"\n[orca-evals] HTML dashboard updated: {paths['dashboard']} ({paths['pages']} cases)")
    except Exception as exc:  # never fail the suite because the report failed
        print(f"\n[orca-evals] WARNING: HTML dashboard refresh skipped ({exc})")
