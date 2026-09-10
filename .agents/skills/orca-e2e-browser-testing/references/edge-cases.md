# ORCA E2E Edge Cases — Maritime Domain-Specific Catalog

This reference file catalogs edge cases unique to the ORCA Marine Intelligence
domain. These go beyond generic web testing — they cover oceanographic data
quirks, vernacular language handling, geospatial coordinate traps, and maritime
safety boundary logic.

---

## Category 1: Geospatial Coordinate Edge Cases

### EC-GEO-01: Coordinate Swap Attack (lon/lat vs lat/lon)
- **Context**: GeoJSON uses `[lon, lat]`, Leaflet uses `[lat, lon]`. Users may
  enter coordinates in either order.
- **Test**: Enter `76.27, 9.93` (lon, lat order) in search
- **Expected**: System detects swap (Indian waters heuristic: `lat > 50 && lon < 40`)
  and auto-corrects to `[9.93, 76.27]`.
- **Verify in**: `/map` search bar, Chat location update, `handleLocationUpdate()`

### EC-GEO-02: Coordinates Outside Indian EEZ
- **Test**: Enter `40.7128, -74.0060` (New York City)
- **Expected**: Map centers there but no PFZ data found. No crash.

### EC-GEO-03: Coordinates at International Date Line
- **Test**: Enter `0.0, 180.0`
- **Expected**: Map centers there gracefully. Boundary clamping applies.

### EC-GEO-04: Negative Coordinates (Southern Hemisphere)
- **Test**: Enter `-34.0, 18.5` (Cape Town)
- **Expected**: Valid coordinate, map centers correctly. No data for Indian coast.

### EC-GEO-05: NaN/Infinity Coordinates
- **Test**: Pass `NaN, NaN` or `Infinity, 76.27` via console
- **Expected**: Fallback to Kochi default `[9.93, 76.27]` per `handleLocationUpdate()`.

### EC-GEO-06: Zero Coordinates (Null Island)
- **Test**: Enter `0.0, 0.0` in search
- **Expected**: Map centers on Gulf of Guinea. No crash. No Indian PFZ data.

---

## Category 2: PFZ Data Edge Cases

### EC-PFZ-01: Empty PFZ Dataset
- **Context**: INCOIS may not publish PFZ data on certain days (monsoon blackout)
- **Test**: If `GET /api/pfz/today` returns `{"features": []}`
- **Expected**: Map renders with no PFZ markers. Chat advisory mentions "no data
  available today" or serves Copernicus fallback.

### EC-PFZ-02: Stale PFZ Data (>6h old)
- **Test**: Check `valid_until` timestamp in PFZ response
- **Expected**: If older than 6 hours, data should be re-fetched or marked stale.

### EC-PFZ-03: PFZ Point with Missing Properties
- **Test**: Feature with `properties: {}` (no sector, bearing, distance)
- **Expected**: Zone card shows "N/A" for missing fields. No undefined crash.

### EC-PFZ-04: Malformed GeoJSON Geometry
- **Test**: Feature with `geometry: null` or `geometry: {type: "Point", coordinates: []}`
- **Expected**: Skipped during rendering. No map crash.

### EC-PFZ-05: Sector Filter with No Matches
- **Test**: `GET /api/pfz/today?sector=NONEXISTENT`
- **Expected**: Returns `{"features": [], "count": 0}`. No error.

### EC-PFZ-06: BBox Filter with Min > Max
- **Test**: `GET /api/pfz/today?bbox=80,15,70,5` (inverted bounds)
- **Expected**: Returns 400 with "Invalid bounding coordinates: min must be <= max".

---

## Category 3: Weather & Safety Edge Cases

### EC-WX-01: Missing Weather API Keys
- **Test**: Remove `OPENWEATHERMAP_API_KEY` from `.env`
- **Expected**: Backend computes synthetic marine estimate. No NaN values. Safety
  badge shows cautious "UNKNOWN" or defaults to "SAFE" with low confidence.

