# M-A — Agents & Orchestration (Copy to Notion → "M-A Agents")

> **Paste tip:** Create Notion page under "ORCA Core" → paste this markdown.

**You own:** `backend/agents/` — the intelligence. **You own all 6 agents**, no frontend, no routers.  
**Official PS:** [SIH26176 — ISRO](https://github.com/vedantchalke36/sih-2026-problem-statements/blob/main/ps_2026/SIH26176.md) — multilingual same-language reply + multi-turn are MVP.  
**Depends on:** M-B `postgis.py` + `redis.py` (shared DB). **Used by:** M-C `routers/chat.py` calls you.

---

## 1) Your 6 files (one stack: Python + logic)

| File | What it does in plain words |
|------|-----------------------------|
| `backend/agents/orchestrator.py` | **The brain.** Understands "Where is fish near Kochi?" → pulls out language + location → asks your 5 other agents **at once** (parallel). |
| `backend/agents/fish_finder.py` | **Closest zones.** "What fishing zones are within 80km of Kochi?" — queries PostGIS `ST_DWithin`. |
| `backend/agents/sea_checker.py` | **Wave check.** Is sea calm? |
| `backend/agents/weather_agent.py` | **Wind check.** Is wind safe? Any cyclone? |
| `backend/agents/danger_agent.py` | **Forbidden check.** Inside sea border? Inside protected park (MPA)? 2km warning near international line? |
| `backend/agents/combiner.py` | **The decider.** Scores every zone `closest*0.4 + sea*0.3 + wind*0.2 + not_forbidden*0.1` → picks one winner with proof. |

Every file has `Owner: M-A (Agents & Orchestration)` + TODOs at top — open it.

---

## 2) Week 1 — Build the brain (by Tue 09 Sep)

### Task A1 — Understand the question

1. Open `orchestrator.py`.
2. Write a function `orchestrate(message, lat, lon, session_id)` that returns:
   - `language` — e.g., `"ml"` for Malayalam, `"en"` for English. Call `M-D's frontend/lib/bhashini.ts` helper or simple unicode check: `if Malayalam chars → ml else en`. For W1, simple check is enough; W2 use real Bhashini ULCA.
   - `location` — use `lat/lon` if GPS was sent from `M-D's ChatPanel`, otherwise extract `"Kochi"` → lookup table `{"Kochi":[9.93,76.26], "Veraval":[21.6,69.6], "Chennai":[13.08,80.27]}`.
   - `intent` — `{"wants_fish": true, "wants_safety": true}`.

*Verify:* Mock test `orchestrator.py` with `message="എവിടെ മത്സ്യം?"` → `language=="ml"` + `location` present.

### Task A2 — Ask your 5 agents in parallel (not one by one)

```python
# in orchestrator.py
results = await asyncio.gather(
  fish_finder.find_fishing_zones(lat, lon),
  sea_checker.check_sea(pts),
  weather_agent.check_weather(pts),
  danger_agent.check_dangers(pts),
)
```

All read the same 437 GeoJSON dots from `M-B's postgis.py`. If one helper is slow (>10s), mark its check as `"unknown"` and proceed — don't crash the whole answer.

### Task A3 — Implement fish_finder

- In `fish_finder.py`, write `find_fishing_zones(lat, lon, radius_km=80)`:
  ```sql
  SELECT * FROM pfz_zones
  WHERE ST_DWithin(geom::geography, ST_MakePoint(:lon,:lat)::geography, 80000)
  ORDER BY ST_Distance(geom, ST_MakePoint(:lon,:lat)) LIMIT 5;
  ```
- If 0 results at 80km, retry 120km, then 160km.
- Return `{place, bearing, depth, distance_km, lat, lon, sector}`.

### Task A4 — Implement sea / weather / danger (mocks for W1)

- `sea_checker.py`: `return wave_m=0.8` for every zone → `status="safe"` (<1.5m safe, 1.5-2.5 caution, >2.5 danger).
- `weather_agent.py`: `return wind_kts=8, cyclone=None` → `status="safe"` (<15kt safe).
- `danger_agent.py`: For each zone:
  ```sql
  -- inside EEZ? (must be yes)
  SELECT ST_Contains(eez.geom, ST_MakePoint(lon,lat)) FROM eez_boundaries;
  -- within 2km of IMBL? (warn)
  SELECT ST_DWithin(geom::geography, ST_MakePoint(lon,lat)::geography, 2000);
  -- inside MPA? (forbidden)
  SELECT ST_Contains(mpa.geom, ST_MakePoint(lon,lat)) FROM mpa_boundaries;
  ```

### Task A5 — Rank and explain (combiner)

1. Open `combiner.py`.
2. For each zone, compute:
   - **Closest 40%:** `closest = 1 - (distance_km / max_distance)` → nearer is higher.
   - **Sea 30%:** `sea = 1.0 if wave<1.5 else linear 1→0 to 3m`.
   - **Wind 20%:** `wind = 1.0 if <15kt else linear 1→0 to 30kt`.
   - **Not forbidden 10%:** `not_forbidden = 0 if in MPA/IMBL else 1`.
3. `score = closest*0.4 + sea*0.3 + wind*0.2 + not_forbidden*0.1`. Highest wins.
4. Return `{ best_zone, explanation: "Picked Pallithottam because closest (12km) and calm (0.8m)", citation: "INCOIS TextData SEC005 KERALA 02-Sep-2026" }`.

*Verify W1:* `curl POST /api/chat '{"message":"Where is fish near Kochi?", "lat":9.93, "lon":76.26}'` (via M-C) → `best_zone.place=="Pallithottam"` + `evidence` contains INCOIS citation.

---

## 3) Week 2 — Polish

- **Memory:** Store `session_id → {lat,lon,boat,risk}` in Redis via `M-B's redis.py` (`save_session`). Follow-up "is it safe tomorrow?" reuses last location without re-asking.
- **Why panel:** Build evidence bar for `M-D` — `frontend` shows 4 score bars (closest, sea, wind, allowed) + citation. You provide the 4 numbers.
- **Real data:** M-B gives you real IMD wind + cyclone; swap mocks: `sea_checker` → OSF 06Z, `weather_agent` → IMD `https://mausam.imd.gov.in`, add lightning. `danger_agent` adds cyclone within 500km = danger.
- **Edge:** If all zones dangerous within 80km, expand 120km/160km and warn; if still all forbidden, return "No safe zone nearby — do not sail NW of Kochi today" with explanation.

---

## 4) Who you talk to

- **Get data from:** M-B `postgis.find_nearest`, `redis.get_cached_pfz`
- **Called by:** M-C `routers/chat.py` (your orchestrator is wrapped as `POST /api/chat`)
- **Helps:** M-D displays your `evidence` + `map.center` (flyTo) + `safety` badge

---

## 5) Verify checklist

- [ ] `pytest backend/agents/` — orchestrator returns `ml` for Malayalam, `en` for English
- [ ] `fish_finder` returns 5 zones within 80km for Kochi, 0.8m/8kt mocks for W1
- [ ] `combiner` picks closest calm zone over closer rough zone (test: Pallithottam 12km/0.8m vs Mampally 8km/2.8m → Pallithottam wins)
- [ ] Fri 05 Sep Global Test #1: Malayalam near Kochi → correct pin + green badge + citation

---

*Source of truth: `docs/ORCA_GeoJSON_Architecture.md` (shared list idea), `docs/API.md` (chat shape), `backend/agents/` TODOs.*
