# Update test_safety_thresholds.py and Ingest Constants Parity

Type: task
Status: closed
Blocked by: 04

## Resolution
Updated `tests/test_safety_thresholds.py` test matrices:
- `WAVE_CASES`: safe (<2.0m), caution (2.0–3.5m), danger (>3.5m)
- `WIND_CASES`: safe (<22.0kt), caution (22.0–27.0kt), danger (>27.0kt)
- `CURRENT_CASES`: safe (<2.0kt), caution (2.0–3.0kt), danger (>3.0kt)
- Verified parity with `live_fetchers.py`, `officer.py`, `sea_checker.py`, `weather_agent.py`, `lexical_mask.py`, `combiner.py`, and `orchestrator.py`.
- Ran `pytest tests/test_safety_thresholds.py`: 97/97 tests passed cleanly.

## Question

How must `tests/test_safety_thresholds.py` and downstream parity constants (e.g. `backend/ingest/live_fetchers.py`) be updated to reflect the new threshold truth?

### Scope of Changes
1. In `tests/test_safety_thresholds.py`:
   - Update `WAVE_CASES` parameter matrix to test:
     - < 2.0 m -> "safe" (e.g., 1.2 m, 1.9 m)
     - 2.0–3.5 m -> "caution" (e.g., 2.0 m, 2.8 m, 3.5 m)
     - > 3.5 m -> "danger" (e.g., 3.6 m, 4.2 m)
   - Update `WIND_CASES` parameter matrix to test:
     - < 20.0 kt -> "safe" (e.g., 12.0 kt, 19.9 kt)
     - 20.0–27.0 kt -> "caution" (e.g., 20.0 kt, 24.0 kt, 27.0 kt)
     - > 27.0 kt -> "danger" (e.g., 27.1 kt, 32.0 kt)
   - Update `CURRENT_CASES` parameter matrix to test:
     - < 2.0 kt -> "safe"
     - 2.0–3.0 kt -> "caution"
     - > 3.0 kt -> "danger"
   - Update `test_canonical_constants()` assertions.
2. In `backend/ingest/live_fetchers.py`:
   - Update `WAVE_SAFE_MAX`, `WAVE_CAUTION_MAX`, `WIND_SAFE_MAX`, `WIND_CAUTION_MAX`, `CURRENT_SAFE_MAX`, `CURRENT_CAUTION_MAX` to import or mirror `safety_thresholds.py`.
3. In `backend/routers/officer.py`:
   - Verify `is_danger_sea_state` logic with `wind_kt > 27.0`, `wave_m > 3.5`, `current_kt > 3.0`.
4. Run `pytest tests/test_safety_thresholds.py` and ensure 100% pass.