### EC-WX-02: Extreme Wave Height (> 6m)
- **Test**: If Open-Meteo returns `wave_height: 8.5m`
- **Expected**: Safety badge turns RED. "DO NOT SAIL" banner in chat. DANGER
  classification.

### EC-WX-03: Active Cyclone Alert
- **Test**: `GET /api/weather/cyclone` returns active cyclone
- **Expected**: Danger agent flags it. Chat shows cyclone warning banner with
  storm name and trajectory.

### EC-WX-04: Barometric Pressure Anomaly (< 995 hPa)
- **Test**: Low-pressure system detection
- **Expected**: Cyclone endpoint flags it. Weather data includes pressure reading.

### EC-WX-05: Weather Cache Expired
- **Test**: Redis weather cache TTL expired (30 min)
- **Expected**: Fresh data fetched from Open-Meteo. No stale data served.

---

## Category 4: Language & Translation Edge Cases

### EC-LANG-01: Unsupported Language Code
- **Test**: Set `localStorage.setItem('orca_language', 'zz')` and reload
- **Expected**: Falls back to English. No crash.

### EC-LANG-02: RTL Language Attempt (Arabic)
- **Test**: Not in supported list, but test if system handles gracefully
- **Expected**: Falls back to English since 'ar' is not in SUPPORTED_LANGUAGES.

### EC-LANG-03: Mixed Script Input
- **Test**: Type "मछली near Kochi" (Hindi + English mixed)
- **Expected**: Chat accepts it. Backend processes as Hindi or English.

### EC-LANG-04: Empty localStorage orca_language
- **Test**: `localStorage.removeItem('orca_language')` and reload
- **Expected**: Defaults to 'en'. Language switcher shows English.

### EC-LANG-05: Concurrent Language Changes
- **Test**: Rapidly switch between multiple languages
- **Expected**: Final selection wins. No race condition in state updates.

---

## Category 5: SSE Streaming Edge Cases

### EC-SSE-01: Backend Disconnects Mid-Stream
- **Test**: Kill backend while chat is streaming
- **Expected**: Streaming stops. Partial response preserved. Error message shown.
  No infinite loading spinner.

### EC-SSE-02: Very Long Response (> 10,000 tokens)
- **Test**: Ask a complex multi-zone query that generates extensive output
- **Expected**: Auto-scroll keeps up. No browser freeze. Memory stable.

### EC-SSE-03: Rapid Sequential Queries
- **Test**: Send 5 queries rapidly without waiting for responses
- **Expected**: Each query creates a separate message. Responses arrive in order
  or clearly labeled. No message duplication.

### EC-SSE-04: Network Reconnection
- **Test**: Temporarily lose network, then restore
- **Expected**: Active stream shows error. New queries work after reconnection.

### EC-SSE-05: SSE Event with Missing Fields
- **Test**: Server sends `event: token\ndata: {}\n\n` (empty token)
- **Expected**: Handled gracefully. No crash. Empty string appended.

---

## Category 6: Map Rendering Edge Cases

### EC-MAP-01: Basemap Tile Failure (CARTO CDN Down)
- **Context**: `MapInner.tsx` has auto-fallback logic
- **Test**: Block CARTO tile URLs, load `/map`
- **Expected**: After >= 3 failed tiles, auto-switches to OSM fallback. Shows
  "OSM Fallback Active" notification.

### EC-MAP-02: Esri Ocean Zoom > 13
- **Test**: Zoom beyond native max for Esri Ocean tiles
- **Expected**: Tiles are clamped at zoom 13 (`getBasemapMaxNativeZoom`). No 404
  tile requests.

### EC-MAP-03: Many PFZ Markers (> 400)
- **Test**: Load all sectors with no limit filter
- **Expected**: Map renders without significant lag. Markers cluster or render
  individually.

### EC-MAP-04: Basemap Query Parameter
- **Test**: Navigate to `/map?basemap=esri_ocean`
- **Expected**: Map initializes with Esri Ocean basemap tiles. `?style=voyager`
  also works.

