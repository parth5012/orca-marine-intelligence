# ORCA Evals — LLM Quality Evaluations (LangSmith, Offline-First)

> **Measure-only quality harness for advisory correctness, safety adherence, and
> multilingual fidelity.** Evals score *how good* the answers are. They never
> gate merges — that is the job of `tests/` (see [Tests vs Evals](#tests-vs-evals)
> below).

## Tests vs Evals

| | `tests/` (35 files) | `evals/` (this dir, 5 files) |
|---|---|---|
| **Question** | Does the code work? | Is the answer good / safe / faithful? |
| **Style** | Deterministic unit + API + integration assertions | Scored evaluators over benchmark datasets (0.0–1.0 per example) |
| **Network** | Fully mocked, offline, fast | Offline by default; LangSmith cloud sync is opt-in |
| **Policy** | **CI gate — must be green to merge** | **Measure-only — tracks baselines, never blocks** |
| **Run** | `python -m pytest tests -q` | `python -m pytest evals -q` |

**Rule of thumb:** if it asserts exact values/status codes with mocks, it belongs
in `tests/`. If it scores groundedness, safety tiers, numeral preservation, or
cross-language equality over `data/golden_v1.json` / generated seeds, it belongs
here.

Related implementation code (not tests): `backend/evals/` (`dataset.py`,
`evaluators.py`, `runner.py`) plus `scripts/freeze_golden.py`.

## Layout

```
evals/
├── README.md                        ← you are here
├── conftest.py                      ← repo-root sys.path + `eval` marker
├── test_data_evals.py               ← Tier-3 parquet fallback + 4 core evaluators + offline runner
├── test_multilingual_evaluators.py  ← 3 multilingual evaluators + golden offline run (#180)
├── test_golden_dataset.py           ← MarineEvalExample multilingual fields + golden loader (#177)
├── test_freeze_golden.py            ← freeze_golden.py → data/golden_v1.json (#179)
└── test_t5_verification.py          ← T5 verify: sync + full offline eval + scorecard (#181)
```

## The 7 evaluators (`backend/evals/evaluators.py`)

**Core (English + safety):**

| Evaluator | What it scores | Fail signal |
|---|---|---|
| `MarineGroundednessEvaluator` | Wave/wind within tolerance (`0.5 m` / `5.0 kt`), cyclone flag exact | Hallucinated metrics |
| `GeofenceSafetyEvaluator` | Tier match; MPA ⇒ `danger`; `mandate_do_not_sail` ⇒ literal `DO NOT SAIL` in text | Danger downgraded to safe (score `0.0`) |
| `MetricPreservationEvaluator` | Upstream numbers preserved verbatim; no `__M*__` placeholder leak | Dropped/altered numbers |
| `RiskCalibrationEvaluator` | Score inside `[min_score, max_score]` + tier match | Miscalibrated combiner output |

**Multilingual (T4 #180):**

| Evaluator | What it scores | Fail signal |
|---|---|---|
| `LanguagePurityEvaluator` | No `__M*__` leak; non-English output contains native-script chars | Placeholder leak, empty text, or English-only text for `ml`/`ta`/… |
| `NumeralInvariantEvaluator` | Arabic digits `0-9` only; expected numbers preserved | Regional Indic digits (e.g. `൧൨`, `१२`) |
| `CrossLangTierEvaluator` | Same `safety_tier` + same `DO NOT SAIL` mandate across all languages of one scenario | Any divergent language |

## Datasets (`backend/evals/dataset.py`)

| Dataset | Source | Size | Content |
|---|---|---|---|
| English seed | `load_marine_eval_dataset()` — generated in code | 80+ examples | 10 coastal centers + 4 high-risk edges + 14-bucket seed (`pfz`, `sea`, `weather`, `geofence_veto`, `intent_split`, `numerals`, `adversarial`, `resilience`, `temporal_forecast`, `sst_chlorophyll`, `species_depth`, `multi_turn_session`, `lang_gate_voice_typo`, `data_freshness`) |
| Golden v1 (frozen multilingual) | `load_golden_v1("data/golden_v1.json")` | **66 records = 22 langs × 3 queries** | Frozen `query_vernacular` + `frozen_reply` + `invariants` per language; falls back to English seed with a warning if file is missing/corrupt |
| Combined (T5 verify) | golden + English seed | **146+ examples** | Full offline gate used by `test_t5_verification.py` |

Each example is a `MarineEvalExample`: `example_id`, `landing_center`,
`inputs{latitude, longitude, query, …}`, `reference{expected_safety_tier,
mandate_do_not_sail, min/max_score, …}`, `language`, `query_vernacular`,
`frozen_reply`, `invariants{safety_tier_same, arabic_numerals_only,
do_not_sail_preserved}`.

## How to run

```bash
# All evals (offline, no keys needed)
python -m pytest evals -q

# Single file
python -m pytest evals/test_multilingual_evaluators.py -q

# Unit tests only (CI gate, unaffected by evals)
python -m pytest tests -q

# Everything
python -m pytest tests evals -q
```

### Full offline scorecard (no pytest)

```bash
# Writes reports/golden_v1_scorecard.md — 14 buckets × 23 languages matrix
python -m backend.evals.runner --out reports/golden_v1_scorecard.md

# Custom golden file
python -m backend.evals.runner --dataset data/golden_v1.json --out reports/custom_scorecard.md

# HTML dashboard only (default --html is reports/evals/; pass empty to skip)
python -m backend.evals.runner --html reports/evals
```

## HTML dashboard (`reports/evals/`, auto-updated)

Every `pytest evals` run regenerates a self-contained static site (no
dependencies, works from `file://`; `reports/` is gitignored, local-only):

```
reports/evals/
├── index.html            ← dashboard: all aggregate metrics, bucket/language
│                           summaries, bucket × language matrix, top failures
├── cases.html            ← compact filterable list of every test case
│                           (search + pass/fail + bucket + language filters;
│                           click a row for its case page)
├── case/<EXAMPLE_ID>.html ← one page per case: query, model output, every
│                           judge score + reasoning, inputs/reference JSON
└── evals_latest.json     ← machine-readable dump of the full report
```

Open `reports/evals/index.html` in a browser after the suite finishes.
Each case page shows every judge (evaluator) score with the reasoning it
returned (`reasoning`/`reason` + `details`) — if an LLM-judge is added
later, its verdict renders automatically. Implementation:
`backend/evals/report_html.py` (`write_html_report()`); auto-refresh hook
in `evals/conftest.py::pytest_sessionfinish`; covered by
`evals/test_html_report.py`. Set `ORCA_SKIP_EVAL_HTML=1` to skip the
refresh for a run.

### LangSmith cloud (opt-in)

Evals run **100% offline** unless *both* are set — otherwise the runner logs and
stays local, and `sync_dataset_to_langsmith()` returns `None`:

```bash
export LANGCHAIN_API_KEY=lsv2_pt_...
export LANGCHAIN_TRACING_V2=true
python -m backend.evals.dataset --sync --name orca-golden-v1
```

## Freezing / refreshing the golden dataset

`data/golden_v1.json` is a **frozen** reference — re-freeze only when canonical
queries change. The freeze translates 3 canonical queries per language via
Bhashini (`scripts/freeze_golden.py`, owner M-B), with template fallback marking
`needs_human_fix: true` when translation fails:

```bash
# Check mode (used by test_t5_verification.py) — validates 66 records / 22 langs
python scripts/freeze_golden.py --check

# Re-freeze (requires BHASHINI_API_KEY; skips human-fixed records unless --force)
python scripts/freeze_golden.py --force
```

## Reading the scorecard (`reports/golden_v1_scorecard.md`)

`EvaluationReport.generate_scorecard()` prints:

- **Pass/fail line** — `PASS (All gates met)` at `pass_rate ≥ 0.80`, else
  `MEASURE-ONLY (Baseline tracked)`. An example passes only if *all six*
  per-example checks pass (groundedness ≥ 0.80, safety, preservation ≥ 0.80,
  risk calibration, language purity, numeral invariant).
- **14×23 matrix** — mean pass rate per (`bucket` × `language`) cell; `-` means
  no examples for that cell (expected: golden covers only `pfz`/`sea`/
  `geofence_veto`-style scenarios per language, English seed covers all 14
  buckets).
- **Top failures** — up to 10 failing examples with per-evaluator reasons.

## Adding a new eval

1. Add the scorer to `backend/evals/evaluators.py` (pure function of
   `(inputs, output, reference)` → `{key, score, passed, reason}`).
2. Wire it into `run_marine_evals()` in `backend/evals/runner.py` + the
   `EvaluationReport` aggregates/scorecard.
3. Cover it with a file in `evals/test_*.py` using a mock `target_fn` —
   never hit the network (see `test_data_evals.py::TestLangSmithEvaluationRunner`
   for the pattern; use `monkeypatch.setattr(socket, "socket", guard)` to prove
   offline-ness like `test_t5_verification.py` does).
4. Regenerate the scorecard and commit `reports/golden_v1_scorecard.md`
   alongside the change.

## CI policy

- `tests/` failures block merge. `evals/` failures **do not** — they record a
  quality regression to investigate (compare the scorecard matrix before/after).
- Keep evals offline-safe: no live Open-Meteo / IMD / Bhashini calls inside
  `evals/`; Tier-3 parquet fallbacks are skipped (not failed) when parquet files
  are absent.
