# ORCA PFZ Daily Cron

INCOIS publishes TextData ~11:30 IST. Refresh runs **12:00 IST (06:30 UTC)** daily
(`30 6 * * *` — 06:30 UTC = 12:00 IST).

## Triggers (pick one per environment)

| Env | How | Config |
|-----|-----|--------|
| Prod (Vercel + Vercel backend) | Vercel Cron → `GET /api/cron/pfz` → `POST /api/pfz/refresh` | `infra/vercel.json` → `crons: [{path:/api/cron/pfz, schedule:"30 6 * * *"}`. **Required on Vercel:** `BACKEND_API_URL=https://orca-marine-intelligence-backend.vercel.app` + `CRON_SECRET`. **Required on backend:** same `CRON_SECRET`. Note: Vercel reads `vercel.json` at project root — copy `infra/vercel.json` contents if dashboard uses another path. |
| Render native | Render Cron Job → `python -m backend.cron.fetch_pfz` | Schedule `30 6 * * *`, same env as backend service (`DATABASE_URL`, `REDIS_URL`, `INCOIS_JSESSIONID`). |
| VM / Docker host | OS cron → CLI or curl | Copy `infra/cron/pfz-cron.example` into `crontab -e`. CLI writes `data/pfz-today.geojson` + PostGIS + Redis; curl variant hits a running backend (`http://localhost:8000` for same-host/isolated Docker only — remote hosts must use an `https://` backend URL, secret still sent via `Authorization: Bearer $CRON_SECRET`). |
| Manual | CLI or HTTP | `python -m backend.cron.fetch_pfz [--sectors SEC005]` or `curl -X POST localhost:8000/api/pfz/refresh -H "Authorization: Bearer $CRON_SECRET"`. |

## Auth

`POST /api/pfz/refresh` fails closed: set `CRON_SECRET` everywhere (Vercel +
backend). For local dev only you may set `ALLOW_UNAUTHENTICATED_REFRESH=true`
instead — never in production.

## What a run does

`backend/cron/fetch_pfz.py` → `ingest_textdata()`:
1. live INCOIS scrape (14 sectors, 4s aggregate SLA, circuit-breaker 120s)
2. on empty/offline → `data/pfz-today.geojson` fallback → Copernicus calibrated fronts
3. writes `data/pfz-today.geojson` (only if non-empty, yesterday retained otherwise)
4. upserts PostGIS `pfz_zones` (skipped gracefully offline), sets Redis `pfz:today` 6h TTL
5. prints `{status, summary, next_actions, artifacts, count, source}` — exit 0 on success/warning, 1 on hard error.

## Verify

```bash
python -m backend.cron.fetch_pfz
curl -s http://localhost:8000/api/pfz/today | head -c 300
ls -l data/pfz-today.geojson
pytest tests/test_pfz_cron.py -q
```
