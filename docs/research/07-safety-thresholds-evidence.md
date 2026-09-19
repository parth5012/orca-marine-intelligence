# Research Report: Safe-sailing thresholds for ORCA safety filter (Issue: safety-thresholds revision)

**Session:** `.tmp/sessions/2026-09-19-safety-thresholds/context.md`
**Target Architecture:** `backend/agents/safety_thresholds.py` (canonical) + `tests/test_safety_thresholds.py` parity consumers (`combiner.py`, `lexical_mask.py`, `orchestrator.py`, `sea_checker.py`, `weather_agent.py`, `live_fetchers.py`, `routers/officer.py`)
**Target Domain:** Kerala / Indian-coast small-scale fishermen, 6–12 m motorised craft (FAO Cat-C equivalent)
**Owners:** M-A (Agents & Orchestration)
**Wayfinder map (handover):** `.scratch/safety-thresholds/map.md`
**Status:** evidence-complete, thresholds proposed — implementation OUT OF SCOPE (see map)

---

## 1. PPT-ready summary (copy-paste)

### Slide A — Proposed bands (IMD/INCOIS-aligned)

| Metric | SAFE (go) | CAUTION (go with care) | DANGER (do not venture) | Govt anchor |
| :--- | :--- | :--- | :--- | :--- |
| Wind (sustained) | <20 kt (<37 kmph) | 20–27 kt (37–50 kmph) | >27 kt (>50 kmph) | IMD Warning 50 kmph = do-not-venture |
| Wave (significant height) | <2.0 m | 2.0–3.5 m | >3.5 m | INCOIS wind-wave Warning >3.5 m; FAO Cat-C ≤2.0 m |
| Current (surface) | <2.0 kt (<1.03 m/s) | 2.0–3.0 kt (1.03–1.54 m/s) | >3.0 kt (>1.54 m/s) | INCOIS current alerts 0.9–1.9 m/s = careful |
| Pressure / cyclone | — | <1005 hPa watch | <995 hPa or cyclone ≤500 km → DANGER | keep current ORCA values (no govt change found) |
| Missing data | — | missing wave/wind → CAUTION (never SAFE) | measured breach + other missing → DANGER | fail-open invariant, unchanged |

Conversions (show on slide footer): `1 kt = 1.852 kmph`, `1 m/s = 1.944 kt`, hence `45 kmph = 24.3 kt`, `50 kmph = 27.0 kt`, `63 kmph = 34.0 kt`, `1.0 m/s = 1.94 kt`, `1.5 m/s = 2.92 kt`.

### Slide B — Why change? (current ORCA vs govt)

| Metric | ORCA today | Govt / research | Gap |
| :--- | :--- | :--- | :--- |
| wind SAFE | 15 kt (27.8 kmph) | IMD no-warning below 45 kmph (24.3 kt); FAO Cat-C to 23.3 kt; NOAA small-craft from 20 kt | ~9 kt too strict → fishable Beaufort-4/5 days flagged CAUTION |
| wind DANGER | 25 kt (46.3 kmph) | IMD do-not-venture 50 kmph (27 kt); LC-III markedly-squally 30 kt | fires at Alert level, 2 kt early |
| wave SAFE | 1.5 m | FAO Cat-C 2.0 m; Douglas Moderate to 2.5 m | 0.5 m too strict |
| wave DANGER | 2.5 m | INCOIS swell Warning >3.0 m; wind-wave Warning >3.5 m | 0.5–1.0 m too strict |
| current 1.5/2.5 kt | 0.77 / 1.29 m/s | INCOIS alerts from 0.9 m/s (1.75 kt) to 1.9 m/s (3.7 kt) | roughly aligned — relax only slightly |

---

## 2. Per-metric evidence (reason for each number)

### 2.1 Wind — SAFE <20 kt, DANGER >27 kt

- **IMD CAP SOP (Sankar Nath, IMD):** fishermen table = No warning wind <45 kmph; Alert 45–50 kmph; Warning 50 kmph sea rough; Warning 63 kmph rough to very rough.
  Link: `https://cap-workshop.s3.amazonaws.com/2021/presentations/india-1.pdf`
