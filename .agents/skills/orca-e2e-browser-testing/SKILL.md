---
name: orca-e2e-browser-testing
description: >-
  Use when testing the ORCA Marine Intelligence website end-to-end using browser
  automation. Covers all pages (Home, Map), all UI components (Chat, Map layers,
  Language switcher, Safety badge, GPS, Voice input), all API endpoints, responsive
  layouts, accessibility, error/edge cases, and cross-browser scenarios. Invoke
  this skill periodically for regression testing or before any release.
---

# ORCA Marine Intelligence — End-to-End Browser Testing Skill

## Overview

This skill provides a **comprehensive, agent-executable** E2E test plan for the
ORCA Marine Intelligence web application. It uses Antigravity's `/browser`
command to interactively test every page, component, API integration, and edge
case through real browser automation.

**When to invoke**: Before releases, after major merges, periodic regression
checks, or when any M-A through M-E lane lands a significant change.

---

## Prerequisites — Environment Checklist

Before running tests, verify these services are live:

```powershell
# 1. Backend (FastAPI on port 8000)
curl http://localhost:8000/docs          # Should return Swagger UI HTML

# 2. Frontend (Next.js on port 3000)
curl http://localhost:3000               # Should return HTML with "ORCA"

# 3. Redis (port 7379 mapped to container 6379)
docker exec orca-redis redis-cli ping    # Should return PONG

# 4. PostGIS (port 5432)
docker exec orca-postgis pg_isready -U orca -d orca_marine
```

If services are down, start them:
```powershell
cd D:\work\projects\orca-marine-intelligence
docker compose up -d postgis redis
cd backend && uvicorn main:app --reload --port 8000
cd frontend && npm run dev
```

---

## Test Execution Protocol

### Step 1: Open the browser
Use the `/browser` command or `read_browser_page` tool to navigate to `http://localhost:3000`.

### Step 2: Run test suites in order
Execute each test suite below sequentially. For each test case:
1. **Navigate** to the target URL
2. **Interact** with the UI elements described
3. **Assert** the expected outcomes
4. **Record** pass/fail with details
5. **Screenshot** on failure for evidence

### Step 3: Generate report
After all suites complete, create a summary artifact with pass/fail counts,
failure details, and recommendations.

---

## Test Suite 1: Navigation & Routing (NAV)

Tests page transitions, link integrity, and URL state management.

| ID | Test Case | Steps | Expected Result |
|----|-----------|-------|-----------------|
| NAV-01 | Home page loads | Navigate to `http://localhost:3000/` | Page renders with ORCA branding, chat panel, map view. Title contains "ORCA". |
| NAV-02 | Map page loads | Navigate to `http://localhost:3000/map` | Full-screen map with layer toggles, sector dropdown, search bar, inspector drawer. |
| NAV-03 | Home → Map navigation | On `/`, click the "🗺️ Ocean Map" link (`[data-testid="nav-map-link"]`) | URL changes to `/map`. Map page renders with sector dropdown. |
| NAV-04 | Map → Home navigation | On `/map`, click "💬 Back to Chat" (`[data-testid="nav-chat-link"]`) | URL changes to `/`. Chat panel visible. |
| NAV-05 | Map logo → Home | On `/map`, click the 🌊 logo icon (`[data-testid="nav-home-link"]`) | URL changes to `/`. |
| NAV-06 | Home brand link | On `/`, click ORCA brand (`[data-testid="nav-brand-link"]`) | Stays on `/`, no navigation error. |
| NAV-07 | Direct URL - 404 | Navigate to `http://localhost:3000/nonexistent` | Next.js 404 page renders (not a blank crash). |
| NAV-08 | Browser back/forward | Navigate `/` → `/map` → browser back | Returns to `/` with chat panel intact. |

---

## Test Suite 2: Chat Advisory Panel (CHAT)

Tests the ChatPanel component, SSE streaming, input validation, and quick actions.

