# ORCA — Agentic Marine Intelligence for Indian Fishermen

![SIH26176 Badge](https://img.shields.io/badge/SIH-26176-blue)

## 🚀 Live Demo (Temporary Hosting)

| Artifact | URL |
|----------|------|
| **Architecture Diagram** | https://cron-system.vercel.app/orca/ |
| **Map View (437 PFZ)** | https://cron-system.vercel.app/orca/map/ |
| **GeoJSON Pipeline** | https://cron-system.vercel.app/orca/geojson/ |
| **MPP Plan** | https://cron-system.vercel.app/orca/plan/ |
| **Raw PFZ Data** | https://cron-system.vercel.app/orca/map/data/pfz-today.geojson |

⚠️ **Note:** Demo hosted on `cron-system` (temporary). Migration to independent Vercel project planned for Week 2.

## 🌊 Problem

Indian fishermen rely on satellite-derived Potential Fishing Zone (PFZ) advisories published daily by INCOIS as HTML tables. But they need:
1. **Spatial reasoning**: "Where exactly is the PFZ relative to my location?"
2. **Safety checks**: Waves, wind, currents, geofences (EEZ/MPA), cyclones.
3. **Multilingual support**: 22 Indian languages + voice.
4. **Route guidance**: Safe path to the recommended zone.

## 🦾 Solution

ORCA is an agentic AI system that:
1. **Listens**: Fishermen ask in their language via voice/text (e.g., "എവിടെ മത്സ്യം?" → Malayalam for "Where is fish?").
2. **Checks in parallel**: Four specialized agents evaluate the same GeoJSON points:
   - **Fish Finder**: Closest productive PFZ zones.
   - **Sea Checker**: Wave height and currents.
   - **Weather Agent**: Wind speed and tide.
   - **Danger Watch**: EEZ/MPA geofences, cyclones.
3. **Combines intelligently**: Ranks zones by safety and proximity, providing a single safe recommendation with proof (bearing, distance, citation).
4. **Guides**: Shows the zone on a map and sends SMS route guidance.

## 🏗️ Tech Stack (MVP)

| Layer | Tech |
|-------|------|
| **Frontend** | Next.js 14, React Leaflet, Tailwind, Bhashini STT/TTS |
| **Backend** | FastAPI, Python 3.11 |
| **Geo** | PostGIS, GeoPandas |
| **Data** | INCOIS TextData → GeoJSON daily ingest |
| **AI** | Tool-calling LLM for agent orchestration |
| **Infra** | Docker, Vercel, Redis (cache + multi-turn memory) |

## 🗂️ Project Structure

```
orca-marine-intelligence/
├── docs/          # Architecture, MPP Plan, API docs
├── data/          # PFZ GeoJSON, EEZ, MPA polygons
├── frontend/      # Next.js app (Map + Chat)
├── backend/       # FastAPI + agent logic
├── infra/         # Docker Compose (FastAPI + PostGIS + Redis)
├── scripts/       # Data ingest utilities
└── .env.example   # Environment variables
```

## 🏃 Quick Start

1. **Prerequisites**: Docker, Node.js, Python 3.11
2. **Clone**: `git clone https://github.com/yourteam/orca-marine-intelligence`
3. **Environment**: `cp .env.example .env` (fill INCOIS_JSESSIONID, BHASHINI_API_KEY)
4. **Infra**: `docker compose -f infra/docker-compose.yml up -d` (PostGIS + Redis)
5. **Ingest data**: `INCOIS_JSESSIONID=<session> bash scripts/extract_pfz.sh` (runs daily at 11:30 AM)
6. **Backend**: `cd backend && pip install -r requirements.txt && uvicorn main:app --reload --port 8000`
7. **Frontend**: `cd frontend && npm install && npm run dev`
8. **Access**: http://localhost:3000 (Chat + Map)

## 📅 Status

- **MVP Build Phase**: Week 1 (02 Sep - 09 Sep 2026)
- **Key Deliverables**: Working agents, Map View, multilingual text, safety geofencing
- **Next**: Voice integration, wave data (OSF), offline caching, SMS gateway

## 📄 Documentation

- [GeoJSON Architecture](docs/ORCA_GeoJSON_Architecture.md)
- [2-Week MPP Plan](docs/ORCA_2Week_MPP_Plan.md)
- [Codebase Guide](docs/ORCA_Codebase_Guide.md)
- [API Endpoints](docs/API.md)

## 🌐 Data Attribution

- **INCOIS TextData**: Daily PFZ advisories (https://incois.gov.in)
- **MarineRegions EEZ**: https://www.marineregions.org
- **WDPA MPA**: https://www.protectedplanet.net

## ⚖️ License

MIT License (see `LICENSE`). Data licenses acknowledged in [DATA_LICENSES.md](DATA_LICENSES.md).

---

*Last updated 02 Sep 2026 — ORCA SIH26176 Team*