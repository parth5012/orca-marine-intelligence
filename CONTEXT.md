# ORCA Marine Intelligence

Golden-dataset evaluation context for the multi-agent advisory pipeline (planner → fish_finder → sea/weather/danger → combiner). Exists to freeze expected multilingual outputs so evals are deterministic offline.

## Language

**Golden dataset**:
Frozen input→expected-output pairs plus invariants used to score the pipeline. Never calls live APIs at eval time.
_Avoid_: benchmark, test set, eval dump

**Frozen reference**:
One-time Bhashini output for a query, human-fixed once, then stored in `data/golden_v1.json` and never overwritten. v2 is a new file.
_Avoid_: live translation, cached translation

**Maritime edge**:
A safety-legality scenario with fixed coords and fixed tier (safe / caution / danger / MPA-ban / cyclone / IMBL-buffer / high-wave).
_Avoid_: linguistic edge, query variation

**Linguistic edge**:
A phrasing variation of the same intent (code-mix, Romanized, transliterated port alias, ASR typo, mixed script).
_Avoid_: maritime edge, translation error

**Invariant**:
A property that must hold in every language for the same coords: same safety tier, Arabic digits 0-9 only, no `__M*__` leak, `DO NOT SAIL` preserved when mandated.
_Avoid_: fluency score, BLEU

**Cross-lang tier equality**:
The invariant that `en` vs `ml` vs `bn` replies for identical lat/lon share tier and veto. Failure means a language-specific safety bug.
_Avoid_: per-lang accuracy

**Canonical query**:
A query in native script for one language (e.g. `കൊച്ചിക്ക് സമീപം മീൻ എവിടെ?`). The source for the one-time freeze.
_Avoid_: Romanized query, code-mix query