| ID | Test Case | Steps | Expected Result |
|----|-----------|-------|-----------------|
| CHAT-01 | Chat panel renders | On `/`, verify `[data-testid="chat-panel-container"]` is visible | Chat panel with input field and send button visible. |
| CHAT-02 | Empty input blocked | Clear the chat input, attempt to submit | Send button is disabled. No request fires. |
| CHAT-03 | Whitespace-only blocked | Type only spaces into chat input | Send button remains disabled. |
| CHAT-04 | Valid input enables send | Type "Where are fishing zones near Kochi?" | Send button becomes enabled. |
| CHAT-05 | Quick action chip | Click "🐟 Fish near Kochi" quick action chip | Input field populates with the chip's query text. |
| CHAT-06 | Send message (SSE stream) | Type a query and click Send | Loading/streaming indicator appears. Assistant response streams in via SSE. Response bubble renders with marine advisory text. |
| CHAT-07 | Subagent reasoning accordion | After a streamed response, look for reasoning accordion | Collapsible sections for Planner, FishFinder, WeatherAgent, DangerAgent, DecisionAgent visible. Clicking expands to show reasoning trace. |
| CHAT-08 | Marine zone card rendering | Ask "Find PFZ near Munambam" | Response includes structured zone card(s) with bearing, distance, depth, SST, safety status. |
| CHAT-09 | "Show on Map" from zone card | Click "Show on Map" button on a marine zone card | Map panel highlights the zone. On mobile, auto-switches to map tab. |
| CHAT-10 | Danger banner display | Ask "Is it safe to sail in a cyclone?" | If danger detected, red "DO NOT SAIL" or yellow "CAUTION" banner appears above chat. |
| CHAT-11 | Multi-turn conversation | Send 3 sequential messages | All messages and responses appear in correct chronological order. Scroll auto-follows. |
| CHAT-12 | Stop stream button | While SSE is streaming, click the stop button | Streaming stops. Partial response is preserved. |
| CHAT-13 | Very long input (2000+ chars) | Paste a 2000-character string and submit | No crash. Input is accepted or gracefully truncated. Backend handles without 413. |
| CHAT-14 | Special characters in input | Type `<script>alert('xss')</script> & "quotes" 'apostrophe'` | Input is sanitized. No XSS. Response renders safely. |
| CHAT-15 | Unicode/emoji input | Type `मछली कहाँ है? 🐟🌊` | Query is accepted. Response may come in Hindi or English. No encoding crash. |

---

## Test Suite 3: Voice Input (VOICE)

Tests the vernacular voice recording and transcription flow.

| ID | Test Case | Steps | Expected Result |
|----|-----------|-------|-----------------|
| VOICE-01 | Mic button visible | On `/`, check for voice/mic button in chat panel | Microphone button is present and clickable. |
| VOICE-02 | Recording state | Click mic button | Recording indicator appears (timer counting up, red dot). |
| VOICE-03 | Stop recording | Click mic button again to stop | Recording stops. "Transcribing..." indicator appears briefly. |
| VOICE-04 | Permission denied | (If possible) Deny mic permission | Graceful error message, no crash. Voice error state shown. |

---

## Test Suite 4: Language Switcher (LANG)

Tests the LanguageSwitch component and localStorage persistence.

| ID | Test Case | Steps | Expected Result |
|----|-----------|-------|-----------------|
| LANG-01 | Switcher renders | On `/`, find language selector in header | Language button visible with current language indicator. |
| LANG-02 | Open dropdown | Click language selector button (`#language-selector-button`) | Dropdown opens showing all 10 languages (EN, ML, TA, HI, TE, GU, BN, KN, MR, OR) with native scripts. |
| LANG-03 | Switch to Malayalam | Click "മലയാളം (Malayalam)" option (`#language-option-ml`) | UI updates. `localStorage.getItem('orca_language')` returns `'ml'`. |
| LANG-04 | Chat placeholder localizes | After switching to ML | Chat input placeholder text changes to Malayalam text. |
| LANG-05 | Switch to Tamil | Click "தமிழ் (Tamil)" | localStorage updates to `'ta'`. |
| LANG-06 | Switch to Hindi | Click "हिन्दी (Hindi)" | localStorage updates to `'hi'`. |
| LANG-07 | Persist across reload | Set language to ML, hard-refresh page | After reload, language is still ML (read from localStorage). |
| LANG-08 | Switch back to English | Click "English" | UI reverts to English. localStorage updates to `'en'`. |
| LANG-09 | Click outside closes | Open dropdown, click elsewhere on page | Dropdown closes without changing language. |

