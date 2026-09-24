"""
Bhashini Dhruva Translation + ULCA ASR Client

Owner: M-A (Agents & Orchestration) — Bhashini Dhruva API translation client
Module: backend/core/bhashini.py

Provides:
1. Bidirectional translation for 10 Indian coastal languages via Bhashini Dhruva API.
2. Speech-to-text (ASR) via Bhashini ULCA 2-call flow (Config -> Compute).
3. Redis caching with 1-hour TTL (orca:bhashini:v1:{src}:{tgt}:{hash},
   orca:asr:v1:{lang}:{hash}).
4. Resilient retry (backoff on 5xx/timeout) and graceful fallback (never raises exceptions).
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
import hashlib
import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger("orca.bhashini")

BHASHINI_ENDPOINT = "https://dhruva-api.bhashini.gov.in/services/inference/translation"
CACHE_TTL = 3600  # 1 hour in seconds

# --- ULCA ASR (voice-to-text) contract — research #192 resolution ---------------
# 2-call flow: Config resolves a per-language serviceId + callbackUrl +
# inference key; Compute runs taskType=asr on 16kHz mono WAV (base64).
# Frontend MediaRecorder emits webm/opus which Bhashini does NOT accept —
# backend/routers/chat.py converts to WAV via ffmpeg before calling transcribe().
BHASHINI_ULCA_DEFAULT_BASE = "https://meity-auth.ulcacontrib.org"
BHASHINI_ULCA_CONFIG_PATH = "/ulca/apis/v0/model/getModelsPipeline"
BHASHINI_ASR_COMPUTE_URL = (
    "https://dhruva-api.bhashini.gov.in/services/inference/pipeline"
)
BHASHINI_DEFAULT_PIPELINE_ID = "64392f96daac500b55c543cd"
BHASHINI_DEFAULT_ASR_TIMEOUT_S = 30.0
ASR_CACHE_TTL = 3600  # 1 hour in seconds
ASR_BACKOFF_DELAYS = [1.0, 2.0, 4.0]  # max 4 attempts (mirror translate())


@dataclass
class TranslationResult:
    text: str
    source_lang: str
    target_lang: str
    translated: bool
    cached: bool = False


def _get_cache_key(text: str, source_lang: str, target_lang: str) -> str:
    """Generate SHA256-based Redis cache key for translation pair."""
    text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"orca:bhashini:v1:{source_lang}:{target_lang}:{text_hash}"


def _get_inference_key() -> Optional[str]:
    """
    Resolve the inference Authorization credential from env vars.

    Preference order:
      1. BHASHINI_INFERENCE_KEY (explicit inference key)
      2. BHASHINI_API_KEY       (ULCA api key fallback, backward compat)
    """
    key = os.getenv("BHASHINI_INFERENCE_KEY", "").strip()
    if key:
        return key
    key = os.getenv("BHASHINI_API_KEY", "").strip()
    return key or None


async def translate(
    text: str,
    source_lang: str,
    target_lang: str,
    redis_client: Optional[Any] = None,
) -> TranslationResult:
    """
    Translate text between supported languages via Bhashini Dhruva API.
    
    Never raises an exception — returns TranslationResult with translated=False on any failure.
    """
    if not text or not text.strip() or source_lang == target_lang:
        return TranslationResult(
            text=text,
            source_lang=source_lang,
            target_lang=target_lang,
            translated=False,
            cached=False,
        )

    cache_key = _get_cache_key(text, source_lang, target_lang)

    # 1. Check Redis cache
    if redis_client is not None:
        try:
            cached_val = await redis_client.get(cache_key)
            if cached_val is not None:
                cached_text = cached_val.decode("utf-8") if isinstance(cached_val, bytes) else str(cached_val)
                return TranslationResult(
                    text=cached_text,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    translated=True,
                    cached=True,
                )
        except Exception as e:
            logger.warning("Redis cache read failed for Bhashini translation: %s", e)

    # 2. Check inference credential (BHASHINI_INFERENCE_KEY, else BHASHINI_API_KEY)
    api_key = _get_inference_key()
    if not api_key:
        logger.debug(
            "Neither BHASHINI_INFERENCE_KEY nor BHASHINI_API_KEY is set; "
            "falling back to original text."
        )
        return TranslationResult(
            text=text,
            source_lang=source_lang,
            target_lang=target_lang,
            translated=False,
            cached=False,
        )

    # 3. Call Bhashini Dhruva API with retry for 5xx/timeouts
    payload = {
        "pipelineTasks": [
            {
                "taskType": "translation",
                "config": {
                    "language": {
                        "sourceLanguage": source_lang,
                        "targetLanguage": target_lang,
                    }
                },
            }
        ],
        "inputData": {
            "input": [{"source": text}]
        },
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": api_key,
    }

    backoff_delays = [1.0, 2.0, 4.0]
    max_attempts = len(backoff_delays) + 1

    for attempt in range(max_attempts):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(BHASHINI_ENDPOINT, json=payload, headers=headers)
                
                if resp.status_code == 200:
                    data = resp.json()
                    translated_text = (
                        data.get("pipelineResponse", [{}])[0]
                        .get("output", [{}])[0]
                        .get("target")
                    )
                    if translated_text:
                        # Cache successful translation in Redis
                        if redis_client is not None:
                            try:
                                await redis_client.set(cache_key, translated_text, ex=CACHE_TTL)
                            except Exception as ce:
                                logger.warning("Redis cache write failed: %s", ce)

                        return TranslationResult(
                            text=translated_text,
                            source_lang=source_lang,
                            target_lang=target_lang,
                            translated=True,
                            cached=False,
                        )
                    else:
                        logger.warning("Bhashini 200 response missing target text: %s", data)
                        return TranslationResult(
                            text=text,
                            source_lang=source_lang,
                            target_lang=target_lang,
                            translated=False,
                            cached=False,
                        )

                elif 400 <= resp.status_code < 500:
                    # 4xx client error (429, 401, 400, etc.) — do not retry per spec
                    logger.warning("Bhashini client error status %s: %s", resp.status_code, resp.text)
                    return TranslationResult(
                        text=text,
                        source_lang=source_lang,
                        target_lang=target_lang,
                        translated=False,
                        cached=False,
                    )

                else:
                    # 5xx server error — retry with backoff
                    logger.warning(
                        "Bhashini server error status %s on attempt %d: %s",
                        resp.status_code,
                        attempt + 1,
                        resp.text,
                    )

        except (httpx.TimeoutException, httpx.NetworkError, httpx.RequestError) as net_err:
            logger.warning("Bhashini request error on attempt %d: %s", attempt + 1, net_err)
        except Exception as err:
            logger.warning("Unexpected error calling Bhashini on attempt %d: %s", attempt + 1, err)

        if attempt < max_attempts - 1:
            await asyncio.sleep(backoff_delays[attempt])

    # All retries exhausted or non-retryable error
    return TranslationResult(
        text=text,
        source_lang=source_lang,
        target_lang=target_lang,
        translated=False,
        cached=False,
    )


async def translate_to_english(
    text: str,
    source_lang: str,
    redis_client: Optional[Any] = None,
) -> TranslationResult:
    """Convenience helper to translate vernacular text to English."""
    return await translate(text, source_lang=source_lang, target_lang="en", redis_client=redis_client)


async def translate_from_english(
    text: str,
    target_lang: str,
    redis_client: Optional[Any] = None,
) -> TranslationResult:
    """Convenience helper to translate English text to target vernacular language."""
    return await translate(text, source_lang="en", target_lang=target_lang, redis_client=redis_client)


# ---------------------------------------------------------------------------
# ULCA Speech-to-Text (ASR) — voice path for POST /api/chat/voice (#194)
# ---------------------------------------------------------------------------


@dataclass
class TranscriptionResult:
    text: str
    source_lang: str
    transcribed: bool
    cached: bool = False
    error_code: Optional[str] = None
    error_detail: Optional[str] = None
    retryable: bool = False


def _normalize_asr_lang(source_lang: object) -> str:
    """Normalize UI language codes (ml-IN -> ml) for the ASR contract."""
    if not source_lang or not isinstance(source_lang, str):
        return "en"
    c = source_lang.strip().lower().split("-")[0].split("_")[0]
    return c if c else "en"


def _get_asr_cache_key(wav_bytes: bytes, source_lang: str) -> str:
    """Generate SHA256-based Redis cache key for ASR audio (16kHz mono WAV)."""
    audio_hash = hashlib.sha256(bytes(wav_bytes)).hexdigest()[:16]
    return f"orca:asr:v1:{source_lang}:{audio_hash}"


def _get_ulca_config_url() -> str:
    base = os.getenv("BHASHINI_ULCA_URL", BHASHINI_ULCA_DEFAULT_BASE).rstrip("/")
    return f"{base}{BHASHINI_ULCA_CONFIG_PATH}"


def _get_asr_timeout_s() -> float:
    try:
        return float(os.getenv("BHASHINI_ASR_TIMEOUT_S", str(BHASHINI_DEFAULT_ASR_TIMEOUT_S)))
    except (TypeError, ValueError):
        return BHASHINI_DEFAULT_ASR_TIMEOUT_S


async def _ulca_post(
    url: str,
    headers: dict,
    payload: dict,
    timeout_s: float,
) -> tuple[Optional[Any], Optional[str]]:
    """
    POST with 5xx/timeout retry (1s->2s->4s, max 4 attempts).

    Returns tuple (response, failure_reason) where failure_reason is
    "TIMEOUT", "NETWORK_ERROR", or None.
    - On 200 or 4xx: (resp, None)
    - On 5xx exhausted: (last_resp, None)
    - On timeout exhausted: (None, "TIMEOUT")
    - On network error exhausted: (None, "NETWORK_ERROR")
    Never raises.
    """
    last_resp: Optional[Any] = None
    last_failure_reason: Optional[str] = None
    for attempt in range(len(ASR_BACKOFF_DELAYS) + 1):
        try:
            async with httpx.AsyncClient(
                timeout=timeout_s, follow_redirects=True
            ) as client:
                resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200 or 400 <= resp.status_code < 500:
                return resp, None
            last_resp = resp
            last_failure_reason = None
            logger.warning(
                "Bhashini ASR server error status %s on attempt %d: %s",
                resp.status_code,
                attempt + 1,
                resp.text,
            )
        except httpx.TimeoutException as time_err:
            logger.warning("Bhashini ASR timeout on attempt %d: %s", attempt + 1, time_err)
            last_failure_reason = "TIMEOUT"
            last_resp = None
        except (httpx.NetworkError, httpx.RequestError) as net_err:
            logger.warning("Bhashini ASR request error on attempt %d: %s", attempt + 1, net_err)
            last_failure_reason = "NETWORK_ERROR"
            last_resp = None
        except Exception as err:
            logger.warning("Unexpected error calling Bhashini ASR on attempt %d: %s", attempt + 1, err)
            last_failure_reason = "NETWORK_ERROR"
            last_resp = None
        if attempt < len(ASR_BACKOFF_DELAYS):
            await asyncio.sleep(ASR_BACKOFF_DELAYS[attempt])
    return last_resp, last_failure_reason


def _parse_pipeline_config(data: Any) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Extract (service_id, callback_url, inference_key) from a ULCA
    getModelsPipeline response. Returns (None, None, None) when unparseable.
    """
    try:
        if not isinstance(data, dict):
            return None, None, None
        service_id: Optional[str] = None
        callback_url: Optional[str] = None
        inference_key: Optional[str] = None

        entries = data.get("pipelineResponseConfig", [])
        if isinstance(entries, dict):
            entries = [entries]
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            ep = entry.get("pipelineInferenceAPIEndPoint") or {}
            if isinstance(ep, dict):
                if not callback_url and isinstance(ep.get("callbackUrl"), str):
                    callback_url = ep["callbackUrl"]
                if not inference_key:
                    raw_key = ep.get("inferenceApiKey")
                    if isinstance(raw_key, dict):
                        raw_key = raw_key.get("value") or raw_key.get("__value") or raw_key.get("key")
                    if isinstance(raw_key, str) and raw_key:
                        inference_key = raw_key
            for cfg in entry.get("config", []) or []:
                if isinstance(cfg, dict) and cfg.get("serviceId") and not service_id:
                    service_id = str(cfg["serviceId"])

        # Top-level fallbacks for schema variants (canonical ULCA shape puts
        # pipelineInferenceAPIEndPoint at the top level).
        top_ep = data.get("pipelineInferenceAPIEndPoint")
        if isinstance(top_ep, dict):
            if not callback_url and isinstance(top_ep.get("callbackUrl"), str):
                callback_url = top_ep["callbackUrl"]
            if not inference_key:
                raw_key = top_ep.get("inferenceApiKey")
                if isinstance(raw_key, dict):
                    raw_key = (
                        raw_key.get("value")
                        or raw_key.get("__value")
                        or raw_key.get("key")
                    )
                if isinstance(raw_key, str) and raw_key:
                    inference_key = raw_key
        return service_id, callback_url, inference_key
    except Exception as err:
        logger.warning("Failed parsing ULCA pipeline config: %s", err)
        return None, None, None


