# Coastal Marine Terminology Dictionary & Prompt Grounding Specification

**Ticket:** [#4 Design Coastal Marine Terminology Dictionary & Prompt Grounding Constraints](https://github.com/parth5012/orca-marine-intelligence/issues/4)  
**Target Codebase:** `backend/agents/orchestrator.py`, `backend/agents/combiner.py`  
**Domain:** ISRO SIH26176 — Coastal Marine Fishing & Safety Advisory  
**Owners:** M-A (Agents & Orchestration)

---

## 1. Major Coastal Landing Centers & Ports Registry

The system injects this canonical dictionary to extract GPS coordinates when fishermen ask questions mentioning local harbors or landing centers.

```json
{
  "ports": {
    "Kochi": {
      "coords": [9.9312, 76.2673],
      "state": "Kerala",
      "aliases": {
        "ml": ["കൊച്ചി", "കൊച്ചിൻ", "തോപ്പുംപടി", "മുനമ്പം"],
        "roman": ["kochi", "cochin", "munambam", "thoppumpady"]
      }
    },
    "Kollam": {
      "coords": [8.8932, 76.6141],
      "state": "Kerala",
      "aliases": {
        "ml": ["കൊല്ലം", "നീണ്ടകര", "ശക്തികുളങ്ങര"],
        "roman": ["kollam", "quilon", "neendakara", "shaktikulangara"]
      }
    },
    "Beypore": {
      "coords": [11.1816, 75.8078],
      "state": "Kerala",
      "aliases": {
        "ml": ["ബേപ്പൂർ", "കോഴിക്കോട്"],
        "roman": ["beypore", "kozhikode", "calicut"]
      }
    },
    "Chennai": {
      "coords": [13.0827, 80.2707],
      "state": "Tamil Nadu",
      "aliases": {
        "ta": ["சென்னை", "காசிமேடு", "ராயபுரம்"],
        "roman": ["chennai", "kasimedu", "madras"]
      }
    },
    "Kanyakumari": {
      "coords": [8.0883, 77.5385],
      "state": "Tamil Nadu",
      "aliases": {
        "ta": ["கன்னியாகுமரி", "குளச்சல்", "முட்டம்"],
        "roman": ["kanyakumari", "colachel", "muttom"]
      }
    },
    "Thoothukudi": {
      "coords": [8.7642, 78.1348],
      "state": "Tamil Nadu",
      "aliases": {
        "ta": ["தூத்துக்குடி", "டூட்டிகோரினா"],
        "roman": ["thoothukudi", "tuticorin"]
      }
    },
    "Visakhapatnam": {
      "coords": [17.6868, 83.2185],
      "state": "Andhra Pradesh",
      "aliases": {
        "te": ["విశాఖపట్నం", "వైజాగ్", "భీమునిపట్నం"],
        "roman": ["visakhapatnam", "vizag", "bheemunipatnam"]
      }
    },
    "Mangalore": {
      "coords": [12.9141, 74.8560],
      "state": "Karnataka",
      "aliases": {
        "kn": ["ಮಂಗಳೂರು", "ಮಲ್ಪೆ", "ಕಾರವಾರ"],
        "roman": ["mangalore", "mangaluru", "malpe", "karwar"]
      }
    },
    "Mumbai": {
      "coords": [18.9220, 72.8347],
      "state": "Maharashtra",
      "aliases": {
        "mr": ["मुंबई", "ससून डॉक", "भाऊचा धक्का", "वर्सोवा"],
        "roman": ["mumbai", "sassoon dock", "bhaucha dhakka", "versova"]
      }
    },
    "Veraval": {
      "coords": [20.9077, 70.3666],
      "state": "Gujarat",
      "aliases": {
        "gu": ["વેરાવળ", "સોમનાથ", "પોરબંદર"],
        "roman": ["veraval", "somnath", "porbandar"]
      }
    },
    "Paradip": {
      "coords": [20.3164, 86.6114],
      "state": "Odisha",
      "aliases": {
        "or": ["ପାରାଦୀପ", "ଚାନ୍ଦବାଲି", "ଗୋପାଳପୁର"],
        "roman": ["paradip", "chandbali", "gopalpur"]
      }
    },
    "Digha": {
      "coords": [21.6266, 87.5074],
      "state": "West Bengal",
      "aliases": {
        "bn": ["দিঘা", "শঙ্করপুর", "কাকদ্বীপ"],
        "roman": ["digha", "shankarpur", "kakdwip"]
      }
    }
  }
}
```

---

## 2. Multi-Language Coastal Fish Species Glossary

To prevent generic machine translation from inventing strange names, the system maps common commercial marine species to authentic coastal market vernacular:

| Commercial Fish | Malayalam (`ml`) | Tamil (`ta`) | Telugu (`te`) | Marathi (`mr`) | Gujarati (`gu`) | Hindi (`hi`) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Indian Oil Sardine** | മത്തി (*Mathi*) | மத்தி / கவலை (*Mathi*) | కవ్వాలు (*Kavvalu*) | तारली (*Tarli*) | તારલી (*Tarli*) | तारली (*Tarli*) |
| **Indian Mackerel** | അയല (*Ayala*) | காணாங்கெளுத்தி / அயலை | కనగర్తలు (*Kanagarthalu*) | बांगडा (*Bangda*) | બાંગડા (*Bangda*) | बांगड़ा (*Bangda*) |
| **Yellowfin Tuna** | കേര / ചൂര (*Choora*) | சூரை (*Soorai*) | సూర చేప (*Soora*) | कुपा / गेदर (*Kupa*) | કુપા (*Kupa*) | टूना (*Tuna*) |
| **Kingfish / Seer Fish** | നെയ്മീൻ (*Neymeen*) | வஞ்சிரம் (*Vanjaram*) | వంజరం (*Vanjaram*) | सुरमई (*Surmai*) | સુરમઈ (*Surmai*) | सुरमई (*Surmai*) |
| **Silver Pomfret** | വെളുത്ത ആവോലി (*Avoli*) | வவ்வால் (*Vavval*) | చందమామ చేపలు (*Chandamama*) | पापलेट (*Paplet*) | પાપલેટ (*Paplet*) | हलवा / पापलेट (*Paplet*) |
| **Tiger Prawn / Shrimp** | കൊഞ്ച് / ചെമ്മീൻ (*Chemmeen*) | இறால் (*Iraal*) | రొయ్యలు (*Royyalu*) | कोळंबी (*Kolambi*) | ઝીંગા (*Zinga*) | झींगा (*Jheenga*) |
| **Anchovy** | കൊഴുcompound / നത്തോലി (*Natholi*) | நெத்திலி (*Nethili*) | నెత్తళ్ళు (*Nethallu*) | काटेली (*Kateli*) | કાટેલી (*Kateli*) | नेथोली (*Netholi*) |
| **Calamari / Squid** | കൂന്തൽ / കണവ (*Kanava*) | கணவாய் (*Kanavai*) | కలమారి (*Kalamari*) | मोंडळी / माकुळ (*Makul*) | માંકડ (*Makad*) | स्क्विड (*Squid*) |
| **Snapper** | ചെമ്പല്ലി (*Chempalli*) | செங்கனி (*Senganai*) | తాంబెలు (*Thambelu*) | तांबोशी (*Tamboshi*) | રાતી માછલી (*Rati Machhli*)| लाल मछली (*Lal Machli*) |

---

## 3. Nautical Numbers, Units & Direction Grounding Rules

1. **Standard International Digits**:
   - Always use standard Arabic numerals (`0-9`) for coordinates, bearings, and measurements (e.g. `14 km`, `1.2 m`, `232°`, `12 knots`).
   - Never convert numbers to local regional script digits (e.g., avoid `൧൪` or `१४`) so fishermen can cross-reference boat GPS and fish-finder screens.
2. **Direction Terminology**:
   - Combine international compass abbreviation with clear local words:
     - **NE (North-East)**: Malayalam `വടക്ക്-കിഴക്ക് (NE)`, Tamil `வடகிழக்கு (NE)`, Telugu `ఈశాన్యం (NE)`, Hindi `उत्तर-पूर्व (NE)`
     - **NW (North-West)**: Malayalam `വടക്ക്-പടിഞ്ഞാറ് (NW)`, Tamil `வடமேற்கு (NW)`, Telugu `వాయువ్యం (NW)`, Hindi `उत्तर-पश्चिम (NW)`
     - **SE (South-East)**: Malayalam `തെക്ക്-കിഴക്ക് (SE)`, Tamil `தென்கிழக்கு (SE)`, Telugu `ఆగ్నేయం (SE)`, Hindi `दक्षिण-पूर्व (SE)`
     - **SW (South-West)**: Malayalam `തെക്ക്-പടിഞ്ഞാറ് (SW)`, Tamil `தென்மேற்கு (SW)`, Telugu `నైరుతి (SW)`, Hindi `दक्षिण-पश्चिम (SW)`
3. **Compass Bearing Protection**:
   - State bearing as an explicit azimuth direction:
     - Malayalam: `ബെയറിംഗ് 240° ദിശയിൽ`
     - Tamil: `திசைக்கோணம் 240° திசையில்`
     - Telugu: `బేరింగ్ 240° దిశలో`
     - Hindi: `दिशा कोण 240° की ओर`

---

## 4. Standardized 3-Tier Safety Vocabulary

| Tier | Meaning | Malayalam (`ml`) | Tamil (`ta`) | Telugu (`te`) | Hindi (`hi`) | Marathi (`mr`) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Safe (Green)** | Waves <1.5m, wind <15kts, safe inside EEZ | **സുരക്ഷിതം (Safe)** | **பாதுகாப்பானது (Safe)** | **సురక్షితం (Safe)** | **सुरक्षित (Safe)** | **सुरक्षित (Safe)** |
| **Caution (Yellow)** | Waves 1.5–2.5m, wind 15–22kts, near EEZ | **ജാഗ്രത (Caution)** | **எச்சரிக்கை (Caution)** | **హెచ్చరిక (Caution)** | **सावधानी (Caution)** | **सावधगिरी (Caution)** |
| **Danger (Red)** | Waves >2.5m, cyclone warning, IMBL border | **അപകടകരം (Danger)** | **ஆபத்தானது (Danger)** | **ప్రమాదకరం (Danger)** | **खतरनाक (Danger)** | **धोकादायक (Danger)** |

Actionable closing sentence rule:
- **Safe**: "കടലിൽ പോകുന്നത് സുരക്ഷിതമാണ്." (It is safe to set sail.)
- **Caution**: "ജാഗ്രത പാലിക്കുക, ചെറിയ ബോട്ടുകൾ കടലിൽ പോകരുത്." (Exercise caution; small craft should stay back.)
- **Danger**: "കടലിൽ പോകരുത്! കാലാവസ്ഥ മോശമാണ്." (Do NOT venture into sea! Severe conditions.)

---

## 5. Production Grounded Prompt Template

Below is the structured prompt template implemented in `backend/agents/combiner.py`:

```markdown
You are ORCA, an intelligent marine advisory assistant built for Indian fishermen.
The user asked a query in {detected_language} ({script}).
Synthesize the multi-agent findings below into a clear, supportive advisory in {detected_language} native script.

GROUND TRUTH METRICS (DO NOT MODIFY OR ESTIMATE NUMBERS):
- Target Port / Reference Place: {port_name} ({lat}, {lon})
- Nearest Safe PFZ Point: {distance_km} km away, Bearing {bearing_deg}° ({direction_text})
- Sea State: Wave height {wave_height_m} m, Sea condition: {sea_status}
- Weather: Wind speed {wind_speed_kts} knots, Cyclone threat: {cyclone_status}
- Geofence & Border: {danger_status} (Distance to EEZ boundary: {eez_distance_km} km)
- Expected Fish Species: {species_list}
- Overall Safety Status: {overall_safety} (SAFE | CAUTION | DANGER)

STRICT FORMATTING RULES:
1. Always write numbers in international digits: "{distance_km} km", "{bearing_deg}°", "{wave_height_m} m", "{wind_speed_kts} knots".
2. Use the local fish names from the coastal dictionary: {localized_species_names}.
3. Use the standardized safety tag at the top: [{localized_safety_status}].
4. End with a single clear, direct safety recommendation on whether it is safe to sail today.
5. Do not include introductory fluff ("Hello", "As an AI"). Be direct, respectful, and nautical.
```