---

## Test Suite 5: Map Visualization (MAP)

Tests the MapView component, Leaflet rendering, and spatial features.

| ID | Test Case | Steps | Expected Result |
|----|-----------|-------|-----------------|
| MAP-01 | Map renders on home | On `/`, verify `[data-testid="map-view-container"]` | Map canvas renders (Leaflet tiles loading). |
| MAP-02 | Map renders on /map | Navigate to `/map` | Full-screen map with all controls visible. |
| MAP-03 | Default center (Kochi) | Check map center coordinates | Map centered near [9.93, 76.27] (Kochi coast). Status bar shows coordinates. |
| MAP-04 | GPS recenter button | Click "📍 Recenter GPS" / "📍 GPS Recenter" button | Map recenters to user location (or Kochi default). |
| MAP-05 | Spatial view status bar | On `/`, check map overlay status | Shows "Spatial View: [lat, lon]" with current coordinates. |
| MAP-06 | Active zones counter | If PFZ zones are loaded | "N Active Zone(s)" badge appears in status overlay. |
| MAP-07 | Zone click → inspector | On `/map`, click a PFZ marker on map | Inspector drawer opens with zone details (sector, bearing, distance, depth, DMS coords). |
| MAP-08 | "Consult Advisory in Chat" | In zone inspector, click the advisory link | Navigates to `/?zone=<name>` — chat page with zone context. |

---

## Test Suite 6: Map Layers & Controls (LAYER)

Tests the 5 layer toggle buttons and their aria-pressed states.

| ID | Test Case | Steps | Expected Result |
|----|-----------|-------|-----------------|
| LAYER-01 | PFZ toggle | Click `[data-testid="layer-toggle-pfz"]` | `aria-pressed` toggles. Button style changes (green active ↔ grey inactive). |
| LAYER-02 | EEZ toggle | Click `[data-testid="layer-toggle-eez"]` | `aria-pressed` toggles. Button style changes (blue active ↔ grey). |
| LAYER-03 | MPA toggle | Click `[data-testid="layer-toggle-mpa"]` | `aria-pressed` toggles. Button style changes (red active ↔ grey). |
| LAYER-04 | IMBL toggle | Click `[data-testid="layer-toggle-imbl"]` | `aria-pressed` toggles. Button style changes (orange active ↔ grey). |
| LAYER-05 | Weather toggle | Click `[data-testid="layer-toggle-weather"]` | `aria-pressed` toggles. Button style changes (cyan active ↔ grey). |
| LAYER-06 | All layers default ON | On fresh `/map` load | All 5 layer buttons have `aria-pressed="true"`. |
| LAYER-07 | Toggle all OFF then ON | Click all 5 toggles to OFF, then back to ON | Each toggle flips independently. No crashes. |
| LAYER-08 | Inspector drawer toggle | Click `[data-testid="inspector-drawer-toggle"]` | Drawer opens/closes. `aria-expanded` toggles. |
| LAYER-09 | Inspector drawer close | Click `[data-testid="inspector-drawer-close"]` | Drawer closes. |

---

## Test Suite 7: Sector Selection (SECTOR)

Tests the coastal sector dropdown and viewport centering.

| ID | Test Case | Steps | Expected Result |
|----|-----------|-------|-----------------|
| SECTOR-01 | Dropdown renders | On `/map`, find `[data-testid="sector-select-dropdown"]` | Select element with 10 sector options visible. |
| SECTOR-02 | Select Kerala | Change dropdown to "Kerala (SEC005)" | Map centers to [9.93, 76.27], zoom ~9. |
| SECTOR-03 | Select Gujarat | Change to "Gujarat (SEC001)" | Map centers to [21.0, 70.0], zoom ~8. |
| SECTOR-04 | Select Maharashtra | Change to "Maharashtra (SEC002)" | Map centers to [18.92, 72.83]. |
| SECTOR-05 | Select Tamil Nadu | Change to "Tamil Nadu (SEC007)" | Map centers to [11.5, 79.8]. |
| SECTOR-06 | Select All India | Change back to "All India Coastal Sectors" | Map centers to [13.0, 78.0], zoom ~6. Wide view. |
| SECTOR-07 | All 10 sectors present | Inspect dropdown options | All sectors: ALL, KERALA, MAHARASHTRA, TAMIL NADU, GUJARAT, KARNATAKA, GOA, ANDHRA PRADESH, ODISHA, WEST BENGAL. |