async def transcribe(
    audio_bytes: bytes,
    source_lang: str,
    redis_client: Optional[Any] = None,
) -> TranscriptionResult:
    """
    Transcribe 16kHz mono WAV audio via Bhashini ULCA ASR (2-call flow).

    Never raises an exception — returns TranscriptionResult with
    transcribed=False on any failure (missing keys, 4xx, 5xx exhausted,
    network error, empty output). Non-empty results are cached 1h in Redis.
    """
    lang = _normalize_asr_lang(source_lang)
    if not audio_bytes:
        return TranscriptionResult(
            text="",
            source_lang=lang,
            transcribed=False,
            cached=False,
            error_code="NO_SPEECH_DETECTED",
            error_detail="Empty audio payload received.",
            retryable=False,
        )

    cache_key = _get_asr_cache_key(audio_bytes, lang)

    # 1. Check Redis cache
    if redis_client is not None:
        try:
            cached_val = await redis_client.get(cache_key)
            if cached_val is not None:
                cached_text = cached_val.decode("utf-8") if isinstance(cached_val, bytes) else str(cached_val)
                if cached_text.strip():
                    return TranscriptionResult(
                        text=cached_text,
                        source_lang=lang,
                        transcribed=True,
                        cached=True,
                    )
        except Exception as e:
            logger.warning("Redis cache read failed for Bhashini ASR: %s", e)

    # 2. Check ULCA credentials (both required for the Config call)
    api_key = os.getenv("BHASHINI_API_KEY")
    user_id = os.getenv("BHASHINI_ULCA_USER_ID")
    if not api_key or not user_id:
        logger.warning(
            "Bhashini ASR credentials missing (BHASHINI_ULCA_USER_ID or BHASHINI_API_KEY unset). Voice transcription disabled."
        )
        return TranscriptionResult(
            text="",
            source_lang=lang,
            transcribed=False,
            cached=False,
            error_code="ASR_CONFIG_MISSING",
            error_detail="Voice transcription service is unconfigured (missing ASR credentials).",
            retryable=False,
        )

    timeout_s = _get_asr_timeout_s()
    pipeline_id = os.getenv("BHASHINI_PIPELINE_ID", BHASHINI_DEFAULT_PIPELINE_ID)

    # 3. Config call — resolve per-language serviceId + Compute endpoint/key
    config_payload = {
        "pipelineTasks": [
            {
                "taskType": "asr",
                "config": {"language": {"sourceLanguage": lang}},
            }
        ],
        "pipelineRequestConfig": {"pipelineId": pipeline_id},
    }
    config_headers = {
        "Content-Type": "application/json",
        "userID": user_id,
        "ulcaApiKey": api_key,
    }
    config_resp, config_failure = await _ulca_post(
        _get_ulca_config_url(), config_headers, config_payload, timeout_s
    )
    if config_resp is None or config_resp.status_code != 200:
        if config_failure == "TIMEOUT":
            return TranscriptionResult(
                text="",
                source_lang=lang,
                transcribed=False,
                cached=False,
                error_code="ASR_TIMEOUT",
                error_detail="Bhashini ASR config request timed out.",
                retryable=True,
            )
        if config_resp is None:
            return TranscriptionResult(
                text="",
                source_lang=lang,
                transcribed=False,
                cached=False,
                error_code="BHASHINI_UPSTREAM_ERROR",
                error_detail="Bhashini ASR config service unreachable (network error).",
                retryable=True,
            )
        status = config_resp.status_code
        if 400 <= status < 500:
            logger.warning(
                "Bhashini ASR config client error status %s: %s",
                config_resp.status_code,
                config_resp.text,
            )
        return TranscriptionResult(
            text="",
            source_lang=lang,
            transcribed=False,
            cached=False,
            error_code="BHASHINI_UPSTREAM_ERROR",
            error_detail=f"Bhashini ASR config call failed with status {status}.",
            retryable=(status >= 500),
        )

    try:
        config_data = config_resp.json()
    except Exception as err:
        logger.warning("Bhashini ASR config response unparseable: %s", err)
        return TranscriptionResult(
            text="",
            source_lang=lang,
            transcribed=False,
            cached=False,
            error_code="BHASHINI_UPSTREAM_ERROR",
            error_detail="Bhashini ASR config response unparseable.",
            retryable=False,
        )

    service_id, callback_url, inference_key = _parse_pipeline_config(config_data)
    # Env-provided inference key (BHASHINI_INFERENCE_KEY) wins over the
    # config-response key; config-derived key remains the fallback.
    env_inference_key = os.getenv("BHASHINI_INFERENCE_KEY", "").strip()
    if env_inference_key:
        inference_key = env_inference_key
    if not service_id or not inference_key:
        logger.warning(
            "Bhashini ASR config missing serviceId/inference key: has_service_id=%s has_key=%s",
            bool(service_id),
            bool(inference_key),
        )
        return TranscriptionResult(
            text="",
            source_lang=lang,
            transcribed=False,
            cached=False,
            error_code="BHASHINI_UPSTREAM_ERROR",
            error_detail="Bhashini ASR config missing serviceId or inference key.",
            retryable=False,
        )
    compute_url = callback_url or BHASHINI_ASR_COMPUTE_URL
    # Security (CodeRabbit review, PR #255): never send the inference
    # Authorization header over cleartext — reject non-HTTPS callback URLs
    # from the Config response before the Compute request.
    if not compute_url.lower().startswith("https://"):
        logger.warning(
            "Bhashini ASR config callbackUrl is not HTTPS (%s); "
            "rejecting Compute call to avoid credential exposure.",
            compute_url,
        )
        return TranscriptionResult(
            text="",
            source_lang=lang,
            transcribed=False,
            cached=False,
            error_code="BHASHINI_UPSTREAM_ERROR",
            error_detail="Bhashini ASR config callbackUrl is not HTTPS; refusing to send credentials over cleartext.",
            retryable=False,
        )

    # 4. Compute call — base64 WAV in inputData.audio[].audioContent
    audio_b64 = base64.b64encode(bytes(audio_bytes)).decode("ascii")
    compute_payload = {
        "pipelineTasks": [
            {
                "taskType": "asr",
                "config": {
                    "language": {"sourceLanguage": lang},
                    "serviceId": service_id,
                    "audioFormat": "wav",
                    "samplingRate": 16000,
                    "preProcessors": ["vad"],
                    "postProcessors": ["itn", "punctuation"],
                },
            }
        ],
        "inputData": {"audio": [{"audioContent": audio_b64}]},
    }
    # Raw token — no Bearer prefix (mirrors translate()).
    compute_headers = {
        "Content-Type": "application/json",
        "Authorization": inference_key,
    }
    compute_resp, compute_failure = await _ulca_post(
        compute_url, compute_headers, compute_payload, timeout_s
    )
    if compute_resp is None or compute_resp.status_code != 200:
        if compute_failure == "TIMEOUT":
            return TranscriptionResult(
                text="",
                source_lang=lang,
                transcribed=False,
                cached=False,
                error_code="ASR_TIMEOUT",
                error_detail="Bhashini ASR compute request timed out.",
                retryable=True,
            )
        if compute_resp is None:
            return TranscriptionResult(
                text="",
                source_lang=lang,
                transcribed=False,
                cached=False,
                error_code="BHASHINI_UPSTREAM_ERROR",
                error_detail="Bhashini ASR compute service unreachable (network error).",
                retryable=True,
            )
        status = compute_resp.status_code
        if 400 <= status < 500:
            logger.warning(
                "Bhashini ASR compute client error status %s: %s",
                compute_resp.status_code,
                compute_resp.text,
            )
        return TranscriptionResult(
            text="",
            source_lang=lang,
            transcribed=False,
            cached=False,
            error_code="BHASHINI_UPSTREAM_ERROR",
            error_detail=f"Bhashini ASR compute call failed with status {status}.",
            retryable=(status >= 500),
        )

    try:
        compute_data = compute_resp.json()
        text = (
            compute_data.get("pipelineResponse", [{}])[0]
            .get("output", [{}])[0]
            .get("source")
        )
    except Exception as err:
        logger.warning("Bhashini ASR compute response unparseable: %s", err)
        return TranscriptionResult(
            text="",
            source_lang=lang,
            transcribed=False,
            cached=False,
            error_code="BHASHINI_UPSTREAM_ERROR",
            error_detail="Bhashini ASR compute response unparseable.",
            retryable=False,
        )

    if not text or not str(text).strip():
        # No-speech path: valid call, nothing detected — do not cache.
        logger.debug("Bhashini ASR returned empty transcription (no speech detected).")
        return TranscriptionResult(
            text="",
            source_lang=lang,
            transcribed=False,
            cached=False,
            error_code="NO_SPEECH_DETECTED",
            error_detail="No speech detected in audio.",
            retryable=False,
        )

    transcription = str(text).strip()
    if redis_client is not None:
        try:
            await redis_client.set(cache_key, transcription, ex=ASR_CACHE_TTL)
        except Exception as ce:
            logger.warning("Redis ASR cache write failed: %s", ce)

    return TranscriptionResult(
        text=transcription,
        source_lang=lang,
        transcribed=True,
        cached=False,
    )
