# ORCA — How It Works (Plain-English Architecture)

This doc explains ORCA in simple terms: where the fishing advice comes from, how we clean it, where we store it, how 4 helpers use it, and what can go wrong.

> Other docs: [2-week plan](ORCA_2Week_MPP_Plan.md) · [Files and how to run](ORCA_Codebase_Guide.md) · [API details](API.md)

**Live demo (temporary):** https://cron-system.vercel.app/orca/  · Map: https://cron-system.vercel.app/orca/map/ · Data: https://cron-system.vercel.app/orca/map/data/pfz-today.geojson

---

## 1. The Problem in One Minute

Every day at 11 AM, the Indian government office INCOIS publishes a table like this:

```
place        direction  bearing  depth   distance  latitude   longitude
Pallithottam    SW       232    55-60   645-650   8 33 18 N  76 10 02 E
...
(about 437 rows across 14 coastal sectors)
```

This says "there may be fish near Pallithottam, southwest, depth 55-60 m, distance 645 m (?), at 8°33'18" N, 76°10'02" E". Useful — but:
- It is **text in a table**, not a map. A fisherman has to guess where.
- It says nothing about whether the sea is **safe** (waves, wind, storms).
- It says nothing about whether it is **allowed** (sea borders, protected parks).
- It is only in **English numerals**, not the fisherman's language.

ORCA fixes this: table → dot on a map → 4 safety checks in parallel → one safest spot with proof + route in the fisherman's language.

---

## 2. The 5-Step Pipeline (Table → Map)

### Step 1 — Go fetch the tables

INCOIS has 14 pages, one per coastal sector:

```
SEC001 Gujarat, SEC002 Maharashtra, ... SEC005 Kerala, ... SEC014 Lakshadweep
Each: https://incois.gov.in/MarineFisheries/TextData?secid=SEC005
```

You cannot open them directly — you first visit `TextDataHome?mfid=1` to get a session cookie (`JSESSIONID`). INCOIS gives you a cookie, you show it back with each SEC request. Cookie expires ≈ daily, so we refresh at 11:30 AM.

**Who does this:** Member B, `scripts/extract_pfz.sh` + `backend/ingest/incois_textdata.py`.

### Step 2 — Read the HTML rows

