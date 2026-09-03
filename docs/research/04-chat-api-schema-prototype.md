# Prototype: Chat API Contract with Localized Advisory Payload

**Ticket:** [#5 Prototype End-to-End Chat API Contract with Localized Advisory Payload](https://github.com/parth5012/orca-marine-intelligence/issues/5)  
**Target Codebase:** `backend/routers/chat.py` (M-C), `backend/agents/orchestrator.py` (M-A), `frontend/chat/ChatPanel.tsx` (M-E)  
**Type:** API Architecture & Data Contract Prototype

---

## 1. Overview in Plain Terms

When a fisherman asks a question in chat (e.g., *"കൊച്ചിക്ക് അടുത്ത് മീൻ എവിടെ?"* or Romanized *"kochi aduth meen evideya?"*), the frontend sends a simple package of data to the backend.

The backend processes the question, checks the satellite and marine databases, and replies with:
1. **The Regional Answer (`reply`)**: A natural, friendly advisory written in the fisherman's language and native script.
2. **The Language Info (`language_meta`)**: What language and script were detected.
3. **The Quick Fact Cards (`cards`)**: Exact, uncorrupted numbers (distance in km, compass bearing in degrees, wave height in meters, wind speed in knots) so the UI can display clean visual badges.
4. **The Map Trigger (`map`)**: The GPS coordinates of the recommended spot and a route line, so the map automatically zooms and flies to the spot.
5. **The Proof Citations (`evidence`)**: Official government source notes (e.g. INCOIS TextData, Indian EEZ verification) proving the advice is trustworthy.

---

## 2. Request Contract (Frontend -> Backend)

### Python Pydantic Model (`backend/routers/chat.py`)
```python
from pydantic import BaseModel, Field
from typing import Optional

class ChatRequest(BaseModel):
    message: str = Field(..., description="The user query in any of the 22 Indian regional languages or Romanized text.")
    lat: Optional[float] = Field(None, description="Current GPS latitude of boat or port (optional).")
    lon: Optional[float] = Field(None, description="Current GPS longitude of boat or port (optional).")
    session_id: Optional[str] = Field(None, description="Session ID for multi-turn conversation memory.")
    language_hint: Optional[str] = Field(None, description="Optional manual language override from LanguageSwitch (e.g. 'ml', 'ta').")
```

### Example Request JSON:
```json
{
  "message": "kochi aduth meen evideya?",
  "lat": 9.9312,
  "lon": 76.2673,
  "session_id": "sess-user-001",
  "language_hint": null
}
```

---

## 3. Response Contract (Backend -> Frontend)

### Python Pydantic Model (`backend/routers/chat.py`)
```python
from pydantic import BaseModel, Field
from typing import List, Optional

class MapPoint(BaseModel):
    center: List[float] = Field(..., description="[longitude, latitude] of recommended spot to center the map.")
    zoom: int = Field(default=11, description="Recommended map zoom level.")
    route: Optional[List[List[float]]] = Field(None, description="List of [lon, lat] points forming the navigation path.")
    spot_name: str = Field(..., description="Name of the fishing zone or landmark.")

class SafetyCards(BaseModel):
    badge: str = Field(..., description="'green' (Safe), 'yellow' (Caution), or 'red' (Danger).")
    status_label: str = Field(..., description="Localized status tag (e.g. 'സുരക്ഷിതം (Safe)').")
    distance_km: float = Field(..., description="Distance in kilometers from user.")
    bearing_deg: int = Field(..., description="Compass bearing (0-360 degrees).")
    direction_text: str = Field(..., description="Localized compass direction (e.g. 'തെക്ക്-പടിഞ്ഞാറ് (SW)').")
    waves_m: float = Field(..., description="Significant wave height in meters.")
    wind_kts: float = Field(..., description="Wind speed in knots.")
    is_safe_to_sail: bool = Field(..., description="True if safe to sail, False if captain should stay back.")

class LanguageMeta(BaseModel):
    detected_language: str = Field(..., description="ISO 639-1 code: 'ml', 'ta', 'te', 'hi', etc.")
    detected_script: str = Field(..., description="'native' or 'roman'.")
    confidence: float = Field(..., description="Detection confidence score from 0.0 to 1.0.")
    provider_used: str = Field(..., description="'llm', 'sarvam', or 'bhashini'.")

class ChatResponse(BaseModel):
    reply: str = Field(..., description="Natural language advisory synthesized in the user's native script.")
    cards: SafetyCards = Field(..., description="Exact numerical facts for visual card display.")
    map: MapPoint = Field(..., description="Map coordinates for automatic flyTo and pin display.")
    evidence: List[str] = Field(..., description="Official government and satellite data proof points.")
    language_meta: LanguageMeta = Field(..., description="Language identification details.")
    session_id: str = Field(..., description="Active session ID for follow-up questions.")
```

---

## 4. Concrete Example Response Payload

Here is exactly what the backend returns for the query *"kochi aduth meen evideya?"*:

```json
{
  "reply": "[സുരക്ഷിതം (Safe)] കൊച്ചിയിൽ നിന്ന് 14 km തെക്ക്-പടിഞ്ഞാറ് (SW, ബെയറിംഗ് 232°) പള്ളിത്തോട്ടം ഭാഗത്ത് മീൻസാന്നിധ്യം (മത്തി, അയല) കണ്ടെത്തിയിട്ടുണ്ട്. തിരമാല 0.8 മീറ്റർ, കാറ്റ് 8 നോട്ട് മാത്രമാണ്. ബോർഡർ പ്രശ്നങ്ങളോ കൊടുങ്കാറ്റ് മുന്നറിയിപ്പോ ഇല്ല. ഇന്ന് കടലിൽ പോകുന്നത് തികച്ചും സുരക്ഷിതമാണ്.",
  "cards": {
    "badge": "green",
    "status_label": "സുരക്ഷിതം (Safe)",
    "distance_km": 14.2,
    "bearing_deg": 232,
    "direction_text": "തെക്ക്-പടിഞ്ഞാറ് (SW)",
    "waves_m": 0.8,
    "wind_kts": 8.0,
    "is_safe_to_sail": true
  },
  "map": {
    "center": [76.167, 8.555],
    "zoom": 11,
    "route": [
      [76.2673, 9.9312],
      [76.167, 8.555]
    ],
    "spot_name": "Pallithottam PFZ"
  },
  "evidence": [
    "INCOIS TextData SEC005 (Kerala Sector, 02-Sep-2026)",
    "OSF Wave Height: 0.8m (Safe threshold <1.5m)",
    "IMD Wind Speed: 8 kts (Safe threshold <15 kts)",
    "Geofence Check: 42 km inside Indian Exclusive Economic Zone (EEZ)"
  ],
  "language_meta": {
    "detected_language": "ml",
    "detected_script": "roman",
    "confidence": 0.98,
    "provider_used": "llm"
  },
  "session_id": "sess-user-001"
}
```

---

## 5. UI Consumption Prototype (TypeScript in `frontend/chat/ChatPanel.tsx`)

In the React Chat UI, Member E renders both the conversational message and visual badges directly from `cards`:

```tsx
// Frontend ChatPanel message renderer snippet
function AdvisoryMessage({ data }: { data: ChatResponse }) {
  return (
    <div className="flex flex-col gap-3 p-4 rounded-xl bg-slate-900 border border-slate-800 text-white">
      {/* 1. Status Badge Header */}
      <div className="flex items-center justify-between">
        <span className={`px-3 py-1 text-xs font-bold rounded-full ${
          data.cards.badge === 'green' ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' :
          data.cards.badge === 'yellow' ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30' :
          'bg-rose-500/20 text-rose-400 border border-rose-500/30'
        }`}>
          {data.cards.status_label}
        </span>
        <span className="text-xs text-slate-400 uppercase tracking-wider">
          Lang: {data.language_meta.detected_language} ({data.language_meta.provider_used})
        </span>
      </div>

      {/* 2. Natural Regional Advisory Text */}
      <p className="text-sm leading-relaxed font-sans">{data.reply}</p>

      {/* 3. Numerical Fact Cards Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-2 border-t border-slate-800 text-xs">
        <div className="bg-slate-800/60 p-2 rounded-lg">
          <div className="text-slate-400">Distance</div>
          <div className="font-semibold text-slate-100">{data.cards.distance_km} km</div>
        </div>
        <div className="bg-slate-800/60 p-2 rounded-lg">
          <div className="text-slate-400">Bearing</div>
          <div className="font-semibold text-slate-100">{data.cards.bearing_deg}° {data.cards.direction_text}</div>
        </div>
        <div className="bg-slate-800/60 p-2 rounded-lg">
          <div className="text-slate-400">Wave Height</div>
          <div className="font-semibold text-slate-100">{data.cards.waves_m} m</div>
        </div>
        <div className="bg-slate-800/60 p-2 rounded-lg">
          <div className="text-slate-400">Wind Speed</div>
          <div className="font-semibold text-slate-100">{data.cards.wind_kts} kts</div>
        </div>
      </div>

      {/* 4. Evidence Citations Accordion */}
      <details className="text-[11px] text-slate-400 pt-1">
        <summary className="cursor-pointer hover:text-slate-300 font-medium">
          Evidence & Data Sources ({data.evidence.length})
        </summary>
        <ul className="list-disc pl-4 mt-1 space-y-0.5 text-slate-500">
          {data.evidence.map((item, idx) => (
            <li key={idx}>{item}</li>
          ))}
        </ul>
      </details>
    </div>
  );
}
```