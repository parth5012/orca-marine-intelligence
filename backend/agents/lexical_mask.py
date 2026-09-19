"""
Marine Lexical Masking & Vernacular Advisory Grounding Engine.

Owner: M-A (Agents & Orchestration) + M-E (Chat & Shell)
Ticket: wayfinder #28 — M-A & M-E: Implement Marine Lexical Masking &
    Vernacular Advisory Grounding Engine.
Map: docs/ORCA_Wayfinder_Map_22_Dynamic_Agents.md (destination: dynamic
    reasoning + grounded multilingual synthesis).

Refs (port these rules, do NOT re-invent):
  - docs/research/02-provider-agnostic-translation-layer.md §4
    (MarineGlossaryMasker: Bearing/knots/km/acronym protection,
    ResilientLanguageEngine failover, LANGUAGE_PROVIDER=llm default).
  - docs/research/03-coastal-marine-dictionary-spec.md §3-§5
    (Arabic numerals only, direction terms, bearing phrases,
    3-tier safety vocabulary + closing sentences, grounded prompt template).
  - docs/research/01-language-identification-cascade.md
    (Unicode-range script detection; planner_schema.detected_language).

Design (cheap regex, no external calls, P95<2.0s):
  1. Mask (pre-translation): replace nautical numbers+units with ASCII
     placeholders ``__MBEARING_X__`` / ``__MKNOTS_X__`` / ``__MDIST_X__``
     (+ ``__MDEG__`` / ``__MMETER__`` / ``__MCOORD__`` / ``__MACR__``).
     Placeholders contain no spaces so SSE ``_chunk_text`` (graph.py)
     never splits them — token-safe. Masking is applied pre-stream at
     the combiner level; graph.py streaming is NOT altered.
  2. Translate / render: offline canned grounding templates per language
     (ml/ta/te/hi/en) fill ground-truth metrics directly — zero network
     hops, so W1/Global Test queries always get pure native-script
     responses offline.
  3. Unmask (post-translation): restore exact original numeric strings.

Envelope: every public tool returns
  ``{"status","summary","next_actions","artifacts", ...}``
per AGENTS.md §3.2 observation contract.

Code-trumps-LLM: combiner.py keeps the deterministic 40/30/20/10 veto
(all_unsafe → DO NOT SAIL); this module only *renders* the veto in the
target language, never overrides it.
"""

from __future__ import annotations

import re
import time
from typing import Callable, Dict, List, Tuple

__all__ = [
    "SUPPORTED_LANGS",
    "SAFETY_TAGS",
    "DIRECTION_TEXT",
    "BEARING_PHRASES",
    "KNOTS_PHRASES",
    "CLOSING_SENTENCES",
    "FISH_GLOSSARY",
    "MarineGlossaryMasker",
    "mask_text",
    "unmask_text",
    "translate_with_masking",
    "render_grounded_advisory",
    "localize_advisory_envelope",
    "derive_safety_tier",
    "contains_native_script",
    "has_regional_digits",
    "verify_numbers_preserved",
]

SUPPORTED_LANGS: Tuple[str, ...] = ("en", "ml", "ta", "te", "hi")

# ---------------------------------------------------------------------------
# Compiled regexes (module-load, reused per call — keeps masking <<1ms).
# Order matters: bearing first (consumes "Bearing 232°"), then knots, km,
# standalone degrees, meters, coordinates, acronyms.
# ---------------------------------------------------------------------------

