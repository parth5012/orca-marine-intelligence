"""
ORCA Conversational Router — chitchat vs marine subgraph gate.

Owner: M-A (Agents & Orchestration)
Module: backend/agents/conversational_router.py

Lets the planner behave like a normal chatbot: greetings, thanks,
help, identity questions are answered directly WITHOUT running the
expensive PFZ multi-agent pipeline (PostGIS/OSF/IMD/combiner).

Only marine-intent queries (PFZ find/details, weather, waves, wind,
cyclone, safety/sail, tide, SST/chlorophyll, route, geofence/EEZ/MPA,
port names, GPS coords) route to the full marine subgraph
(planner -> fish_finder -> sea/weather/danger -> decision).

Design: deterministic <1ms gate (no LLM) so chitchat never pays the
5s planner SLA. Marine keywords always win over chitchat patterns.
Chitchat replies are canned vernacular (no coords/metrics invented).

Envelope: helpers return plain values per AGENTS.md 3.2 where useful.
"""

from __future__ import annotations

import re

# Marine intent wins over chitchat — if any of these match, route=marine.
_MARINE_RE = re.compile(
    r"(pfz|fish|fishing|catch|zone|coord|weather|wave|wind|cyclone|storm|"
    r"safety|safe|sail|tide|sst|chlorophyll|temperature|route|geofence|"
    r"eez|mpa|imb|harbor|harbour|port|sea|ocean|marine|advisory|alert|"
    r"kochi|munambam|beypore|kollam|vizag|visakhapatnam|veraval|chennai|"
    r"\b\d{1,2}\.\d+\s*,\s*\d{1,3}\.\d+)",
    re.IGNORECASE,
)

# Pure chitchat / help / identity / small-talk — only when NO marine keyword present.
_CHITCHAT_RES = [
    re.compile(r"^(hi+|hello+|hey+|namaste|namaskaram|vanakkam)\b", re.IGNORECASE),
    re.compile(r"\b(thank|thanks|nanni|nanri|nandri|dhanyavad)\b", re.IGNORECASE),
    re.compile(r"\b(bye|good\s?(morning|evening|night))\b", re.IGNORECASE),
    re.compile(r"\b(who are you|what are you|your name|about you|നീ ആരാണ്|நீ யார்|నీవు ఎవరు|तुम कौन|आप कौन)\b", re.IGNORECASE),
    re.compile(r"\b(what can you do|help|how (do|can)|സഹായം|உதவி|సహాయం|मदद (you|i) (work|use)|commands)\b", re.IGNORECASE),
    re.compile(r"^(ok|okay|yes|no|alright|sure)\.?$", re.IGNORECASE),
    # small-talk: how's life / how are you / what's up (no marine keywords by then)
    re.compile(r"\bhow'?s (life|it going|things|you|your day)\b", re.IGNORECASE),
    re.compile(r"\bhow (are|r) (you|u|things)\b", re.IGNORECASE),
    re.compile(r"^(what'?s up|sup|howdy|yo)\b", re.IGNORECASE),
    # native-script small-talk (ml/ta/te/hi) — Latin patterns above miss these
    re.compile(r"(നമസ്കാരം|നന്ദി|വിട|സഹായം|നീ ആരാണ്)", re.IGNORECASE),
    re.compile(r"(வணக்கம்|நன்றி|பிரியாவிடை|உதவி|நீ யார்)", re.IGNORECASE),
    re.compile(r"(నమస్కారం|ధన్యవాదాలు|వీడ్కోలు|సహాయం|నీవు ఎవరు)", re.IGNORECASE),
    re.compile(r"(नमस्ते|धन्यवाद|शुक्रिया|अलविदा|मदद|तुम कौन|आप कौन)", re.IGNORECASE),
]

