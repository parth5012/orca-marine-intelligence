"""
ORCA Eval HTML Report — static dashboard regenerated on every evals run.

Owner: M-A (Agents & Orchestration)
Ticket: evals-html-dashboard

Generates a self-contained, dependency-free static site under
``reports/evals/`` (gitignored, local-only):

    reports/evals/
    ├── index.html          ← dashboard with all aggregate metrics
    ├── cases.html          ← compact filterable list of every test case
    ├── case/<EXAMPLE_ID>.html ← one detail page per test case
    └── evals_latest.json   ← machine-readable dump of the report

Each case page shows the test-case inputs, the model output, and every
judge (evaluator) score + reasoning. The evaluators are currently
deterministic rule-based judges (see ``backend/evals/evaluators.py``);
if an LLM-judge is added later its ``score``/``reasoning`` fields render
automatically because every evaluator card reads the generic
``score`` + ``reasoning``/``reason`` + ``details`` keys.

Usage:
    from backend.evals.report_html import write_html_report
    paths = write_html_report(report)  # defaults to reports/evals/
    paths = write_html_report(report, out_dir="reports/evals")
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_OUT_DIR = "reports/evals"

# (result-key, display label)
EVALUATOR_CARDS: list[tuple[str, str]] = [
    ("groundedness", "Marine Groundedness"),
    ("safety", "Geofence Safety"),
    ("preservation", "Metric Preservation"),
    ("risk_calibration", "Risk Calibration"),
    ("language_purity", "Language Purity"),
    ("numeral_invariant", "Numeral Invariant"),
]

CSS = """
:root{--bg:#0b1622;--panel:#12202f;--panel2:#0f1c2a;--line:#22384f;--txt:#e8f1f8;
--mut:#93a9bd;--ok:#2ecc71;--bad:#ff5d5d;--warn:#f5a623;--acc:#38bdf8}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);
font:15px/1.55 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
a{color:var(--acc)}header.top{border-bottom:1px solid var(--line);background:#0d1926;
padding:14px 22px;display:flex;gap:18px;align-items:center;flex-wrap:wrap}
header.top .brand{font-weight:700;font-size:17px}
header.top nav a{margin-right:14px;text-decoration:none;color:var(--txt);opacity:.85}
header.top nav a.on{color:var(--acc);font-weight:700}
header.top .stamp{margin-left:auto;color:var(--mut);font-size:12.5px}
.wrap{max-width:1180px;margin:0 auto;padding:22px}
.badge{display:inline-block;padding:3px 12px;border-radius:999px;font-weight:700;font-size:13px}
.badge.pass{background:rgba(46,204,113,.15);color:var(--ok);border:1px solid var(--ok)}
.badge.measure{background:rgba(245,166,35,.14);color:var(--warn);border:1px solid var(--warn)}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%}
.dot.ok{background:var(--ok)}.dot.bad{background:var(--bad)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:12px;margin:16px 0}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}
.card .k{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.06em}
.card .v{font-size:24px;font-weight:700;margin:2px 0}
.card .s{color:var(--mut);font-size:12.5px}
.bar{height:7px;background:#1d2f44;border-radius:99px;overflow:hidden;margin-top:8px}
.bar>i{display:block;height:100%;background:var(--acc)}
table{width:100%;border-collapse:collapse;background:var(--panel);border-radius:10px;overflow:hidden}
th,td{padding:9px 10px;border-bottom:1px solid var(--line);text-align:left;font-size:13.5px}
th{background:#16293d;color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.05em}
tr.rowlink{cursor:pointer}tr.rowlink:hover td{background:#16293d}
.toolbar{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0}
.toolbar input,.toolbar select{background:#0f1e30;color:var(--txt);border:1px solid var(--line);
border-radius:8px;padding:8px 10px;font-size:14px}
pre{background:#0a141f;border:1px solid var(--line);border-radius:8px;padding:12px;overflow:auto;
font-size:12.5px;max-height:340px}
details{background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin:10px 0}
summary{cursor:pointer;font-weight:600}
.jgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:12px}
.jcard{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}
.jcard h3{margin:0 0 6px;font-size:15px}
.jcard .score{font-size:22px;font-weight:700}
.meta{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px;margin:12px 0}
.meta div{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px}
.meta .k{color:var(--mut);font-size:11.5px;text-transform:uppercase;letter-spacing:.06em}
.mtx{overflow:auto}footer{color:var(--mut);font-size:12px;padding:18px;text-align:center}
"""


def _esc(v: Any) -> str:
    return html.escape("" if v is None else str(v), quote=True)


def _slug(example_id: str) -> str:
    return "".join(c if (c.isalnum() or c in ("-", "_")) else "_" for c in str(example_id))


def _judge_text(ev: dict[str, Any]) -> str:
    """Best-effort judge reasoning: evaluators use `reasoning` or `reason`."""
    if not isinstance(ev, dict):
        return ""
    return str(ev.get("reasoning") or ev.get("reason") or "")


def _judge_score(ev: dict[str, Any]) -> float | None:
    if not isinstance(ev, dict):
        return None
    s = ev.get("score")
    try:
        return float(s) if s is not None else None
    except (TypeError, ValueError):
        return None


def _judge_passed(ev: dict[str, Any]) -> bool | None:
    if not isinstance(ev, dict):
        return None
    for k in ("passed", "preserved", "grounded"):
        if k in ev:
            return bool(ev[k])
    s = _judge_score(ev)
    return (s >= 0.8) if s is not None else None


def _nav(active: str, stamp: str) -> str:
    def cls(name: str) -> str:
        return ' class="on"' if name == active else ""

    return (
        f'<header class="top"><div class="brand">🌊 ORCA Evals</div><nav>'
        f'<a href="index.html"{cls("dash")}>Dashboard</a>'
        f'<a href="cases.html"{cls("cases")}>Test Cases</a>'
        f"</nav>"
        f'<span class="stamp">updated {_esc(stamp)}</span></header>'
    )


def _status_badge(pass_rate: float) -> str:
    if pass_rate >= 0.80:
        return '<span class="badge pass">PASS — all gates met</span>'
    return '<span class="badge measure">MEASURE-ONLY — baseline tracked</span>'


def _metric_cards(report: Any) -> str:
    metrics = [
        ("Total examples", f"{report.total_examples}", "", None),
        ("Passed", f"{report.passed_examples}", f"{report.pass_rate * 100:.1f}% pass rate", report.pass_rate),
        ("Groundedness", f"{report.mean_groundedness_score * 100:.1f}%", "mean score", report.mean_groundedness_score),
        ("Safety", f"{report.safety_adherence_rate * 100:.1f}%", "adherence rate", report.safety_adherence_rate),
        ("Preservation", f"{report.metric_preservation_rate * 100:.1f}%", "preservation rate", report.metric_preservation_rate),
        ("Risk calibration", f"{report.risk_calibration_rate * 100:.1f}%", "calibration rate", report.risk_calibration_rate),
        ("Language purity", f"{report.mean_language_purity_score * 100:.1f}%", "mean score", report.mean_language_purity_score),
        ("Numeral invariant", f"{report.numeral_invariant_rate * 100:.1f}%", "invariant rate", report.numeral_invariant_rate),
        ("Cross-lang tiers", f"{report.cross_lang_tier_equality_rate * 100:.1f}%", "equality rate", report.cross_lang_tier_equality_rate),
        ("Latency", f"{report.execution_time_s:.2f}s", "execution time", None),
    ]
    out = ['<div class="grid">']
    for label, val, sub, frac in metrics:
        bar = f'<div class="bar"><i style="width:{max(0.0, min(1.0, frac)) * 100:.1f}%"></i></div>' if frac is not None else ""
        out.append(f'<div class="card"><div class="k">{_esc(label)}</div><div class="v">{_esc(val)}</div><div class="s">{_esc(sub)}</div>{bar}</div>')
    out.append("</div>")
    return "\n".join(out)


def _bucket_summary(results: list[dict[str, Any]]) -> str:
    agg: dict[str, list[int]] = {}
    for r in results:
        b = str(r.get("bucket") or "unknown")
        agg.setdefault(b, [0, 0])
        agg[b][0] += 1
        agg[b][1] += 1 if r.get("passed") else 0
    rows = []
    for b in sorted(agg):
        tot, ok = agg[b]
        pct = (ok / tot * 100) if tot else 0.0
        rows.append(f"<tr><td>{_esc(b)}</td><td>{tot}</td><td>{ok}</td><td>{pct:.1f}%</td></tr>")
    return (
        "<h2>Pass rate by bucket</h2><table><tr><th>Bucket</th><th>Total</th>"
        "<th>Passed</th><th>Pass %</th></tr>" + "".join(rows) + "</table>"
    )


def _lang_summary(results: list[dict[str, Any]]) -> str:
    agg: dict[str, list[int]] = {}
    for r in results:
        lang = str(r.get("language") or "en")
        agg.setdefault(lang, [0, 0])
        agg[lang][0] += 1
        agg[lang][1] += 1 if r.get("passed") else 0
    rows = []
    for lang in sorted(agg):
        tot, ok = agg[lang]
        pct = (ok / tot * 100) if tot else 0.0
        rows.append(f"<tr><td>{_esc(lang)}</td><td>{tot}</td><td>{ok}</td><td>{pct:.1f}%</td></tr>")
    return (
        "<h2>Pass rate by language</h2><table><tr><th>Lang</th><th>Total</th>"
        "<th>Passed</th><th>Pass %</th></tr>" + "".join(rows) + "</table>"
    )


def _matrix_table(report: Any) -> str:
    matrix = getattr(report, "matrix", {}) or {}
    try:
        from backend.evals.runner import ALL_LANGS, BUCKET_NAMES
    except Exception:
        langs = sorted({str(r.get("language") or "en") for r in getattr(report, "results", [])})
        buckets = sorted({str(r.get("bucket") or "?") for r in getattr(report, "results", [])})
    else:
        langs, buckets = ALL_LANGS, BUCKET_NAMES
    head = "<tr><th>Bucket</th>" + "".join(f"<th>{_esc(l)}</th>" for l in langs) + "</tr>"
    rows = [head]
    for b in buckets:
        cells = []
        for lang in langs:
            v = matrix.get(b, {}).get(lang)
            cells.append(f"<td>{v:.2f}</td>" if isinstance(v, (int, float)) else "<td>–</td>")
        rows.append(f"<tr><td><b>{_esc(b)}</b></td>" + "".join(cells) + "</tr>")
    return "<h2>Bucket × language matrix</h2><div class='mtx'><table>" + "".join(rows) + "</table></div>"


def _fail_list(results: list[dict[str, Any]]) -> str:
    failed = [r for r in results if not r.get("passed")]
    if not failed:
        return "<h2>Top failures</h2><p>No failures — every case passed.</p>"
    items = []
    for r in failed[:10]:
        eid = str(r.get("example_id", "?"))
        reasons = []
        for key, _label in EVALUATOR_CARDS:
            ev = r.get(key, {})
            if isinstance(ev, dict) and _judge_passed(ev) is False:
                reasons.append(f"{key}: {_judge_text(ev)}")
        reason = "; ".join(reasons) if reasons else "threshold not reached"
        items.append(
            f'<li><a href="case/{_slug(eid)}.html"><b>{_esc(eid)}</b></a> '
            f'({_esc(r.get("landing_center", ""))}) — {_esc(reason)}</li>'
        )
    more = f"<p>…and {len(failed) - 10} more — see <a href='cases.html'>Test Cases</a>.</p>" if len(failed) > 10 else ""
    return f"<h2>Top failures ({len(failed)})</h2><ol>" + "".join(items) + f"</ol>{more}"


def render_dashboard(report: Any, stamp: str) -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ORCA Evals — Dashboard</title><style>{CSS}</style></head><body>
{_nav("dash", stamp)}
<div class="wrap">
<h1>Eval dashboard</h1>
<p>{_status_badge(report.pass_rate)} &nbsp; {report.passed_examples}/{report.total_examples} passed
({report.pass_rate * 100:.1f}%)</p>
{_metric_cards(report)}
{_bucket_summary(report.results)}
{_lang_summary(report.results)}
{_matrix_table(report)}
{_fail_list(report.results)}
</div><footer>ORCA Marine Intelligence · evals are measure-only, never a merge gate ·
<a href="cases.html">browse all {len(report.results)} test cases →</a></footer></body></html>"""


def render_cases(results: list[dict[str, Any]], stamp: str) -> str:
    buckets = sorted({str(r.get("bucket") or "unknown") for r in results})
    langs = sorted({str(r.get("language") or "en") for r in results})
    rows = []
    for r in sorted(results, key=lambda d: str(d.get("example_id"))):
        eid = str(r.get("example_id", "?"))
        ok = bool(r.get("passed"))
        dot = '<span class="dot ok"></span>' if ok else '<span class="dot bad"></span>'
        g = _judge_score(r.get("groundedness", {}))
        s = _judge_score(r.get("safety", {}))
        rows.append(
            f'<tr class="rowlink" data-id="{_esc(eid.lower())}" data-pass="{str(ok).lower()}" '
            f'data-bucket="{_esc(str(r.get("bucket") or ""))}" data-lang="{_esc(str(r.get("language") or ""))}" '
            f'onclick="location.href=\'case/{_slug(eid)}.html\'">'
            f"<td>{dot} {'PASS' if ok else 'FAIL'}</td>"
            f"<td><a href=\"case/{_slug(eid)}.html\">{_esc(eid)}</a></td>"
            f"<td>{_esc(r.get('landing_center', ''))}</td>"
            f"<td>{_esc(r.get('language', ''))}</td>"
            f"<td>{_esc(r.get('bucket', ''))}</td>"
            f"<td>{'' if g is None else f'{g:.2f}'}</td>"
            f"<td>{'' if s is None else f'{s:.2f}'}</td></tr>"
        )
    b_opts = "".join(f'<option value="{_esc(b)}">{_esc(b)}</option>' for b in buckets)
    l_opts = "".join(f'<option value="{_esc(l)}">{_esc(l)}</option>' for l in langs)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ORCA Evals — Test Cases</title><style>{CSS}</style></head><body>
{_nav("cases", stamp)}
<div class="wrap">
<h1>Test cases ({len(results)})</h1>
<p>Compact list — click any row for the full case page with judge scores &amp; reasoning.</p>
<div class="toolbar">
<input id="q" type="search" placeholder="Filter by id, centre, query…" oninput="fil()">
<select id="fpass" onchange="fil()"><option value="">pass + fail</option>
<option value="true">pass only</option><option value="false">fail only</option></select>
<select id="fb" onchange="fil()"><option value="">all buckets</option>{b_opts}</select>
<select id="fl" onchange="fil()"><option value="">all languages</option>{l_opts}</select>
</div>
<table id="t"><tr><th>Status</th><th>Case</th><th>Centre</th><th>Lang</th>
<th>Bucket</th><th>Ground.</th><th>Safety</th></tr>
{"".join(rows)}</table>
<p id="n"></p>
</div>
<script>
function fil(){{const q=document.getElementById('q').value.toLowerCase();
const p=document.getElementById('fpass').value,b=document.getElementById('fb').value,
l=document.getElementById('fl').value;let n=0;
document.querySelectorAll('#t tr.rowlink').forEach(tr=>{{
const ok=(!p||tr.dataset.pass===p)&&(!b||tr.dataset.bucket===b)&&(!l||tr.dataset.lang===l)
&&(!q||tr.innerText.toLowerCase().includes(q));
tr.style.display=ok?'':'none';if(ok)n++;}});
document.getElementById('n').textContent=n+' case(s) shown';}}
fil();
</script>
<footer>ORCA Marine Intelligence · <a href="index.html">← back to dashboard</a></footer></body></html>"""


def render_case(r: dict[str, Any], stamp: str) -> str:
    eid = str(r.get("example_id", "unknown"))
    ok = bool(r.get("passed"))
    badge = '<span class="badge pass">PASS</span>' if ok else '<span class="badge measure">FAIL</span>'
    cards = []
    for key, label in EVALUATOR_CARDS:
        ev = r.get(key, {}) if isinstance(r.get(key), dict) else {}
        s = _judge_score(ev)
        p = _judge_passed(ev)
        reason = _judge_text(ev)
        details = ev.get("details") if isinstance(ev, dict) else None
        dot = '<span class="dot ok"></span>' if p else ('<span class="dot bad"></span>' if p is False else "")
        det = f"<pre>{_esc(json.dumps(details, indent=2, ensure_ascii=False))}</pre>" if details else ""
        cards.append(
            f'<div class="jcard"><h3>{dot} {_esc(label)}</h3>'
            f'<div class="score">{"" if s is None else f"{s:.2f}"}</div>'
            f"<p><b>Judge reasoning:</b> {_esc(reason) or '<i>—</i>'}</p>{det}</div>"
        )
    # Cross-lang group verdict is aggregate-level; show raw if present.
    if isinstance(r.get("cross_lang"), dict):
        ev = r["cross_lang"]
        cards.append(
            f'<div class="jcard"><h3>{_esc("Cross-lang tier equality")}</h3>'
            f'<div class="score">{_esc(ev.get("score", ""))}</div>'
            f"<p><b>Judge reasoning:</b> {_esc(_judge_text(ev))}</p></div>"
        )
    inputs_pre = _esc(json.dumps(r.get("inputs", {}), indent=2, ensure_ascii=False))
    ref_pre = _esc(json.dumps(r.get("reference", {}), indent=2, ensure_ascii=False))
    out_pre = _esc(json.dumps(r.get("output", {}), indent=2, ensure_ascii=False))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ORCA Evals — {_esc(eid)}</title><style>{CSS}</style></head><body>
{_nav("", stamp)}
<div class="wrap">
<p><a href="../cases.html">← all cases</a> · <a href="../index.html">dashboard</a></p>
<h1>{_esc(eid)} {badge}</h1>
<div class="meta">
<div><div class="k">Landing centre</div>{_esc(r.get("landing_center", ""))}</div>
<div><div class="k">Language</div>{_esc(r.get("language", ""))}</div>
<div><div class="k">Bucket</div>{_esc(r.get("bucket", ""))}</div>
<div><div class="k">Verdict</div>{'passed — every judge check green' if ok else 'failed — at least one judge check red'}</div>
</div>
<h2>Query</h2><p>{_esc(r.get("query", ""))}</p>
{"<h2>Query (vernacular)</h2><p>" + _esc(r.get("query_vernacular", "")) + "</p>" if r.get("query_vernacular") else ""}
<h2>Model output (advisory)</h2><p>{_esc(r.get("advisory_text", "")) or "<i>—</i>"}</p>
<h2>Judge scores &amp; reasoning</h2>
<div class="jgrid">{"".join(cards)}</div>
<details><summary>Inputs (JSON)</summary><pre>{inputs_pre}</pre></details>
<details><summary>Reference / ground truth (JSON)</summary><pre>{ref_pre}</pre></details>
<details><summary>Full model output (JSON)</summary><pre>{out_pre}</pre></details>
</div><footer>ORCA Marine Intelligence · case {_esc(eid)} · <a href="../cases.html">← all cases</a></footer></body></html>"""


def write_html_report(report: Any, out_dir: str | Path = DEFAULT_OUT_DIR) -> dict[str, str]:
    """Write dashboard + case list + per-case pages + JSON dump. Returns paths."""
    out = Path(out_dir)
    case_dir = out / "case"
    case_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    results = list(getattr(report, "results", []) or [])
    (out / "index.html").write_text(render_dashboard(report, stamp), encoding="utf-8")
    (out / "cases.html").write_text(render_cases(results, stamp), encoding="utf-8")

    pages = 0
    for r in results:
        eid = str(r.get("example_id", f"case_{pages}"))
        (case_dir / f"{_slug(eid)}.html").write_text(render_case(r, stamp), encoding="utf-8")
        pages += 1

    # Machine-readable dump (scorecard string included via to_dict()).
    try:
        payload = report.to_dict()
    except Exception:
        payload = {"results": results}
    (out / "evals_latest.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return {
        "dashboard": str(out / "index.html"),
        "cases": str(out / "cases.html"),
        "case_dir": str(case_dir),
        "json": str(out / "evals_latest.json"),
        "pages": str(pages),
    }
