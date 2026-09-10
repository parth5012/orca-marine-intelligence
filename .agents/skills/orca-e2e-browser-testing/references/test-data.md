# ORCA E2E Test Data — Sample Inputs & Expected Outputs

Reference data for browser-based testing. Use these exact values when
executing test cases to ensure deterministic validation.

---

## 1. Coordinate Test Vectors

### Valid Indian Coastal Coordinates
| Label | Lat | Lon | Expected Sector | Expected Center |
|-------|-----|-----|-----------------|-----------------|
| Kochi Harbor | 9.9312 | 76.2673 | SEC005 (KERALA) | [9.93, 76.27] |
| Munambam | 10.1750 | 76.1690 | SEC005 (KERALA) | [10.18, 76.17] |
| Veraval | 20.9070 | 70.3680 | SEC001 (GUJARAT) | [20.91, 70.37] |
| Mumbai (Gateway) | 18.9220 | 72.8347 | SEC002 (MAHARASHTRA) | [18.92, 72.83] |
| Chennai | 13.0827 | 80.2707 | SEC007 (TAMIL NADU) | [13.08, 80.27] |
| Mangalore | 12.8700 | 74.8400 | SEC004 (KARNATAKA) | [12.87, 74.84] |
| Vizag | 17.6868 | 83.2185 | SEC008 (ANDHRA PRADESH) | [17.69, 83.22] |
| Porbandar | 21.6417 | 69.6293 | SEC001 (GUJARAT) | [21.64, 69.63] |
| Tuticorin | 8.7642 | 78.1348 | SEC007 (TAMIL NADU) | [8.76, 78.13] |
| Paradip | 20.3167 | 86.6100 | SEC009 (ODISHA) | [20.32, 86.61] |
| Digha | 21.6280 | 87.5100 | SEC010 (WEST BENGAL) | [21.63, 87.51] |
| Mormugao (Goa) | 15.4909 | 73.8278 | SEC003 (GOA) | [15.49, 73.83] |

### Swapped (lon, lat) Coordinates — Should Auto-Correct
| Input | Should Resolve To | Reason |
|-------|-------------------|--------|
| 76.27, 9.93 | [9.93, 76.27] | lat > 50 && lon < 40 swap heuristic |
| 72.83, 18.92 | [18.92, 72.83] | Mumbai swapped |
| 70.37, 20.91 | [20.91, 70.37] | Veraval swapped |

### Invalid / Edge Coordinates
| Input | Expected Behavior |
|-------|-------------------|
| 999.0, 999.0 | Error banner or clamped to [-90..90, -180..180] |
| NaN, NaN | Fallback to Kochi default |
| Infinity, 76.27 | Fallback to Kochi default |
| 0.0, 0.0 | Centers on Null Island (Gulf of Guinea) |
| -90.0, 180.0 | Valid extreme: South Pole edge, date line |
| 91.0, 181.0 | Out of bounds — clamped or error |

### Port Name Search Strings
| Input | Expected Match | Expected Center |
|-------|----------------|-----------------|
| Kochi | Kochi port | [9.93, 76.27] |
| Veraval | Veraval port | [20.91, 70.37] |
| Chennai | Chennai port | [13.08, 80.27] |
| Mumbai | Mumbai port | [18.92, 72.83] |
| Mangalore | Mangalore port | [12.87, 74.84] |
| Vizag | Vizag port | [17.69, 83.22] |
| xyzabc123 | No match | Error banner shown |
| Atlantis | No match | Error banner shown |
| "" (empty) | No action | Nothing happens |

---

## 2. Chat Query Test Vectors

### Valid Queries — Expected to Return Advisory
| Query | Expected Response Content |
|-------|--------------------------|
| Where are the nearest fishing zones near Kochi today? | PFZ coordinates, zone cards, safety badge |
| What is the current wind and wave weather advisory? | Wave height (m), wind speed (kts), safety classification |
| Is it safe for a small motorized boat to sail right now? | Safety assessment (SAFE/CAUTION/DANGER) with reasoning |
| Are there any cyclone or high-wave alerts for Kerala coast? | Cyclone status (active/none), wave alert |
| Check PFZ fishing coordinates near Munambam. | PFZ points near Munambam with bearing and distance |
| मछली कहाँ है? (Hindi: Where are fish?) | Advisory in Hindi or bilingual response |
| കൊച്ചിയിൽ മീൻ എവിടെ? (Malayalam: Where is fish in Kochi?) | Advisory in Malayalam or bilingual response |

### Input Validation — Should be Blocked or Handled
| Input | Expected Behavior |
|-------|-------------------|
| "" (empty) | Send button disabled |
| "   " (spaces only) | Send button disabled |
| `<script>alert('xss')</script>` | Sanitized, no XSS execution |
| `<img src=x onerror=alert(1)>` | Sanitized, no XSS execution |
| A string of 2000+ chars | Accepted, no crash, backend processes |

---

## 3. Sector Dropdown Values

