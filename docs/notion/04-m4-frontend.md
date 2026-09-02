# M-D — Frontend & Maps (Copy to Notion → "M-D Frontend")

> **Paste tip:** Create Notion page under "ORCA Core" → paste this markdown.

**You own:** `frontend/chat/` + `frontend/map/` + `frontend/app/` + `diagrams/` — **everything the fisherman sees, split into 2 subdirectories.**  
**Official PS:** [SIH26176 — ISRO](https://github.com/vedantchalke36/sih-2026-problem-statements/blob/main/ps_2026/SIH26176.md) — maps, alerts, same-language reply are MVP.  
**Depends on:** M-C's 5 APIs (`/api/chat`, `/api/pfz/today`, `/api/tiles`, `/api/geofence/check`, `/api/weather`) + M-A's bhashini shape. **Used by:** Judges' eyes — if your map doesn't load, W1 fails.

**Your 2 subdirectories:**

| Subdirectory | What it holds | Files |
|--------------|---------------|-------|
| `frontend/chat/` | **1) Core Chat UI** | `ChatPanel.tsx` (chat box), `LanguageSwitch.tsx` (22-language dropdown), `bhashini.ts` (translator helper), `index.ts` (barrel) |
| `frontend/map/` | **2) Map View + geo** | `MapView.tsx` (map + 437 circles), `SafetyBadge.tsx` (green/yellow/red), `geo.ts` (haversine/bearing), `index.ts` (barrel) |

Plus `frontend/app/` (Next.js routing: `page.tsx` shell, `map/page.tsx` full map, `api/pfz/route.ts` proxy) stays in `app/`.

---

## 1) Your 11 files in 2 subdirectories (one stack: React + Leaflet + Tailwind)

| File | What it does in plain words |
|------|-----------------------------|
| `frontend/chat/ChatPanel.tsx` | **The chat box.** Where fisherman types. `chat/` — core chat UI. |
| `frontend/chat/LanguageSwitch.tsx` | **22-language switch.** Dropdown + auto-detect. `chat/` |
| `frontend/chat/bhashini.ts` | **Translator helper.** `detectLanguage()` + `translate()` via Bhashini ULCA. `chat/` |
| `frontend/chat/index.ts` | **Barrel.** `export * from "./ChatPanel"` so shell does `import {ChatPanel} from "@/chat"` |
| `frontend/map/MapView.tsx` | **The map.** Draw base map + 437 zone circles + popups + route line. `map/` |
| `frontend/map/SafetyBadge.tsx` | **Safety dot.** Green/yellow/red badge. `map/` |
| `frontend/map/geo.ts` | **Map math.** `haversine`, `bearing`, `dmsToDecimal`, `parseLocation`. `map/` |
| `frontend/map/index.ts` | **Barrel.** `export * from "./MapView"` so shell does `import {MapView} from "@/map"` |
| `frontend/app/page.tsx` | **The full shell (your heaviest).** Top bar `LanguageSwitch (from chat/)` + `SafetyBadge (from map/)`, left ChatPanel + right MapView. `app/` |
| `frontend/app/map/page.tsx` | **Full map page.** Full-screen `MapView` without chat. `app/` |
| `frontend/app/api/pfz/route.ts` | **Map data proxy + offline cache.** Next.js proxy with 6h cache + service worker fallback. `app/api/` |
| `diagrams/*` | **Polish 5 HTML diagrams** for SIH video screenshots. |

Every file has `Owner: M-D (Frontend & Maps)` + TODOs — open it.

---

## 2) Week 1 — Make the map live (you have a head start)

### Task D1 — Show 437 zones (copy the live sample)

