"""
Chat Endpoint Router — ORCA Brain Interface

Owner: M-C (Backend API & Platform) — POST /api/chat wrapper
Module: backend/routers/chat.py

Provides conversational interface to ORCA's multi-agent system.
Handles user queries, language detection, agent dispatch, response streaming,
conversation memory via Redis, and vernacular voice transcription.

Endpoints:
  POST /api/chat          Send query, receive SSE advisory stream
  POST /api/chat/voice    Ingest vernacular voice audio, transcribe via Bhashini ULCA ASR

Wayfinder T3 (map #92): /chat/stream alias and /chat/history deleted per
human grill decision — single primary kept, history deferred post-MVP.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import tempfile
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

try:
    from backend.agents.graph import orchestrate_stream_via_graph
    from backend.core.bhashini import (
        TranscriptionResult,
        transcribe,
        translate_from_english,
        translate_to_english,
    )
    from backend.core.security import (
        check_ip_rate_limit,
        get_client_ip,
        sanitize_session_id,
    )
    from backend.db.redis import append_message, get_redis_client
except ImportError:
    from agents.graph import orchestrate_stream_via_graph  # type: ignore
    from core.bhashini import (  # type: ignore
        TranscriptionResult,
        transcribe,
        translate_from_english,
        translate_to_english,
    )
    from core.security import (  # type: ignore
        check_ip_rate_limit,
        get_client_ip,
        sanitize_session_id,
    )
    from db.redis import append_message, get_redis_client  # type: ignore

logger = logging.getLogger("orca.chat")

router = APIRouter(tags=["chat"])

# Security caps (#199): 2k chat chars, 25MB voice. Rate limits per IP:
# 30/min chat, 10/min voice (env-overridable ORCA_CHAT_RPM/ORCA_VOICE_RPM).
CHAT_MESSAGE_MAX_CHARS = 2000
VOICE_MAX_AUDIO_BYTES = 25 * 1024 * 1024
VOICE_FILENAME_MAX_CHARS = 255


def _enforce_rate_limit(request: Request, bucket: str) -> None:
    allowed, retry_after = check_ip_rate_limit(get_client_ip(request), bucket)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded for {bucket}; retry in {retry_after}s",
            headers={"Retry-After": str(retry_after)},
        )


# Generic client-facing SSE error — full traceback stays server-side only.
GENERIC_CHAT_ERROR_MESSAGE = "Internal chat error; please retry."

# ---------------------------------------------------------------------------
# Hindi dual-gate: Hindi reply ONLY when BOTH UI language == hi AND the
# user query itself is Hindi. Otherwise respond in English.
# ---------------------------------------------------------------------------

import re as _re

_HINDI_DEVANAGARI_RE = _re.compile(r"[ऀ-ॿ]")
_HINDI_HINGLISH_RE = _re.compile(
    r"\b(kya|kahan|kaise|kab|kyon|kyun|hai|hain|nahi|nahin|nahn|"
    r"machhli|machhali|machli|samudra|samundra|lahrein|lehren|lahar|hawa|"
    r"toofan|surakshit|mausam|madad|batao|batayen|mujhe|kripya|kal|subah|"
    r"safe hai|kharab|achha|accha)\b",
    _re.IGNORECASE,
)


def _normalize_ui_lang(code: object) -> str:
    if not code or not isinstance(code, str):
        return "en"
    c = code.strip().lower().split("-")[0].split("_")[0]
    return c if c else "en"


def query_is_hindi(text: str) -> bool:
    if not text or not text.strip():
        return False
    if _HINDI_DEVANAGARI_RE.search(text):
        return True
    return bool(_HINDI_HINGLISH_RE.search(text))


def resolve_response_language(ui_language: object, message: str) -> str:
    ui = _normalize_ui_lang(ui_language)
    if ui == "hi":
        return "hi" if query_is_hindi(message or "") else "en"
    return ui



class ChatRequest(BaseModel):
    """Chat advisory request payload."""

    session_id: Optional[str] = Field(default=None, max_length=128)
    message: str = Field(min_length=1, max_length=CHAT_MESSAGE_MAX_CHARS)
    lat: Optional[float] = None
    lon: Optional[float] = None
    language: Optional[str] = "en"


@router.post("/chat")
async def chat(req: ChatRequest, request: Request) -> StreamingResponse:
    """Process chat query through ORCA multi-agent system and stream SSE events."""
    _enforce_rate_limit(request, "chat")
    # session_id stays client-controlled (frontend localStorage flow) but is
    # format-validated; invalid values get a fresh uuid (fixation mitigation,
    # 24h Redis TTL bounds the window — full server-secret deferred post-MVP).
    session_id: str = sanitize_session_id(req.session_id)
    accumulated_tokens: List[str] = []
    full_reply: str = ""
    saved_to_redis: bool = False

    async def save_turn(reply_text: str) -> None:
        nonlocal saved_to_redis
        if saved_to_redis:
            return
        saved_to_redis = True
        try:
            await append_message(session_id, "user", req.message)
            await append_message(session_id, "assistant", reply_text)
        except Exception as exc:
            logger.warning(
                "Failed saving chat turn to Redis for session %s: %s",
                session_id,
                exc,
            )

    async def event_generator():
        nonlocal full_reply, session_id
        location = (
            {"lat": req.lat, "lon": req.lon}
            if req.lat is not None and req.lon is not None
            else None
        )
        user_lang = _normalize_ui_lang(req.language)
        # Dual-gate: Hindi reply only when UI==hi AND query is Hindi.
        effective_lang = resolve_response_language(user_lang, req.message)
        query_hindi = query_is_hindi(req.message or "")
        english_query = req.message
        redis_client = None

        # Input translation: use effective_lang when non-English (existing
        # Bhashini flow). When gated to English but raw query is Hindi
        # (UI=en + Hindi query), still translate hi->en for retrieval — output stays English.
        input_source_lang: str | None = None
        if effective_lang != "en":
            input_source_lang = effective_lang
        elif query_hindi:
            input_source_lang = "hi"

        if input_source_lang is not None:
            try:
                redis_client = await get_redis_client()
            except Exception as e:
                logger.warning("Failed to get redis client: %s", e)
            try:
                result = await translate_to_english(req.message, input_source_lang, redis_client)
                english_query = result.text
                if not result.translated:
                    # Only warn when actually needed (non-English understanding).
                    if effective_lang != "en":
                        warning_event = {
                        "type": "warning",
                        "message": "Bhashini input translation unavailable — processing in original language",
                    }
                        yield f"event: warning\ndata: {json.dumps(warning_event)}\n\n"
            except Exception as te:
                logger.warning("translate_to_english failed: %s", te)

        try:
            async for event in orchestrate_stream_via_graph(
                query=english_query,
                language=effective_lang,
                location=location,
                session_id=session_id,
            ):
                ev_type = event.get("type")
                if ev_type == "token":
                    text = event.get("text") or event.get("content") or ""
                    accumulated_tokens.append(str(text))
                elif ev_type == "done":
                    if not accumulated_tokens and event.get("reply"):
                        full_reply = str(event.get("reply"))
                    else:
                        full_reply = "".join(accumulated_tokens).strip()

                    if event.get("session_id"):
                        session_id = str(event["session_id"])

                    if effective_lang != "en" and full_reply:
                        if redis_client is None:
                            try:
                                redis_client = await get_redis_client()
                            except Exception:
                                pass
                        try:
                            t_result = await translate_from_english(full_reply, effective_lang, redis_client)
                            if t_result.translated:
                                event = dict(event)
                                event["reply"] = t_result.text
                                event["translated"] = True
                                event["original_reply_en"] = full_reply
                            else:
                                event = dict(event)
                                event["translation_warning"] = "Bhashini translation unavailable — showing English response"
                        except Exception as ote:
                            logger.warning("translate_from_english failed: %s", ote)
                            event = dict(event)
                            event["translation_warning"] = "Bhashini translation unavailable; showing English response"

                    # Attach dual-gate language metadata before serialization (required by frontend useSSEChat)
                    event = dict(event)
                    event["ui_language"] = user_lang
                    event["response_language"] = effective_lang
                    event["query_is_hindi"] = query_hindi
                    event["language_gated"] = (effective_lang == "hi")

                    await save_turn(full_reply)

                event_name = event.get("type", "message")
                data_str = json.dumps(event)
                yield f"event: {event_name}\ndata: {data_str}\n\n"
        except Exception as exc:
            logger.error(
                "Error in orchestrate_stream_via_graph: %s", exc, exc_info=True
            )
            err_event = {
                "type": "error",
                "agent": "orchestrator",
                "message": GENERIC_CHAT_ERROR_MESSAGE,
            }
            yield f"event: error\ndata: {json.dumps(err_event)}\n\n"
        finally:
            if not saved_to_redis:
                full_reply = "".join(accumulated_tokens).strip()
                await save_turn(full_reply)

    headers = {
        # no-store: session-specific stream, must never sit in an intermediary cache
        "Cache-Control": "no-store",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=headers,
    )


def _ffmpeg_exe() -> Optional[str]:
    """Resolve an ffmpeg binary: system PATH first, imageio static fallback.

    Vercel serverless (and other slim images) ship no system ffmpeg, which
    used to force raw webm passthrough that ULCA ASR rejects (-> voice 503).
    imageio-ffmpeg bundles a static binary; prefer PATH so host-managed
    ffmpeg (with security updates) wins when present. Returns None only when
    neither exists (passthrough, same as before). Never raises.
    """
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        from imageio_ffmpeg import get_ffmpeg_exe

        bundled = get_ffmpeg_exe()
        if bundled and os.path.isfile(bundled) and os.access(bundled, os.X_OK):
            return str(bundled)
        logger.debug("imageio-ffmpeg binary not usable: %s", bundled)
    except Exception as exc:
        logger.debug("imageio-ffmpeg fallback unavailable: %s", exc)
    return None


def _convert_to_16k_mono_wav(raw: bytes, filename: Optional[str] = None) -> bytes:
    """
    Convert uploaded audio bytes to 16kHz mono WAV (Bhashini ASR requirement).

    Frontend MediaRecorder emits webm/opus which ULCA ASR does NOT accept.
    Tries ffmpeg (`ffmpeg -i in -ac 1 -ar 16000 -sample_fmt s16 out.wav`);
    on any failure (ffmpeg missing/error) falls back to raw passthrough so
    already-WAV uploads still work. Never raises.
    """
    suffix = ""
    if filename and "." in filename:
        ext = filename.rsplit(".", 1)[-1][:8]
        ext = "".join(ch for ch in ext if ch.isalnum())
        if ext:
            suffix = "." + ext
    src_path = None
    dst_path = None
    try:
        ffmpeg_exe = _ffmpeg_exe()
        if ffmpeg_exe is None:
            logger.warning("ffmpeg not found; passing voice audio through unconverted.")
            return raw
        with tempfile.NamedTemporaryFile(suffix=suffix or ".webm", delete=False) as src:
            src.write(raw)
            src_path = src.name
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as dst:
            dst_path = dst.name
        try:
            proc = subprocess.run(
                [ffmpeg_exe, "-y", "-v", "error", "-i", src_path,
                 "-ac", "1", "-ar", "16000", "-sample_fmt", "s16", dst_path],
                capture_output=True,
                timeout=30,
            )
            if proc.returncode != 0:
                logger.warning(
                    "ffmpeg conversion failed (rc=%s): %s; passing audio through unconverted.",
                    proc.returncode,
                    (proc.stderr or b"")[:200],
                )
                return raw
            with open(dst_path, "rb") as fh:
                return fh.read()
        finally:
            for path in (src_path, dst_path):
                if not path:
                    continue
                try:
                    os.unlink(path)
                except OSError:
                    pass
    except Exception as err:
        logger.warning("Voice audio conversion failed, using raw passthrough: %s", err)
        return raw


class VoiceTranscriptionException(HTTPException):
    """Exception raised when voice transcription fails, preserving structured error metadata."""

    def __init__(
        self,
        status_code: int,
        detail: str,
        error_code: str,
        retryable: bool = False,
        headers: Optional[Dict[str, str]] = None,
    ):
        super().__init__(
            status_code=status_code,
            detail={"detail": detail, "error_code": error_code, "retryable": retryable},
            headers=headers,
        )
        self.error_detail = detail
        self.error_code = error_code
        self.retryable = retryable


@router.post("/chat/voice")
async def chat_voice(
    request: Request,
    file: Optional[UploadFile] = File(None),
    audio: Optional[UploadFile] = File(None),
    session_id: Optional[str] = Form(None),
    lat: Optional[float] = Form(None),
    lon: Optional[float] = Form(None),
    language: Optional[str] = Form("en"),
) -> Dict[str, Any]:
    """Ingest vernacular voice audio, transcribe via Bhashini ULCA ASR, and return transcription."""
    _enforce_rate_limit(request, "voice")
    upload_file = file if file is not None else audio
    if upload_file is None:
        raise HTTPException(
            status_code=422,
            detail="Audio file required as 'file' or 'audio' in multipart form data",
        )

    resolved_session_id = sanitize_session_id(session_id)
    transcription_text = ""
    MAX_AUDIO_BYTES = VOICE_MAX_AUDIO_BYTES
    result = None

    try:
        content = await upload_file.read(MAX_AUDIO_BYTES + 1)
        if len(content) == 0:
            raise HTTPException(
                status_code=422,
                detail={
                    "detail": "Audio file is empty",
                    "error_code": "NO_SPEECH_DETECTED",
                    "retryable": False,
                },
            )
        if len(content) > MAX_AUDIO_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Audio file exceeds maximum size of 25MB ({len(content)} bytes)",
            )
        source_lang = _normalize_ui_lang(language)
        # Client filename is untrusted: cap length, suffix extraction only.
        safe_filename = (upload_file.filename or "")[:VOICE_FILENAME_MAX_CHARS]
        wav_bytes = await asyncio.to_thread(
            _convert_to_16k_mono_wav, content, safe_filename
        )
        if not wav_bytes:
            raise HTTPException(
                status_code=400,
                detail={
                    "detail": "Audio processing failed: invalid audio format.",
                    "error_code": "AUDIO_PROCESSING_ERROR",
                    "retryable": False,
                },
            )
        redis_client = None
        try:
            redis_client = await get_redis_client()
        except Exception as e:
            logger.warning("Failed to get redis client for voice ASR: %s", e)
        try:
            result = await transcribe(wav_bytes, source_lang, redis_client)
            if result.transcribed and result.text.strip():
                transcription_text = result.text.strip()
        except Exception as err:
            # transcribe() itself never raises; this guards the call boundary.
            logger.warning("Bhashini ASR transcription failed: %s", err)
            result = TranscriptionResult(
                text="",
                source_lang=source_lang,
                transcribed=False,
                error_code="BHASHINI_UPSTREAM_ERROR",
                error_detail=f"Bhashini ASR transcription failed: {err}",
                retryable=True,
            )
    finally:
        await upload_file.close()

    if not result or not result.transcribed or not transcription_text:
        if result and result.error_code:
            err_code = result.error_code
            err_detail = result.error_detail or "Voice transcription unavailable"
            retryable = result.retryable
        elif result is None:
            # Unexpected: exception escaped before transcribe() returned.
            err_code = "BHASHINI_UPSTREAM_ERROR"
            err_detail = "Voice transcription unavailable"
            retryable = True
        else:
            # Result present but no error_code — legacy generic failure.
            err_code = "ASR_CONFIG_MISSING"
            err_detail = result.error_detail or "Voice transcription unavailable"
            retryable = result.retryable

        STATUS_MAP = {
            "ASR_CONFIG_MISSING": 503,
            "NO_SPEECH_DETECTED": 422,
            "BHASHINI_UPSTREAM_ERROR": 502,
            "ASR_TIMEOUT": 504,
            "AUDIO_PROCESSING_ERROR": 400,
        }
        code = STATUS_MAP.get(err_code, 503)
        detail_obj = {
            "detail": err_detail,
            "error_code": err_code,
            "retryable": retryable,
        }
        raise HTTPException(status_code=code, detail=detail_obj)

    return {
        "transcription": transcription_text,
        "session_id": resolved_session_id,
        "mock": False,
    }
