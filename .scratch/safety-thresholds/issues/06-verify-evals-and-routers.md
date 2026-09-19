# Re-verify Evals Dataset and Golden References against New Bands

Type: task
Status: closed
Blocked by: 05

## Resolution
Re-verified and updated evals datasets, test fixtures, and router consumers against revised safety thresholds:
1. Updated `backend/evals/dataset.py` `EDGE_HIGH_WAVE_01` fixture to 3.8m wave (above revised 3.5m DANGER threshold).
2. Updated `backend/agents/synthesizer_service.py` so that vetoed advisories with empty search/best properly retain DANGER safety tier.
3. Updated `tests/test_agents.py` and `tests/test_dynamic_agents.py` mocks and asserts to align with new thresholds.
4. Verified `tests/test_agents.py`, `tests/test_api_chat.py`, `tests/test_api_route.py`, `tests/test_gonogo_flag.py`, `tests/test_data_evals.py`, and `tests/test_dynamic_agents.py` — all pass cleanly.

## Question

Which evals scenarios and test fixtures flip status due to the relaxed safety bands, and how should they be reconciled?

### Scope of Changes
1. Search codebase for tests asserting specific safety tiers for mock data:
   - `tests/test_agents.py`
   - `tests/test_api_chat.py`
   - `tests/test_api_route.py`
   - `tests/test_data_evals.py`
   - `tests/test_gonogo_flag.py`
   - `backend/evals/dataset.py`
2. Identify test cases where wave was between 1.5m and 2.0m (previously "caution", now "safe") or wind between 15kt and 20kt (previously "caution", now "safe"), or wave between 2.5m and 3.5m (previously "danger", now "caution").
3. Ensure mocks explicitly set wave/wind values appropriate to the intended test scenario (e.g., if a test specifically tests DANGER veto, ensure mock wave > 3.5m or wind > 27kt rather than 2.8m).
4. Verify offline evals in `backend/evals/` continue to evaluate cleanly without breaking golden invariants.