| Dropdown Label | Value | Center Lat | Center Lon | Zoom |
|----------------|-------|-----------|-----------|------|
| All India Coastal Sectors | ALL | 13.0 | 78.0 | 6 |
| Kerala (SEC005) | KERALA | 9.93 | 76.27 | 9 |
| Maharashtra (SEC002) | MAHARASHTRA | 18.92 | 72.83 | 8 |
| Tamil Nadu (SEC007) | TAMIL NADU | 11.5 | 79.8 | 8 |
| Gujarat (SEC001) | GUJARAT | 21.0 | 70.0 | 8 |
| Karnataka (SEC004) | KARNATAKA | 13.5 | 74.5 | 8 |
| Goa (SEC003) | GOA | 15.49 | 73.82 | 9 |
| Andhra Pradesh (SEC008) | ANDHRA PRADESH | 16.5 | 82.5 | 8 |
| Odisha (SEC009) | ODISHA | 19.8 | 86.0 | 8 |
| West Bengal (SEC010) | WEST BENGAL | 21.5 | 88.0 | 8 |

---

## 4. Language Codes & Native Scripts

| Code | Name | Native | Region | Chat Placeholder |
|------|------|--------|--------|-----------------|
| en | English | English | Pan-India | "Ask ORCA about fishing zones, weather, or safety..." |
| ml | Malayalam | മലയാളം | Kerala & Lakshadweep | (Localized Malayalam text) |
| ta | Tamil | தமிழ் | Tamil Nadu & Puducherry | (Localized Tamil text) |
| hi | Hindi | हिन्दी | Northern / Central | (Localized Hindi text) |
| te | Telugu | తెలుగు | Andhra Pradesh & Telangana | (Localized Telugu text) |
| gu | Gujarati | ગુજરાતી | Gujarat (Veraval / Porbandar) | (Localized Gujarati text) |
| bn | Bengali | বাংলা | West Bengal & Andaman | (Localized Bengali text) |
| kn | Kannada | ಕನ್ನಡ | Karnataka (Mangalore) | (Localized Kannada text) |
| mr | Marathi | मराठी | Maharashtra (Mumbai / Ratnagiri) | (Localized Marathi text) |
| or | Odia | ଓଡ଼ିଆ | Odisha (Paradip / Puri) | (Localized Odia text) |

---

## 5. Layer Toggle Test IDs

| Layer | Toggle Button Test ID | Initial State | Active Style | Inactive Style |
|-------|----------------------|---------------|-------------|----------------|
| PFZ | `layer-toggle-pfz` | ON (`aria-pressed="true"`) | Green (`bg-emerald-950`) | Grey (`bg-slate-950 opacity-60`) |
| EEZ | `layer-toggle-eez` | ON | Blue (`bg-sky-950`) | Grey |
| MPA | `layer-toggle-mpa` | ON | Red (`bg-red-950`) | Grey |
| IMBL | `layer-toggle-imbl` | ON | Orange (`bg-orange-950`) | Grey |
| Weather | `layer-toggle-weather` | ON | Cyan (`bg-cyan-950`) | Grey |

---

## 6. Safety Badge States

| Condition | Badge Color | Badge Text | Wave Threshold | Wind Threshold |
|-----------|-------------|-----------|----------------|----------------|
| Safe | Green (emerald) | SAFE | < 2.0 m | < 20 kts |
| Caution | Amber (yellow) | CAUTION | 2.0 - 4.0 m | 20 - 35 kts |
| Danger | Red | DO NOT SAIL | > 4.0 m | > 35 kts |
| Cyclone | Red (pulsing) | CYCLONE ALERT | Any | Any |

---

## 7. API Response Shapes

### GET /api/pfz/today — Success
```json
{
  "type": "FeatureCollection",
  "valid_until": "2026-09-10T18:00:00+00:00",
  "source": "incois_textdata",
  "sector_count": 5,
  "count": 42,
  "metadata": {
    "valid_until": "...",
    "source": "incois_textdata",
    "sector_count": 5,
    "count": 42
  },
  "features": [
    {
      "type": "Feature",
      "geometry": {"type": "Point", "coordinates": [76.27, 9.93]},
      "properties": {
        "sector": "SEC005",
        "sector_name": "KERALA",
        "place": "Off Kochi",
        "bearing": 232,
        "dir": "SW",
        "distance": 25,
        "depth_m": 40,
        "suitability": "HIGH"
      }
    }
  ]
}
```

### GET /api/geofence/status — Success
```json
{
  "status": "ok",
  "active_mpas": ["Gulf of Mannar National Park", "Gahirmatha Marine Sanctuary"],
  "eez_zones": ["India Mainland EEZ", "Andaman & Nicobar EEZ"],
  "imbl_buffer_km": 2.0,
  "imbl_caution_threshold_km": 5.0,
  "eez_caution_threshold_km": 10.0,
  "count_protected_boundaries": 4,
  "protected_boundaries_count": 4,
  "boundary_counts": {"eez": 2, "mpa": 2, "total": 4}
}
```

### POST /api/chat — SSE Events
```
event: reasoning
data: {"type":"reasoning","agent":"planner","status":"running","message":"Analyzing query..."}

event: reasoning
data: {"type":"reasoning","agent":"fish_finder","status":"done","message":"Found 5 PFZ zones","latency_ms":124}

event: token
data: {"type":"token","text":"Based on "}

event: token
data: {"type":"token","text":"today's INCOIS data..."}

event: done
data: {"type":"done","reply":"Based on today's INCOIS data...","session_id":"abc123","zones":[...]}
```