- **IMD daily warnings (operational proof "do not venture" = 40–50 kmph):** Kerala/Karnataka/Lakshadweep 25–28 May 2026, AP 07–10 Jun 2026, TN Sep 2026, Maharashtra-Goa Sep 2026 — all phrase "Squally 40–50 kmph gusting 60 kmph → fishermen advised not to venture".
  Links: `https://mausam.imd.gov.in/` bulletins (`FW07060029.pdf`, Thiruvananthapuram `fishermen warning.pdf`, Mumbai `fisherman.pdf`, Chennai `fishermen.pdf`).
- **IMD port LC-III (RSMC):** squally = mean ≥20 kt; markedly-squally ≥30 kt; inner-storm >33 kt.
  Link: `https://rsmcnewdelhi.imd.gov.in/images/pdf/port-warning.pdf`
- **Why SAFE 20 kt not verbatim 24.3 kt:** 45 kmph covers all vessels incl. large ships. 20 kt (37 kmph) keeps a ~4 kt gust buffer, matches NOAA small-craft lower bound (20 kt) and Beaufort-5 onset (17–21 kt), and still recovers ~5 kt of fishable days vs today. DANGER 27 kt is verbatim IMD Warning (50 kmph).
  Wind open point (see map ticket 02): 20 vs 22 kt SAFE — 22 = Beaufort-6 onset, less conservative. Recommendation stays 20 kt for PS safety margin.

### 2.2 Wave — SAFE <2.0 m, DANGER >3.5 m (user-locked)

- **INCOIS–IMD joint bulletin thresholds (Balakrishnan, Tropmet ERPA):** wind-wave Alert 3.0–3.5 m / Warning >3.5 m; swell Alert 2.5–3.0 m / Warning >3.0 m; swell period >18 s; surge >0.5 m.
  Link: `https://www.tropmet.res.in/erpas/s2s/presentation/Balakrishnan.pdf`
