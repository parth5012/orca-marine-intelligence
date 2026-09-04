# ORCA Multi-Agent System Architecture & Tools Specification (Map 30)

> **Domain**: ISRO SIH26176 — ORCA Marine Ecosystem Reasoning with Collaborative Agents  
> **Source Guide**: [`docs/ORCA_Wayfinder_Map_30_LLM_Reasoning_Implementation.md`](file:///D:/work/projects/orca-marine-intelligence/docs/ORCA_Wayfinder_Map_30_LLM_Reasoning_Implementation.md) & [`docs/ORCA_Wayfinder_Map_22_Dynamic_Agents.md`](file:///D:/work/projects/orca-marine-intelligence/docs/ORCA_Wayfinder_Map_22_Dynamic_Agents.md)  
> **Owner**: M-A (Agents & Orchestration in [`backend/agents/`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/))

---

## 1. System Architecture Diagram

![ORCA Multi-Agent System Architecture Diagram](C:/Users/DELL/.gemini/antigravity-cli/brain/55b77380-bb88-4615-a291-4c7a39482abd/orca_multiagent_architecture_1788521469718.jpg)

```mermaid
flowchart TD
    User(["Fisherman / Client Query<br/>(Voice, Text, Map click)"])
    
    subgraph SupervisorPlane ["1. Supervisor & Dynamic Planner Plane"]
        PlannerNode["planner_node<br/>Supervisor / Planner Agent"]
        GeminiPlanner["gemini-2.5-flash<br/>Budget: &lt;500ms"]
        SchemaValidator["Pydantic Schema Validation<br/>PlannerOutput"]
        ClarificationGate{"Confidence &ge; 0.6?"}
        ClarificationOut["Clarification Prompt<br/>(Ask GPS / Port in Vernacular)"]
        
        T_Geo["Tool: _resolve_location()<br/>COASTAL_PORTS_REGISTRY fast-path"]
        T_Offset["Tool: _parse_relative_offset()<br/>Spatial delta: '10km south'"]
        T_RedisGet["Tool: redis.get_session()<br/>Multi-turn history (last 3 turns)"]
    end

    subgraph StateGraphPipeline ["2. LangGraph StateGraph Execution Pipeline"]
        direction TB
        
        subgraph DiscoveryNode ["Node 1: PFZ Discovery"]
            FishFinder["fish_finder<br/>Fish Finder Specialist Agent"]
            T_PostGIS_PFZ["Tool: find_pfz_near()<br/>PostGIS ST_DWithin (80&rarr;120&rarr;160km)"]
            T_GeoJSON_PFZ["Tool: _geojson_fallback()<br/>Haversine on data/pfz-today.geojson"]
            T_Mock_PFZ["Tool: mock_fetch_incois_pfz()<br/>Scenario/Offline test mock"]
        end

        subgraph ParallelAnalysis ["Node 2: parallel_analysis_node (asyncio.gather / Send Fan-Out)"]
            direction TB
            
            subgraph SeaCheckerNode ["Subagent: sea_checker"]
                SeaChecker["sea_checker<br/>Ocean Dynamics Agent"]
                T_OSF["Tool: fetch_osf_wave_current()<br/>OSF/GOFS 06Z Zarr/xarray"]
                T_SeaHeuristic["Tool: _heuristic_wave_height &amp; current<br/>MD5 deterministic hash mock"]
                T_SeaWrapper["Tool: get_wave_current()<br/>OSF &rarr; Heuristic fallback wrapper"]
                T_SeaMock["Tool: mock_fetch_osf_ocean_state()<br/>Scenario mock fetcher"]
            end

            subgraph WeatherNode ["Subagent: weather_agent"]
                WeatherAgent["weather_agent<br/>Atmospheric Agent"]
                T_IMD_Wind["Tool: fetch_imd_wind()<br/>IMD Mausam scraper/API"]
                T_IMD_Cyclone["Tool: fetch_imd_cyclones()<br/>IMD cyclone feed scraper"]
                T_CycloneAlert["Tool: get_cyclone_alert()<br/>500km haversine proximity alert"]
                T_WeatherWrapper["Tool: get_wind()<br/>IMD &rarr; Heuristic fallback wrapper"]
                T_WeatherMock["Tool: mock_fetch_imd_marine_weather()<br/>Scenario mock fetcher"]
            end

            subgraph DangerNode ["Subagent: danger_agent"]
                DangerAgent["danger_agent<br/>Geospatial Geofence Agent"]
                T_PG_Geofence["Tool: check_geofence()<br/>PostGIS ST_Contains (EEZ/MPA)"]
                T_Raycast_EEZ["Tool: _fallback_check_eez()<br/>Ray-cast on data/eez.geojson"]
                T_Raycast_MPA["Tool: _fallback_check_mpa()<br/>Ray-cast on data/mpa.geojson"]
                T_IMBL_Dist["Tool: _fallback_distance_to_imbl()<br/>2km buffer boundary calculation"]
                T_IMD_Safety["Tool: fetch_imd_lightning/cyclone<br/>W2 safety alerts stub"]
                T_DangerMock["Tool: mock_check_geofence_boundaries()<br/>Scenario mock fetcher"]
            end
        end

        subgraph DecisionNode ["Node 3: decision_agent &amp; Smart Combiner"]
            DecisionAgent["decision_agent<br/>Decision &amp; Reporting Agent"]
            CombinerRank["Tool: combiner.combine_and_rank()<br/>Multi-factor 40/30/20/10 scoring"]
            HardSafetyVeto{"Strict Invariant:<br/>all_unsafe OR Banned?"}
            DoNotSail["Hard Veto Directive:<br/>DO NOT SAIL (Mandatory)"]
            
            subgraph SynthesisLayer ["Masked Vernacular Advisory Synthesis"]
                Masker["Tool: MarineGlossaryMasker.mask_text()<br/>Mask bearings, knots, km, coords"]
                LLMSynth["gemini-2.5-flash<br/>Advisory Synthesizer"]
                Unmasker["Tool: unmask_text()<br/>Restore exact original numbers"]
                Validator["Tool: verify_numbers_preserved()<br/>Verify Arabic numerals 0-9"]
                Vernacular["Tool: render_grounded_advisory()<br/>ml / ta / te / hi / en dictionary"]
                BadgeAssign["Tool: _badge_for_best()<br/>green / amber / red badge"]
            end
        end
    end

    subgraph StreamingOutput ["3. Reactive SSE Event Streamer (P95 &lt; 2.0s)"]
        SSEStream["orchestrate_stream_via_graph()<br/>Strict Event Protocol:"]
        EV_Status["1. status* (running/done per node)"]
        EV_Map["2. map (early flyTo provisional &rarr; final)"]
        EV_Safety["3. safety (provisional &rarr; final badge)"]
        EV_Tokens["4. token+ (live LLM stream / chunks)"]
        EV_Evidence["5. evidence (INCOIS citation &amp; warnings)"]
        EV_Done["6. done (confidence &amp; session_id)"]
    end

    subgraph StatePersistence ["4. Session State Store"]
        T_RedisSave["Tool: redis.save_session()<br/>Persist coords, turn history, TTL 24h"]
    end

    %% Flow connections
    User --> PlannerNode
    PlannerNode --> T_Geo
    PlannerNode --> T_Offset
    PlannerNode --> T_RedisGet
    PlannerNode --> GeminiPlanner
    GeminiPlanner --> SchemaValidator
    SchemaValidator --> ClarificationGate

    ClarificationGate -- "No (conf &lt; 0.6)" --> ClarificationOut
    ClarificationOut --> User

    ClarificationGate -- "Yes (conf &ge; 0.6)" --> FishFinder
    
    FishFinder --> T_PostGIS_PFZ
    FishFinder --> T_GeoJSON_PFZ
    FishFinder --> T_Mock_PFZ
    FishFinder -- "Candidate Points (GeoJSON)" --> ParallelAnalysis
    FishFinder -. "Early Provisional Map" .-> EV_Map

    SeaChecker --> T_OSF
    SeaChecker --> T_SeaHeuristic
    SeaChecker --> T_SeaWrapper
    SeaChecker --> T_SeaMock

    WeatherAgent --> T_IMD_Wind
    WeatherAgent --> T_IMD_Cyclone
    WeatherAgent --> T_CycloneAlert
    WeatherAgent --> T_WeatherWrapper
    WeatherAgent --> T_WeatherMock

    DangerAgent --> T_PG_Geofence
    DangerAgent --> T_Raycast_EEZ
    DangerAgent --> T_Raycast_MPA
    DangerAgent --> T_IMBL_Dist
    DangerAgent --> T_IMD_Safety
    DangerAgent --> T_DangerMock

    ParallelAnalysis -- "Sea, Weather, Danger Results" --> DecisionAgent
    ParallelAnalysis -. "Early Provisional Safety" .-> EV_Safety

    DecisionAgent --> CombinerRank
    CombinerRank --> HardSafetyVeto
    HardSafetyVeto -- "Yes" --> DoNotSail
    HardSafetyVeto -- "No" --> Masker
    DoNotSail --> Masker
    Masker --> LLMSynth
    LLMSynth --> Unmasker
    Unmasker --> Validator
    Validator --> Vernacular
    Vernacular --> BadgeAssign

    BadgeAssign --> SSEStream
    SSEStream --> EV_Status
    SSEStream --> EV_Map
    SSEStream --> EV_Safety
    SSEStream --> EV_Tokens
    SSEStream --> EV_Evidence
    SSEStream --> EV_Done
    EV_Done --> T_RedisSave
    EV_Done --> User
```

---

## 2. Agent & Subagent Specifications with Tool Sets

### 2.1 Supervisor / Dynamic Query Planner
* **Source Module**: [`backend/agents/planner_schema.py`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/planner_schema.py) & [`backend/agents/graph.py`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/graph.py#L139-L200)
* **Model**: Gemini 2.5 Flash (`gemini-2.5-flash`)
* **SLA Budget**: `< 500ms`
* **Responsibilities**: Intent decomposition (`wants_fish`, `wants_safety`), multi-turn context resolution, coastal port geocoding, autonomous selective tool subset dispatch (`find_fishing_zones`, `check_ocean_state`, `check_weather`, `check_geofence`), clarification gating.
* **Output Schema**: [`PlannerOutput`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/planner_schema.py#L92-L144) (`target_location`, `intents`, `confidence`, `reasoning_trace`, `selected_tools`).

#### Tools:
| Tool Name | Type | Signature / Purpose | Implementation Details |
| :--- | :--- | :--- | :--- |
| [`_resolve_location`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/orchestrator.py#L94-L104) | Deterministic Geocoder | `(query: str, location: dict \| None) -> tuple[float, float] \| None` | Prioritizes explicit GPS dictionary, then matches against [`COASTAL_PORTS_REGISTRY`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/planner_schema.py#L42-L49) (Kochi, Munambam, Beypore, Kollam, Vizag, Veraval, Chennai). |
| [`_parse_relative_offset`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/orchestrator.py#L113-L120) | Spatial Offset Calculator | `(query: str, cached_lat: float, cached_lon: float) -> tuple[float, float] \| None` | Parses conversational relative directions (e.g., "10km south", "20km further west") using 0.09° per 10km projection. |
| [`redis.get_session`](file:///D:/work/projects/orca-marine-intelligence/backend/db/redis.py) | Memory Lookup | `async (session_id: str) -> dict \| None` | Fetches fisherman's last resolved GPS coordinates, previous zone, vessel type, and turn history. Timeout = 1.0s. |
| `gemini-2.5-flash Structured Planner` | LLM Dispatcher | `(query: str, context: dict) -> PlannerOutput` | Dynamic tool picker with auditable reasoning trace per tool decision. Gated by `confidence >= 0.6`. |

---

### 2.2 Fish Finder Agent (Subagent 1)
* **Source Module**: [`backend/agents/subagents/fish_finder.py`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/subagents/fish_finder.py)
* **Node Name**: `fish_finder`
* **Responsibilities**: INCOIS Potential Fishing Zone (PFZ) discovery, sector filtering (`SEC005`, `KERALA`, etc.), staged radius expansion (80km &rarr; 120km &rarr; 160km).
* **Passthrough Invariant**: If planner omits `find_fishing_zones`, node executes zero-latency passthrough (`<1ms`).

#### Tools:
| Tool Name | Type | Signature / Purpose | Implementation Details |
| :--- | :--- | :--- | :--- |
| [`find_pfz_near`](file:///D:/work/projects/orca-marine-intelligence/backend/db/postgis.py) | PostGIS Spatial DB Tool | `async (lat: float, lon: float, radius_km: float, limit: int) -> list[dict]` | PostGIS spatial index query using spherical `ST_DWithin` on loaded daily INCOIS PFZ polygons. |
| [`_geojson_fallback`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/subagents/fish_finder.py#L86-L185) | Local Haversine Spatial Tool | `(lat: float, lon: float, radius_km: float, limit: int, sector: str \| None) -> list[dict]` | Offline zero-dependency fallback computing spherical haversine distances directly on `data/pfz-today.geojson`. |
| [`_haversine_km`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/subagents/fish_finder.py#L42-L55) | Mathematical Utility | `(lat1: float, lon1: float, lat2: float, lon2: float) -> float` | WGS84 great-circle distance algorithm using mean earth radius `6371.0088 km`. |
| [`mock_fetch_incois_pfz`](file:///D:/work/projects/orca-marine-intelligence/backend/ingest/mock_fetchers.py) | Testing Mock Tool | `(sector: str, center_lat: float, center_lon: float, count: int) -> dict` | Pluggable mock fetcher returning deterministic GeoJSON envelopes for offline simulation and test suites. |

---

### 2.3 Sea Checker Agent (Subagent 2)
* **Source Module**: [`backend/agents/subagents/sea_checker.py`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/subagents/sea_checker.py)
* **Node Name**: `sea_checker` (runs within [`parallel_analysis_node`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/graph.py#L446-L474))
* **Responsibilities**: Wave height and current speed evaluation at candidate PFZ points.
* **Safety Thresholds**:
  * Wave height `< 1.5m` &rarr; `safe`, `1.5m - 2.5m` &rarr; `caution`, `> 2.5m` &rarr; `danger`.
  * Current `> 2.0 kt` &rarr; `caution`, `> 3.0 kt` &rarr; `danger` (current overrides wave).

#### Tools:
| Tool Name | Type | Signature / Purpose | Implementation Details |
| :--- | :--- | :--- | :--- |
| [`fetch_osf_wave_current`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/subagents/sea_checker.py#L190-L206) | Live Ocean Grid Tool (W2) | `async (lat: float, lon: float) -> tuple[float, float]` | OSF/GOFS 06Z forecast fetcher reading Zarr/xarray wave/current numerical model grids. |
| [`_heuristic_wave_height`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/subagents/sea_checker.py#L157-L175) | Deterministic Hash Mock | `(lat: float \| None, lon: float \| None, zone_id: str, idx: int) -> float` | Stable MD5 integer seed producing deterministic mock wave height `[0.3, 3.8] m`. |
| [`_heuristic_current`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/subagents/sea_checker.py#L177-L184) | Deterministic Hash Mock | `(lat: float \| None, lon: float \| None, zone_id: str, idx: int) -> float` | Stable MD5 integer seed producing deterministic mock current `[0.4, 4.0] kt`. |
| [`get_wave_current`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/subagents/sea_checker.py#L208-L235) | Fallback Wrapper Tool | `async (lat, lon, zone_id, idx) -> tuple[float, float, str]` | Tries OSF live data first; on unconfigured/error, seamlessly degrades to heuristic with source tag. |
| [`mock_fetch_osf_ocean_state`](file:///D:/work/projects/orca-marine-intelligence/backend/ingest/mock_fetchers.py) | Scenario Mock Tool | `(zones: list[dict], scenario: str) -> dict` | Supports scenario injection (`normal`, `rough_seas`, `cyclone_warning`, `border_violation`). |

---

### 2.4 Weather Agent (Subagent 3)
* **Source Module**: [`backend/agents/subagents/weather_agent.py`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/subagents/weather_agent.py)
* **Node Name**: `weather_agent` (runs within [`parallel_analysis_node`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/graph.py#L446-L474))
* **Responsibilities**: Wind speed, wind direction, and cyclone proximity detection.
* **Safety Thresholds**:
  * Wind `< 15 kt` &rarr; `safe`, `15 kt - 25 kt` &rarr; `caution`, `> 25 kt` &rarr; `danger`.
  * Active cyclone within `500 km` &rarr; **mandatory danger** overriding wind.

#### Tools:
| Tool Name | Type | Signature / Purpose | Implementation Details |
| :--- | :--- | :--- | :--- |
| [`fetch_imd_wind`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/subagents/weather_agent.py) | Atmospheric Fetcher (W2) | `async (lat: float, lon: float) -> tuple[float, str]` | IMD Mausam API/scraper returning wind speed in knots and 8-point compass direction. |
| [`fetch_imd_cyclones`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/subagents/weather_agent.py#L179-L188) | Storm Warning Feed (W2) | `async () -> list[dict]` | Scrapes active cyclone advisories and storm centers from IMD cyclone bulletin. |
| [`get_cyclone_alert`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/subagents/weather_agent.py#L218-L260) | Proximity Distance Tool | `async (lat, lon, cyclones) -> tuple[bool, float \| None, str \| None, dict \| None]` | Calculates haversine distance to all active storm centers; triggers warning if distance &le; 500 km. |
| [`get_wind`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/subagents/weather_agent.py#L190-L216) | Fallback Wrapper Tool | `async (lat, lon, zone_id, idx) -> tuple[float, str, int \| None, str]` | Extensible wrapper routing to live IMD wind or deterministic mock heuristic. |
| [`mock_fetch_imd_marine_weather`](file:///D:/work/projects/orca-marine-intelligence/backend/ingest/mock_fetchers.py) | Scenario Mock Tool | `(zones: list[dict], scenario: str) -> dict` | Scenario controllable atmospheric mock. |

---

### 2.5 Danger Watch Agent (Subagent 4)
* **Source Module**: [`backend/agents/subagents/danger_agent.py`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/subagents/danger_agent.py)
* **Node Name**: `danger_agent` (runs within [`parallel_analysis_node`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/graph.py#L446-L474))
* **Responsibilities**: International Maritime Boundary Line (IMBL), Marine Protected Areas (MPA), and Indian Exclusive Economic Zone (EEZ) compliance.
* **Safety Invariants**:
  * Inside Marine Protected Area (MPA) &rarr; **`danger` (strictly banned)**.
  * Outside Indian EEZ &rarr; **`danger` (illegal)**.
  * Within `2.0 km` of IMBL or EEZ boundary &rarr; **`caution` (risk of border crossing)**.

#### Tools:
| Tool Name | Type | Signature / Purpose | Implementation Details |
| :--- | :--- | :--- | :--- |
| [`check_geofence`](file:///D:/work/projects/orca-marine-intelligence/backend/db/postgis.py) | PostGIS Geofence Tool | `async (lat: float, lon: float) -> dict` | High-performance PostGIS `ST_Contains` query against `eez_boundaries` and `mpa_boundaries` with 10s timeout. |
| [`_fallback_check_eez`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/subagents/danger_agent.py#L340-L369) | Ray-Casting Spatial Tool | `(lat: float, lon: float) -> tuple[bool, float \| None]` | Ray-casting point-in-polygon verification against cached `data/eez.geojson` multipolygons. |
| [`_fallback_check_mpa`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/subagents/danger_agent.py#L371-L391) | Ray-Casting MPA Tool | `(lat: float, lon: float) -> tuple[bool, str \| None]` | Tests containment against cached `data/mpa.geojson` features, returning MPA name. |
| [`_fallback_distance_to_imbl`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/subagents/danger_agent.py#L393-L411) | Distance-to-Boundary Tool | `(lat: float, lon: float) -> float \| None` | Minimum segment distance calculation to IMBL/EEZ border coordinates to detect 2km buffer. |
| [`fetch_imd_lightning_alert`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/subagents/danger_agent.py#L425-L428) | Severe Weather Stub | `async (lat: float, lon: float) -> dict \| None` | Severe storm and lightning alert integration stub (W2). |
| [`check_safety_batch`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/subagents/danger_agent.py#L671-L680) | Concurrent Point Batcher | `async (points: list) -> list[dict]` | Evaluates shared candidate points concurrently via `asyncio.gather`. |

---

### 2.6 Decision Agent & Smart Combiner
* **Source Module**: [`backend/agents/combiner.py`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/combiner.py), [`backend/agents/lexical_mask.py`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/lexical_mask.py), & [`backend/agents/graph.py`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/graph.py#L328-L440)
* **Node Name**: `decision_agent`
* **Responsibilities**: Multi-factor scoring formula, hard safety veto enforcement, masked vernacular advisory generation, citation and evidence packaging.
* **Deterministic Scoring Formula**:
  $$\text{score} = (\text{closest} \times 0.4) + (\text{safe\_sea} \times 0.3) + (\text{wind\_ok} \times 0.2) + (\text{not\_banned} \times 0.1)$$
  * $\text{closest} = 1.0 - (\text{dist\_km} / \text{max\_dist})$
  * $\text{safe\_sea} = 1.0 \text{ if wave } < 1.5\text{m, else } \max(0.0, 1.0 - (\text{wave} - 1.5)/1.5)$
  * $\text{wind\_ok} = 1.0 \text{ if wind } < 15\text{kt, else } \max(0.0, 1.0 - (\text{wind} - 15)/15)$
  * $\text{not\_banned} = 0.0 \text{ if inside MPA or outside EEZ, else } 1.0$
* **Strict Invariant ("Code Trumps LLM")**:
  * If $\text{not\_banned} == 0.0$ or all spots unsafe &rarr; `all_unsafe = True`, mandatory directive: **`DO NOT SAIL`**. LLM cannot override this rule.

#### Tools:
| Tool Name | Type | Signature / Purpose | Implementation Details |
| :--- | :--- | :--- | :--- |
| [`combine_and_rank`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/combiner.py#L126-L216) | Multi-Factor Combiner Tool | `(fish, sea, weather, danger, user_location, detected_language) -> dict` | Joins specialist outputs on `zone_id`, computes composite scores, evaluates tie-breakers (lower wave &rarr; closer distance), formats evidence and citations. |
| [`MarineGlossaryMasker`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/lexical_mask.py#L56-L90) | Lexical Masker Tool | `mask_text(text: str) -> tuple[str, dict]` | Replaces bearings (`__MBEARING_0__`), knots (`__MKNOTS_0__`), distances (`__MDIST_0__`), and coordinates (`__MCOORD_0__`) with token-safe ASCII tokens before LLM synthesis. |
| `gemini-2.5-flash Advisory Synthesizer` | LLM Synthesizer | `(masked_prompt: str) -> str` | Generates natural language advisory while strictly preserving masked placeholders. Mandatory directive for `DO NOT SAIL` if `all_unsafe=True`. |
| [`unmask_text`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/lexical_mask.py#L58) | Metric Unmasker Tool | `unmask_text(masked_text: str, mask_map: dict) -> str` | Restores original exact numeric values and units into generated text. |
| [`verify_numbers_preserved`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/lexical_mask.py#L65) | Verification Audit Tool | `(original: str, rendered: str) -> bool` | Audits that every number in the ground truth exists identically in rendered advisory without corruption. |
| [`has_regional_digits`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/lexical_mask.py#L64) | Script Purity Tool | `(text: str) -> bool` | Ensures no Indic/regional digits (e.g. Malayalam/Tamil script numbers) corrupted Arabic digits `0-9` (fishermen need Arabic digits for GPS/sonar screens). |
| [`render_grounded_advisory`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/lexical_mask.py#L60) | Vernacular Template Engine | `(lang: str, zone_data: dict, safe_status: str) -> str` | Offline deterministic template grounding engine covering `en`, `ml` (Malayalam), `ta` (Tamil), `te` (Telugu), `hi` (Hindi). |
| [`_badge_for_best`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/orchestrator.py#L107) | Safety Badge Classifier | `(best: dict, sea_s: str, wind_s: str, danger_s: str) -> str` | Produces tri-state badge: `green` (all safe), `amber` (caution/unknown), `red` (danger/DO NOT SAIL). |

---

## 3. Server-Sent Events (SSE) Streaming Sequence

To fulfill the **P95 < 2.0s latency SLA** and the strict ordering contract defined in [`docs/API.md`](file:///D:/work/projects/orca-marine-intelligence/docs/API.md):

```mermaid
sequenceDiagram
    autonumber
    actor Client as Fisherman Client
    participant Router as SSE Stream Router
    participant Planner as Supervisor / Planner
    participant Fish as Fish Finder
    participant Specialists as Parallel Subagents (Sea/Weather/Danger)
    participant Decision as Decision Agent (Combiner + LLM)
    participant Redis as Redis Session Cache

    Client->>Router: POST /api/chat (stream=true)
    Router-->>Client: event: status (agent: planner, state: running)
    Router->>Planner: planner_node(query, location, session_id)
    Planner->>Planner: Geocode / Session Lookup / Tool Selection
    Planner-->>Router: PlannerOutput (selected_tools, target_location)
    Router-->>Client: event: status (agent: planner, state: done)

    Router-->>Client: event: status (agent: fish_finder, state: running)
    Router->>Fish: find_fishing_zones(lat, lon, radius_km=80)
    Fish-->>Router: fish_results (candidate zones)
    Router-->>Client: event: status (agent: fish_finder, state: done)
    Router-->>Client: event: map (center, pfz_features, route) [PROVISIONAL EARLY FLY-TO]

    Router-->>Client: event: status (agent: parallel_analysis, state: running)
    par Concurrent Execution (Send Fan-Out)
        Router->>Specialists: sea_checker.check_sea_conditions(fish_results)
        Router->>Specialists: weather_agent.check_weather(fish_results)
        Router->>Specialists: danger_agent.check_safety_batch(fish_results)
    end
    Specialists-->>Router: merged sea, weather, danger results
    Router-->>Client: event: status (agent: parallel_analysis, state: done)
    Router-->>Client: event: safety (waves_m, wind_kts, danger, badge) [PROVISIONAL SAFETY BADGE]

    Router-->>Client: event: status (agent: decision_agent, state: running)
    Router->>Decision: combine_and_rank() + Masked LLM Synthesizer
    Decision->>Decision: 40/30/20/10 Scoring & Hard Veto Check
    loop on_chat_model_stream (Buffered until Map/Safety emitted)
        Decision-->>Client: event: token (text: "...")
    end
    Router-->>Client: event: status (agent: decision_agent, state: done)

    Router-->>Client: event: evidence (items: ["INCOIS TextData", "Wave: OSF", ...])
    Router->>Redis: save_session(session_id, session_data, ttl=86400)
    Router-->>Client: event: done (confidence: 0.87, session_id: "...")
```

---

## 4. Architectural Invariants Summary

1. **Code Trumps LLM**:
   * PostGIS spatial geofencing and the 40/30/20/10 scoring formula with hard safety veto (`all_unsafe` &rarr; `DO NOT SAIL`) are strictly deterministic. LLM cannot override danger classifications.
2. **No Silent Fallbacks**:
   * LLM errors or timeouts (>500ms) emit explicit SSE `error` events with transparent advisories rather than masking failures with regex guesses.
3. **Arabic Numeral Invariant**:
   * Nautical metrics (knots, degrees, bearings, distances) are masked during translation/synthesis and unmasked to guarantee ASCII Arabic digits `0-9` in all languages (`en`, `ml`, `ta`, `te`, `hi`).
4. **Isolated Subagent Directory**:
   * Subagents reside cleanly in [`backend/agents/subagents/`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/subagents/) with backward-compatible facades in [`backend/agents/__init__.py`](file:///D:/work/projects/orca-marine-intelligence/backend/agents/__init__.py).
5. **Strict Latency Budget**:
   * End-to-end P95 &lt; 2.0s enforced via early provisional map streaming (`flyTo`), 1.4s subagent timeouts, and parallel fan-out.