---

## Test Suite 8: Coordinate Search (SEARCH)

Tests the search form on the `/map` page.

| ID | Test Case | Steps | Expected Result |
|----|-----------|-------|-----------------|
| SEARCH-01 | Search form renders | On `/map`, find `[data-testid="coord-search-form"]` | Input field and "Go" button visible. |
| SEARCH-02 | Valid coordinates | Enter `9.93, 76.27` and click Go | Map centers to Kochi. No error banner. |
| SEARCH-03 | Port name search | Enter `Kochi` and click Go | Map centers to Kochi coordinates (parsed by `parseLocation`). |
| SEARCH-04 | Port name - Veraval | Enter `Veraval` and click Go | Map centers to Veraval. |
| SEARCH-05 | Invalid text | Enter `xyzabc123` and click Go | Error banner appears: "Location not recognized..." (`[data-testid="coord-search-error"]`). |
| SEARCH-06 | Out-of-bounds coords | Enter `999.0, 999.0` and click Go | Error banner appears OR coordinates are clamped. No crash. |
| SEARCH-07 | Swapped lat/lon defense | Enter `76.27, 9.93` (lon, lat order) | System detects swap (Indian waters heuristic) and corrects. Map centers near Kochi, not in Arctic. |
| SEARCH-08 | Empty search | Click Go with empty input | Nothing happens. No error, no navigation. |
| SEARCH-09 | Dismiss error | After SEARCH-05 error, click ✕ dismiss (`[data-testid="coord-search-error-dismiss"]`) | Error banner disappears. |
| SEARCH-10 | DMS format | Enter `9°55'52"N, 76°16'12"E` | If `parseLocation` supports DMS, map centers correctly. Otherwise, shows error gracefully. |

---

## Test Suite 9: Safety Badge & Telemetry (SAFETY)

Tests the SafetyBadge component and weather telemetry display.

| ID | Test Case | Steps | Expected Result |
|----|-----------|-------|-----------------|
| SAFETY-01 | Badge visible on home | On `/`, check header for safety badge | Safety badge shows status text (SAFE/CAUTION/DANGER) with color coding. |
| SAFETY-02 | Badge on map page | On `/map`, check inspector drawer | Safety badge in drawer with wave height and wind speed telemetry. |
| SAFETY-03 | Wave height display | Check inspector drawer telemetry grid | Shows wave height value in meters (e.g., "0.8 m") with status label. |
| SAFETY-04 | Wind speed display | Check inspector drawer telemetry grid | Shows wind speed in knots (e.g., "12 kts") with status label. |
| SAFETY-05 | Geofence status | Check "Maritime Legal Boundaries" section in drawer | Shows EEZ status, MPA distance, IMBL clearance with color indicators. |
| SAFETY-06 | Badge language support | Switch language to ML, check safety badge | Badge text should update to localized version if `language` prop is passed. |

---

## Test Suite 10: Responsive & Mobile Layout (MOBILE)

Tests responsive breakpoints and mobile-specific UI.

| ID | Test Case | Steps | Expected Result |
|----|-----------|-------|-----------------|
| MOBILE-01 | Mobile tab bar visible | Set viewport to 375×812 (iPhone), load `/` | Mobile tab switcher appears with "💬 Chat Advisory" and "🗺️ Ocean Map" tabs. |
| MOBILE-02 | Chat tab active | Click `[data-testid="mobile-tab-chat"]` | Chat panel visible. Map panel hidden. `aria-selected="true"` on chat tab. |
| MOBILE-03 | Map tab active | Click `[data-testid="mobile-tab-map"]` | Map panel visible. Chat panel hidden. `aria-selected="true"` on map tab. |
| MOBILE-04 | Auto-switch on highlight | In chat, trigger a zone highlight (Show on Map) | On mobile viewport, automatically switches to map tab. |
| MOBILE-05 | Desktop: side-by-side | Set viewport to 1440×900, load `/` | Chat and Map panels render side-by-side. No mobile tabs visible. |
| MOBILE-06 | Ocean Map link hidden mobile | On mobile viewport | "🗺️ Ocean Map" header link is hidden (`hidden sm:inline-flex`). |
| MOBILE-07 | GPS badge hidden mobile | On mobile viewport | GPS telemetry badge is hidden (`hidden md:flex`). |
| MOBILE-08 | Map search hidden mobile | On `/map` with mobile viewport | Search form and sector dropdown hidden on small screens (`hidden lg:flex`). |

