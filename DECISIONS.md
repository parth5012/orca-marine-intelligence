# Architectural & Design Decisions

## 2026-09-19: ADR-0003 IMD/INCOIS-aligned Safety Thresholds
- **Decision**: Update canonical bands in `backend/agents/safety_thresholds.py`:
  - Wave: Safe < 2.0m, Caution 2.0–3.5m, Danger > 3.5m (INCOIS wind-wave warning, FAO Cat-C).
  - Wind: Safe < 22.0kt (40.74 kmph, Beaufort F6 onset), Caution 22.0–27.0kt, Danger > 27.0kt (50 kmph IMD warning).
  - Current: Safe < 2.0kt, Caution 2.0–3.0kt, Danger > 3.0kt (INCOIS alert range).
- **Alternatives Considered**:
  - Keep 15kt wind / 1.5m wave: overly restrictive, excessive false-positive advisories.
  - Wind Safe at 20kt vs 22kt: user elected 22.0kt to match Beaufort Force 6 and IMD 45 kmph limit.
  - Current bands at 1.5/2.5kt vs 2.0/3.0kt: user elected 2.0/3.0kt to match INCOIS operational notices.
- **Invariants**:
  - Code Trumps LLM, Fail-Open Caution on missing data, Single canonical module.
