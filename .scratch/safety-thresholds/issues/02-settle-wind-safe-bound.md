# Settle Wind SAFE Upper Bound (20 kt vs 22 kt)

Type: grilling
Status: closed
Blocked by: 

## Resolution
Selected **Option B**: Codify `WIND_SAFE_MAX_KT = 22.0` (40.74 kmph), aligning with Beaufort Force 6 onset and IMD's 45 kmph "No Warning" limit to maximize the fishable window for small artisanal craft. Caution band will be 22.0–27.0 kt.

## Question

Should the upper boundary for `SAFE` wind speed be codified at `20.0 kt` (37.0 kmph) or `22.0 kt` (40.7 kmph)?

### Background & Trade-offs
- **Current ORCA threshold**: `15.0 kt` (27.8 kmph) — overly restrictive, triggers Caution during mild/moderate breeze.
- **Option A (Recommended: 20.0 kt / 37.0 kmph)**:
  - Aligns with NOAA Small Craft Advisory lower threshold (20 kt).
  - Keeps a 3–5 kt safety margin before IMD's 40–45 kmph "squally weather" threshold.
  - Accounts for sudden coastal gusting (Kerala pre-monsoon squalls / *Kondalkattu*).
- **Option B (22.0 kt / 40.7 kmph)**:
  - Exact onset of Beaufort Force 6 ("Strong Breeze").
  - Closer to IMD's 45 kmph "No Warning" limit.
  - Less safety margin for small artisanal craft.

### Outcome Needed
Select Option A (20.0 kt) or Option B (22.0 kt) to feed directly into Ticket 04 implementation.