### EC-MAP-05: Invalid Basemap Parameter
- **Test**: Navigate to `/map?basemap=nonexistent`
- **Expected**: Falls back to default basemap (Dark Matter). No crash.

### EC-MAP-06: Floating Layer Panel Toggle
- **Test**: Click `#floating-layers-toggle` on `/map`
- **Expected**: Floating layers panel opens/closes. Layer checkboxes and basemap
  options are accessible.

---

## Category 7: Voice Input Edge Cases

### EC-VOICE-01: Audio File > 25MB
- **Test**: Upload audio larger than 25MB
- **Expected**: Backend returns 413 with size limit detail.

### EC-VOICE-02: Invalid Audio Format
- **Test**: Upload a `.txt` file renamed to `.wav`
- **Expected**: Whisper transcription fails. Backend returns 503 or empty transcription.

### EC-VOICE-03: Silent Audio (No Speech)
- **Test**: Record 5 seconds of silence
- **Expected**: Whisper returns empty or minimal transcription. UI handles gracefully.

### EC-VOICE-04: Groq API Key Missing
- **Test**: Remove GROQ_API_KEY from environment
- **Expected**: Voice endpoint returns 503 "Voice transcription unavailable".

---

## Category 8: Chat Session Edge Cases

### EC-CHAT-01: Clear Session Button
- **Test**: Click `#chat-clear-session-button` during active conversation
- **Expected**: Chat history clears. New session ID generated. Active stream aborted.

### EC-CHAT-02: Session ID in Redis Failure
- **Test**: Redis down when sending chat message
- **Expected**: Chat still works. Warning logged about Redis save failure. Response
  streams normally.

### EC-CHAT-03: XSS Injection in Chat
- **Test**: Send `<img src=x onerror=alert(1)>` as chat message
- **Expected**: Input is sanitized/escaped. No script execution. Message renders
  as plain text.

### EC-CHAT-04: Markdown in Response
- **Test**: Backend returns response with markdown formatting
- **Expected**: Markdown renders correctly (bold, lists, code blocks) in assistant
  bubble.

---

## Category 9: Geofence & Maritime Boundaries

### EC-FENCE-01: Position Inside MPA
- **Test**: Check coordinates within a Marine Protected Area
- **Expected**: Geofence status shows MPA proximity warning. Safety badge may show
  caution.

### EC-FENCE-02: Position Near IMBL (< 2km buffer)
- **Test**: Check coordinates near India-Sri Lanka maritime boundary
- **Expected**: IMBL clearance shows critical proximity. Orange/red warning.

### EC-FENCE-03: Position Outside EEZ
- **Test**: Check coordinates beyond India's 200nm EEZ
- **Expected**: EEZ status shows "Outside India EEZ" or international waters.

---

## Category 10: Backend Resilience

### EC-BACK-01: INCOIS Ingest Failure
- **Test**: INCOIS TextDataHome is unreachable
- **Expected**: System falls back to Copernicus Marine fallback data. PFZ endpoint
  still returns data with `source: "copernicus_fallback"`.

### EC-BACK-02: All Data Sources Down
- **Test**: Both INCOIS and Copernicus unavailable
- **Expected**: System serves cached data from Redis or local `data/pfz-today.geojson`.
  Response includes `X-Data-Source: local_file` header.

### EC-BACK-03: Database Connection Failure
- **Test**: PostGIS is down on startup
- **Expected**: Backend starts in degraded mode. `/health` returns
  `{"status": "degraded", "database": "disconnected"}`. Non-DB endpoints still work.

### EC-BACK-04: LLM Synthesis Timeout
- **Test**: Gemini/Groq LLM exceeds 12s budget
- **Expected**: Decision agent falls back to deterministic template advisory.
  Frontend shows `data-testid="synth-warning"` banner.

### EC-BACK-05: Agent Node Timeout (> 10s)
- **Test**: A single agent in LangGraph exceeds `ORCA_NODE_TIMEOUT_S`
- **Expected**: Agent is marked as timed out (⏱ icon in reasoning accordion).
  Pipeline continues with remaining agents. Partial result served.