Each page contains a `<table>` with 7 columns. Use a HTML parser (Python's `BeautifulSoup`) to loop rows:

```
row → [ "Pallithottam", "SW", "232", "55-60", "645-650", "8 33 18 N", "76 10 02 E" ]
```

Skip rows that are broken or missing coordinates — log them but don't crash.

### Step 3 — Convert DMS coordinates to normal numbers

INCOIS uses Degrees-Minutes-Seconds (8 33 18 N). Maps need decimal (8.555). Convert:

```
decimal = degrees + minutes/60 + seconds/3600
8 33 18 N → 8 + 33/60 + 18/3600 = 8.555   (N = positive)
76 10 02 E → 76 + 10/60 + 2/3600 = 76.167  (E = positive)
S or W → negative (not needed for India, but handle it)
```

**Helper:** `scripts/dms_to_decimal.py` already has `dms_to_decimal()` — call it.

GeoJSON stores it as `[longitude, latitude]` (note: lon first).

### Step 4 — Build one shared list (GeoJSON)

Each row becomes a dot on the map:

```json
{
  "type": "Feature",
  "properties": {
    "zone_id": "SEC005_001",
    "place": "Pallithottam",
    "direction": "SW",
    "bearing": 232,
    "depth": "55-60",
    "distance_km": 645,
    "sector": "KERALA",
    "source": "incois_textdata",
    "timestamp": "2026-09-02T11:30:00+05:30"
  },
  "geometry": { "type": "Point", "coordinates": [76.167, 8.555] }
}
```

All 437 dots together form a `FeatureCollection` saved as `data/pfz-today.geojson`. This single file is the **shared list** — every helper reads the same dots so they don't disagree.

### Step 5 — Save in two fast places

1. **File:** `data/pfz-today.geojson` — a teammate without a database can still see today's points.
2. **Map database (PostGIS):** a database that understands "near Kochi" queries. Tables are in `backend/db/schema.sql`, helper is `backend/db/postgis.py`.
3. **Fast memory (Redis):** keeps the same data for 6 hours so we don't re-fetch on every click. Helper is `backend/db/redis.py`. If Redis is down, we read from the database; if the database is down, we read the file — ORCA keeps working, just slower.

---

## 3. The Shared List Idea (Why It Matters)

Without a shared list, each helper would search on its own and you'd get nonsense:

```
Fish helper: "Go to Pallithottam!"
Sea helper:  "Wave at Pallithottam is 2.8m — dangerous!"
→ No one compared the two.
```

With a shared list, the **same coordinates** flow through all helpers:

```
Fish helper: Pallithottam 12 km (closest), Mampally 18 km
Sea helper:  Pallithottam wave 0.8m (safe), Mampally wave 2.8m (danger)
Weather:     Pallithottam wind 8kt (ok), Mampally wind 28kt (danger)
Danger:      Both outside forbidden zones
→ Decider sees the full picture for each dot and picks Pallithottam.
```

**Member B creates** this list once at 11:30 AM; **Members A, C, D read** it all day.

---

## 4. The 4 Helpers + The Brain (How an Answer Is Made)

When a fisherman types "Where is fish?" we dispatch 4 helpers **at the same time** (parallel), not one after another.

```
User message ("എവിടെ മത്സ്യം?" + GPS 9.93, 76.26)
         │
         ▼
   ┌─────────────┐  figures out: language=ml, location=[9.93,76.26]
   │ The Brain   │  then asks 4 helpers in parallel:
   │ (Member A)  │ ─────────────────────────────────────┐
   └─────────────┘                                      │
         │         ┌──────────────┬──────────────┬──────────────┬──────────────┐
         │         ▼              ▼              ▼              ▼              ▼
         │    Helpers all read the same 437 GEO dots
         │     ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
         │     │Fish      │ │Sea       │ │Weather   │ │Danger    │
         │     │Finder    │ │Checker   │ │Agent     │ │Watch     │
         │     │(Member B)│ │(Member B)│ │(Member B)│ │(Member B)│
         │     │"closest  │ │"wave     │ │"wind     │ │"is it    │
         │     │within 80 │ │0.8m? safe│ │8kt? ok"  │ │forbidden?│
         │     │km"       │ │          │ │          │ │           │
         │     └──────────┘ └──────────┘ └──────────┘ └──────────┘
         │         │              │              │              │
         │         └──────────────┴──────────────┴──────────────┘
         ▼
   ┌─────────────┐  scores: closest*0.4 + sea*0.3 + wind*0.2 + not_forbidden*0.1
   │ The Decider │  winner = highest total
   │ (Member A)  │  e.g. Pallithottam 0.87 (closest 12km, calm 0.8m, wind 8kt, allowed)
   └─────────────┘  returns: { best_zone, explanation, citation }
         │
         ▼
   Map flies to the winner, popup shows bearing/distance/citation, route drawn
   Reply translated back to Malayalam + SMS sent (Member D)
```

### Who is what

| Helper | What it checks | W1 mock | W2 real |
|--------|---------------|---------|---------|
| **Fish Finder** (`backend/agents/fish_finder.py`) | Closest zones within 80km (expand to 120km/160km if none). Rank by distance. | PostGIS `ST_DWithin` query | Same |
| **Sea Checker** (`backend/agents/sea_checker.py`) | Wave height at each zone. Safe <1.5m, caution 1.5-2.5m, danger >2.5m. | Returns 0.8m (safe) | OSF 06Z wave data |
| **Weather Agent** (`backend/agents/weather_agent.py`) | Wind speed + cyclone. Safe <15kt, caution 15-25kt, danger >25kt. | Returns 8kt, no cyclone | IMD https://mausam.imd.gov.in |
| **Danger Watch** (`backend/agents/danger_agent.py`) | Inside sea border? Inside protected park (MPA)? Near international line (IMBL 2km)? Cyclone within 500km? | Checks PostGIS `ST_Contains` + `ST_DWithin` for EEZ/MPA | + real IMD cyclone overlay |

The **Decider** (`backend/agents/combiner.py`) weights the four scores and always cites the government source: `INCOIS TextData SEC005 KERALA 02-Sep-2026`.

### Why parallel?

Asking 4 helpers one by one would take 4×2 sec = 8 sec. Asking at once with `asyncio.gather(...)` takes ~2 sec (the slowest one). For a fisherman checking before sailing, 2 sec vs 8 sec matters.

---

## 5. Walkthrough: Fisherman in Kochi Asking in Malayalam

Follow the message through the system:

1. **He types:** "എവിടെ മത്സ്യം?" (Where is fish?) on `ChatPanel.tsx` (Member A) — GPS auto-attached `[9.9312, 76.2673]` if location permission granted, otherwise extracted from "near Kochi" text.

2. **Language detect:** `frontend/lib/bhashini.ts` sees Malayalam unicode → language = `ml`. If unsure, defaults to `en`.

3. **Brain extracts location:** `[9.93, 76.26]` (Kochi coast).

4. **Fish Finder runs:** SQL finds Pallithottam at `[76.167, 8.555]`, 12 km away bearing 232 (southwest), depth 55-60m. This is closest within 80km.

5. **Sea Checker sees:** wave 0.8 m → safe.

6. **Weather sees:** wind 8 knots → safe, no cyclone within 500 km → safe.

7. **Danger Watch sees:** outside forbidden parks, inside Indian EEZ, not within 2 km of international line → allowed.

8. **Decider scores:** `closest 0.85*0.4 + sea 1.0*0.3 + wind 1.0*0.2 + allowed 1.0*0.1 = 0.94`. Runner-up Mampally scores 0.62 (far + rough 2.8m). Winner: Pallithottam.

9. **Map reacts:** `frontend/components/MapView.tsx` (Member C) flies to `[8.555, 76.167]`, shows cyan circle, popup "Pallithottam — Bearing 232 — 12 km — Depth 55-60m — INCOIS SEC005 02-Sep", draws green route from GPS dot.

10. **Reply in Malayalam:** Brain translates: "പല്ലിത്തോട്ടം 12 കി.മീ SW, തരംഗം 0.8 മീ — പോകാൻ സുരക്ഷിതം." Safety badge: **green**.

> If all zones are dangerous inside 80km, the system expands to 120km/160km and warns "closest safe zone is farther — 98 km away."

---

## 6. Where Data Is Stored (Tables)

Database tables are created by `backend/db/schema.sql`:

| Table | What it holds | Example row |
|-------|--------------|-------------|
| `pfz_zones` | 437 fishing dots for today | `zone_id: SEC005_001, place: Pallithottam, geom: Point(76.167, 8.555), sector: KERALA, depth: 55-60, created_at: ...` |
| `eez_boundaries` | India's sea border polygon | `eez_name: India EEZ, geom: MultiPolygon(...)` (from MarineRegions) |
| `mpa_boundaries` | Protected parks (no fishing) | `mpa_name: Vembanad, area_km2: 12.5, geom: Polygon(...)` (from WDPA) |
| `ingest_log` | When we last fetched | `sector: SEC005, count: 32, fetched_at: 2026-09-02T11:30Z, status: ok` |

All `geom` columns use `GEOMETRY(Point/MultiPolygon, 4326)` — that just means WGS84 lat/lon, the same coordinates Google Maps uses.

---

## 7. What Can Go Wrong and What We Do

| If this breaks | How we notice | What we do so ORCA keeps running | Who fixes |
|----------------|---------------|----------------------------------|-----------|
| **INCOIS returns 404 / no data** | `incois_textdata.py` gets HTTP 404 or empty table | Show yesterday's `data/pfz-today.geojson` from Redis/disk. Warn fisherman: "Data up to 24h old". Log it in `ingest_log`. No Copernicus fallback in W1 (comes W5). | Member B |
| **JSESSIONID cookie expired** | INCOIS returns login page instead of table | `extract_pfz.sh` re-fetches `TextDataHome` for a new cookie before each SEC. Retry 3× with backoff (1s,2s,4s). | Member B |
| **INCOIS CORS blocked in browser** | Browser console: `No 'Access-Control-Allow-Origin'` | Never call INCOIS from browser. Frontend calls `GET /api/pfz/today` on our FastAPI proxy (Member D), which calls INCOIS server-side where CORS doesn't apply. Next.js proxy `frontend/app/api/pfz/route.ts` as second layer. | Member D |
| **Database (PostGIS) down** | `psycopg` error on query | Serve today's points directly from `data/pfz-today.geojson` file (no spatial query). "Near me" still works via simple math (`haversine` in `frontend/lib/geo.ts`); forbiddenchecks return "unknown" instead of crash. | Members B, D |
| **Fast memory (Redis) down** | `redis-py` error | Skip cache: query PostGIS directly. Slower (~100ms vs ~5ms) but same answer. Conversation memory (multi-turn) is lost — fisherman must resend location. | Members A, D |
| **One helper is slow (>10s)** | Orchestrator timeout | Proceed with the other 3 helpers, mark missing check as `"unknown"`, lower confidence score (e.g., 0.87 → 0.62). Show badge Yellow instead of Green with note "wave check unavailable". | Member A |
| **All zones dangerous within 80km** | Every zone scores < threshold | Expand radius to 120km, then 160km. If still forbidden everywhere, return "No safe zone nearby — do not sail north-west of Kochi today" with explanation and forbid-list. | Members A, B |
| **Phone has no internet at sea** | Frontend can't fetch | Offline tile cache `mbtiles` (Member D, W2) + yesterday's `data/pfz-today.geojson` cached by service worker. Show cached map. | Member D |

> Rule: **never show a crash**. Always return something — even if it's "data is old / check unavailable" — with a clear color badge and an explanation.

---

## 8. Tools We Use (No Jargon Summary)

| What it is | Plain meaning |
|------------|---------------|
| **PostGIS** | A database that can answer "what is within 80km of Kochi?" Geographic search, like Google Maps but inside our database. |
| **Redis** | A sticky note that self-erases after 6 hours — fast memory so we don't re-fetch the same file on every click. |
| **`ST_DWithin` / `ST_Contains`** | Database questions: "Is this point within X meters of this border?" / "Is this point inside this park polygon?" Member B writes them, you don't have to memorize. |
| **`ST_AsMVT`** | Slices map data into tiny tile squares that load fast on slow 2G internet at sea. Member C fetches them. |
| **FastAPI** | The Python web framework that runs the server URLs (`/api/pfz/today`, `/api/chat`). Member D owns it. |
| **Leaflet** | The open-source map library that draws circles and popups. Member C uses it inside React. |
| **Bhashini** | Government translator that converts between 22 Indian languages. Member A uses it. |
| **Vercel** | A website host — `git push` → live URL. Temporary hosting at `cron-system` until ORCA gets its own project in W2. |

---

*Architecture for ORCA SIH26176 — written for 4 team members. For daily tasks, see [ORCA_2Week_MPP_Plan.md](ORCA_2Week_MPP_Plan.md). For file locations and local setup, see [ORCA_Codebase_Guide.md](ORCA_Codebase_Guide.md).*