_BEARING_RE = re.compile(
    r"\bBearing\s+(\d+(?:\.\d+)?)\s*(?:°|deg(?:rees?)?)?",
    re.IGNORECASE,
)
# wind speed: "8 knots" / "8 knot" / "8 kt" (internal data uses wind_kt)
_KNOTS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*knots?\b", re.IGNORECASE)
_KT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*kt\b", re.IGNORECASE)
_DIST_RE = re.compile(r"(\d+(?:\.\d+)?)\s*kms?\b", re.IGNORECASE)
_DEGREE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:°|deg(?:rees?)?\b)", re.IGNORECASE)
# wave height "0.8 m" — run AFTER km so "km" is already masked.
_METER_RE = re.compile(r"(\d+(?:\.\d+)?)\s*m\b", re.IGNORECASE)
_COORD_RE = re.compile(r"-?\d+\.\d+\s*,\s*-?\d+\.\d+")
_ACRONYM_RE = re.compile(r"\b(PFZ|EEZ|MPA|IMBL|INCOIS|OSF|IMD)\b")

_PLACEHOLDER_RE = re.compile(r"__M[A-Z]+_\d+__")

# Regional-script digits that must NEVER appear in advisories (spec §3.1:
# always Arabic 0-9 so fishermen can cross-check GPS/fish-finder screens).
_REGIONAL_DIGITS_RE = re.compile(
    "[\u0d66-\u0d6f\u0be6-\u0bef\u0c66-\u0c6f\u0660-\u0669\u06f0-\u06f9"
    "\u0966-\u096f\u09e6-\u09ef\u0a66-\u0a6f\u0ae6-\u0aef\u0b66-\u0b6f"
    "\u0ce6-\u0cef]"
)

# Native-script Unicode blocks for purity checks.
_NATIVE_RANGES: Dict[str, Tuple[Tuple[int, int], ...]] = {
    "ml": ((0x0D00, 0x0D7F),),
    "ta": ((0x0B80, 0x0BFF),),
    "te": ((0x0C00, 0x0C7F),),
    "hi": ((0x0900, 0x097F),),
}


# ---------------------------------------------------------------------------
# MarineGlossaryMasker
# ---------------------------------------------------------------------------


class MarineGlossaryMasker:
    """Protect nautical numbers/units/acronyms across translation.

    Example:
        >>> m = MarineGlossaryMasker()
        >>> masked, table = m.mask("Bearing 232 deg, wind 8 knots, 14 km")
        >>> masked
        '__MBEARING_0__, wind __MKNOTS_0__, __MDIST_0__'
        >>> m.unmask(masked, table)
        'Bearing 232 deg, wind 8 knots, 14 km'
    """

    def mask(self, text: str) -> Tuple[str, Dict[str, str]]:
        """Mask nautical spans. Returns (masked_text, placeholder->original)."""
        if not text:
            return "", {}
        table: Dict[str, str] = {}
        counters: Dict[str, int] = {}

        def _store(prefix: str, original: str) -> str:
            idx = counters.get(prefix, 0)
            counters[prefix] = idx + 1
            token = f"__M{prefix}_{idx}__"
            table[token] = original
            return token

        def _sub(pattern: re.Pattern, s: str, prefix: str) -> str:
            def _repl(mt: re.Match) -> str:
                return _store(prefix, mt.group(0))

            return pattern.sub(_repl, s)

        out = text
        out = _sub(_BEARING_RE, out, "BEARING")
        out = _sub(_KNOTS_RE, out, "KNOTS")
        out = _sub(_KT_RE, out, "KNOTS")
        out = _sub(_DIST_RE, out, "DIST")
        out = _sub(_DEGREE_RE, out, "DEG")
        out = _sub(_METER_RE, out, "METER")
        out = _sub(_COORD_RE, out, "COORD")
        out = _sub(_ACRONYM_RE, out, "ACR")
        return out, table

    def unmask(self, text: str, table: Dict[str, str]) -> str:
        """Restore originals. Unknown placeholders are left untouched."""
        if not text or not table:
            return text
        out = text
        for token, original in table.items():
            if token in out:
                out = out.replace(token, original)
        return out

    def translate_with_masking(
        self,
        text: str,
        translator_fn: Callable[[str], str],
    ) -> Tuple[str, Dict[str, str]]:
        """Mask → translator_fn(masked) → unmask.

        Args:
            text: source English advisory.
            translator_fn: ``masked_en -> masked_target`` (any provider:
                Direct LLM / Sarvam / Bhashini / offline canned). Must pass
                ``__M*__`` tokens through verbatim.

        Returns:
            (final_text, table). final_text has exact original numbers.
        """
        masked, table = self.mask(text)
        translated_masked = translator_fn(masked)
        final = self.unmask(translated_masked, table)
        # Placeholder-leak guard: never emit raw __M*__ tokens. If the
        # translator dropped/corrupted placeholders, fall back to the
        # unmasked source text (exact original numbers, no placeholders).
        if _PLACEHOLDER_RE.search(final):
            return text, table
        return final, table

    # -- envelope variant (AGENTS.md §3.2) --------------------------------
    def mask_envelope(self, text: str) -> dict:
        """Mask with status+summary+next_actions+artifacts envelope."""
        t0 = time.perf_counter()
        masked, table = self.mask(text)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return {
            "status": "success",
            "summary": f"masked {len(table)} nautical spans in {elapsed_ms}ms",
            "next_actions": ["call translator", "call unmask"],
            "artifacts": [],
            "masked": masked,
            "table": table,
            "elapsed_ms": elapsed_ms,
        }