---

## Test Suite 11: API Integration (API)

Tests backend API endpoints directly via browser fetch or by verifying UI behavior that depends on them.

| ID | Test Case | Steps | Expected Result |
|----|-----------|-------|-----------------|
| API-01 | GET /api/pfz/today | Execute `fetch('http://localhost:8000/api/pfz/today')` in console | Returns JSON with `type: "FeatureCollection"`, `features` array, `metadata`. |
| API-02 | PFZ with sector filter | `fetch('http://localhost:8000/api/pfz/today?sector=KERALA')` | Returns only Kerala sector features. |
| API-03 | PFZ with bbox filter | `fetch('http://localhost:8000/api/pfz/today?bbox=75,9,77,11')` | Returns features within bounding box. |
| API-04 | PFZ invalid bbox | `fetch('http://localhost:8000/api/pfz/today?bbox=invalid')` | Returns 400 with error detail. |
| API-05 | GET /api/geofence/status | `fetch('http://localhost:8000/api/geofence/status')` | Returns JSON with `status: "ok"`, `active_mpas`, `eez_zones`, boundary counts. |
| API-06 | GET /api/weather/current | `fetch('http://localhost:8000/api/weather/current?lat=9.93&lon=76.27')` | Returns weather data (temperature, wind, waves, pressure). |
| API-07 | GET /api/weather/cyclone | `fetch('http://localhost:8000/api/weather/cyclone')` | Returns cyclone alert data (may be empty array if no active cyclones). |
| API-08 | POST /api/chat | POST with `{"message":"test","lat":9.93,"lon":76.27}` | Returns SSE stream with `event: token` and `event: done` events. |
| API-09 | POST /api/chat empty msg | POST with `{"message":""}` | Returns error or empty response gracefully. |
| API-10 | POST /api/chat/voice (no file) | POST without audio file | Returns 422 with "Audio file required" detail. |
| API-11 | Frontend → API proxy | On `/`, verify `/api/chat` route in Next.js | Frontend API proxy (`frontend/app/api/chat/route.ts`) forwards to backend. |
| API-12 | Frontend → PFZ proxy | Verify `/api/pfz` route in Next.js | Frontend PFZ proxy (`frontend/app/api/pfz/route.ts`) returns GeoJSON. |
| API-13 | Backend health | Navigate to `http://localhost:8000/docs` | Swagger/OpenAPI docs page loads with all endpoints listed. |

---

## Test Suite 12: Error & Edge Cases (EDGE)

Tests error handling, degraded states, and unusual inputs.

| ID | Test Case | Steps | Expected Result |
|----|-----------|-------|-----------------|
| EDGE-01 | Backend down | Stop backend, load `/` | Chat shows error gracefully. Map still renders with cached/offline data. No white screen. |
| EDGE-02 | Redis down | Stop Redis, send chat query | Response still works (may be slower, no caching). Warning logged. |
| EDGE-03 | GPS denied | Block geolocation permission, load `/` | Falls back to Kochi [9.93, 76.27]. GPS status shows "default" (cyan dot, not red). |
| EDGE-04 | GPS unavailable | Load in browser without geolocation API | Falls back to Kochi default. No crash. |
| EDGE-05 | Network timeout | Throttle network to slow 3G, send chat query | Loading state visible. Eventually times out with user-friendly message. |
| EDGE-06 | Double-click send | Rapidly double-click send button | Only one request fires. No duplicate messages. |
| EDGE-07 | Concurrent tab sessions | Open `/` in two tabs, send messages in both | Each tab has independent session. No cross-contamination. |
| EDGE-08 | localStorage cleared | Clear localStorage, reload `/` | Language defaults to 'en'. No crash from missing stored values. |
| EDGE-09 | Invalid zone data | If a zone has no geometry/coordinates | Inspector shows "N/A" for missing fields. No undefined crash. |
| EDGE-10 | Extreme zoom | On map, zoom to max in / max out | Map handles gracefully. Tiles load. No infinite loop. |
| EDGE-11 | Page refresh during stream | While SSE is streaming, hard-refresh the page | Page reloads cleanly. No orphaned connections. |
| EDGE-12 | Console errors clean | Open DevTools console on all pages | No uncaught exceptions, no React hydration mismatches, no 404 resource loads. |

