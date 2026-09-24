# Architectural & Design Decisions

### 2026-09-24: ADR-0006 Force-Include Badge Tools with Fish Recommendations

**Context**:
Kollam/QuilonPort chat showed "wave data unavailable, wind data unavailable" and SEA ADVISORY rendered `Waves --m, winds -- kts`. Root cause: LLM planner fish-only plan (`selected_tools=["find_fishing_zones","check_geofence"]`) skipped `check_ocean_state`/`check_weather`. `route_after_fish_finder` only Sends to selected tools, so sea/weather never ran → combiner best had `wave/wind=None`. Planner prompt already says ocean/weather run "when fish zones need a safety badge", but the UI always shows that badge for zone recommendations.

**Decision**:
In `planner_node` (after intent guards, before empty-selection fallback): if `TOOL_FIND_FISH in selected_tools` and ocean and/or weather are missing, force-append them with an auditable `reasoning_trace` note (`planner note: force-selected ... — fish zones always show a safety badge`).

**Alternatives Considered**:
- Keep latency skip + fix frontend messaging ("not checked" instead of `--`): rejected — prompt already mandates badge tools; fishers need real wave/wind for the advisory they always see.
- Force-include only when `intent["wants_fish"]`: fish selection alone is the signal; safety-only plans already include ocean/weather without fish.
- Change `route_after_fish_finder` to always Send sea/weather: weaker — would bypass `selected_tools` contract and break selective-dispatch tests.

**Invariants**:
- Force-include only when `selected_tools is not None` (legacy `None` = run-all, already includes badge tools).
- Clarification gate still short-circuits before force-include can cause dispatch (`needs_clarification` clears tools earlier in validate).
- Auditable: every force-include appends a reasoning_trace line; no silent tool mutation.

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

## 2026-09-21: ADR-0004 Officer Mobile Navigation & Responsive Parity (#216, #222)
- **Decision**: Reuse the `BottomNavigation` architectural pattern by implementing `OfficerBottomNav` as a bottom-docked navigation bar on mobile (`md:hidden fixed bottom-0`), instead of collapsing the sticky top bar into hamburger or multi-tiered dropdowns.
- **Alternatives Considered**:
  - Collapse TopBar into hamburger drawer or dropdown on mobile: rejected because TopBar already hosts brand, state/port selectors, role switcher, GPS, theme toggle, and status badges. Cramming section anchors into the top bar causes vertical viewport crowding on mobile screens and violates ergonomic thumb-reach navigation on handheld devices.
  - No mobile navigation (reliance on document scrolling): rejected because the 7-card dashboard is long on mobile viewports; officers need instant 1-tap jumps between Decision, Register, Alerts, and Fisherman Home.
- **Invariants**:
  - Motion transitions respect `prefers-reduced-motion` across all components (scroll behavior and Framer Motion spring/fade durations collapse to immediate).
  - Zero modifications to fisherman routes, layouts, or `frontend/app/page.tsx`.

### 2026-09-23: ADR-0005 PostGIS PFZ Date Filtering Loosening & Government INCOIS Feed Migration Strategy

**Context**:
When deployed in cloud environments (Render, AWS, Supabase), ORCA backend containers operate in UTC (date.today() is UTC). INCOIS (Indian National Centre for Ocean Information Services) generates PFZ advisories daily based on Indian Standard Time (IST, UTC+05:30), typically releasing advisories around 11:30 IST (~06:00 UTC).
Previously, find_pfz_near in backend/db/postgis.py used a strict equality filter:
.where(PFZZone.valid_date == date.today())
This caused critical failures in production:
1. **Timezone Rollover**: Between 00:00 IST and 05:30 IST (18:30-23:59 UTC previous day), server UTC date is day D-1 while INCOIS data was dated D.
2. **Pre-Ingestion Window**: Every morning between 00:00 UTC and 06:00 UTC, today's INCOIS advisory has not yet been published by INCOIS. Strict filtering returned 0 zones.
3. **Empty/Fresh Deployments**: On fresh deployment before the first daily cron executes, valid_date == today returned empty arrays without raising an exception, causing fish_finder.py to exhaust search radii and report 'No fishing zones found' instead of falling back to bundled data.

**Decision**:
1. **Loosen Spatial Query Date Filtering in find_pfz_near**:
   - Primary: Query for valid_date == valid_date (defaults to date.today()).
   - Resilient Fallback: If 0 rows return, query for MAX(valid_date) within the spatial radius. If recent zones exist (e.g. yesterday's advisory), return them.
2. **Auto-Seed on Startup**:
   - init_db() invokes seed_initial_pfz_if_empty() to populate PostGIS from data/pfz-today.geojson with today's date if pfz_zones is empty.
3. **Agent-Level Safety Fallback**:
   - fish_finder.find_fishing_zones falls back to _geojson_fallback_staged whenever PostGIS returns 0 zones across all expansion radii (80/120/160 km), not just on connection errors.

**Future Government Live Data Protocol (INCOIS / MoES / ISRO)**:
When official government feeds (INCOIS TextData Webhook, ISRO OCM-3/Oceansat satellite thermal fronts, or MoES Marine API) become active:
1. **Advisory Lifecycle & Staleness Bound**:
   - INCOIS PFZ maps remain biologically and oceanographically valid for 24 to 48 hours. However, during monsoon fishing bans (April-May East Coast, June-July West Coast) or adverse weather/cyclone warnings, INCOIS does not publish new PFZ advisories.
   - **Staleness SLA Guard**: Once real-time feeds run in production, constrain the fallback to a bounded window (e.g., maximum 48 hours):
     if latest_date and (valid_date - latest_date).days <= 2:
   - If latest data is older than 48 hours, return stale_warning: true or state clearly: 'INCOIS advisory from [date] - satellite update pending due to cloud cover / fishing ban'.
2. **Data Provenance Metadata**:
   - Keep valid_date and source in all returned zone objects so the frontend and LLM explicitly state the advisory date (e.g., 'Advisory valid for: 23-Sep-2026').
3. **Re-tightening Criteria**:
   - Do NOT revert to strict single-day equality (valid_date == date.today()) because INCOIS publication frequency is subject to cloud cover and satellite overpass schedules. Instead, rely on bounded validity windows (valid_date >= today - 2 days) with explicit provenance badges.
