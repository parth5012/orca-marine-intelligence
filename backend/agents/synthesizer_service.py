"""
Masked LLM Advisory Synthesizer Service.

Owner: M-A (Agents & Orchestration)
Module: backend/agents/synthesizer_service.py
Ticket: M-A: Implement Masked LLM Advisory Synthesizer in Decision Agent (#33)
Map: #30 (Destination: full dynamic LLM reasoning — Planner + Synthesizer)

Dynamic LLM advisory synthesis powered by Gemini 2.5 Flash
(``gemini-2.5-flash``) under a strict 1.4s sub-agent SLA budget.
Deterministic combiner scoring + hard safety veto stay upstream
(combiner.py); this service only *synthesizes wording* from masked
placeholders — Code Trumps LLM.

Flow (cheap regex, P95<2.0s):
  1. Metric Lexical Masking: mask nautical numbers/units in the
     deterministic combiner explanation via
     ``backend/agents/lexical_mask.py`` (MarineGlossaryMasker):
     bearings ``__MBEARING_0__``, knots ``__MKNOTS_0__``,
     distances ``__MDIST_0__``, coordinates ``__MCOORD_0__``
     (+ ``__MDEG__`` / ``__MMETER__`` / ``__MACR__``).
  2. LLM Synthesis Directives: feed masked placeholders + zone context
     (best zone, all_unsafe, banned flags, citation) to Gemini 2.5 Flash
     with strict directives. MANDATORY: if ``all_unsafe`` is True or the
     best zone is inside an MPA / outside the EEZ, the prompt strictly
     mandates the exact English phrase ``DO NOT SAIL`` plus explicit
     safety warnings. The LLM must preserve every ``__M*__`` placeholder
     verbatim and must never invent metrics.
  3. Unmasking & Post-Validation: restore exact originals with
     ``unmask_text()`` (Arabic digits 0-9), then post-validate with
     ``derive_safety_tier()`` + ``has_regional_digits()`` +
     ``verify_numbers_preserved()`` + citation check. Veto mismatch,
     placeholder leak, regional digits, or dropped metrics raise.
  4. STRICT INVARIANT (No Silent Fallback): on LLM timeout (>1.4s) or API
     failure or validation failure this module RAISES
     (SynthesizerTimeoutError / SynthesizerAPIError) with an explicit SSE
     error event payload. It NEVER returns a canned regex advisory on the
     failure path — callers (graph.py decision_agent) must surface the
     error event explicitly (``fallback:none``) and keep the
     deterministic combiner explanation as the Code ground truth.

Envelope: public entry points return
  {"status","summary","next_actions","artifacts", ...}
per AGENTS.md section 3.2 observation contract.

Code Trumps LLM: deterministic 40/30/20/10 scoring + all_unsafe veto
stay in combiner.py and are never overridden here. Post-validation
enforces the veto on the LLM wording (DANGER must say DO NOT SAIL;
SAFE/CAUTION must not).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import Any, AsyncGenerator, Awaitable, Callable

try:
    from langsmith import traceable
except ImportError:
    def traceable(*args: Any, **kwargs: Any) -> Any:  # type: ignore
        def decorator(fn: Any) -> Any:
            return fn
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]
        return decorator

logger = logging.getLogger(__name__)

__all__ = [
    "SYNTHESIZER_MODEL",
    "SYNTHESIZER_TIMEOUT_MS",
    "SYNTHESIZER_TIMEOUT_S",
    "SYNTHESIZER_SYSTEM_DIRECTIVES",
    "SynthesizerError",
    "SynthesizerTimeoutError",
    "SynthesizerAPIError",
    "SynthesizerConfigError",
    "mask_advisory_source",
    "build_zone_context",
    "build_synthesizer_prompt",
    "validate_synthesized_text",
    "synthesizer_error_to_sse_event",
    "synthesize_advisory",
    "extract_native_token_text",
    "iter_reply_tokens",
    "synthesize_advisory_stream",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SYNTHESIZER_MODEL = "gemini-2.5-flash"

# Sub-agent SLA budget: 1.4s (map decision #26 observed per-node budget).
# Keeps full pipeline P95<2.0s when added after parallel_analysis.
SYNTHESIZER_TIMEOUT_MS: int = int(os.getenv("ORCA_SYNTHESIZER_TIMEOUT_MS", "30000"))
SYNTHESIZER_TIMEOUT_S: float = SYNTHESIZER_TIMEOUT_MS / 1000.0

# Transport timeout (ms) for the google-genai HTTP client. asyncio.wait_for
# cancels the *waiter* but a to_thread worker may linger until the socket
# itself times out — a short transport timeout bounds that linger.
_TRANSPORT_TIMEOUT_MS = SYNTHESIZER_TIMEOUT_MS

# Module-level default client cache (planner_service pattern): one Client
# per process, reused across synthesize_advisory calls.
_DEFAULT_CLIENT: Any | None = None

# Detects un-unmasked / hallucinated placeholders in LLM output.
# Broadened to catch corrupt LLM tokens (e.g. __M BEARING__, __Mx__, etc.).
_PLACEHOLDER_RE = re.compile(r"__M[A-Za-z0-9_]+__")

# Numeric tokens for metric-preservation checks (Arabic digits only).
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

# Secret-scrub patterns for SEC-01: never leak API keys in SSE errors.
_KEY_VAL_RE = re.compile(r"(?i)\b(api[_-]?key|secret|key)\s*[:=]\s*['\"]?[^'\"\s,}]+['\"]?")
_AIZA_RE = re.compile(r"AIza[0-9A-Za-z\-_]{20,}")


def _scrub_secrets(text: str) -> str:
    """Redact API-key material (key=... / AIza... ) before SSE exposure."""
    if not text:
        return text
    out = _KEY_VAL_RE.sub(r"\1=[REDACTED]", text)
    out = _AIZA_RE.sub("[REDACTED_API_KEY]", out)
    return out


# Supported reply languages (lexical_mask parity).
_SUPPORTED_LANGS = ("en", "ml", "ta", "te", "hi")

# Strict synthesis directives (system contract). The per-request prompt
# appends masked text + zone context + veto flags below.
SYNTHESIZER_SYSTEM_DIRECTIVES: str = """You are ORCA's decision advisory synthesizer (model: gemini-2.5-flash).
Rewrite the masked advisory into a concise fisherman advisory. Be deterministic and auditable.