- **FAO/ILO/IMO Safety Recommendations `i3108e` §1.2.14 (design categories):** Cat-C (the 6–12 m decked craft that matches Kerala's motorised fleet) = seas up to 2.0 m + Beaufort 6 (12 m/s = 23.3 kt); Cat-D (inland/tiny) = 0.3 m (occ 0.5 m) + Beaufort 4 (7 m/s = 13.6 kt); Cat-B = 4 m + Beaufort 8.
  Link: `https://www.fao.org/4/i3108e/i3108e.pdf`
- **Douglas Sea Scale (calibration):** Slight 0.5–1.25 m, Moderate 1.25–2.5 m, Rough 2.5–4.0 m. Beaufort F4 11–16 kt / 1–1.5 m, F5 17–21 kt / 2–2.5 m, F6 22–27 kt / 3–4 m.
  Link: `https://www.dragdevicedb.com/appendix-viii-beaufort-wind-and-douglas-sea-scales` and `https://www.weather.gov/pqr/beaufort`
- **Why 2.0 / 3.5:** SAFE 2.0 = FAO Cat-C vessel limit (going to 2.5 SAFE would exceed what the boats are built for). CAUTION 2.0–3.5 absorbs the whole INCOIS alert zone. DANGER 3.5 = INCOIS wind-wave Warning (user chose 3.5 over 3.0 swell-warning — stricter swell events 3.0–3.5 read CAUTION, acceptable because swell period/steepness handled in SVAS follow-up).

### 2.3 Current — SAFE <2.0 kt, DANGER >3.0 kt

- **INCOIS Ocean Current Alerts (inside IMD fishermen PDFs, Sep 2026):** AP/TN ranges 0.9–1.9 m/s all phrased "Harbour & marine operations to be careful" — e.g. East Godavari 1.4–1.6, Nellore 1.6–1.9, Guntur 0.9–1.5, Chennai 1.2–1.6 m/s.
  Links: `https://mausam.imd.gov.in/visakhapatnam/mcdata/Fisherman_warning.pdf`, `https://mausam.imd.gov.in/thiruvananthapuram/mcdata/fishermen%20warning.pdf`
- **Math:** 0.9 m/s = 1.75 kt, 1.0 = 1.94, 1.5 = 2.92, 1.9 = 3.69 kt. ORCA today (1.5/2.5 kt = 0.77/1.29 m/s) fires at the *low* end of INCOIS caution — already govt-close. Proposed 2.0/3.0 kt (1.03/1.54 m/s) centres on the INCOIS alert band instead of its floor.
  Open point (map ticket 03): keep 1.5/2.5 vs move 2.0/3.0. Recommendation: move, with CRO-style before/after day-count on 2023–24 OSF reanalysis.

### 2.4 Boat-size future (SVAS — not in this change, but PPT roadmap slide)

- **INCOIS SVAS overview:** Boat Safety Index from height + steepness + directional spread + rapid wind-sea development; beam bands <4 m / 6 m / 7 m; 10-day overturning zones; 9 coastal states.
  Link: `https://incois.gov.in/site/services/SVA_overview.jsp`
- **Aditya et al. 2020 (peer-reviewed):** *Development of small vessel advisory and forecast services system*, J. Operational Oceanography — BSI decision mechanism + SOP, verified on past capsizes, thresholds refined on user feedback, boats classified by beam.
  DOI: `https://doi.org/10.1080/1755876x.2020.1846267`
- **Kerala beam context (SVAS press):** popular beams 2.1–6.5 m (Goa example: trawls 5–6 m, gillnetters 4.5–5 m, others 2.5–3 m).
  Link: `https://indiaseatradenews.com/incois-launches-small-vessel-advisory-and-forecast-services/`
- PPT line: "Phase 2: beam-tiered bands (SVAS-style) — <4 m stricter, 6–7 m relaxed — needs vessel survey first."

### 2.5 Supporting (small-craft cross-check, surf, OSF)

- **NOAA small-craft advisory:** 20–33 kt (region-tuned 20/21/22/25 lower bounds), seas 4–10 ft (1.2–3 m). Confirms 20 kt SAFE floor is international norm.
  Link: `https://marinenavigation.noaa.gov/weather-warnings.html`
- **FAO BOBP surf reports (`ad947e`, `BOBP/MAG/16`, `BOBP/REP/112`):** surf-crossing needs decked/self-draining/high beam-to-length — why missing-data → CAUTION and surf-zone advice stay strict even as open-sea bands relax.
  Links: `https://www.fao.org/4/ad947e/ad947e00.pdf`, `https://openknowledge.fao.org/handle/20.500.14283/ak191e`
- **INCOIS OSF + RSMC designation:** 3-hourly 5–10-day forecasts (waves/winds/currents/SST), WMO EC-76 RSMC for wave prediction.
  Link: `https://incois.gov.in/site/services/osf.jsp`

---

## 3. Glossary (for PPT appendix + ADR)

- **SAFE / CAUTION / DANGER:** ORCA deterministic tiers from `derive_safety_tier()` — Code Trumps LLM, fail-open CAUTION on missing wave/wind, never SAFE.
- **BSI (Boat Safety Index):** INCOIS capsizing-risk index (height, steepness, spread, wind-sea growth), beam-specific.
- **Beaufort Force:** wind-effect scale (F4 11–16 kt, F5 17–21 kt, F6 22–27 kt). **Douglas Sea State:** wave-height scale (Slight ≤1.25 m, Moderate ≤2.5 m, Rough ≤4 m).
- **kt / kmph / m/s:** `kt × 1.852 = kmph`; `m/s × 1.944 = kt`.
- **LC-III:** IMD port signal for squally weather (≥20 kt, markedly ≥30 kt). **PFZ / OSF / SVAS:** INCOIS fishing-zone / ocean-state / small-vessel advisories.

---

## 4. What is NOT decided here (hand to map)

- Wind SAFE 20 vs 22 kt (ticket 02). Current 1.5/2.5 vs 2.0/3.0 (ticket 03). Pressure/cyclone keep vs revisit (ticket 04). Beam-tiering survey (fog, not ticketed). Code + tests are implementing-agent work (tickets 05–07).
