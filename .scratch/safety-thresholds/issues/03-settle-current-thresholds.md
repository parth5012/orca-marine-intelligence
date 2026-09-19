# Settle Surface Current Bands (2.0/3.0 kt vs keep 1.5/2.5 kt)

Type: grilling
Status: closed
Blocked by: 

## Resolution
Selected **Option A**: Relax surface current thresholds to `CURRENT_SAFE_MAX_KT = 2.0` (1.03 m/s) and `CURRENT_DANGER_MIN_KT = 3.0` (1.54 m/s). Caution band will be 2.0–3.0 kt. This aligns with INCOIS current alerts (0.9–1.9 m/s) and prevents premature Caution states in coastal tidal currents.

## Question

Should surface current bands be relaxed to `Safe < 2.0 kt / Danger > 3.0 kt` or kept at `Safe < 1.5 kt / Danger > 2.5 kt`?

### Background & Trade-offs
- **Current ORCA bands**: Safe < 1.5 kt (0.77 m/s), Caution 1.5–2.5 kt, Danger > 2.5 kt (1.29 m/s).
- **Govt / INCOIS Observation**:
  - INCOIS daily Ocean Current Alerts trigger around 0.9 m/s to 1.9 m/s (1.75 kt to 3.7 kt) advising "Harbour & marine operations to be careful" (cautionary, not ban).
- **Option A (Relax to 2.0 kt / 3.0 kt)**:
  - 2.0 kt = 1.03 m/s (sits neatly inside INCOIS cautious alert zone).
  - 3.0 kt = 1.54 m/s (high alert level for small craft drift).
  - Prevents premature Caution states in coastal regions with tidal rip currents.
- **Option B (Keep 1.5 kt / 2.5 kt)**:
  - Conservative; current 1.5/2.5 kt is already the closest existing parameter to govt practice.
  - Less impact on existing navigation safety evaluations.

### Outcome Needed
Select Option A or Option B to resolve constant definition for Ticket 04.
