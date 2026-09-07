"""
Gemini 2.5 Flash Structured Planner Service.

Owner: M-A (Agents & Orchestration)
Module: backend/agents/planner_service.py
Ticket: M-A: Implement Gemini 2.5 Flash Structured Planner Service (#31)
Map: #30 (Destination: full dynamic LLM reasoning — Planner + Synthesizer)

Dynamic LLM query planner powered by Gemini 2.5 Flash (``gemini-2.5-flash``)
under a strict <500ms SLA budget. Produces structured ``PlannerOutput``
(pydantic, see ``backend/agents/planner_schema.py``): detected language,
geocoded target location, decomposed intents, confidence, auditable
reasoning trace, and the minimal selective tool subset.

Scope (ticket #31 — root node, standalone; wiring into graph.py is #32):
  1. Gemini 2.5 Flash structured JSON output matching ``PlannerOutput``.
  2. Intent decomposition (find_fish / check_safety) + geocoding against
     ``COASTAL_PORTS_REGISTRY`` with confidence scoring + last-3-turns
     Redis session context.
  3. Minimal tool subsets of [find_fishing_zones, check_ocean_state,
     check_weather, check_geofence] + line-by-line reasoning_trace.
  4. Clarification gating: confidence < 0.6 or coords unresolved ->
     needs_clarification + vernacular GPS prompt.
  5. STRICT INVARIANT (No Silent Fallback): on LLM timeout (>500ms) or API
     failure this module RAISES (PlannerTimeoutError / PlannerAPIError)
     with an explicit SSE error event payload. It NEVER calls legacy
      regex heuristics (fallback._parse_intent / _resolve_location)
     on the failure path — callers must surface the error event.

Envelope: public entry points return
  {"status","summary","next_actions","artifacts", ...}
per AGENTS.md section 3.2 observation contract.

Code Trumps LLM: this service only PLANS (which tools to run). PostGIS/GIS
retrieval and combiner 40/30/20/10 scoring + hard safety veto stay
deterministic downstream (combiner.py) and are never overridden here.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Awaitable, Callable

try:
    from langsmith import traceable
except ImportError:
    def traceable(*args: Any, **kwargs: Any) -> Any:  # type: ignore
        def decorator(fn: Any) -> Any:
            return fn
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]
        return decorator

from backend.agents.planner_schema import (
    CLARIFICATION_THRESHOLD,
    COASTAL_PORTS_REGISTRY,
    KNOWN_TOOLS,
    PLANNER_MODEL,
    PLANNER_SYSTEM_PROMPT,
    PLANNER_TIMEOUT_MS,
    PlannerOutput,
    TargetLocation,
)

logger = logging.getLogger(__name__)

__all__ = [
    "PLANNER_MODEL",
    "PLANNER_TIMEOUT_MS",
    "PLANNER_TIMEOUT_S",
    "CLARIFICATION_THRESHOLD",
    "CLARIFICATION_TEXTS",
    "PlannerError",
    "PlannerTimeoutError",
    "PlannerAPIError",
    "PlannerConfigError",
    "get_recent_turns",
    "build_planner_prompt",
    "validate_and_normalize_plan",
    "build_clarification_text",
    "planner_error_to_sse_event",
    "plan_query",
    "generate_structured_plan",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PLANNER_TIMEOUT_S: float = PLANNER_TIMEOUT_MS / 1000.0  # 0.5s SLA budget

_HISTORY_LIMIT = 3  # multi-turn context: last 3 turns from Redis session cache

# Known intent vocabulary (LLM free-form list is normalized toward these;
# unknown intents are preserved verbatim, never dropped).
_INTENT_FISH_ALIASES = {"find_fish", "wants_fish", "find_fishing", "fish", "pfz"}
_INTENT_SAFETY_ALIASES = {
    "check_safety",
    "wants_safety",
    "check_sea",
    "check_weather",
    "safety",
    "safe",
}

# Vernacular clarification prompts (GPS request). Native script + Arabic
# digits only (lexical_mask spec: never regional digits). English names for
# the 7 registry ports are kept verbatim so fishermen can match signboards.
CLARIFICATION_TEXTS: dict[str, str] = {
    "en": (
        "Please share your GPS location (latitude, longitude) or mention a nearby "
        "coastal place like Kochi, Munambam, Beypore, Kollam, Vizag, Veraval, or "
        "Chennai so I can find safe fishing zones near you."
    ),
    "ml": (
        "ദയവായി നിങ്ങളുടെ GPS ലൊക്കേഷൻ (അക്ഷാംശം, രേഖാംശം) പങ്കിടുക അല്ലെങ്കിൽ "
        "കൊച്ചി, മുനമ്പം, ബേപ്പൂർ, കൊല്ലം, വിശാഖപട്ടണം, വെരാവൽ, ചെന്നൈ തുടങ്ങിയ "
        "അടുത്ത തീരദേശ സ്ഥലം പറയുക, അപ്പോൾ നിങ്ങൾക്ക് അടുത്തുള്ള സുരക്ഷിത "
        "മീൻപിടിത്ത മേഖലകൾ കണ്ടെത്താം."
    ),
    "ta": (
        "தயவுசெய்து உங்கள் GPS இருப்பிடத்தை (அட்சரேகை, தீர்க்கரேகை) பகிரவும் "
        "அல்லது கொச்சி, முனம்பம், பேப்பூர், கொல்லம், விசாகப்பட்டினம், வேராவல், "
        "சென்னை போன்ற அருகிலுள்ள கடலோர இடத்தைக் குறிப்பிடவும், உங்களுக்கு "
        "அருகிலுள்ள பாதுகாப்பான மீன்பிடி மண்டலங்களைக் கண்டறியலாம்."
    ),
    "te": (
        "దయచేసి మీ GPS స్థానాన్ని (అక్షాంశం, రేఖాంశం) పంచుకోండి లేదా కొచ్చి, "
        "మునంబం, బేపూర్, కొల్లం, వైజాగ్, వేరావల్, చెన్నై వంటి సమీప తీర "
        "ప్రాంతాన్ని చెప్పండి, అప్పుడు మీకు సమీపంలోని సురక్షిత చేపల "
        "మండలాలను కనుగొనగలను."
    ),
    "hi": (
        "कृपया अपना GPS स्थान (अक्षांश, देशांतर) साझा करें या कोच्चि, मुनंबम, "
        "बेपोर, कोल्लम, विजाग, वेरावल, चेन्नई जैसे नज़दीकी तटीय स्थान का नाम "
        "बताएँ ताकि आपके पास के सुरक्षित मत्स्य क्षेत्र खोजे जा सकें।"
    ),
}

# Portable alias: Vizag <-> Visakhapatnam resolve to the same coordinates.
_PORT_ALIASES: dict[str, str] = {
    "vizag": "Vizag",
    "visakhapatnam": "Vizag",
}

# Max haversine drift (km) allowed between an LLM-returned port_name and its
# LLM-returned coordinates before the match is rejected as inconsistent.
_PORT_COORD_DRIFT_KM = 50.0

# Redis context budget: 50ms of the 500ms SLA. get_recent_turns must never
# consume 1s (1.0s + 0.5s LLM = 1500ms total); context degrades to [] instead.
_REDIS_BUDGET_S = 0.05

# Transport timeout (ms) for the google-genai HTTP client. asyncio.wait_for
# cancels the *waiter* but a to_thread worker may linger until the socket
# itself times out — a short transport timeout bounds that linger.
_TRANSPORT_TIMEOUT_MS = PLANNER_TIMEOUT_MS

# Module-level default client cache (finding 2.2): one Client per process,
# reused across plan_query calls instead of per-invocation construction.
_DEFAULT_CLIENT: Any | None = None


# ---------------------------------------------------------------------------
# Explicit errors — No Silent Fallback (invariant 2)
# ---------------------------------------------------------------------------


class PlannerError(Exception):
    """Base planner failure. Carries an explicit SSE error event payload."""

    def __init__(self, message: str, *, elapsed_ms: int = 0) -> None:
        super().__init__(message)
        self.elapsed_ms = elapsed_ms

    def to_sse_event(self) -> dict[str, Any]:
        return planner_error_to_sse_event(self)


class PlannerTimeoutError(PlannerError):
    """LLM exceeded the 500ms SLA budget (or the underlying call timed out)."""


class PlannerAPIError(PlannerError):
    """LLM API failure: missing key, transport error, or invalid JSON output."""


class PlannerConfigError(PlannerError):
    """Planner misconfiguration (e.g. no API key and no injected client)."""


def planner_error_to_sse_event(exc: BaseException, *, elapsed_ms: int = 0) -> dict[str, Any]:
    """Render an explicit SSE ``error`` event for a planner failure.

    ``fallback`` is always ``"none"`` — legacy regex heuristics must NOT
    mask this failure (ticket invariant 2). Callers stream this event
    verbatim and stop the planning branch.
    """
    ms = int(getattr(exc, "elapsed_ms", elapsed_ms) or elapsed_ms or 0)
    return {
        "type": "error",
        "agent": "planner",
        "message": f"planner failed: {exc}",
        "fallback": "none",
        "retry_hint": "retry plan_query once within 500ms budget; do NOT fall back to regex heuristics",
        "elapsed_ms": ms,
    }


# ---------------------------------------------------------------------------
# Multi-turn context — last 3 turns from Redis session cache
# ---------------------------------------------------------------------------


async def get_recent_turns(session_id: str | None, limit: int = _HISTORY_LIMIT) -> list[dict]:
    """Fetch the last ``limit`` conversation turns for planner context.

    Best-effort: uses ``backend.db.redis.get_history`` (in-memory fallback
    when no live Redis). Returns [] when there is no session or the cache
    is unreachable. Degrading *context* to empty is NOT a planning
    fallback — the LLM plan call itself still must succeed or raise.
    """
    if not session_id:
        return []
    try:
        from backend.db import redis as redis_mod  # lazy: M-A must not touch backend/db at import

        turns = await asyncio.wait_for(
            redis_mod.get_history(session_id, limit=limit), timeout=_REDIS_BUDGET_S
        )
        if not isinstance(turns, list):
            return []
        return [t for t in turns if isinstance(t, dict)][-limit:]
    except asyncio.TimeoutError:
        logger.warning("planner_service: redis history timeout session=%s", session_id)
        return []
    except Exception as exc:
        logger.warning("planner_service: redis history failed session=%s: %s", session_id, exc)
        return []


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def _format_history(turns: list[dict]) -> str:
    if not turns:
        return "(no prior turns)"
    lines: list[str] = []
    for t in turns:
        q = t.get("query") or t.get("content") or ""
        place = t.get("place") or ""
        zid = t.get("zone_id") or ""
        extra = f" -> {place or zid}".rstrip() if (place or zid) else ""
        lines.append(f"- {str(q)[:160]}{extra}")
    return "\n".join(lines)


def build_planner_prompt(
    query: str,
    language_hint: str = "en",
    location: dict | None = None,
    recent_turns: list[dict] | None = None,
) -> str:
    """Compose the Gemini user prompt: query + hints + GPS + history.

    The system contract (``PLANNER_SYSTEM_PROMPT``) carries the tool table,
    registry, and JSON-schema rules; this adds the per-request facts.
    Explicit caller GPS is ground truth handed to the LLM as a candidate —
    the LLM still decides, and ``validate_and_normalize_plan`` snaps to it
    only when the LLM leaves coordinates unresolved.
    """
    lat = lon = None
    if isinstance(location, dict):
        for k in ("lat", "latitude", "y"):
            if location.get(k) is not None:
                try:
                    lat = float(location[k])
                    break
                except (TypeError, ValueError):
                    continue
        for k in ("lon", "lng", "longitude", "x"):
            if location.get(k) is not None:
                try:
                    lon = float(location[k])
                    break
                except (TypeError, ValueError):
                    continue
        if lat is not None and not (-90.0 <= lat <= 90.0):
            lat = None
        if lon is not None and not (-180.0 <= lon <= 180.0):
            lon = None
    gps_line = (
        f"Explicit caller GPS (ground truth, prefer it): lat={lat}, lon={lon}"
        if lat is not None and lon is not None
        else "Explicit caller GPS: none provided"
    )
    return (
        f"{PLANNER_SYSTEM_PROMPT}\n\n"
        f"User query: {query or ''}\n"
        f"Caller language hint: {language_hint or 'en'}\n"
        f"{gps_line}\n"
        f"Recent conversation (last {len(recent_turns or [])} turns):\n"
        f"{_format_history(recent_turns or [])}\n\n"
        f"Respond with ONLY the PlannerOutput JSON object."
    )


# ---------------------------------------------------------------------------
# Validation & normalization (deterministic checks on the LLM output)
# ---------------------------------------------------------------------------


def _normalize_language(code: Any) -> str:
    if not code or not isinstance(code, str):
        return "en"
    c = code.strip().lower().split("-")[0].split("_")[0]
    return c if c in ("en", "ml", "ta", "te", "hi") else "en"


def _normalize_intents(intents: Any) -> list[str]:
    if not intents or not isinstance(intents, list):
        return []
    out: list[str] = []
    for i in intents:
        if not isinstance(i, str):
            continue
        s = i.strip().lower().replace("-", "_").replace(" ", "_")
        if s in _INTENT_FISH_ALIASES:
            s = "find_fish"
        elif s in _INTENT_SAFETY_ALIASES:
            s = "check_safety"
        if s and s not in out:
            out.append(s)
    return out


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math as _math

    r = 6371.0088
    p1, p2 = _math.radians(lat1), _math.radians(lat2)
    a = (
        _math.sin(_math.radians(lat2 - lat1) / 2.0) ** 2
        + _math.cos(p1) * _math.cos(p2) * _math.sin(_math.radians(lon2 - lon1) / 2.0) ** 2
    )
    return 2.0 * r * _math.asin(_math.sqrt(a))


def _registry_lookup(port_name: str | None) -> tuple[str | None, list[float] | None]:
    """Canonical (name, [lat, lon]) for a registry port or alias; (None, None) if unknown."""
    if not port_name or not isinstance(port_name, str):
        return None, None
    key = port_name.strip().lower()
    key = _PORT_ALIASES.get(key, port_name.strip())
    # case-insensitive match against registry keys
    for name, coords in COASTAL_PORTS_REGISTRY.items():
        if name.lower() == key.lower() or (isinstance(key, str) and name.lower() == key):
            return name, coords
    return None, None


def _verify_geocoding(plan: PlannerOutput) -> PlannerOutput:
    """Deterministic registry verification of the LLM's geocoding.

    - Known port + missing/far coords -> snap to registry (cap 0.85: the
      LLM named the port but did not localize it precisely).
    - Coords far (>50km) from the named port -> drop port_name, downgrade
      location confidence to 0.5 so the clarification gate fires (never
      serve a self-contradictory location).
    - Unknown port name -> keep coords, clear port_name (no fabrication).
    """
    loc = plan.target_location
    if not loc.port_name:
        return plan
    canon, coords = _registry_lookup(loc.port_name)
    if coords is None:
        loc.port_name = None
        return plan
    loc.port_name = canon
    reg_lat, reg_lon = float(coords[0]), float(coords[1])
    if loc.lat is None or loc.lon is None:
        loc.lat, loc.lon = reg_lat, reg_lon
        # Snapped from registry: LLM named the port but gave no coords.
        # Floor to 0.85 (not min(): a 0.0 LLM confidence must not survive
        # the snap and cause a false clarification); keep higher values
        # capped at 0.95.
        cur = float(loc.confidence)
        loc.confidence = 0.85 if cur < 0.6 else min(cur, 0.95)
        return plan
    try:
        drift = _haversine_km(float(loc.lat), float(loc.lon), reg_lat, reg_lon)
    except (TypeError, ValueError):
        drift = float("inf")
    if drift > _PORT_COORD_DRIFT_KM:
        loc.port_name = None
        loc.confidence = min(float(loc.confidence), 0.5)
    return plan


def _line_refers_to_tool(line: str, tool: str) -> bool:
    """Anchored trace-line attribution.

    Matches only when the line *starts with* the tool name or with
    ``SELECT <tool>`` / ``SKIP <tool>`` (after stripping). A bare
    substring check (``tool in line``) misattributes lines that mention
    a tool mid-sentence.
    """
    s = line.strip()
    return (
        s.startswith(tool)
        or s.startswith(f"SELECT {tool}")
        or s.startswith(f"SKIP {tool}")
    )


def _complete_reasoning_trace(plan: PlannerOutput) -> PlannerOutput:
    """Guarantee one auditable trace line per known tool.

    Lines the LLM wrote are kept verbatim. For any tool the LLM never
    mentioned, a transparent completion line is appended (marked as
    auto-added) so auditors can distinguish LLM reasoning from filler.
    Tools never mentioned are also ensured absent from selected_tools.
    """
    trace = list(plan.reasoning_trace or [])
    mentioned = {t for t in KNOWN_TOOLS if any(_line_refers_to_tool(line, t) for line in trace)}
    for tool in KNOWN_TOOLS:
        if tool not in mentioned:
            if tool in plan.selected_tools:
                trace.append(
                    f"{tool} selected by planner (trace line auto-added; "
                    f"LLM gave no explicit justification)"
                )
            else:
                trace.append(
                    f"SKIP {tool}: planner gave no justification; treated as "
                    f"not selected (trace completion, auditable)"
                )
    # Safety: a tool with only a SKIP-style line must not stay selected.
    selected: list[str] = []
    for t in plan.selected_tools:
        lines = [ln for ln in trace if _line_refers_to_tool(ln, t)]
        if lines and all(ln.startswith("SKIP ") for ln in lines):
            continue
        selected.append(t)
    plan.reasoning_trace = trace
    plan.selected_tools = selected
    return plan


def validate_and_normalize_plan(
    raw: dict[str, Any] | PlannerOutput,
    *,
    explicit_location: dict | None = None,
) -> PlannerOutput:
    """Parse + deterministically check an LLM plan (raises PlannerAPIError).

    Steps: schema parse (unknown tools rejected by PlannerOutput validator)
    -> language/intent normalization -> registry geocoding verification ->
    trace completion -> caller-GPS snap (only when LLM left coords empty)
    -> clarification gating (needs_clarification forces selected_tools=[]).

    Raises:
        PlannerAPIError: raw payload does not match PlannerOutput schema.
    """
    try:
        plan: PlannerOutput
        if isinstance(raw, PlannerOutput):
            plan = raw
        else:
            plan = PlannerOutput.model_validate(raw)
    except Exception as exc:
        raise PlannerAPIError(f"planner returned invalid PlannerOutput JSON: {exc}") from exc

    plan.detected_language = _normalize_language(plan.detected_language)
    plan.intents = _normalize_intents(plan.intents)
    plan = _verify_geocoding(plan)

    # Caller GPS is ground truth: adopt it only when the LLM resolved nothing.
    if plan.target_location.lat is None or plan.target_location.lon is None:
        if isinstance(explicit_location, dict):
            lat = lon = None
            for k in ("lat", "latitude", "y"):
                if explicit_location.get(k) is not None:
                    try:
                        lat = float(explicit_location[k])
                        break
                    except (TypeError, ValueError):
                        continue
            for k in ("lon", "lng", "longitude", "x"):
                if explicit_location.get(k) is not None:
                    try:
                        lon = float(explicit_location[k])
                        break
                    except (TypeError, ValueError):
                        continue
            if (
                lat is not None
                and lon is not None
                and -90.0 <= lat <= 90.0
                and -180.0 <= lon <= 180.0
            ):
                plan.target_location = TargetLocation(
                    lat=lat, lon=lon, port_name=None, confidence=0.95
                )

    plan = _complete_reasoning_trace(plan)

    # Clarification gate: low confidence or unresolved coords -> no dispatch.
    if plan.needs_clarification():
        if plan.selected_tools:
            plan.reasoning_trace.append(
                "SKIP all tools: clarification gate fired "
                f"(confidence {plan.confidence:.2f} < {CLARIFICATION_THRESHOLD} "
                "or coords unresolved) — asking for GPS instead"
            )
        plan.selected_tools = []

    return plan


# ---------------------------------------------------------------------------
# Clarification text
# ---------------------------------------------------------------------------


def build_clarification_text(language: str = "en") -> str:
    """Vernacular GPS clarification prompt (offline canned, no LLM call)."""
    return CLARIFICATION_TEXTS.get(_normalize_language(language), CLARIFICATION_TEXTS["en"])


# ---------------------------------------------------------------------------
# Gemini call (structured output, hard 500ms budget)
# ---------------------------------------------------------------------------


def _resolve_api_key() -> str | None:
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")


def _get_or_create_client(explicit: Any | None = None) -> Any:
    """Return the explicit client, else the cached module-level default.

    The default is created once per process with a short transport
    timeout (``_TRANSPORT_TIMEOUT_MS``) so a thread blocked in a sync
    SDK call aborts at the socket even if ``asyncio.wait_for`` has
    already cancelled the waiter (thread itself may linger briefly).
    """
    global _DEFAULT_CLIENT
    if explicit is not None:
        return explicit
    if _DEFAULT_CLIENT is not None:
        return _DEFAULT_CLIENT
    api_key = _resolve_api_key()
    if not api_key:
        raise PlannerConfigError(
            "no GEMINI_API_KEY/GOOGLE_API_KEY set and no client injected"
        )
    try:
        from google import genai as _genai  # lazy: optional dep at runtime
    except ImportError as exc:
        raise PlannerConfigError(f"google-genai SDK not installed: {exc}") from exc
    try:
        _DEFAULT_CLIENT = _genai.Client(
            api_key=api_key, http_options={"timeout": int(_TRANSPORT_TIMEOUT_MS)}
        )
    except TypeError:
        # Older SDKs without http_options support.
        _DEFAULT_CLIENT = _genai.Client(api_key=api_key)
    return _DEFAULT_CLIENT


def _strip_code_fences(text: str) -> str:
    """Strip Markdown ``` / ```json fences the model may wrap around JSON."""
    s = text.strip()
    if s.startswith("```"):
        first_nl = s.find("\n")
        if first_nl != -1:
            s = s[first_nl + 1 :]
        else:
            s = s[3:]
        end = s.rfind("```")
        if end != -1:
            s = s[:end]
        return s.strip()
    return s


def _build_planner_config(max_output_tokens: int = 512) -> Any | None:
    """Build the structured-output GenerateContentConfig (None for stubs)."""
    try:
        from google.genai import types as _types  # lazy: optional dep at runtime

        return _types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=PlannerOutput,
            temperature=0.0,
            max_output_tokens=max_output_tokens,
        )
    except ImportError:
        return None  # injected stub clients in tests may not need SDK types


def _generate_structured_json(
    prompt: str,
    client: Any | None,
    *,
    max_output_tokens: int = 512,
) -> str:
    """Synchronous Gemini structured-JSON call. Returns raw JSON text.

    Uses the ``google-genai`` SDK (``response_schema=PlannerOutput`` +
    ``response_mime_type="application/json"``) so the model itself is
    constrained to the contract. Raises PlannerConfigError/PlannerAPIError.
    Runs in a worker thread via the caller (see plan_query). The module-
    level client cache is reused when ``client`` is None.

    Thread-leak note: the caller wraps this in ``asyncio.wait_for``; on
    timeout the waiter is cancelled but the worker thread may linger
    until the socket times out — bounded by the short transport timeout
    set at client creation (``_TRANSPORT_TIMEOUT_MS``).
    """
    client = _get_or_create_client(client)

    config = _build_planner_config(max_output_tokens=max_output_tokens)

    try:
        if config is not None:
            response = client.models.generate_content(
                model=PLANNER_MODEL, contents=prompt, config=config
            )
        else:  # pragma: no cover — test-stub path
            response = client.models.generate_content(model=PLANNER_MODEL, contents=prompt)
    except Exception as exc:
        raise PlannerAPIError(f"gemini {PLANNER_MODEL} call failed: {exc}") from exc

    text = getattr(response, "text", None)
    if not text or not str(text).strip():
        raise PlannerAPIError(f"gemini {PLANNER_MODEL} returned empty response")
    return str(text)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


@traceable(
    name="orca_planner_service",
    run_type="chain",
    tags=["orca", "planner", "gemini-2.5-flash"],
)
async def plan_query(
    query: str,
    language: str = "en",
    location: dict | None = None,
    session_id: str | None = None,
    *,
    client: Any | None = None,
    timeout_s: float = PLANNER_TIMEOUT_S,
    generate_fn: Callable[..., Awaitable[str]] | None = None,
) -> dict[str, Any]:
    """Plan a user query with Gemini 2.5 Flash structured output.

    Args:
        query: raw user text (any supported language).
        language: caller language hint (BCP-47-ish; LLM decides final code).
        location: optional explicit GPS {"lat","lon"} (ground truth).
        session_id: optional session for last-3-turns Redis context.
        client: optional injected ``google-genai`` client (tests/di).
        timeout_s: SLA budget, default 0.5s. Exceeding it RAISES
            PlannerTimeoutError — never degrades to regex heuristics.
        generate_fn: optional async ``(prompt) -> json_text`` override for
            tests (bypasses the SDK but keeps timeout + validation paths).

    Returns:
        Envelope {"status","summary","next_actions","artifacts",
        "plan": PlannerOutput, "needs_clarification": bool,
        "clarification_text": str|None, "elapsed_ms": int}.

    Raises:
        PlannerTimeoutError / PlannerAPIError / PlannerConfigError — with
        ``.to_sse_event()`` for explicit SSE error streaming.
    """
    t0 = time.perf_counter()

    def _elapsed_ms() -> int:
        return int((time.perf_counter() - t0) * 1000)

    recent_turns = await get_recent_turns(session_id)
    prompt = build_planner_prompt(query, language, location, recent_turns)

    # Total SLA budget is timeout_s (default 0.5s) INCLUDING the Redis
    # context fetch above. Whatever Redis consumed is subtracted so the
    # LLM call only gets the remainder (floored at 50ms), keeping the
    # end-to-end total within budget instead of 50ms + 500ms.
    remaining_s = max(0.05, timeout_s - (time.perf_counter() - t0))

    try:
        if generate_fn is not None:
            raw_text = await asyncio.wait_for(generate_fn(prompt), timeout=remaining_s)
        else:
            resolved = _get_or_create_client(client)
            aio_models = getattr(getattr(resolved, "aio", None), "models", None)
            if aio_models is not None and hasattr(aio_models, "generate_content"):
                # Preferred: native async SDK call — wait_for truly cancels,
                # no worker thread to linger (finding 1.1).
                config = _build_planner_config()
                try:
                    if config is not None:
                        aresp = await asyncio.wait_for(
                            aio_models.generate_content(
                                model=PLANNER_MODEL, contents=prompt, config=config
                            ),
                            timeout=remaining_s,
                        )
                    else:  # pragma: no cover — stub path
                        aresp = await asyncio.wait_for(
                            aio_models.generate_content(
                                model=PLANNER_MODEL, contents=prompt
                            ),
                            timeout=remaining_s,
                        )
                except Exception as exc:
                    if isinstance(exc, asyncio.TimeoutError):
                        raise
                    if isinstance(exc, PlannerError):
                        raise
                    raise PlannerAPIError(
                        f"gemini {PLANNER_MODEL} call failed: {exc}"
                    ) from exc
                raw_text = getattr(aresp, "text", None)
                if not raw_text or not str(raw_text).strip():
                    raise PlannerAPIError(
                        f"gemini {PLANNER_MODEL} returned empty response"
                    )
                raw_text = str(raw_text)
            else:
                # Fallback: sync SDK in a worker thread. wait_for cancels
                # the waiter but the thread may linger until the socket
                # times out (bounded by _TRANSPORT_TIMEOUT_MS).
                raw_text = await asyncio.wait_for(
                    asyncio.to_thread(_generate_structured_json, prompt, resolved),
                    timeout=remaining_s,
                )
    except asyncio.TimeoutError as exc:
        ms = _elapsed_ms()
        raise PlannerTimeoutError(
            f"gemini {PLANNER_MODEL} exceeded {int(timeout_s * 1000)}ms SLA budget",
            elapsed_ms=ms,
        ) from exc
    except PlannerError:
        raise
    except Exception as exc:  # pragma: no cover — defensive (SDK wraps most)
        raise PlannerAPIError(f"gemini {PLANNER_MODEL} call failed: {exc}") from exc

    elapsed_ms = _elapsed_ms()
    # SLA is a hard budget: even a successful call past the deadline fails
    # explicitly rather than silently consuming tail latency (P95 < 2.0s).
    if elapsed_ms > int(timeout_s * 1000):
        raise PlannerTimeoutError(
            f"gemini {PLANNER_MODEL} exceeded {int(timeout_s * 1000)}ms SLA budget "
            f"(took {elapsed_ms}ms)",
            elapsed_ms=elapsed_ms,
        )

    try:
        plan = PlannerOutput.model_validate_json(_strip_code_fences(raw_text))
    except Exception as exc:
        raise PlannerAPIError(
            f"planner returned invalid PlannerOutput JSON: {exc}"
        ) from exc

    plan = validate_and_normalize_plan(plan, explicit_location=location)
    needs_clarification = plan.needs_clarification()
    clarification = build_clarification_text(plan.detected_language) if needs_clarification else None

    summary = (
        f"planner {PLANNER_MODEL} ok in {elapsed_ms}ms: "
        f"intents={plan.intents} tools={plan.selected_tools} "
        f"conf={plan.confidence:.2f}"
        if not needs_clarification
        else (
            f"planner {PLANNER_MODEL} ok in {elapsed_ms}ms: "
            f"needs_clarification (conf={plan.confidence:.2f})"
        )
    )
    return {
        "status": "success",
        "summary": summary,
        "next_actions": (
            ["dispatch selected_tools via graph.py (#32)"]
            if not needs_clarification
            else ["stream clarification_text, await GPS"]
        ),
        "artifacts": [],
        "plan": plan,
        "needs_clarification": needs_clarification,
        "clarification_text": clarification,
        "elapsed_ms": elapsed_ms,
    }


@traceable(
    name="orca_generate_structured_plan",
    run_type="chain",
    tags=["orca", "planner", "structured_plan"],
)
async def generate_structured_plan(
    query: str,
    language: str = "en",
    location: dict | None = None,
    session_id: str | None = None,
    *,
    client: Any | None = None,
    timeout_s: float = PLANNER_TIMEOUT_S,
    generate_fn: Callable[..., Awaitable[str]] | None = None,
) -> dict[str, Any]:
    """Generate structured planner output with LangSmith tracing support."""
    return await plan_query(
        query=query,
        language=language,
        location=location,
        session_id=session_id,
        client=client,
        timeout_s=timeout_s,
        generate_fn=generate_fn,
    )

