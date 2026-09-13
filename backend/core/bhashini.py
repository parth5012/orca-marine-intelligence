"""
Bhashini Dhruva Translation Client

Owner: M-A (Agents & Orchestration) — Bhashini Dhruva API translation client
Module: backend/core/bhashini.py

Provides:
1. Bidirectional translation for 10 Indian coastal languages via Bhashini Dhruva API.
2. Redis caching with 1-hour TTL (orca:bhashini:v1:{src}:{tgt}:{hash}).
3. Resilient retry (backoff on 5xx/timeout) and graceful fallback (never raises exceptions).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger("orca.bhashini")

BHASHINI_ENDPOINT = "https://dhruva-api.bhashini.gov.in/services/inference/translation"
CACHE_TTL = 3600  # 1 hour in seconds


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

    # 2. Check API key
    api_key = os.getenv("BHASHINI_API_KEY")
    if not api_key:
        logger.debug("BHASHINI_API_KEY is not set; falling back to original text.")
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
