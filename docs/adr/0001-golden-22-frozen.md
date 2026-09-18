# Golden covers 22 Bhashini languages with frozen references

We evaluated 5-core offline templates vs 10 frontend langs vs 22 Bhashini langs for the golden dataset. We chose 22 with one-time Bhashini translate → native-speaker fix → freeze in `data/golden_v1.json`; evals compare against frozen text plus invariants and never call Bhashini live.

## Considered Options

- 5 core (`en/ml/ta/te/hi`) via `render_grounded_advisory()` only: deterministic but abandons the ISRO 22-language MVP promise.
- Live Bhashini as oracle at eval time: fresh but flakes on 429/5xx (`backend/core/bhashini.py` returns `translated=False`) and burns quota.

## Consequences

Freezing 66 multilingual (3×22) plus ~75 English cases costs one day of Bhashini calls plus human review, but makes `backend/evals/` deterministic. Re-freeze only on template or Bhashini-model change, as `golden_v2.json`, never overwriting v1.