---

## Test Suite 13: Accessibility (A11Y)

Tests ARIA attributes, keyboard navigation, and screen reader compatibility.

| ID | Test Case | Steps | Expected Result |
|----|-----------|-------|-----------------|
| A11Y-01 | Tab navigation | Press Tab key through home page | Focus moves logically through interactive elements. Focus ring visible. |
| A11Y-02 | ARIA labels present | Inspect all buttons and links | All interactive elements have `aria-label` attributes (verified by `data-testid` elements). |
| A11Y-03 | Tab role on mobile tabs | Inspect mobile tab buttons | Have `role="tab"`, `aria-selected`, `aria-controls` attributes. |
| A11Y-04 | Tabpanel role on panels | Inspect chat and map sections | Have `role="tabpanel"`, `aria-labelledby` attributes. |
| A11Y-05 | Layer toggle aria-pressed | Inspect layer toggle buttons | All have `aria-pressed` reflecting current state. |
| A11Y-06 | Drawer aria-expanded | Inspect inspector drawer toggle | Has `aria-expanded` reflecting drawer state. |
| A11Y-07 | Search error role="alert" | Trigger coordinate search error | Error banner has `role="alert"` for screen reader announcement. |
| A11Y-08 | Color contrast | Check text against backgrounds | Cyan text (#67e8f9) on dark bg (#0f172a) meets WCAG AA ratio ≥ 4.5:1. |

---

## Test Suite 14: Performance Smoke (PERF)

Quick performance checks to catch regressions.

| ID | Test Case | Steps | Expected Result |
|----|-----------|-------|-----------------|
| PERF-01 | Home page LCP | Measure Largest Contentful Paint on `/` | LCP < 3 seconds on localhost. |
| PERF-02 | Map tile loading | On `/map`, wait for tiles | Map tiles fully loaded within 5 seconds. |
| PERF-03 | Chat response time | Send a chat query, measure first token | First SSE token arrives within 5 seconds. |
| PERF-04 | No memory leak on nav | Navigate `/` → `/map` → `/` 5 times | No significant memory growth in Performance tab. |
| PERF-05 | Bundle size check | Check Next.js build output | No single JS chunk exceeds 500KB. |

---

## Reporting Template

After all suites complete, generate a report artifact with this structure:

```markdown
# ORCA E2E Browser Test Report — [DATE]

## Summary
- **Total tests**: X
- **Passed**: Y (Z%)
- **Failed**: N
- **Skipped**: M
- **Duration**: T seconds

## Failed Tests
| Suite | ID | Test Case | Actual Result | Screenshot |
|-------|-----|-----------|---------------|------------|
| ... | ... | ... | ... | [link] |

## Recommendations
1. [Issue description and suggested fix]
2. ...

## Environment
- Frontend: localhost:3000
- Backend: localhost:8000
- Browser: [Chromium version]
- OS: Windows
- Date: [timestamp]
```

---

## Reference Files

For detailed edge case catalog and domain-specific scenarios, see:
- [Edge Case Catalog](./references/edge-cases.md) — Maritime-domain-specific edge cases
- [Test Data](./references/test-data.md) — Sample coordinates, queries, and expected responses
- [Existing Runner](file:///D:/work/projects/orca-marine-intelligence/scripts/e2e_orca_browser_runner.py) — Legacy Python-based browser test runner (8 edge cases)

---

## Quick Start

To run the full E2E suite, tell the agent:

> Run the ORCA E2E browser testing skill against localhost

Or use the `/browser` command:

> /browser Navigate to http://localhost:3000 and run through all ORCA E2E test
> suites from the orca-e2e-browser-testing skill
