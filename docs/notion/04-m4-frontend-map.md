# M-D — Frontend Map (Copy to Notion → "M-D Map")

> **Paste tip:** Create Notion page under "ORCA Core" → paste this markdown.

**You own:** `frontend/map/` + `frontend/app/map/` + `frontend/app/api/pfz/` + `diagrams/` — the visual map.  
**Official PS:** [SIH26176 — ISRO](https://github.com/vedantchalke36/sih-2026-problem-statements/blob/main/ps_2026/SIH26176.md) — maps, alerts, geofencing visuals are MVP.  
**Depends on:** M-C's 5 APIs (`/api/pfz/today`, `/api/tiles`, `/api/geofence/check`, `/api/weather`) + M-B's static `data/pfz-today.geojson`. **Used by:** M-E's shell `app/page.tsx` embeds your `MapView`.

**Your files (one stack: React + Leaflet):**

| File | What it does in plain words |
|------|-----------------------------|
| `frontend/map/MapView.tsx` | **The map.** Draw base map + 437 zone circles + popups + green route line. |
| `frontend/map/SafetyBadge.tsx` | **Safety dot.** Green/yellow/red badge for a zone. |
| `frontend/map/geo.ts` | **Map math.** `haversine`, `bearing`, `dmsToDecimal`, `parseLocation`. |
| `frontend/map/index.ts` | **Barrel.** `export * from "./MapView"` → shell does `import {MapView} from "@/map"` |
| `frontend/app/map/page.tsx` | **Full map page.** Full-screen `MapView` without chat. `https://cron-system.vercel.app/orca/map/` |
| `frontend/app/api/pfz/route.ts` | **Map data proxy + offline cache.** Next.js proxy with 6h cache + service worker fallback for offline at sea. |
| `diagrams/*` | **Polish 5 HTML diagrams** for SIH video screenshots. |

Every file has `Owner: M-D (Frontend Map)` + TODOs — open it.

---

## 1) Week 1 — Make the map live (you have a head start)

### Task D1 — Show 437 zones (copy the live sample)

1. Open `diagrams/map-prototype.html` in your browser — it already renders the 437 points via Leaflet. Copy the `<MapContainer>` + `<TileLayer>` + `CircleMarker` logic into `frontend/map/MapView.tsx`.
2. Install is done: `npm install leaflet react-leaflet` (already in `frontend/package.json`).
3. Render a base map: use **Bhuvan WMS** (India's satellite map, URL in `infra/vercel.json`) or fallback to OpenStreetMap `https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png` if Bhuvan is slow.
4. Fetch `GET /api/pfz/today` (M-C exposes it, M-B fills it) → loop `features` → draw **cyan circle** per point:
   ```tsx
   features.map(f => <CircleMarker center={[f.geometry.coordinates[1], f.geometry.coordinates[0]]} color="cyan" />)
   ```
   Highlight top picks within 60 km (M-A's ranking gives you which via `map.pfz_features`) brighter cyan, safe zones green border.

5. Add popup on tap:
   ```
   Pallithottam
   Bearing 232  Distance 12 km  Depth 55-60m
   Source: INCOIS TextData SEC005 02-Sep
   [Green route line]
   ```

### Task D2 — Safety badge + map data proxy

1. **SafetyBadge:** `props: {wave_m, wind_kts, danger}` → red if forbidden or wave>2.5m or wind>25kt, yellow if wave>1.5m or wind>15kt, else green. Values come from M-A's agents via M-C's APIs. Just display.

2. **Map data proxy:** `frontend/app/api/pfz/route.ts`:
   ```typescript
   export async function GET() {
     // W1: fetch("http://localhost:8000/api/pfz/today") → unstable_cache 6h
     // on fail: return data/pfz-today.geojson from public/ via service worker
   }
   ```
   Fisherman at sea with no signal still sees yesterday's map.

### Task D3 — Full map page + diagrams

1. `frontend/app/map/page.tsx` — wraps `MapView` full-screen. Same fetch as shell but no chat. Used for `https://cron-system.vercel.app/orca/map/`.
2. `diagrams/*` — polish `architecture.html`, `geojson-pipeline.html`, `mpp-table.html` for SIH video. Make them match your React map.

---

## 2) Week 2 — Make it navigable + offline

- **Tiles:** Replace whole-file fetch with `GET /api/tiles/{z}/{x}/{y}.pbf` from M-C's `tiles.py`. Tiles = small squares that load fast on slow 2G (`ST_AsMVT` in PostGIS).
- **GPS pin:** `navigator.geolocation.getCurrentPosition` → blue dot "you are here" (accuracy ±10m).
- **Route with avoidance:** Ask M-C's `pgRouting` cost `wave*0.5 + wind*0.3 + forbidden_penalty (big)`. Makes route go around rough/forbidden areas.
- **Fly-to polish:** M-E's shell `app/page.tsx` calls your `MapView`'s `flyTo(center, 12)` — you provide the `ref` + method.

---

## 3) Who you talk to

- **You call:** M-C's `/api/pfz/today`, `/api/tiles`, `/api/geofence/check`, `/api/weather` + M-B's static `data/pfz-today.geojson` fallback
- **You are embedded by:** M-E's `app/page.tsx` shell (left ChatPanel + right MapView) — provide `MapView` ref + `flyTo`
- **Your judge view:** `https://cron-system.vercel.app/orca/map/` (full map)

---

## 4) Verify checklist

- [ ] `cd frontend && npm run dev` → `http://localhost:3000/map` shows 437 cyan circles, tap → popup
- [ ] `GET /api/pfz/today` → 437, `GET /api/tiles/6/40/22.pbf` (W2) → protobuf
- [ ] Offline: Stop backend, refresh `/map` → still shows yesterday's GeoJSON via `route.ts` fallback
- [ ] Fri 05 Sep Global Test #1: same on live Vercel

---

*Source of truth: `diagrams/map-prototype.html` (live sample to copy), `docs/API.md` (API shapes), `frontend/map/` TODOs.*
