"""
Chat Endpoint Router — ORCA Brain Interface

Owner: M-C (Backend API & Platform) — POST /api/chat wrapper
Module: backend/routers/chat.py

Provides conversational interface to ORCA's multi-agent system.
Handles user queries, language detection, agent dispatch, response streaming,
conversation memory via Redis, and vernacular voice transcription.

Endpoints:
  POST /api/chat          Send query, receive SSE advisory stream
  POST /api/chat/voice    Ingest vernacular voice audio, transcribe via Groq Whisper

Wayfinder T3 (map #92): /chat/stream alias and /chat/history deleted per
human grill decision — single primary kept, history deferred post-MVP.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

try:
    from backend.agents.graph import orchestrate_stream_via_graph
    from backend.core.bhashini import translate_from_english, translate_to_english
    from backend.db.redis import append_message, get_redis_client
except ImportError:
    from agents.graph import orchestrate_stream_via_graph  # type: ignore
    from core.bhashini import translate_from_english, translate_to_english  # type: ignore
    from db.redis import append_message, get_redis_client  # type: ignore

logger = logging.getLogger("orca.chat")

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    """Chat advisory request payload."""

    session_id: Optional[str] = None
    message: str
    lat: Optional[float] = None
    lon: Optional[float] = None
    language: Optional[str] = "en"


@router.post("/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    """Process chat query through ORCA multi-agent system and stream SSE events."""
    session_id: str = req.session_id or uuid.uuid4().hex
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
        user_lang = req.language or "en"
        english_query = req.message
        redis_client = None

        if user_lang != "en":
            try:
                redis_client = await get_redis_client()
            except Exception as e:
                logger.warning("Failed to get redis client: %s", e)
            try:
                result = await translate_to_english(req.message, user_lang, redis_client)
                english_query = result.text
                if not result.translated:
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
                language=user_lang,
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

                    if user_lang != "en" and full_reply:
                        if redis_client is None:
                            try:
                                redis_client = await get_redis_client()
                            except Exception:
                                pass
                        try:
                            t_result = await translate_from_english(full_reply, user_lang, redis_client)
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
                            event["translation_warning"] = "Bhashini translation unavailable — showing English response"

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
                "message": str(exc),
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


@router.post("/chat/voice")
async def chat_voice(
    file: Optional[UploadFile] = File(None),
    audio: Optional[UploadFile] = File(None),
    session_id: Optional[str] = Form(None),
    lat: Optional[float] = Form(None),
    lon: Optional[float] = Form(None),
    language: Optional[str] = Form("en"),
) -> Dict[str, Any]:
    """Ingest vernacular voice audio, transcribe via Groq Whisper, and return transcription."""
    upload_file = file if file is not None else audio
    if upload_file is None:
        raise HTTPException(
            status_code=422,
            detail="Audio file required as 'file' or 'audio' in multipart form data",
        )

    resolved_session_id = session_id or uuid.uuid4().hex
    groq_api_key = os.getenv("GROQ_API_KEY")
    transcription_text = ""
    MAX_AUDIO_BYTES = 25 * 1024 * 1024

    try:
        content = await upload_file.read()
        if len(content) > MAX_AUDIO_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Audio file exceeds maximum size of 25MB ({len(content)} bytes)",
            )
        if groq_api_key:
            try:
                filename = upload_file.filename or "audio.wav"
                content_type = upload_file.content_type or "audio/wav"

                async with httpx.AsyncClient(timeout=30.0) as http_client:
                    headers = {"Authorization": f"Bearer {groq_api_key}"}
                    files_payload = {
                        "file": (filename, content, content_type),
                    }
                    data_payload = {
                        "model": "whisper-large-v3",
                    }
                    if language:
                        data_payload["language"] = language

                    resp = await http_client.post(
                        "https://api.groq.com/openai/v1/audio/transcriptions",
                        headers=headers,
                        data=data_payload,
                        files=files_payload,
                    )
                    if resp.status_code == 200:
                        result_json = resp.json()
                        transcription_text = result_json.get("text", "").strip()
                    else:
                        logger.warning(
                            "Groq Whisper API returned %s: %s",
                            resp.status_code,
                            resp.text,
                        )
            except Exception as err:
                logger.warning("Groq Whisper transcription failed: %s", err)
    finally:
        await upload_file.close()

    if not transcription_text:
        raise HTTPException(
            status_code=503,
            detail="Voice transcription unavailable: no transcription produced (missing GROQ_API_KEY or upstream failure).",
        )

    return {
        "transcription": transcription_text,
        "session_id": resolved_session_id,
        "mock": False,
    }
