# IMD and INCOIS Aligned Safety Thresholds for Coastal Fleets

We updated ORCA canonical safety thresholds in `backend/agents/safety_thresholds.py` and downstream parity consumers to align with India Meteorological Department (IMD) warning protocols, Indian National Centre for Ocean Information Services (INCOIS) ocean state alerts, and FAO Category-C small-scale vessel guidelines (6–12 m motorized craft).

## Decision

The revised canonical thresholds are:
- **Wind Speed (sustained)**:
  - `SAFE`: < 22.0 kt (< 40.74 kmph, aligns with Beaufort F6 onset and IMD 45 kmph squally advisory lower boundary).
  - `CAUTION`: 22.0–27.0 kt (40.74–50.00 kmph, operational advisory zone).
  - `DANGER`: > 27.0 kt (> 50.00 kmph, verbatim IMD "Do Not Venture" red alert threshold).
- **Significant Wave Height**:
  - `SAFE`: < 2.0 m (FAO Category-C 6–12 m craft design limit; Douglas Moderate sea boundary).
  - `CAUTION`: 2.0–3.5 m (absorbs INCOIS swell and wind-wave alert band).
  - `DANGER`: > 3.5 m (verbatim INCOIS wind-wave warning threshold).
- **Surface Current Speed**:
  - `SAFE`: < 2.0 kt (< 1.03 m/s, comfortably within INCOIS harbor advisory envelope).
  - `CAUTION`: 2.0–3.0 kt (1.03–1.54 m/s, active drift caution).
  - `DANGER`: > 3.0 kt (> 1.54 m/s, severe drift danger for artisanal craft).
- **Atmospheric Pressure & Cyclone**:
  - `CAUTION`: < 1005 hPa watch.
  - `DANGER`: < 995 hPa depression/cyclone core, or named cyclone within 500 km radius (preserved).
- **Safety Invariants (Strictly Preserved)**:
  - *Code Trumps LLM*: Safety tier derivation is 100% deterministic and cannot be bypassed or downgraded by generative text.
  - *Fail-Open Caution*: Any query missing wave or wind measurements defaults to `CAUTION`, never `SAFE`.
  - *Single Source of Truth*: `backend/agents/safety_thresholds.py` is the single canonical source; all other modules import or mirror its values.

## Considered Options

- **Wind SAFE Upper Bound (20.0 kt vs 22.0 kt)**:
  - *20.0 kt*: NOAA Small Craft Advisory lower limit with 3–5 kt buffer before IMD squalls.
  - *22.0 kt (Selected)*: Aligns with Beaufort F6 onset and IMD's 45 kmph "No Warning" limit, recovering ~7 kt of fishable weather days for artisanal fishermen without compromising storm warnings.
- **Surface Current Bands (1.5 / 2.5 kt vs 2.0 / 3.0 kt)**:
  - *1.5 / 2.5 kt*: Legacy ORCA baseline; triggered cautionary alerts at the extreme lower boundary of INCOIS daily notices.
  - *2.0 / 3.0 kt (Selected)*: Aligns with INCOIS 0.9–1.9 m/s alert ranges, centering operational caution on actual strong drift events and avoiding premature warnings from coastal tidal rips.

## Consequences

- Recovers significant fishable days previously misclassified as `CAUTION` or `DANGER`.
- Requires parity updates in:
  - `backend/agents/safety_thresholds.py`
  - `backend/ingest/live_fetchers.py`
  - `tests/test_safety_thresholds.py`
- Requires calibration of synthetic test mocks in evals and regression suites to ensure scenarios designed to trigger `DANGER` use values above the new 3.5 m wave or 27.0 kt wind thresholds.