def mask_text(text: str) -> Tuple[str, Dict[str, str]]:
    """Module convenience: mask without instantiating the class."""
    return MarineGlossaryMasker().mask(text)


def unmask_text(text: str, table: Dict[str, str]) -> str:
    """Module convenience: unmask without instantiating the class."""
    return MarineGlossaryMasker().unmask(text, table)


def translate_with_masking(
    text: str, translator_fn: Callable[[str], str]
) -> str:
    """One-shot mask→translate→unmask returning final text only."""
    final, _ = MarineGlossaryMasker().translate_with_masking(text, translator_fn)
    return final


# ---------------------------------------------------------------------------
# Vernacular grounding data (ported from research 02 §4 + 03 §3-§5).
# All numbers rendered with Arabic digits 0-9 (never regional digits).
# ---------------------------------------------------------------------------

# 3-tier safety tags: lang -> TIER -> tag (spec 03 §4).
SAFETY_TAGS: Dict[str, Dict[str, str]] = {
    "en": {"SAFE": "Safe", "CAUTION": "Caution", "DANGER": "Danger"},
    "ml": {
        "SAFE": "സുരക്ഷിതം (Safe)",
        "CAUTION": "ജാഗ്രത (Caution)",
        "DANGER": "അപകടകരം (Danger)",
    },
    "ta": {
        "SAFE": "பாதுகாப்பானது (Safe)",
        "CAUTION": "எச்சரிக்கை (Caution)",
        "DANGER": "ஆபத்தானது (Danger)",
    },
    "te": {
        "SAFE": "సురక్షితం (Safe)",
        "CAUTION": "హెచ్చరిక (Caution)",
        "DANGER": "ప్రమాదకరం (Danger)",
    },
    "hi": {
        "SAFE": "सुरक्षित (Safe)",
        "CAUTION": "सावधानी (Caution)",
        "DANGER": "खतरनाक (Danger)",
    },
}

