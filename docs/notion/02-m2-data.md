# M-B — Data Extractors & Storage (Copy to Notion → "M-B Data")

> **Paste tip:** Create Notion page under "ORCA Core" → paste this markdown.

**You own:** `backend/ingest/` + `backend/db/` + `scripts/` — the data pipeline. **You are the blocking path — deliver Tue or everyone is blocked.**  
**Official PS:** [SIH26176 — ISRO](https://github.com/vedantchalke36/sih-2026-problem-statements/blob/main/ps_2026/SIH26176.md) — data discovery is core.  
**Depends on:** INCOIS website (needs JSESSIONID cookie). **Used by:** M-A (agents query your PostGIS), M-C (APIs serve your GeoJSON), M-D (map draws your dots).

---

## 1) Your 8 files (one stack: Python + SQL + scraping)

| File | What it does in plain words |
|------|-----------------------------|
| `backend/ingest/incois_textdata.py` | **The daily fetcher.** Goes to INCOIS at 11:30 AM, reads 14 HTML pages, converts to 437-dot list. |
| `backend/ingest/boundaries.py` | **Downloads sea borders once.** EEZ (India's sea border) from MarineRegions + MPA (protected parks) from WDPA. |
| `backend/ingest/copernicus_fallback.py` | **Backup data** — only if INCOIS is down. Skip in W1, do W5. |
| `backend/db/postgis.py` | **Talks to the map database.** Helper for PostGIS (the database that understands lat/lon). |
| `backend/db/redis.py` | **Talks to fast memory.** Helper for Redis (sticky note that erases after 6h). |
| `backend/db/schema.sql` | **Creates tables.** `pfz_zones, eez_boundaries, mpa_boundaries, ingest_log` + spatial index. |
| `scripts/extract_pfz.sh` | **Shell helper.** Loops SEC001-014 with `curl -b cookies.txt`. |
| `scripts/dms_to_decimal.py` | **Math helper.** `8 33 18 N → 8.555`. |

Every file has `Owner: M-B (Data Extractors & Storage)` + TODOs — open it.

---

## 2) Week 1 — Get the data flowing (most urgent, do Tue 02 Sep)

### Task B1 — Fetch INCOIS TextData (your #1 priority)

*What INCOIS is:* Government site publishing 14 sector pages (SEC001 Gujarat … SEC014 Lakshadweep). Each page is an HTML `<table>` with 7 columns: place, compass direction, bearing, depth, distance, latitude DMS, longitude DMS. DMS looks like `8 33 18 N`.

*Step by step:*

1. **Get a session cookie** — INCOIS requires it:
   ```bash
   curl -c cookies.txt https://incois.gov.in/MarineFisheries/TextDataHome?mfid=1 -o /tmp/home.html
   # cookies.txt now has JSESSIONID=...
   for id in SEC001 SEC002 SEC003 SEC004 SEC005 SEC006 SEC007 SEC008 SEC009 SEC010 SEC011 SEC012 SEC013 SEC014; do
     curl -b cookies.txt "https://incois.gov.in/MarineFisheries/TextData?secid=$id" -o "data/raw_${id}.html"
   done
   ```
   Cookie expires daily — refresh at 11:30 AM before fetching. See `scripts/extract_pfz.sh` (already has the loop, make it executable: `chmod +x scripts/extract_pfz.sh`).

2. **Parse each `data/raw_*.html`:**
   - Open `backend/ingest/incois_textdata.py`.
   - For each HTML file, use `BeautifulSoup` or `html.parser` to loop `<table><tr>` rows.
   - For each row, read the 7 columns.
   - Convert DMS to decimal: `8 33 18 N → 8 + 33/60 + 18/3600 = 8.555` (S/W negative). Call `scripts/dms_to_decimal.py`'s `dms_to_decimal()`. GeoJSON order is `[longitude, latitude]`.
   - Build a GeoJSON Feature (shape in `ORCA_GeoJSON_Architecture.md`) and push to list. You should get ~437 features today (count changes daily).

3. **Save in 3 places:**
   - **File:** `data/pfz-today.geojson` (so a teammate without DB can still see today's points)
   - **Database:** `backend/db/postgis.py` → `upsert_zones(features)` → `INSERT INTO pfz_zones` (schema in `backend/db/schema.sql`)
   - **Fast memory:** `backend/db/redis.py` → `SET pfz:today` → JSON string with 6h expiry (`TTL 21600`).

*Verify:* `ls -lh data/pfz-today.geojson` + `jq '.features | length'` → ~437. `curl http://localhost:8000/api/pfz/today | jq .metadata.count` → same.

### Task B2 — Database setup

1. Open `backend/db/schema.sql` + `postgis.py`.
2. Run `docker compose -f infra/docker-compose.yml up -d` (starts PostGIS 5432 + Redis 6379, auto-runs `schema.sql`).
3. Verify: `docker exec -it orca-postgis psql -U orca -c "\d pfz_zones"` + index `CREATE INDEX ON pfz_zones USING GIST(geom)`.
4. If `schema.sql` changes, `docker compose down -v && docker compose up -d` to re-apply.

### Task B3 — Download forbidden zones (once in W1)

Open `backend/ingest/boundaries.py`:
- **EEZ:** Download `https://geo.vliz.be/.../eez.geojson` → save `data/eez.geojson` → load into PostGIS `eez_boundaries`.
- **MPA:** Download `https://www.protectedplanet.net/downloads` → save `data/mpa.geojson` → load into `mpa_boundaries`.
- These are static — run once, not daily.

*Verify:* `psql -c "SELECT count(*) FROM eez_boundaries"` >0, `SELECT count(*) FROM mpa_boundaries` >0.

---

## 3) Week 2 — Harden

- **Tile server help:** M-C's `routers/tiles.py` needs `ST_AsMVT` — ensure your PostGIS has data and `postgis.py` has `tiles()` helper. M-D's map will fetch `/api/tiles/{z}/{x}/{y}.pbf` instead of whole file (fast on 2G).
- **Daily cron:** Create `infra/cron_ingest.sh` that runs **11:30 AM IST daily**: refresh cookie → fetch 14 sectors → rebuild GeoJSON → upsert PostGIS → refresh Redis → log `ingest_log` (count + errors). Test with `bash infra/cron_ingest.sh` manually first.
- **Real mocks replacement (help M-A):** Provide helpers for `sea_checker` → OSF 06Z wave data (via xarray), `weather_agent` → IMD `https://mausam.imd.gov.in` — M-A will call them, you ensure PostGIS has the joined lat/lon grid.
- **Logging:** `ingest_log` table should log every fetch: `sector, count, fetched_at, status`.

---

## 4) Who you talk to

- **You unblock:** M-A (queries your PostGIS via `find_nearest`), M-C (serves your GeoJSON via `/api/pfz/today`), M-D (draws your dots)
- **You call:** INCOIS website (with JSESSIONID), MarineRegions, WDPA

---

## 5) Verify checklist

- [ ] `bash scripts/extract_pfz.sh` → `data/pfz-today.geojson` 437 features
- [ ] `docker compose -f infra/docker-compose.yml up -d` → `docker ps` shows postgis + redis
- [ ] `curl http://localhost:8000/api/pfz/today` (via M-C) → 437, cached in Redis `GET pfz:today`
- [ ] `psql -c "SELECT * FROM eez_boundaries LIMIT 1"` → India's polygon
- [ ] Fri 05 Sep Global Test #1: same data visible on live map `https://cron-system.vercel.app/orca/map/`

---

*Source of truth: `docs/ORCA_GeoJSON_Architecture.md` (§ Pipeline), `backend/ingest/` + `backend/db/` TODOs.*