1. Open `diagrams/map-prototype.html` in your browser — it already renders the 437 points via Leaflet. Copy the `<MapContainer>` + `<TileLayer>` + `CircleMarker` logic into `frontend/components/MapView.tsx`.
2. Install is done: `npm install leaflet react-leaflet` (already in `frontend/package.json`).
3. Render a base map: use **Bhuvan WMS** (India's satellite map, URL in `infra/vercel.json`) or fallback to OpenStreetMap `https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png` if Bhuvan is slow.
4. Fetch `GET /api/pfz/today` (Member C exposes it, Member B fills it) → loop `features` → draw **cyan circle** per point:
   ```tsx
   features.map(f => <CircleMarker center={[f.geometry.coordinates[1], f.geometry.coordinates[0]]} color="cyan" />)
   ```
   Highlight top picks within 60 km (Member A's ranking gives you which via `map.pfz_features`) brighter cyan, safe zones green border.

5. Add popup on tap:
   ```
   Pallithottam
   Bearing 232  Distance 12 km  Depth 55-60m
   Source: INCOIS TextData SEC005 02-Sep
   [Green route line]
   ```

### Task D2 — React to recommendations (flyTo)

When `POST /api/chat` (M-C) returns `{map:{center:[8.555,76.167]}}`, call `map.flyTo(center, 12)` — smooth fly animation. Draw green `<Polyline positions={route}>` from user's GPS `[lat,lon]` (blue dot) to zone. W1 straight line is fine; W2 M-C's `pgRouting` makes it avoid forbidden zones.

### Task D3 — Shell + chat wiring + safety badge

1. **Shell `frontend/app/page.tsx`:** Top bar `LanguageSwitch + SafetyBadge`, left `30% <ChatPanel onRecommend={c=>mapRef.current.flyTo(c)}>`, right `70% <MapView ref={mapRef}>`, responsive (`flex-col` mobile, `flex-row` desktop). GPS on mount: `navigator.geolocation.getCurrentPosition` → blue dot + pass lat/lon to ChatPanel.

2. **ChatPanel:** Text input + send → `fetch POST /api/chat` (M-C) → show reply + evidence citations + call `onMapFlyTo(center)`. React `useState` for messages. In W1, text only — no voice.

3. **SafetyBadge:** `props: {wave_m, wind_kts, danger}` → red if forbidden or wave>2.5m or wind>25kt, yellow if wave>1.5m or wind>15kt, else green. Values come from M-A's agents via M-C's APIs.

4. **Language:** `LanguageSwitch.tsx` dropdown for 22 languages + `bhashini.ts` helper:
   ```typescript
   export function detectLanguage(text: string): string {
     // W1: simple unicode check — if Malayalam chars → "ml" else "en" is enough
     // W2: call Bhashini ULCA detect API (URL in .env.example)
   }
   ```
   **MVP per ISRO PS:** Same-language reply is mandatory — if user types Malayalam, answer must be Malayalam. M-A's orchestrator also calls your `bhashini.ts` server-side.

5. **Map data proxy + offline:** `frontend/app/api/pfz/route.ts`:
   ```typescript
   export async function GET() {
     // W1: fetch("http://localhost:8000/api/pfz/today") → unstable_cache 6h
     // on fail: return data/pfz-today.geojson from public/ via service worker
   }
   ```
   Fisherman at sea with no signal still sees yesterday's map.

---

## 3) Week 2 — Make it navigable + offline + polished

- **Tiles:** Replace whole-file fetch with `GET /api/tiles/{z}/{x}/{y}.pbf` from M-C's `tiles.py`. Tiles = small squares that load fast on slow 2G at sea (`ST_AsMVT` in PostGIS).
- **GPS pin:** `navigator.geolocation.getCurrentPosition` → blue dot "you are here" (accuracy ±10m).
- **Route with avoidance:** Ask M-C's new `/api/tiles` with `pgRouting` cost `wave*0.5 + wind*0.3 + forbidden_penalty (big)`. Makes route go around rough/forbidden areas.
- **SMS display:** `POST /api/chat` also returns `sms_text` in Malayalam (M-C's SMS gateway) — show it in ChatPanel with "Send SMS" button.
- **Diagrams polish:** Update `diagrams/architecture.html`, `geojson-pipeline.html`, `mpp-table.html` colors/labels for final SIH video. Make them match your React map.

---

## 4) Who you talk to

- **You call:** M-C's 5 APIs (`/api/chat`, `/api/pfz/today`, `/api/tiles`, `/api/geofence/check`, `/api/weather`) + M-B's static `data/pfz-today.geojson` as fallback
- **You provide:** `bhashini.ts` helper that M-A's orchestrator also imports server-side
- **Your judge view:** `https://cron-system.vercel.app/orca/map/` (full map) + `https://cron-system.vercel.app/orca/` (shell)

---

## 5) Verify checklist

- [ ] `cd frontend && npm install && npm run dev` → `http://localhost:3000` shows shell (chat left, map right)
- [ ] `http://localhost:3000/map` shows 437 cyan circles, tap → popup with bearing/distance
- [ ] Type Malayalam "എവിടെ മത്സ്യം?" → `ChatPanel` calls `/api/chat` → map flies + green route + SafetyBadge green
- [ ] `LanguageSwitch` dropdown shows 22 languages, auto-detect `ml` for Malayalam
- [ ] Offline: Stop backend, refresh map → still shows yesterday's GeoJSON via `route.ts` fallback
- [ ] Fri 05 Sep Global Test #1: same on live Vercel

---

*Source of truth: `diagrams/map-prototype.html` (live sample to copy), `docs/API.md` (API shapes you fetch), `frontend/` TODOs, `docs/ORCA_GeoJSON_Architecture.md` (shared list idea).*