# Compass direction: code -> localized "words (CODE)" (spec 03 §3.2).
DIRECTION_TEXT: Dict[str, Dict[str, str]] = {
    "en": {
        "N": "North (N)", "NE": "North-East (NE)",
        "E": "East (E)", "SE": "South-East (SE)",
        "S": "South (S)", "SW": "South-West (SW)",
        "W": "West (W)", "NW": "North-West (NW)",
    },
    "ml": {
        "N": "വടക്ക് (N)", "NE": "വടക്ക്-കിഴക്ക് (NE)",
        "E": "കിഴക്ക് (E)", "SE": "തെക്ക്-കിഴക്ക് (SE)",
        "S": "തെക്ക് (S)", "SW": "തെക്ക്-പടിഞ്ഞാറ് (SW)",
        "W": "പടിഞ്ഞാറ് (W)", "NW": "വടക്ക്-പടിഞ്ഞാറ് (NW)",
    },
    "ta": {
        "N": "வடக்கு (N)", "NE": "வடகிழக்கு (NE)",
        "E": "கிழக்கு (E)", "SE": "தென்கிழக்கு (SE)",
        "S": "தெற்கு (S)", "SW": "தென்மேற்கு (SW)",
        "W": "மேற்கு (W)", "NW": "வடமேற்கு (NW)",
    },
    "te": {
        "N": "ఉత్తరం (N)", "NE": "ఈశాన్యం (NE)",
        "E": "తూర్పు (E)", "SE": "ఆగ్నేయం (SE)",
        "S": "దక్షిణం (S)", "SW": "నైరుతి (SW)",
        "W": "పడమర (W)", "NW": "వాయువ్యం (NW)",
    },
    "hi": {
        "N": "उत्तर (N)", "NE": "उत्तर-पूर्व (NE)",
        "E": "पूर्व (E)", "SE": "दक्षिण-पूर्व (SE)",
        "S": "दक्षिण (S)", "SW": "दक्षिण-पश्चिम (SW)",
        "W": "पश्चिम (W)", "NW": "उत्तर-पश्चिम (NW)",
    },
}

# Bearing azimuth phrases with {deg} in Arabic digits (spec 03 §3.3).
BEARING_PHRASES: Dict[str, str] = {
    "en": "Bearing {deg}°",
    "ml": "ബെയറിംഗ് {deg}° ദിശയിൽ",
    "ta": "திசைக்கோணம் {deg}° திசையில்",
    "te": "బేరింగ్ {deg}° దిశలో",
    "hi": "दिशा कोण {deg}° की ओर",
}

# Wind-speed phrases with {v} in Arabic digits (research 02 §4).
KNOTS_PHRASES: Dict[str, str] = {
    "en": "{v} knots",
    "ml": "{v} നോട്ട്",
    "ta": "{v} நாட்ஸ்",
    "te": "{v} నాట్లు (knots)",
    "hi": "{v} समुद्री मील/घंटा (knots)",
}

# Actionable closing per tier (spec 03 §4 + translated equivalents).
CLOSING_SENTENCES: Dict[str, Dict[str, str]] = {
    "en": {
        "SAFE": "It is safe to set sail.",
        "CAUTION": "Exercise caution; small craft should stay back.",
        "DANGER": "Do NOT sail — conditions are unsafe.",
    },
    "ml": {
        "SAFE": "കടലിൽ പോകുന്നത് സുരക്ഷിതമാണ്.",
        "CAUTION": "ജാഗ്രത പാലിക്കുക, ചെറിയ ബോട്ടുകൾ കടലിൽ പോകരുത്.",
        "DANGER": "കടലിൽ പോകരുത്! കാലാവസ്ഥ മോശമാണ്.",
    },
    "ta": {
        "SAFE": "கடலுக்கு செல்வது பாதுகாப்பானது.",
        "CAUTION": "எச்சரிக்கையாக இருங்கள், சிறிய படகுகள் கடலுக்கு செல்ல வேண்டாம்.",
        "DANGER": "கடலுக்கு செல்ல வேண்டாம்! வானிலை மோசமாக உள்ளது.",
    },
    "te": {
        "SAFE": "సముద్రంలోకి వెళ్లడం సురక్షితం.",
        "CAUTION": "హెచ్చరిక పాటించండి, చిన్న పడవలు సముద్రంలోకి వెళ్లవద్దు.",
        "DANGER": "సముద్రంలోకి వెళ్లవద్దు! వాతావరణం ప్రమాదకరంగా ఉంది.",
    },
    "hi": {
        "SAFE": "समुद्र में जाना सुरक्षित है।",
        "CAUTION": "सावधानी बरतें, छोटी नावें समुद्र में न जाएँ।",
        "DANGER": "समुद्र में न जाएँ! मौसम खराब है।",
    },
}

