# Wayfinder Map: IMD/INCOIS-aligned Safety Thresholds Implementation

## Destination

Update ORCA canonical safety thresholds (`backend/agents/safety_thresholds.py`) and all parity consumers to IMD/INCOIS-aligned bands, verified with a 100% passing test suite, accompanied by ADR-0003 and PPT research documentation.

## Notes

- **Owner Lane:** M-A (Agents & Orchestration: `backend/agents/`)
- **Branch:** `feat/m-a-safety-thresholds`
- **Primary References:**
  - Evidence Report: `docs/research/07-safety-thresholds-evidence.md`
  - Canonical Implementation: `backend/agents/safety_thresholds.py`
  - Parity Tests: `tests/test_safety_thresholds.py`
- **Core Invariants:**
  - "Code Trumps LLM": deterministic safety tier derivation must never be overridden by LLM text.
  - "Fail-Open Caution": missing wave or wind measurements must resolve to CAUTION, never SAFE.
  - "Single Truth": only `safety_thresholds.py` defines thresholds; all other modules import or mirror them.
- **Relevant Skills:** `wayfinder`, `domain-modeling`, `tdd`, `visual-findings`

## Decisions so far

- [Govt-Aligned Safety Thresholds Research](docs/research/07-safety-thresholds-evidence.md): Researched IMD, INCOIS, and FAO standards. Confirmed current thresholds are 5–9 kt and 0.5–1.0 m too restrictive. Locked wave danger at 3.5 m (INCOIS wind-wave warning) and wind danger at 27.0 kt (IMD 50 kmph "do not venture" warning) for 6–12 m Kerala fleet (FAO Category C).
- [Settle Wind SAFE Upper Bound](issues/02-settle-wind-safe-bound.md) — Option B selected: Codify `WIND_SAFE_MAX_KT = 22.0` (40.74 kmph) aligning with Beaufort Force 6 onset and IMD 45 kmph margin.
- [Settle Surface Current Bands](issues/03-settle-current-thresholds.md) — Option A selected: Relax surface currents to `CURRENT_SAFE_MAX_KT = 2.0` and `CURRENT_DANGER_MIN_KT = 3.0` aligning with INCOIS alert range (0.9–1.9 m/s).
- [Draft ADR-0003: IMD/INCOIS-aligned Safety Thresholds](issues/01-draft-adr-thresholds.md) — Codified in `docs/adr/0003-safety-thresholds-alignment.md`.
- [Implement Canonical Constants and Classifiers in safety_thresholds.py](issues/04-implement-canonical-constants.md) — Updated canonical constants and classifier bounds in `backend/agents/safety_thresholds.py`.
- [Update test_safety_thresholds.py and Ingest Constants Parity](issues/05-update-test-parity-tables.md) — Updated test tables in `tests/test_safety_thresholds.py`, all 97 parity tests pass.
- [Re-verify Evals Dataset and Golden References against New Bands](issues/06-verify-evals-and-routers.md) — Reconciled evals datasets, test fixtures, and mock scenarios; all test suites pass.
- [Run Full Test Suite and Verification Gate](issues/07-run-full-verification-gate.md) — Verified full backend test suite passes (693 passed, 15 skipped, 0 failed).

## Open Frontier Tickets (Takeable Now)

(All tickets resolved)

## Blocked Downstream Tickets

(None)

## Not yet specified

- **SVAS Boat Safety Index (BSI) Engine**: Multi-parameter calculation factoring in wave period, steepness, and beam categories (<4m, 6m, 7m). Dependent on vessel registry survey and INCOIS live BSI API availability.
- **Dynamic Port Warning Ingestion**: Automatic parsing of IMD LC-III / Local Caution signals directly into `danger_agent.py`.

## Out of scope

- Re-scoring or changing weights in `combiner.py` (safety bands only act as a veto / classification filter).
- Re-translating Bhashini golden datasets (only numeric thresholds and test fixtures change).
- Modifying UI components in `frontend/map/` or `frontend/chat/` (they read the existing `safety` field).
