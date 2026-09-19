# Implement Canonical Constants and Classifiers in safety_thresholds.py

Type: task
Status: closed
Blocked by: 01, 02, 03

## Resolution
Implemented revised canonical constants and classifier bounds in `backend/agents/safety_thresholds.py`:
- `WAVE_SAFE_MAX_M = 2.0`, `WAVE_DANGER_MIN_M = 3.5`
- `WIND_SAFE_MAX_KT = 22.0`, `WIND_DANGER_MIN_KT = 27.0`
- `CURRENT_SAFE_MAX_KT = 2.0`, `CURRENT_DANGER_MIN_KT = 3.0`
- `WIND_SAFE_MAX_KPH = 40.74`, `WIND_DANGER_MIN_KPH = 50.0`
- Verified `classify_wave`, `classify_wind`, `classify_current`, `derive_safety_tier`, `veto_safety`, and `apply_safety_veto`.
- Fail-open caution and geofence veto remain intact.

## Question

How should `backend/agents/safety_thresholds.py` be modified to implement the agreed canonical thresholds without breaking its single-source-of-truth invariant?

### Scope of Changes
1. Update canonical constants in `backend/agents/safety_thresholds.py`:
   - `WAVE_SAFE_MAX_M = 2.0` (was 1.5)
   - `WAVE_DANGER_MIN_M = 3.5` (was 2.5)
   - `WIND_SAFE_MAX_KT = 20.0` (or value resolved in Ticket 02; was 15.0)
   - `WIND_DANGER_MIN_KT = 27.0` (was 25.0)
   - `CURRENT_SAFE_MAX_KT = 2.0` (or value resolved in Ticket 03; was 1.5)
   - `CURRENT_DANGER_MIN_KT = 3.0` (was 2.5)
   - Update derived kmph values:
     - `WIND_SAFE_MAX_KPH = round(WIND_SAFE_MAX_KT * KT_TO_KPH, 2)` -> 37.04
     - `WIND_DANGER_MIN_KPH = round(WIND_DANGER_MIN_KT * KT_TO_KPH, 2)` -> 50.00
2. Verify that `classify_wave`, `classify_wind`, `classify_current`, `derive_safety_tier`, `veto_safety`, and `apply_safety_veto` correctly reference the revised constants.
3. Ensure fail-open caution on missing wave/wind and geofence veto rules remain 100% intact.