_CHITCHAT_REPLIES: dict[str, dict[str, str]] = {
    "greet": {
        "en": "Hello! I'm ORCA, your marine fishing assistant. Ask me where to find fish (e.g. 'Fish near Kochi today?'), or about waves, wind, cyclones and sailing safety.",
        "ml": "നമസ്കാരം! ഞാൻ ORCA ആണ്, നിങ്ങളുടെ കടൽ മീൻപിടിത്ത സഹായി. 'കൊച്ചിക്ക് സമീപം ഇന്ന് മീൻ എവിടെ?' എന്ന് ചോദിക്കൂ, അല്ലെങ്കിൽ തിരമാല, കാറ്റ്, ചുഴലിക്കാറ്റ്, സുരക്ഷ എന്നിവയെക്കുറിച്ച് ചോദിക്കൂ.",
        "ta": "வணக்கம்! நான் ORCA, உங்கள் கடல் மீன்பிடி உதவியாளர். 'கொச்சி அருகே இன்று மீன் எங்கே?' என்று கேளுங்கள், அல்லது அலை, காற்று, புயல், பாதுகாப்பு பற்றி கேளுங்கள்.",
        "te": "నమస్కారం! నేను ORCA, మీ సముద్ర చేపల సహాయకుడిని. 'కొచ్చి దగ్గర ఈరోజు చేపలు ఎక్కడ?' అని అడగండి, లేదా అలలు, గాలి, తుఫాను, భద్రత గురించి అడగండి.",
        "hi": "नमस्ते! मैं ORCA हूँ, आपका समुद्री मत्स्य सहायक। पूछें 'आज कोच्चि के पास मछली कहाँ है?', या लहरों, हवा, चक्रवात और नौकायन सुरक्षा के बारे में पूछें।",
    },
    "thanks": {
        "en": "You're welcome! Stay safe at sea — ask me anytime for fresh PFZ zones or a safety check before you sail.",
        "ml": "സന്തോഷം! കടലിൽ സുരക്ഷിതമായിരിക്കൂ — പുതിയ PFZ മേഖലകൾക്കോ കടലിൽ പോകുന്നതിന് മുമ്പുള്ള സുരക്ഷാ പരിശോധനയ്ക്കോ എപ്പോഴും ചോദിക്കൂ.",
        "ta": "மகிழ்ச்சி! கடலில் பாதுகாப்பாக இருங்கள் — புதிய PFZ மண்டலங்கள் அல்லது பயணத்திற்கு முந்தைய பாதுகாப்பு சரிபார்ப்புக்கு எப்போதும் கேளுங்கள்.",
        "te": "మీకు స్వాగతం! సముద్రంలో సురక్షితంగా ఉండండి — తాజా PFZ మండలాలు లేదా ప్రయాణానికి ముందు భద్రతా తనిఖీ కోసం ఎప్పుడైనా అడగండి.",
        "hi": "आपका स्वागत है! समुद्र में सुरक्षित रहें — ताज़ा PFZ क्षेत्रों या नौकायन से पहले सुरक्षा जाँच के लिए कभी भी पूछें।",
    },
    "bye": {
        "en": "Goodbye and safe sailing! I'll keep today's PFZ chart ready for your next trip.",
        "ml": "വിട! സുരക്ഷിത യാത്ര ആശംസിക്കുന്നു! അടുത്ത യാത്രയ്ക്കായി ഇന്നത്തെ PFZ ചാർട്ട് തയ്യാറാക്കി വെക്കാം.",
        "ta": "பிரியாவிடை, பாதுகாப்பான பயணம்! உங்கள் அடுத்த பயணத்திற்கு இன்றைய PFZ வரைபடம் தயாராக இருக்கும்.",
        "te": "వీడ్కోలు, సురక్షిత ప్రయాణం! మీ తదుపరి యాత్రకు నేటి PFZ చార్ట్ సిద్ధంగా ఉంచుతాను.",
        "hi": "अलविदा और सुरक्षित नौकायन! आपकी अगली यात्रा के लिए आज का PFZ चार्ट तैयार रखूँगा।",
    },
    "howareyou": {
        "en": "Doing well, thanks for asking! I'm ORCA, keeping watch over today's fishing zones. How can I help — fish location, waves, wind, or sailing safety?",
        "ml": "സുഖമാണ്, ചോദിച്ചതിന് നന്ദി! ഇന്നത്തെ മീൻപിടിത്ത മേഖലകൾ നിരീക്ഷിച്ചുകൊണ്ടിരിക്കുന്നു. എങ്ങനെ സഹായിക്കാം — മീൻ സ്ഥാനം, തിരമാല, കാറ്റ്, അതോ സുരക്ഷ?",
        "ta": "நலம், கேட்டதற்கு நன்றி! இன்றைய மீன்பிடி மண்டலங்களை கண்காணித்து வருகிறேன். எப்படி உதவலாம் — மீன் இருப்பிடம், அலை, காற்று, பாதுகாப்பு?",
        "te": "బాగున్నాను, అడిగినందుకు ధన్యవాదాలు! నేటి చేపల మండలాలను పర్యవేక్షిస్తున్నాను. ఎలా సహాయపడగలను — చేపల స్థానం, అలలు, గాలి, భద్రత?",
        "hi": "बढ़िया हूँ, पूछने के लिए शुक्रिया! आज के मत्स्य क्षेत्रों पर नज़र रख रहा हूँ। कैसे मदद करूँ — मछली स्थान, लहरें, हवा या सुरक्षा?",
    },
    "who": {
        "en": "I'm ORCA (Marine EcOsystem Reasoning with Collaborative Agents) — built for ISRO SIH26176. I run 4 specialist agents (fish finder, sea checker, weather, danger watch) over today's INCOIS zones and give you one safest spot with proof. Just say 'Fish near Kochi?' to start.",
        "ml": "ഞാൻ ORCA ആണ് (Marine EcOsystem Reasoning with Collaborative Agents) — ISRO SIH26176-നായി നിർമ്മിച്ചത്. ഇന്നത്തെ INCOIS മേഖലകളിൽ 4 വിദഗ്ധ ഏജന്റുമാരെ (ഫിഷ് ഫൈൻഡർ, കടൽ പരിശോധകൻ, കാലാവസ്ഥ, അപകട നിരീക്ഷകൻ) പ്രവർത്തിപ്പിച്ച് തെളിവോടെ ഏറ്റവും സുരക്ഷിതമായ ഒരിടം നൽകുന്നു. തുടങ്ങാൻ 'കൊച്ചിക്ക് സമീപം മീൻ?' എന്ന് പറയൂ.",
        "ta": "நான் ORCA (Marine EcOsystem Reasoning with Collaborative Agents) — ISRO SIH26176-க்காக உருவாக்கப்பட்டது. இன்றைய INCOIS மண்டலங்களில் 4 நிபுணர் முகவர்களை இயக்கி ஆதாரத்துடன் பாதுகாப்பான இடத்தைத் தருகிறேன். தொடங்க 'கொச்சி அருகே மீன்?' என்று சொல்லுங்கள்.",
        "te": "నేను ORCA (Marine EcOsystem Reasoning with Collaborative Agents) — ISRO SIH26176 కోసం నిర్మించబడింది. నేటి INCOIS మండలాలపై 4 నిపుణ ఏజెంట్లను నడిపి రుజువుతో అత్యంత సురక్షిత స్థలాన్ని ఇస్తాను. ప్రారంభించడానికి 'కొచ్చి దగ్గర చేపలు?' అని చెప్పండి.",
        "hi": "मैं ORCA हूँ (Marine EcOsystem Reasoning with Collaborative Agents) — ISRO SIH26176 के लिए निर्मित। आज के INCOIS क्षेत्रों पर 4 विशेषज्ञ एजेंट चलाकर प्रमाण सहित सबसे सुरक्षित स्थान देता हूँ। शुरू करने के लिए कहें 'कोच्चि के पास मछली?'।",
    },
    "help": {
        "en": "I can help with:\n• Where is fish today? ('Fish near Kochi?')\n• Is it safe to sail? ('Safe for small boat now?')\n• Wind/waves/cyclone alerts ('Any cyclone alert for Kerala?')\n• Zone details ('PFZ near Munambam')\nJust chat normally — I'll run the full marine analysis only when you ask about sea data.",
        "ml": "എനിക്ക് സഹായിക്കാനാവുന്നത്:\n• ഇന്ന് മീൻ എവിടെ? ('കൊച്ചിക്ക് സമീപം മീൻ?')\n• കടലിൽ പോകുന്നത് സുരക്ഷിതമാണോ?\n• കാറ്റ്/തിര/ചുഴലിക്കാറ്റ് മുന്നറിയിപ്പുകൾ\n• മേഖലാ വിവരങ്ങൾ ('മുനമ്പത്തിന് സമീപം PFZ')\nസാധാരണ സംസാരിക്കൂ — കടൽ വിവരം ചോദിക്കുമ്പോൾ മാത്രം പൂർണ്ണ വിശകലനം നടത്താം.",
        "ta": "நான் உதவக்கூடியவை:\n• இன்று மீன் எங்கே? ('கொச்சி அருகே மீன்?')\n• பயணம் பாதுகாப்பானதா?\n• காற்று/அலை/புயல் எச்சரிக்கைகள்\n• மண்டல விவரங்கள்\nசாதாரணமாக பேசுங்கள் — கடல் தரவு கேட்கும்போது மட்டும் முழு பகுப்பாய்வு இயக்குவேன்.",
        "te": "నేను సహాయపడగలవి:\n• ఈరోజు చేపలు ఎక్కడ? ('కొచ్చి దగ్గర చేపలు?')\n• ప్రయాణం సురక్షితమేనా?\n• గాలి/అలలు/తుఫాను హెచ్చరికలు\n• మండల వివరాలు\nసాధారణంగా మాట్లాడండి — సముద్ర డేటా అడిగినప్పుడు మాత్రమే పూర్తి విశ్లేషణ నడుపుతాను.",
        "hi": "मैं इनमें मदद कर सकता हूँ:\n• आज मछली कहाँ है? ('कोच्चि के पास मछली?')\n• क्या नौकायन सुरक्षित है?\n• हवा/लहर/चक्रवात अलर्ट\n• क्षेत्र विवरण\nबस सामान्य बात करें — समुद्री डेटा पूछने पर ही पूर्ण विश्लेषण चलाऊँगा।",
    },
}