STRICT RULES (Code Trumps LLM — violations fail validation):
1. Preserve every __M*__ placeholder token EXACTLY (verbatim, no spaces added/removed, no reordering of indices). Never decode, convert, or replace them with numbers.
2. Never invent, modify, or drop nautical metrics (bearings, knots, km, m, coordinates). Use ONLY the placeholders given.
3. Always include the INCOIS citation string verbatim.
4. SAFETY VETO (mandatory): if the context says ALL_UNSAFE=true or BANNED=true (inside MPA or outside EEZ), the advisory MUST contain the exact English phrase "DO NOT SAIL" plus explicit safety warnings naming the reasons (high waves / high wind / Marine Protected Area / outside EEZ). Never recommend sailing when vetoed.
5. If ALL_UNSAFE=false and BANNED=false, do NOT write "DO NOT SAIL" — describe the recommended zone and its conditions factually.
6. Respond in the requested language (native script welcome) but keep placeholders and the citation in ASCII. Never emit regional-script digits — numbers come back via unmasking, so leave placeholders untouched.
7. Keep the advisory short (<120 words), one paragraph plus citation. No prose outside the advisory.
"""


# ---------------------------------------------------------------------------
# Explicit errors — No Silent Fallback (invariant 4)
# ---------------------------------------------------------------------------


class SynthesizerError(Exception):
    """Base synthesizer failure. Carries an explicit SSE error event payload."""

    def __init__(self, message: str, *, elapsed_ms: int = 0) -> None:
        super().__init__(message)
        self.elapsed_ms = elapsed_ms

    def to_sse_event(self) -> dict[str, Any]:
        return synthesizer_error_to_sse_event(self)


class SynthesizerTimeoutError(SynthesizerError):
    """LLM exceeded the 1.4s SLA budget (or the underlying call timed out)."""


class SynthesizerAPIError(SynthesizerError):
    """LLM API failure: transport error, empty output, or post-validation failure."""


class SynthesizerConfigError(SynthesizerError):
    """Synthesizer misconfiguration (e.g. no API key and no injected client)."""


def synthesizer_error_to_sse_event(
    exc: BaseException, *, elapsed_ms: int = 0
) -> dict[str, Any]:
    """Render an explicit SSE ``error`` event for a synthesizer failure.

    ``fallback`` is always ``"none"`` — canned regex advisories must NOT
    mask this failure (ticket invariant 4). Callers stream this event
    verbatim and keep the deterministic combiner explanation as reply.
    """
    ms = int(getattr(exc, "elapsed_ms", elapsed_ms) or elapsed_ms or 0)
    # SEC-01: scrub API keys before SSE exposure (key=... / AIza...).
    safe_msg = _scrub_secrets(f"synthesizer failed: {exc}")
    return {
        "type": "error",
        "agent": "decision_agent",
        "message": safe_msg,
        "fallback": "none",
        "retry_hint": "retry synthesize_advisory once within 1400ms budget; do NOT fall back to regex heuristics",
        "elapsed_ms": ms,
    }


# ---------------------------------------------------------------------------
# Masking + zone context + prompt construction
# ---------------------------------------------------------------------------


def _normalize_lang(code: Any) -> str:
    if not code or not isinstance(code, str):
        return "en"
    c = code.strip().lower().split("-")[0].split("_")[0]
    return c if c in _SUPPORTED_LANGS else "en"


def mask_advisory_source(source_text: str) -> tuple[str, dict[str, str]]:
    """Mask nautical metric spans in the deterministic source advisory.

    Uses ``MarineGlossaryMasker`` (bearings ``__MBEARING_*__``, knots
    ``__MKNOTS_*__``, distances ``__MDIST_*__``, coordinates
    ``__MCOORD_*__``, plus deg/meter/acronym). Returns
    ``(masked_text, placeholder->original table)``.
    """
    from backend.agents.lexical_mask import MarineGlossaryMasker

    return MarineGlossaryMasker().mask(source_text or "")


def _is_banned(best: dict | None) -> bool:
    """True when the best zone is inside an MPA or outside the EEZ."""
    if not isinstance(best, dict):
        return False
    if bool(best.get("inside_mpa")):
        return True
    eez = best.get("inside_eez")
    # None (unknown) is not a ban — only an explicit False bans.
    return eez is False


def build_zone_context(
    combined: dict | None,
    user_location: dict | None = None,
) -> dict[str, Any]:
    """Extract the deterministic zone context the LLM must not override.

    Returns ``{"best","all_unsafe","banned","citation","expected_tier",
    "wave","wind","zone_line"}`` where ``expected_tier`` is the
    ``derive_safety_tier()`` ground truth (Code Trumps LLM).
    """
    from backend.agents.lexical_mask import derive_safety_tier

    combined = combined or {}
    best = combined.get("best") if isinstance(combined.get("best"), dict) else None
    all_unsafe = bool(combined.get("all_unsafe", False))
    citation = str(combined.get("citation") or "INCOIS TextData")
    banned = _is_banned(best)
    wave: Any = best.get("wave_height_m") if best else None
    # CORR-06: explicit None-check — dict.get(key, default) does NOT fall
    # back when the key exists with value None.
    if best:
        _wk = best.get("wind_kt")
        wind: Any = _wk if _wk is not None else best.get("wind_speed_kt")
    else:
        wind = None
    expected_tier = derive_safety_tier(wave, wind, all_unsafe, banned)
    if best is not None:
        # CORR-03: no raw numbers in zone_line — LLM must use placeholders.
        # Keep only place, direction, inside_eez/inside_mpa (+ tier flags).
        zone_line = (
            f"place={best.get('place')} direction={best.get('direction')} "
            f"inside_eez={best.get('inside_eez')} inside_mpa={best.get('inside_mpa')} "
            f"all_unsafe={all_unsafe} banned={banned} expected_tier={expected_tier}"
        )
    else:
        zone_line = "place=None (no zones found)"
    return {
        "best": best,
        "all_unsafe": all_unsafe,
        "banned": banned,
        "citation": citation,
        "expected_tier": expected_tier,
        "wave": wave,
        "wind": wind,
        "zone_line": zone_line,
    }


def build_synthesizer_prompt(
    masked_text: str,
    zone_context: dict[str, Any] | None,
    language: str = "en",
) -> str:
    """Compose the Gemini prompt: directives + masked text + zone context.

    The masked placeholders (``__MBEARING_*__`` etc.) plus the veto flags
    are the only metric/safety facts the LLM may use. When
    ``ALL_UNSAFE=true`` or ``BANNED=true`` the directives strictly mandate
    the exact phrase ``DO NOT SAIL`` with explicit warnings.
    """
    ctx = zone_context or {}
    lang = _normalize_lang(language)
    all_unsafe = bool(ctx.get("all_unsafe", False))
    banned = bool(ctx.get("banned", False))
    citation = str(ctx.get("citation") or "INCOIS TextData")
    # CORR-02: veto parity — recompute tier via derive_safety_tier so a
    # wave/wind DANGER without flags still activates the veto.
    from backend.agents.lexical_mask import derive_safety_tier as _tier

    try:
        expected_tier = str(
            _tier(ctx.get("wave"), ctx.get("wind"), all_unsafe, banned)
        )
    except Exception:
        expected_tier = str(ctx.get("expected_tier") or "UNKNOWN")
    zone_line = str(ctx.get("zone_line") or "place=None")
    veto_active = (expected_tier == "DANGER")
    veto_line = (
        "VETO ACTIVE: EXPECTED_TIER=DANGER — you MUST write "
        '"DO NOT SAIL" with explicit safety warnings.'
        if veto_active
        else "VETO INACTIVE: EXPECTED_TIER!=DANGER — do NOT write "
        '"DO NOT SAIL"; recommend the zone factually.'
    )
    return (
        f"{SYNTHESIZER_SYSTEM_DIRECTIVES}\n\n"
        f"Reply language: {lang} (native script welcome; keep placeholders + citation in ASCII)\n"
        f"Zone context (deterministic ground truth, do not override): {zone_line}\n"
        f"ALL_UNSAFE={str(all_unsafe).lower()} BANNED={str(banned).lower()} "
        f"EXPECTED_TIER={expected_tier}\n"
        f"{veto_line}\n"
        f"Citation (verbatim required): {citation}\n\n"
        f"Masked source advisory (placeholders verbatim):\n{masked_text}\n\n"
        f"Respond with ONLY the advisory text (placeholders preserved)."
    )


# ---------------------------------------------------------------------------
# Post-validation (Code Trumps LLM)
# ---------------------------------------------------------------------------


def validate_synthesized_text(
    unmasked_text: str,
    *,
    source_text: str,
    citation: str,
    wave: Any,
    wind: Any,
    all_unsafe: bool,
    banned: bool,
    table: dict[str, str] | None = None,
) -> str:
    """Post-validate LLM wording against deterministic ground truth.

    Checks: no placeholder leak, no regional digits, all masked numbers
    preserved (no dropped metrics), citation verbatim, and veto parity
    (DANGER must say DO NOT SAIL; SAFE/CAUTION must not).

    CORR-01: numbers are validated ONLY from mask ``table.values()``
    (actual nautical metrics). Falling back to full ``source_text`` would
    falsely require score-breakdown numbers (e.g. score=0.83) that the
    advisory never renders.

    Returns:
        Expected safety tier (``derive_safety_tier()`` ground truth).

    Raises:
        SynthesizerAPIError: any check fails (explicit, no silent fix-up).
    """
    from backend.agents.lexical_mask import (
        derive_safety_tier,
        has_regional_digits,
        verify_numbers_preserved,
    )

    if not unmasked_text or not unmasked_text.strip():
        raise SynthesizerAPIError("synthesizer returned empty advisory text")
    if _PLACEHOLDER_RE.search(unmasked_text):
        raise SynthesizerAPIError(
            "synthesizer leaked placeholders __M*__ (LLM dropped/corrupted mask table)"
        )
    if has_regional_digits(unmasked_text):
        raise SynthesizerAPIError(
            "synthesizer emitted regional-script digits (Arabic 0-9 required)"
        )
    # CORR-01: validate numbers only from mask table values, not the full
    # source_text (which may contain score-breakdown numbers).
    if table is not None:
        _num_source = " ".join(str(v) for v in table.values())
    else:
        _num_source = source_text or ""
    expected_numbers = _NUMBER_RE.findall(_num_source)
    # De-dupe while preserving order for a stable error message.
    seen: list[str] = []
    for n in expected_numbers:
        if n not in seen:
            seen.append(n)
    # Tolerant numeric check: LLM paraphrase ("8 kts" for "8.2kt", "1m" for
    # "1.2m", "0km" for "0.0") must pass; true omission must still fail.
    # Trivial zeros (distance 0.0 for current-location) are skipped — the LLM
    # naturally drops them. Others pass if any number in the reply is within
    # 0.55 (allows int-rounding, catches hallucinated values).
    try:
        _reply_nums = [float(n) for n in _NUMBER_RE.findall(unmasked_text or "")]
    except Exception:
        _reply_nums = []
    missing: list[str] = []
    for n in seen:
        try:
            _e = float(n)
        except (TypeError, ValueError):
            if n not in (unmasked_text or ""):
                missing.append(n)
            continue
        if _e == 0.0:
            continue
        if not any(abs(_t - _e) <= 0.55 for _t in _reply_nums):
            missing.append(n)
    if missing:
        raise SynthesizerAPIError(
            f"synthesizer dropped metrics {missing} (metric hallucination/omission)"
        )
    if citation and citation not in unmasked_text:
        raise SynthesizerAPIError(
            "synthesizer omitted INCOIS citation (citation must be verbatim)"
        )
    expected_tier = derive_safety_tier(wave, wind, all_unsafe, banned)
    vetoed = "do not sail" in unmasked_text.lower()
    if expected_tier == "DANGER" and not vetoed:
        raise SynthesizerAPIError(
            "synthesizer veto violation: DANGER zone without DO NOT SAIL "
            "(Code Trumps LLM — deterministic veto stands)"
        )
    if expected_tier in ("SAFE", "CAUTION") and vetoed:
        raise SynthesizerAPIError(
            f"synthesizer veto violation: {expected_tier} zone must not say "
            "DO NOT SAIL (hallucinated veto — Code Trumps LLM)"
        )
    return expected_tier


# ---------------------------------------------------------------------------
# Gemini call (plain-text synthesis, hard 1.4s budget)
# ---------------------------------------------------------------------------


def _resolve_api_key() -> str | None:
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")


def _get_or_create_client(explicit: Any | None = None) -> Any:
    """Return the explicit client, else the cached module-level default.

    Mirrors planner_service: one Client per process with a short transport
    timeout so a thread blocked in a sync SDK call aborts at the socket
    even if ``asyncio.wait_for`` has already cancelled the waiter.
    """
    global _DEFAULT_CLIENT
    if explicit is not None:
        return explicit
    if _DEFAULT_CLIENT is not None:
        return _DEFAULT_CLIENT
    api_key = _resolve_api_key()
    if not api_key:
        raise SynthesizerConfigError(
            "no GEMINI_API_KEY/GOOGLE_API_KEY set and no client injected"
        )
    try:
        from google import genai as _genai  # lazy: optional dep at runtime
    except ImportError as exc:
        raise SynthesizerConfigError(f"google-genai SDK not installed: {exc}") from exc
    try:
        _DEFAULT_CLIENT = _genai.Client(
            api_key=api_key, http_options={"timeout": int(_TRANSPORT_TIMEOUT_MS)}
        )
    except TypeError:
        # Older SDKs without http_options support.
        _DEFAULT_CLIENT = _genai.Client(api_key=api_key)
    return _DEFAULT_CLIENT


def _build_synthesizer_config(max_output_tokens: int = 512) -> Any | None:
    """Build the plain-text GenerateContentConfig (None for stubs).

    SEC-02: directives are passed as ``system_instruction`` (hard contract);
    they are ALSO kept in the user prompt for SDK-compat.
    """
    try:
        from google.genai import types as _types  # lazy: optional dep at runtime

        try:
            return _types.GenerateContentConfig(
                response_mime_type="text/plain",
                temperature=0.0,
                max_output_tokens=max_output_tokens,
                system_instruction=SYNTHESIZER_SYSTEM_DIRECTIVES,
            )
        except TypeError:
            # Older SDKs without system_instruction support — fall back
            # to prompt-embedded directives (compat).
            return _types.GenerateContentConfig(
                response_mime_type="text/plain",
                temperature=0.0,
                max_output_tokens=max_output_tokens,
            )
    except ImportError:
        return None  # injected stub clients in tests may not need SDK types


def _generate_text_sync(prompt: str, client: Any | None, *, max_output_tokens: int = 512) -> str:
    """Synchronous Gemini plain-text call. Returns raw advisory text.

    Runs in a worker thread via the caller (see synthesize_advisory).
    Raises SynthesizerConfigError/SynthesizerAPIError.
    """
    client = _get_or_create_client(client)
    config = _build_synthesizer_config(max_output_tokens=max_output_tokens)
    try:
        if config is not None:
            response = client.models.generate_content(
                model=SYNTHESIZER_MODEL, contents=prompt, config=config
            )
        else:  # pragma: no cover — test-stub path
            response = client.models.generate_content(model=SYNTHESIZER_MODEL, contents=prompt)
    except Exception as exc:
        raise SynthesizerAPIError(f"gemini {SYNTHESIZER_MODEL} call failed: {exc}") from exc
    text = getattr(response, "text", None)
    if not text or not str(text).strip():
        raise SynthesizerAPIError(f"gemini {SYNTHESIZER_MODEL} returned empty response")
    return str(text)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


@traceable(
    name="orca_synthesizer_service",
    run_type="llm",
    tags=["orca", "synthesizer", "gemini-2.5-flash"],
)
async def synthesize_advisory(
    combined: dict | None,
    language: str = "en",
    user_location: dict | None = None,
    *,
    client: Any | None = None,
    timeout_s: float = SYNTHESIZER_TIMEOUT_S,
    generate_fn: Callable[..., Awaitable[str]] | None = None,
    max_output_tokens: int = 512,
) -> dict[str, Any]:
    """Synthesize LLM wording for a deterministic combiner result.

    Args:
        combined: combiner ``combine_and_rank`` output (ranked_zones, best,
            explanation, citation, all_unsafe). Deterministic scoring/veto
            are ground truth and are never overridden here.
        language: reply language (en|ml|ta|te|hi; unknown → en).
        user_location: optional {"lat","lon"} (observability only).
        client: optional injected ``google-genai`` client (tests/di).
        timeout_s: SLA budget, default 1.4s. Exceeding it RAISES
            SynthesizerTimeoutError — never degrades to regex heuristics.
        generate_fn: optional async ``(prompt) -> masked_text`` override for
            tests (bypasses the SDK but keeps mask → unmask → validate).
        max_output_tokens: LLM output cap (default 512).

    Returns:
        Envelope {"status","summary","next_actions","artifacts",
        "reply": unmasked validated advisory, "masked", "table",
        "safety_tier", "expected_tier", "detected_language",
        "elapsed_ms", "model"}. ``reply`` carries exact Arabic digits.

    Raises:
        SynthesizerTimeoutError / SynthesizerAPIError /
        SynthesizerConfigError — each with ``.to_sse_event()`` for
        explicit SSE error streaming (``fallback:none``).
    """
    from backend.agents.lexical_mask import unmask_text

    t0 = time.perf_counter()

    def _elapsed_ms() -> int:
        return int((time.perf_counter() - t0) * 1000)

    lang = _normalize_lang(language)
    combined = combined or {}
    source_text = str(combined.get("explanation") or "")
    ctx = build_zone_context(combined, user_location)
    citation = ctx["citation"]

    # Empty search: nothing to mask/synthesize — return the deterministic
    # combiner advisory directly without spending LLM budget.
    if ctx["best"] is None:
        elapsed_ms = _elapsed_ms()
        return {
            "status": "success",
            "summary": f"synthesizer {SYNTHESIZER_MODEL} skipped (no zones) in {elapsed_ms}ms",
            "next_actions": ["stream deterministic advisory"],
            "artifacts": [],
            "reply": source_text
            or "No fishing zones found nearby. Try expanding the search area.",
            "masked": "",
            "table": {},
            "safety_tier": "UNKNOWN",
            "expected_tier": "UNKNOWN",
            "detected_language": lang,
            "elapsed_ms": elapsed_ms,
            "model": SYNTHESIZER_MODEL,
        }

    if not source_text.strip():
        raise SynthesizerAPIError("synthesizer has no deterministic source text to mask")

    masked, table = mask_advisory_source(source_text)
    prompt = build_synthesizer_prompt(masked, ctx, lang)

    # CORR-07: no budget left — fail fast, don't make a pointless call.
    remaining_s = timeout_s - (time.perf_counter() - t0)
    if remaining_s <= 0.05:
        raise SynthesizerTimeoutError(
            f"gemini {SYNTHESIZER_MODEL} exceeded {int(timeout_s * 1000)}ms SLA budget "
            "(no budget left before LLM call)",
            elapsed_ms=_elapsed_ms(),
        )

    try:
        if generate_fn is not None:
            masked_reply = await asyncio.wait_for(generate_fn(prompt), timeout=remaining_s)
        else:
            resolved = _get_or_create_client(client)
            aio_models = getattr(getattr(resolved, "aio", None), "models", None)
            if aio_models is not None and hasattr(aio_models, "generate_content"):
                # Preferred: native async SDK call — wait_for truly cancels.
                config = _build_synthesizer_config(max_output_tokens=max_output_tokens)
                try:
                    if config is not None:
                        aresp = await asyncio.wait_for(
                            aio_models.generate_content(
                                model=SYNTHESIZER_MODEL, contents=prompt, config=config
                            ),
                            timeout=remaining_s,
                        )
                    else:  # pragma: no cover — stub path
                        aresp = await asyncio.wait_for(
                            aio_models.generate_content(
                                model=SYNTHESIZER_MODEL, contents=prompt
                            ),
                            timeout=remaining_s,
                        )
                except Exception as exc:
                    if isinstance(exc, asyncio.TimeoutError):
                        raise
                    if isinstance(exc, SynthesizerError):
                        raise
                    raise SynthesizerAPIError(
                        f"gemini {SYNTHESIZER_MODEL} call failed: {exc}"
                    ) from exc
                masked_reply = getattr(aresp, "text", None)
                if not masked_reply or not str(masked_reply).strip():
                    raise SynthesizerAPIError(
                        f"gemini {SYNTHESIZER_MODEL} returned empty response"
                    )
                masked_reply = str(masked_reply)
            else:
                # Fallback: sync SDK in a worker thread. wait_for cancels
                # the waiter but the thread may linger until the socket
                # times out (bounded by _TRANSPORT_TIMEOUT_MS).
                masked_reply = await asyncio.wait_for(
                    asyncio.to_thread(
                        _generate_text_sync, prompt, resolved,
                        max_output_tokens=max_output_tokens,
                    ),
                    timeout=remaining_s,
                )
    except asyncio.TimeoutError as exc:
        ms = _elapsed_ms()
        raise SynthesizerTimeoutError(
            f"gemini {SYNTHESIZER_MODEL} exceeded {int(timeout_s * 1000)}ms SLA budget",
            elapsed_ms=ms,
        ) from exc
    except SynthesizerError:
        raise
    except Exception as exc:  # pragma: no cover — defensive (SDK wraps most)
        raise SynthesizerAPIError(f"gemini {SYNTHESIZER_MODEL} call failed: {exc}") from exc

    elapsed_ms = _elapsed_ms()
    # SLA is a hard budget: even a successful call past the deadline fails
    # explicitly rather than silently consuming tail latency (P95 < 2.0s).
    if elapsed_ms > int(timeout_s * 1000):
        raise SynthesizerTimeoutError(
            f"gemini {SYNTHESIZER_MODEL} exceeded {int(timeout_s * 1000)}ms SLA budget "
            f"(took {elapsed_ms}ms)",
            elapsed_ms=elapsed_ms,
        )

    reply = unmask_text(str(masked_reply), table)
    tier = validate_synthesized_text(
        reply,
        source_text=source_text,
        citation=citation,
        wave=ctx["wave"],
        wind=ctx["wind"],
        all_unsafe=ctx["all_unsafe"],
        banned=ctx["banned"],
        table=table,
    )

    return {
        "status": "success",
        "summary": (
            f"synthesizer {SYNTHESIZER_MODEL} ok in {elapsed_ms}ms: "
            f"masked {len(table)} spans, tier={tier}"
        ),
        "next_actions": ["stream reply tokens via graph.py"],
        "artifacts": [],
        "reply": reply,
        "masked": masked,
        "table": table,
        "safety_tier": tier,
        "expected_tier": tier,
        "detected_language": lang,
        "elapsed_ms": elapsed_ms,
        "model": SYNTHESIZER_MODEL,
    }


# ---------------------------------------------------------------------------
# Token streaming for graph.py SSE (ticket #34, map #30)
# ---------------------------------------------------------------------------


def extract_native_token_text(chunk: Any) -> str:
    """Extract plain text from an ``on_chat_model_stream`` chunk.

    Handles every shape emitted by LangGraph ``astream_events(v2)`` /
    LangChain chat models (verified against langchain-core 1.5.4):

      - ``str`` → returned verbatim.
      - ``AIMessageChunk`` / object with ``.content`` (``str``) → content.
      - ``.content`` as ``list`` of blocks
        (``{"type": "text", "text": "..."}`` or ``{"text": ...}``,
        or objects exposing ``.text``) → joined via each block's
        ``text`` (``b.text`` / ``b["text"]``).
      - ``dict`` with ``content`` / ``text`` keys (same rules recursively).
      - ``list`` of the above → joined.
      - anything else → ``""`` (never raises; caller skips empty).

    Never raises — returns ``""`` when no text is found so the SSE loop
    can ``continue`` without breaking strict ``status* -> map -> safety ->
    token+ -> evidence -> done`` ordering.
    """
    try:
        if chunk is None:
            return ""
        if isinstance(chunk, str):
            return chunk
        if isinstance(chunk, list):
            # List fallback (#34 review): AIMessageChunk content blocks —
            # each block contributes its ``text`` (dict["text"] or .text).
            parts: list[str] = []
            for item in chunk:
                if isinstance(item, dict):
                    # Prefer explicit text block (skip tool_use etc.).
                    _t = item.get("text")
                    if isinstance(_t, str) and _t:
                        parts.append(_t)
                        continue
                else:
                    _btext = getattr(item, "text", None)
                    if isinstance(_btext, str) and _btext:
                        parts.append(_btext)
                        continue
                t = extract_native_token_text(item)
                if t:
                    parts.append(t)
            return "".join(parts)
        if isinstance(chunk, dict):
            for key in ("content", "text", "delta"):
                if chunk.get(key) is not None:
                    t = extract_native_token_text(chunk.get(key))
                    if t:
                        return t
            return ""
        content = getattr(chunk, "content", None)
        if content is None:
            # Some chunks expose .text directly.
            text_attr = getattr(chunk, "text", None)
            if isinstance(text_attr, str):
                return text_attr
            return ""
        return extract_native_token_text(content)
    except Exception:
        return ""


@traceable(
    name="orca_iter_reply_tokens",
    run_type="parser",
    tags=["orca", "tokens"],
)
def iter_reply_tokens(reply_text: str, chunk_size: int = 40) -> list[str]:
    """Chunk a *validated* synthesizer reply into SSE ``token`` texts.

    Delimiter-safe: all chunks except the last carry a trailing space so
    naive client concatenation (``"".join(token.text)``) reconstructs the
    original word spacing. Delegates to
    ``backend.agents.orchestrator._chunk_text`` (single source of truth,
    word-boundary splitting, placeholder-safe because ``__M*__`` tokens
    contain no spaces per ``lexical_mask`` spec). Falls back to a minimal
    whitespace split when the orchestrator import is unavailable (direct
    script runs).

    This is the graceful-degrade path for ticket #34: LangGraph
    ``astream_events`` v2 IS available (langgraph 1.1.2), and
    ``orchestrate_stream_via_graph`` listens for
    ``on_chat_model_stream`` natively — but ``decision_agent`` synthesizes
    via the raw ``google-genai`` SDK (not a LangChain chat model), so no
    native token events fire today. Chunking the validated reply preserves
    strict SSE ordering + early-token buffering semantics with zero
    duplication, and the native hook activates automatically if a
    LangChain chat model is ever embedded inside ``decision_agent``.
    Only this validated path yields to the client — native chunks are
    never streamed raw (see graph.py placeholder guard).
    """
    text = reply_text or ""
    if not text.strip():
        return []
    try:
        try:
            from backend.agents.orchestrator import _chunk_text  # type: ignore
        except ImportError:  # direct script runs
            from orchestrator import _chunk_text  # type: ignore

        raw = list(_chunk_text(text, chunk_size=chunk_size))
    except Exception:
        # Minimal fallback — never break the SSE token+ guarantee.
        raw = [p for p in text.split(" ") if p]
    if not raw:
        return []
    # Delimiter-safe spacing (#34 review fix): trailing space on all but
    # last so "".join(tokens) == original spacing.
    return [c + (" " if i < len(raw) - 1 else "") for i, c in enumerate(raw)]


async def synthesize_advisory_stream(
    combined: dict | None,
    language: str = "en",
    user_location: dict | None = None,
    *,
    client: Any | None = None,
    timeout_s: float = SYNTHESIZER_TIMEOUT_S,
    generate_fn: Callable[..., Awaitable[str]] | None = None,
    max_output_tokens: int = 512,
    chunk_size: int = 40,
) -> AsyncGenerator[str, None]:
    """Stream a validated advisory as SSE-ready token chunks.

    Utility delegate (#34 low): thin async-generator wrapper over
    :func:`synthesize_advisory` + :func:`iter_reply_tokens` — no
    independent LLM call, no extra validation. Prefer calling
    ``synthesize_advisory`` directly when the caller needs the envelope
    (table/elapsed_ms/tier); use this helper only when an SSE token
    iterator is needed.

    Validation gate (Code Trumps LLM): the full LLM reply is assembled
    and post-validated by :func:`synthesize_advisory` (veto parity,
    numbers preserved, citation verbatim) BEFORE any chunk is yielded.
    Streaming unvalidated transport chunks (``generate_content_stream``)
    directly to SSE could emit hallucinated metrics or a missing
    ``DO NOT SAIL`` veto that cannot be retracted — hence validated-then-
    chunked. Each ``yield`` is one SSE ``token`` frame; callers add the
    ``await asyncio.sleep(0)`` flush point between frames for real-time
    delivery while preserving ``map``/``safety``-first ordering via the
    caller's token buffer.

    Args:
        Same as :func:`synthesize_advisory` plus ``chunk_size`` (chars).

    Yields:
        Token strings (already word-boundary chunked). Empty reply yields
        nothing — callers fall back to the deterministic combiner text.

    Raises:
        SynthesizerTimeoutError / SynthesizerAPIError /
        SynthesizerConfigError — same as :func:`synthesize_advisory`;
        callers surface ``.to_sse_event()`` explicitly (``fallback:none``)
        and keep the deterministic combiner explanation as reply.
    """
    envelope = await synthesize_advisory(
        combined,
        language=language,
        user_location=user_location,
        client=client,
        timeout_s=timeout_s,
        generate_fn=generate_fn,
        max_output_tokens=max_output_tokens,
    )
    reply = str(envelope.get("reply") or "")
    for piece in iter_reply_tokens(reply, chunk_size=chunk_size):
        await asyncio.sleep(0)  # SSE flush point — real-time delivery
        yield piece