# Sea/wind connective lines per language (offline canned, numbers ASCII).
_SEA_WIND_LINES: Dict[str, str] = {
    "en": "Waves {wave} m, wind {knots}.",
    "ml": "തിരമാല {wave} m, കാറ്റ് {knots}.",
    "ta": "அலை {wave} m, காற்று {knots}.",
    "te": "అలలు {wave} m, గాలి {knots}.",
    "hi": "लहरें {wave} m, हवा {knots}।",
}

# Minimal commercial-species → coastal-market vernacular (spec 03 §2).
# Only species needed for W1/Global Test canned replies; extend on demand.
FISH_GLOSSARY: Dict[str, Dict[str, str]] = {
    "Indian Oil Sardine": {
        "en": "Indian Oil Sardine", "ml": "മത്തി (Mathi)",
        "ta": "மத்தி (Mathi)", "te": "కవ్వాలు (Kavvalu)", "hi": "तारली (Tarli)",
    },
    "Indian Mackerel": {
        "en": "Indian Mackerel", "ml": "അയല (Ayala)",
        "ta": "அயலை (Ayalai)", "te": "కనగర్తలు (Kanagarthalu)", "hi": "बांगड़ा (Bangda)",
    },
    "Kingfish / Seer Fish": {
        "en": "Kingfish / Seer Fish", "ml": "നെയ്മീൻ (Neymeen)",
        "ta": "வஞ்சிரம் (Vanjaram)", "te": "వంజరం (Vanjaram)", "hi": "सुरमई (Surmai)",
    },
    "Tiger Prawn / Shrimp": {
        "en": "Tiger Prawn / Shrimp", "ml": "ചെമ്മീൻ (Chemmeen)",
        "ta": "இறால் (Iraal)", "te": "రొయ్యలు (Royyalu)", "hi": "झींगा (Jheenga)",
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_lang(lang: str | None) -> str:
    if not lang or not isinstance(lang, str):
        return "en"
    code = lang.strip().lower().split("-")[0].split("_")[0]
    return code if code in SUPPORTED_LANGS else "en"


def derive_safety_tier(
    wave_m: float | None,
    wind_kts: float | None,
    all_unsafe: bool = False,
    banned: bool = False,
    current_kt: float | None = None,
    cyclone_alert: bool = False,
) -> str:
    """Deterministic SAFE/CAUTION/DANGER mirror of sea/weather thresholds.

    Canonical implementation lives in
    ``backend/agents/safety_thresholds.py`` — this wrapper preserves the
    legacy signature (plus additive ``current_kt``/``cyclone_alert``) so
    existing importers keep working. Code trumps LLM: all_unsafe, banned,
    cyclone, or wave>2.5 / wind>25kt / current>2.5kt → DANGER; missing
    wave/wind → CAUTION (fail-open, never SAFE).
    """
    from backend.agents.safety_thresholds import derive_safety_tier as _canonical

    return _canonical(wave_m, wind_kts, all_unsafe, banned, current_kt, cyclone_alert)


def contains_native_script(text: str, lang: str) -> bool:
    """True if text has ≥1 char in the lang's native Unicode block."""
    ranges = _NATIVE_RANGES.get(lang)
    if not ranges or not text:
        return False
    return any(
        any(lo <= ord(ch) <= hi for lo, hi in ranges) for ch in text
    )


def has_regional_digits(text: str) -> bool:
    """True if text contains non-Arabic indic digits (spec violation)."""
    if not text:
        return False
    return bool(_REGIONAL_DIGITS_RE.search(text))


def _fmt_num(value: object, decimals: int = 2) -> str:
    """Format with Arabic digits, strip trailing zeros (GPS-safe)."""
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(value)
    s = f"{f:.{decimals}f}".rstrip("0").rstrip(".")
    return s if s else "0"


def verify_numbers_preserved(expected_numbers: List[str], text: str) -> List[str]:
    """Return the subset of expected numeric tokens MISSING from text.

    Empty list ⇒ 0 corrupted coordinates / broken compass degrees.
    """
    return [n for n in expected_numbers if n not in text]


# ---------------------------------------------------------------------------
# Grounded advisory renderer (offline canned — no external calls).
# ---------------------------------------------------------------------------


def render_grounded_advisory(metrics: dict, lang: str = "en") -> str:
    """Render a same-language advisory from ground-truth metrics.

    Args:
        metrics: {
            place, lat, lon, distance_km, bearing_deg, direction (NE..),
            wave_height_m, wind_kts, overall_safety (SAFE|CAUTION|DANGER),
            all_unsafe (bool), citation, species_list (optional),
            inside_eez/inside_mpa (optional, for banned veto),
        }
        lang: ml | ta | te | hi | en (unknown → en fallback).

    Returns:
        Native-script advisory string with Arabic numerals, ``°``, km/m,
        localized bearing/knots/direction/safety/closing. Pure offline.
    """
    code = _normalize_lang(lang)
    m = dict(metrics or {})

    place = str(m.get("place") or m.get("port_name") or "Unknown")
    lat_s = _fmt_num(m.get("lat"), 4) if m.get("lat") is not None else "—"
    lon_s = _fmt_num(m.get("lon"), 4) if m.get("lon") is not None else "—"
    dist_s = _fmt_num(m.get("distance_km", m.get("distance_from_user_km", 0)), 2)
    bearing_raw = m.get("bearing_deg", m.get("bearing"))
    try:
        bearing_s: str | None = (
            _fmt_num(bearing_raw, 1) if bearing_raw is not None else None
        )
    except Exception:
        bearing_s = None
    direction = str(m.get("direction") or m.get("dir") or "").upper().strip()
    wave_s = _fmt_num(m.get("wave_height_m", m.get("wave_m", 0)), 2)
    wind_raw = m.get("wind_kts", m.get("wind_kt", m.get("wind_speed_kt", 0)))
    wind_s = _fmt_num(wind_raw, 1)
    citation = str(m.get("citation") or "INCOIS TextData")

    from backend.agents.safety_thresholds import is_banned as _is_banned

    banned = _is_banned(m.get("inside_mpa"), m.get("inside_eez"))
    tier = str(m.get("overall_safety") or "").upper()
    if tier not in ("SAFE", "CAUTION", "DANGER"):
        tier = derive_safety_tier(
            m.get("wave_height_m", m.get("wave_m")),
            wind_raw,
            bool(m.get("all_unsafe", False)),
            banned,
            m.get("current_kt", m.get("current_speed_kt")),
            bool(m.get("cyclone_alert", m.get("cyclone", False))),
        )
    if bool(m.get("all_unsafe", False)):
        tier = "DANGER"  # veto: code trumps LLM
    # SAFETY veto: an explicit overall_safety must never override physical
    # bans/limits — force DANGER on banned waters or extreme sea/weather.
    # Canonical bands (safety_thresholds): wave>2.5m / wind>25kt /
    # current>2.5kt / cyclone.
    from backend.agents.safety_thresholds import (
        CURRENT_DANGER_MIN_KT as _CUR_D,
    )
    from backend.agents.safety_thresholds import (
        WAVE_DANGER_MIN_M as _WAV_D,
    )
    from backend.agents.safety_thresholds import (
        WIND_DANGER_MIN_KT as _WND_D,
    )

    try:
        _wave_veto = float(m.get("wave_height_m", m.get("wave_m", 0)) or 0)
    except (TypeError, ValueError):
        _wave_veto = 0.0
    try:
        _wind_veto = float(wind_raw or 0)
    except (TypeError, ValueError):
        _wind_veto = 0.0
    try:
        _cur_veto = float(m.get("current_kt", m.get("current_speed_kt", 0)) or 0)
    except (TypeError, ValueError):
        _cur_veto = 0.0
    try:
        _cyc_veto = bool(m.get("cyclone_alert", m.get("cyclone", False)))
    except Exception:
        _cyc_veto = False
    if banned or _cyc_veto or _wave_veto > _WAV_D or _wind_veto > _WND_D or _cur_veto > _CUR_D:
        tier = "DANGER"

    tag = SAFETY_TAGS[code][tier]
    closing = CLOSING_SENTENCES[code][tier]
    knots_phrase = KNOTS_PHRASES[code].format(v=wind_s)
    sea_wind = _SEA_WIND_LINES[code].format(wave=wave_s, knots=knots_phrase)

    if bearing_s is not None:
        bearing_phrase = BEARING_PHRASES[code].format(deg=bearing_s)
        if direction and direction in DIRECTION_TEXT[code]:
            loc = f"{bearing_phrase} ({DIRECTION_TEXT[code][direction]})"
        else:
            loc = bearing_phrase
    elif direction and direction in DIRECTION_TEXT[code]:
        loc = DIRECTION_TEXT[code][direction]
    else:
        loc = ""

    species = m.get("species_list") or m.get("species") or []
    if isinstance(species, str):
        species = [species]
    localized_species: List[str] = []
    for sp in species:
        entry = FISH_GLOSSARY.get(str(sp))
        if entry:
            localized_species.append(entry.get(code, str(sp)))
        elif sp:
            localized_species.append(str(sp))
    species_clause = ""
    if localized_species:
        joined = ", ".join(localized_species)
        if code == "ml":
            species_clause = f" പ്രതീക്ഷിക്കുന്ന മീൻ: {joined}."
        elif code == "ta":
            species_clause = f" எதிர்பார்க்கப்படும் மீன்: {joined}."
        elif code == "te":
            species_clause = f" ఆశించే చేపలు: {joined}."
        elif code == "hi":
            species_clause = f" संभावित मछली: {joined}।"
        else:
            species_clause = f" Expected species: {joined}."

    head = f"[{tag}] {place} ({lat_s}, {lon_s}) — {dist_s} km"
    if loc:
        head += f", {loc}"
    return f"{head}. {sea_wind}{species_clause} {closing} ({citation})"


def localize_advisory_envelope(
    metrics: dict,
    lang: str = "en",
    translator_fn: Callable[[str], str] | None = None,
) -> dict:
    """Offline localization with envelope (status+summary+next_actions+artifacts).

    Default path renders the canned grounded template (no external calls).
    If ``translator_fn`` is supplied, the English source is masked →
    translated → unmasked to prove nautical-number protection.
    """
    t0 = time.perf_counter()
    code = _normalize_lang(lang)
    try:
        if translator_fn is not None:
            source_en = render_grounded_advisory(metrics, "en")
            final, table = MarineGlossaryMasker().translate_with_masking(
                source_en, translator_fn
            )
            # Placeholder-leak guard: never emit raw __M*__ tokens; fall
            # back to the rendered-safe canned advisory in the target lang.
            if _PLACEHOLDER_RE.search(final):
                final = render_grounded_advisory(metrics, code)
                table = {}
        else:
            final = render_grounded_advisory(metrics, code)
            table = {}
        if _PLACEHOLDER_RE.search(final):
            final = render_grounded_advisory(metrics, code)
            table = {}
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return {
            "status": "success",
            "summary": f"grounded {code} advisory in {elapsed_ms}ms (offline canned)",
            "next_actions": ["stream tokens via graph.py (unchanged)"],
            "artifacts": [],
            "reply": final,
            "detected_language": code,
            "masked_spans": len(table),
            "elapsed_ms": elapsed_ms,
        }
    except Exception as exc:  # degrade gracefully, never crash pipeline
        return {
            "status": "error",
            "summary": f"localization fallback to en ({exc})",
            "next_actions": ["serve English advisory + warn"],
            "artifacts": [],
            "reply": render_grounded_advisory(metrics, "en"),
            "detected_language": "en",
            "masked_spans": 0,
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
        }
