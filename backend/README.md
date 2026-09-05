# ORCA Backend — Agentic Intelligence & Ingest Engine

FastAPI backend orchestrating multi-agent spatial reasoning, live oceanographic data extraction, and multilingual vernacular chat for ORCA Marine Intelligence.

---

## 🏗️ Directory Architecture

```
backend/
├── agents/                    # Multi-agent intelligence layer
│   ├── orchestrator.py        # Central query intent detector & agent coordinator
│   ├── graph.py               # LangGraph compiled state machine
│   ├── combiner.py            # Multi-criteria safety ranker & veto badge engine
│   ├── synthesizer_service.py # LLM synthesis with lexical secret masking
│   ├── lexical_mask.py        # Bidirectional prompt injection & secret scrubbing
│   ├── planner_schema.py      # Dynamic tool planner (find_fishing_zones, ocean, weather)
│   └── subagents/             # Specialist subagents
│       ├── fish_finder.py     # PFZ zone proximity & commercial depth logic
│       ├── sea_checker.py     # Wave height & ocean current analyzer
│       ├── weather_agent.py   # Wind, gusts, and cyclone alert analyzer
│       └── danger_agent.py    # EEZ & MPA polygon raycasting geofence
├── ingest/                    # Live and simulated data extractors
│   ├── live_fetchers.py       # Live Open-Meteo Marine/Weather & INCOIS GeoJSON fetchers
│   ├── mock_fetchers.py       # Deterministic scenario simulation engine (NORMAL, ROUGH_SEAS)
│   ├── incois_textdata.py     # Daily INCOIS PFZ HTML bulletin scraper
│   ├── copernicus_fallback.py # Copernicus CMEMS SST/Chlorophyll backup
│   └── boundaries.py          # MarineRegions EEZ & WDPA MPA ingest routines
├── db/                        # Database & persistence layer
│   ├── session.py             # SQLAlchemy 2.0 async engine & session maker
│   ├── models.py              # PostGIS models (PFZZones, Boundaries, Observations)
│   └── postgis.py             # Spatial query utilities (ST_DWithin, ST_Contains)
├── routers/                   # FastAPI HTTP & SSE route handlers
│   ├── chat.py                # Conversational endpoint with SSE streaming
│   ├── pfz.py                 # PFZ GeoJSON API
│   ├── weather.py             # Live marine weather API
│   ├── geofence.py            # Maritime boundary audit API
│   └── tiles.py               # Vector tile server for map layers
└── main.py                    # FastAPI application entry point & CORS configuration
```

---

## 📡 Live Telemetry & Open-Meteo Integration

ORCA's `backend/ingest/live_fetchers.py` layer connects directly to live operational data sources:

1. **Open-Meteo Marine API** (`https://marine-api.open-meteo.com/v1/marine`):
   * Extracts real-time hourly wave height (`m`), wave period (`s`), wave direction, and ocean current velocity (`m/s` converted to `kt`) and direction.
   * Feeds directly into `SeaChecker` (`backend/agents/subagents/sea_checker.py`).
2. **Open-Meteo Forecast API** (`https://api.open-meteo.com/v1/forecast`):
   * Extracts 10m sustained wind speed (`kt`), wind gusts (`kt`), and surface barometric pressure (`hPa`).
   * Pressure drops below `995 hPa` trigger an automatic cyclone alert.
   * Feeds directly into `WeatherAgent` (`backend/agents/subagents/weather_agent.py`).
3. **Licensing & Terms of Use**:
   * **Free / Non-Commercial**: Open-Meteo is completely free with **no API key required** for open-source, academic, research, and non-commercial usage up to 10,000 requests/day.
   * **Commercial**: Any commercial deployment requires purchasing an official commercial API key from Open-Meteo.

---

## ⚡ Redis Configuration (Upstash vs. Local Docker)

ORCA requires Redis for 6-hour PFZ caching, multi-turn chat history, and request deduplication.

### 1. Upstash Redis (Recommended for Cloud / Serverless)
Upstash offers a permanent free tier providing:
* **256 MB Storage**
* **10,000 commands/day**
* Native `rediss://` TLS protocol

Set in `.env`:
```env
REDIS_URL=rediss://default:<PASSWORD>@<ENDPOINT>.upstash.io:6379
```

### 2. Local Docker Redis (Recommended for Local Dev)
Run local Redis with zero network latency:
```bash
docker run -d --name orca-redis -p 6379:6379 redis:7-alpine
```
Set in `.env`:
```env
REDIS_URL=redis://localhost:6379/0
```

---

## 🛠️ Local Development & Testing

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run test suite
python -m pytest

# 3. Start development server
uvicorn main:app --reload --port 8000
```