def _norm_lang(language: str | None) -> str:
    c = str(language or "en").strip().lower().split("-")[0].split("_")[0]
    return c if c in ("en", "ml", "ta", "te", "hi") else "en"


def is_marine_query(query: str) -> bool:
    """True when the query asks for PFZ/marine/weather data."""
    if not query or not query.strip():
        return False
    return bool(_MARINE_RE.search(query))


def is_chitchat(query: str) -> bool:
    """True for pure chitchat: matches a chitchat pattern AND no marine keywords."""
    if not query or not query.strip():
        return False
    if is_marine_query(query):
        return False
    text = query.strip()
    return any(rx.search(text) for rx in _CHITCHAT_RES)


def classify_route(query: str) -> str:
    """Return 'chitchat' or 'marine' (marine is the default)."""
    return "chitchat" if is_chitchat(query) else "marine"


def build_chitchat_reply(query: str, language: str = "en") -> str:
    """Canned vernacular reply — never invents coords/metrics/zones."""
    lang = _norm_lang(language)
    q = query.lower()
    if re.search(r"thank|nanni|nandri|dhanyavad|നന്ദി|நன்றி|ధన్యవాదాలు|धन्यवाद|शुक्रिया", q):
        kind = "thanks"
    elif re.search(r"\bbye\b|വിട|பிரியாவிடை|వీడ్కోలు|अलविदा", q):
        kind = "bye"
    elif re.search(r"who are you|what are you|your name|about you|നീ ആരാണ്|நீ யார்|నీవు ఎవరు|तुम कौन|आप कौन", q):
        kind = "who"
    elif re.search(r"what can you do|help|how (do|can)|സഹായം|உதவி|సహాయం|मदद", q):
        kind = "help"
    elif re.search(r"how'?s (life|it going|things)|how (are|r) (you|u)|what'?s up", q):
        kind = "howareyou"
    else:
        kind = "greet"
    return _CHITCHAT_REPLIES[kind].get(lang, _CHITCHAT_REPLIES[kind]["en"])


__all__ = [
    "is_marine_query",
    "is_chitchat",
    "classify_route",
    "build_chitchat_reply",
]
