"""
Canonical safety truth — single thresholds module (wayfinder #196).

Owner: M-A (Agents & Orchestration)

All wave/wind/current/geofence thresholds live HERE. Every other module
(combiner, orchestrator, lexical_mask, graph, sea_checker, weather_agent,
live_fetchers, routers/weather, routers/officer, evals/dataset,
synthesizer_service) imports from here — grep must show no second
literal definition.

Canonical bands (fail-open caution, never SAFE on missing data):
  - wave:    <2.0m safe, 2.0–3.5m caution, >3.5m danger
  - wind:    <22kt safe, 22–27kt caution, >27kt danger
  - current: <2.0kt safe, 2.0–3.0kt caution, >3.0kt danger (metric band)
  - banned (inside MPA or explicitly outside EEZ) or cyclone alert → danger.
  - missing wave/wind (None) → caution, never safe. Missing geofence
    (inside_eez=None) is unknown, never a ban — only an explicit
    ``inside_eez is False`` bans. Missing current alone is informational
    (does not force caution when wave+wind are measured).

Option 1 — current-only never vetoes (Kochi/Munambam DO NOT SAIL bug):
  Tier DANGER / all_unsafe / DO NOT SAIL requires wave danger, wind
  danger, geofence ban, cyclone, or the all_unsafe flag. A current
  breach ALONE (even >3.0kt) yields CAUTION — strong current, proceed
  with care — never a sole DO NOT SAIL. Wave/wind danger combined with
  a current breach still yields DANGER.

Map invariant: Code Trumps LLM, fail-open caution never SAFE.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Canonical bands
# ---------------------------------------------------------------------------

WAVE_SAFE_MAX_M = 2.0
WAVE_DANGER_MIN_M = 3.5

WIND_SAFE_MAX_KT = 22.0
WIND_DANGER_MIN_KT = 27.0

CURRENT_SAFE_MAX_KT = 2.0
CURRENT_DANGER_MIN_KT = 3.0

KT_TO_KPH = 1.852
WIND_SAFE_MAX_KPH = round(WIND_SAFE_MAX_KT * KT_TO_KPH, 2)  # 40.74
WIND_DANGER_MIN_KPH = round(WIND_DANGER_MIN_KT * KT_TO_KPH, 2)  # 50.0

CYCLONE_RADIUS_KM = 500.0
PRESSURE_DANGER_HPA = 995.0
PRESSURE_CAUTION_HPA = 1005.0

SUCCESS_CONFIDENCE = 0.87
DEGRADED_CONFIDENCE = 0.62
CONFIDENCE_SUCCESS_FLOOR = 0.80

__all__ = [
    "WAVE_SAFE_MAX_M",
    "WAVE_DANGER_MIN_M",
    "WIND_SAFE_MAX_KT",
    "WIND_DANGER_MIN_KT",
    "CURRENT_SAFE_MAX_KT",
    "CURRENT_DANGER_MIN_KT",
    "KT_TO_KPH",
    "WIND_SAFE_MAX_KPH",
    "WIND_DANGER_MIN_KPH",
    "CYCLONE_RADIUS_KM",
    "PRESSURE_DANGER_HPA",
    "PRESSURE_CAUTION_HPA",
    "SUCCESS_CONFIDENCE",
    "DEGRADED_CONFIDENCE",
    "CONFIDENCE_SUCCESS_FLOOR",
    "is_banned",
    "classify_wave",
    "classify_wind",
    "classify_current",
    "derive_safety_tier",
    "veto_safety",
    "apply_safety_veto",
    "wind_kt_to_kph",
    "wind_kph_to_kt",
    "is_geofence_violation_text",
    "resolve_geofence_evidence",
]


# ---------------------------------------------------------------------------
# Unit conversion
# ---------------------------------------------------------------------------


def wind_kt_to_kph(wind_kt: Any) -> float | None:
    """Knots → kph (None-safe)."""
    if wind_kt is None:
        return None
    try:
        return round(float(wind_kt) * KT_TO_KPH, 2)
    except (TypeError, ValueError):
        return None


def wind_kph_to_kt(wind_kph: Any) -> float | None:
    """Kph → knots (None-safe)."""
    if wind_kph is None:
        return None
    try:
        return round(float(wind_kph) / KT_TO_KPH, 2)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Geofence
# ---------------------------------------------------------------------------


def is_banned(inside_mpa: Any, inside_eez: Any) -> bool:
    """True only on explicit ban: inside MPA or explicitly outside EEZ.

    ``inside_eez=None`` (unknown/skipped) is NEVER a ban — fail-open.
    """
    try:
        if bool(inside_mpa):
            return True
    except Exception:
        pass
    return inside_eez is False


def _finite_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        f = float(value)
        # NaN is missing, not zero
        if f != f:  # noqa: PLR0124 (NaN check without math import)
            return None
        return f
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Per-metric classifiers (None → "unknown"; veto maps unknown → caution)
# ---------------------------------------------------------------------------


def classify_wave(wave_m: Any) -> str:
    """<2.0 safe, 2.0–3.5 caution, >3.5 danger, None → unknown."""
    w = _finite_or_none(wave_m)
    if w is None:
        return "unknown"
    if w < WAVE_SAFE_MAX_M:
        return "safe"
    if w <= WAVE_DANGER_MIN_M:
        return "caution"
    return "danger"


def classify_wind(wind_kt: Any) -> str:
    """<22kt safe, 22–27kt caution, >27kt danger, None → unknown."""
    w = _finite_or_none(wind_kt)
    if w is None:
        return "unknown"
    if w < WIND_SAFE_MAX_KT:
        return "safe"
    if w <= WIND_DANGER_MIN_KT:
        return "caution"
    return "danger"


def classify_current(current_kt: Any) -> str:
    """<2.0kt safe, 2.0–3.0kt caution, >3.0kt danger, None → unknown."""
    c = _finite_or_none(current_kt)
    if c is None:
        return "unknown"
    if c < CURRENT_SAFE_MAX_KT:
        return "safe"
    if c <= CURRENT_DANGER_MIN_KT:
        return "caution"
    return "danger"


# ---------------------------------------------------------------------------
# Tier derivation (uppercase SAFE/CAUTION/DANGER — Code Trumps LLM)
# ---------------------------------------------------------------------------


def derive_safety_tier(
    wave_m: Any,
    wind_kts: Any,
    all_unsafe: bool = False,
    banned: bool = False,
    current_kt: Any = None,
    cyclone_alert: Any = False,
) -> str:
    """Deterministic tier. DANGER on wave/wind/ban/cyclone; current alone → CAUTION.

    Backward compatible: first four params match the legacy
    ``lexical_mask.derive_safety_tier`` signature; ``current_kt`` and
    ``cyclone_alert`` are additive (missing current never forces caution
    when wave+wind are measured).

    Option 1: a current breach ALONE never reaches DANGER — it caps at
    CAUTION. Only wave danger, wind danger, geofence ban, cyclone, or
    the explicit ``all_unsafe`` flag force DANGER (sole DO NOT SAIL
    vetoes). Wave/wind danger combined with a current breach still DANGER.
    """
    try:
        veto = bool(all_unsafe) or bool(banned) or bool(cyclone_alert)
    except Exception:
        veto = False
    if veto:
        return "DANGER"
    wave = _finite_or_none(wave_m)
    wind = _finite_or_none(wind_kts)
    current = _finite_or_none(current_kt)
    # Wave/wind danger → DANGER even when the other metric is missing.
    # Current danger NEVER escalates past CAUTION on its own (option 1).
    wave_danger = wave is not None and wave > WAVE_DANGER_MIN_M
    wind_danger = wind is not None and wind > WIND_DANGER_MIN_KT
    if wave_danger or wind_danger:
        return "DANGER"
    # Fail-open: missing wave/wind can never read SAFE (current alone
    # stays CAUTION here, not DANGER).
    if wave is None or wind is None:
        return "CAUTION"
    if (
        wave >= WAVE_SAFE_MAX_M
        or wind >= WIND_SAFE_MAX_KT
        or (current is not None and current >= CURRENT_SAFE_MAX_KT)
    ):
        return "CAUTION"
    return "SAFE"


def veto_safety(
    wave_m: Any,
    wind_kt: Any,
    inside_eez: Any,
    inside_mpa: Any,
    cyclone_alert: Any = False,
    current_kt: Any = None,
) -> tuple[str, float]:
    """Lowercase (safety, confidence). Safe only on measured calm + allowed.

    All inputs in knots/metres. Missing wave/wind → caution + degraded.
    """
    banned = is_banned(inside_mpa, inside_eez)
    try:
        cyclone = bool(cyclone_alert)
    except Exception:
        cyclone = False
    if banned or cyclone:
        return "danger", DEGRADED_CONFIDENCE
    tier = derive_safety_tier(wave_m, wind_kt, False, False, current_kt, False)
    if tier == "DANGER":
        return "danger", DEGRADED_CONFIDENCE
    if tier == "CAUTION":
        return "caution", DEGRADED_CONFIDENCE
    return "safe", SUCCESS_CONFIDENCE


def _zone_wind_kt(zone: dict) -> float | None:
    if not isinstance(zone, dict):
        return None
    # Explicit kt keys first; kph only when no kt key is present.
    for k in ("wind_kt", "wind_speed_kt", "wind_kts", "wind_speed_kts", "wind"):
        if zone.get(k) is not None:
            v = _finite_or_none(zone.get(k))
            if v is not None:
                return v
    if zone.get("wind_kph") is not None:
        return wind_kph_to_kt(zone.get("wind_kph"))
    return None


def _zone_current_kt(zone: dict) -> float | None:
    if not isinstance(zone, dict):
        return None
    for k in ("current_kt", "current_speed_kt", "current", "current_kts"):
        if zone.get(k) is not None:
            v = _finite_or_none(zone.get(k))
            if v is not None:
                return v
    return None


def apply_safety_veto(zone: dict) -> str:
    """Lowercase safety for a ranked zone dict (additive — never alters scoring).

    Reads wave (wave_height_m/wave_m/wave), wind (kt keys or wind_kph),
    current (current_kt/current_speed_kt), banned flags, cyclone flags.
    Missing wave/wind → caution; missing current alone is informational.
    """
    if not isinstance(zone, dict):
        return "caution"
    wave = None
    for k in ("wave_height_m", "wave_m", "wave", "wave_height"):
        if zone.get(k) is not None:
            wave = _finite_or_none(zone.get(k))
            break
    wind = _zone_wind_kt(zone)
    current = _zone_current_kt(zone)
    try:
        cyclone = bool(zone.get("cyclone_alert", zone.get("cyclone", False)))
    except Exception:
        cyclone = False
    if is_banned(zone.get("inside_mpa"), zone.get("inside_eez")) or cyclone:
        return "danger"
    # Option 1: current-only breach (even >3.0kt) → caution, never danger.
    # Wave/wind danger still reaches danger via derive_safety_tier.
    tier = derive_safety_tier(wave, wind, False, False, current, False)
    return tier.lower()


# ---------------------------------------------------------------------------
# EEZ evidence guard — canonical banned flag, never substring double-talk
# ---------------------------------------------------------------------------

_GEOFENCE_VIOLATION_TOKENS: tuple[str, ...] = (
    "eez",
    "mpa",
    "violation",
    "banned",
    "not permitted",
    "protected area",
    "exclusive economic zone",
    "boundary",
    "imbl",
    "geofence",
    "cyclone",
    "lightning",
)


def is_geofence_violation_text(text: object) -> bool:
    """True when a warning/evidence line reports a geofence violation.

    Matches full words ("Exclusive Economic Zone") as well as the
    EEZ/MPA abbreviations, so the spelled-out danger_agent warning
    ("Outside Indian Exclusive Economic Zone — fishing not permitted")
    is recognised even though it contains neither "EEZ" nor "MPA".
    """
    if not isinstance(text, str) or not text.strip():
        return False
    lowered = text.lower()
    return any(tok in lowered for tok in _GEOFENCE_VIOLATION_TOKENS)


def resolve_geofence_evidence(
    banned: bool,
    warnings: list[str] | None,
) -> list[str]:
    """Build the geofence slice of chat evidence without double-talk.

    - Banned → keep violation warnings, ensure at least one violation
      line, NEVER append "No EEZ/MPA violation".
    - Not banned → keep warnings; append "No EEZ/MPA violation" only
      when no warning already reports a violation.
    Unavailable/skipped notes are dropped (unknown, not verdicts).
    """
    kept: list[str] = []
    for w in warnings or []:
        if not isinstance(w, str) or not w.strip():
            continue
        low = w.lower()
        if "unavailable" in low or "skipped" in low:
            continue
        if w not in kept:
            kept.append(w)
    violation_present = any(is_geofence_violation_text(w) for w in kept)
    if banned:
        if not violation_present:
            kept.append("EEZ/MPA violation — restricted waters")
        return kept
    if not violation_present:
        kept.append("No EEZ/MPA violation")
    return kept
