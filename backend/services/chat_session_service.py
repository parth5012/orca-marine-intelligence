"""
Chat Session & Memory Domain Service
Owner: M-B / M-C
Module: backend/services/chat_session_service.py

Manages multi-turn conversation memory with dual persistence:
- PostgreSQL: Durable source of truth for all chat sessions & messages
- Redis: Low-latency session state & recent turn cache (24h TTL)
"""

import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from backend.crud.chat import (
    CRUDChatMessage,
    CRUDChatSession,
    chat_message_crud,
    chat_session_crud,
)
from backend.db.models import ChatSession
from backend.schemas.chat import (
    ChatMessageCreate,
    ChatMessageRead,
    ChatSessionCreate,
    ChatSessionRead,
    ChatSessionUpdate,
)
from backend.services.base import BaseService
from backend.services.cache import CacheManager, cache_manager

logger = logging.getLogger("orca.chat_service")


class ChatSessionService(
    BaseService[ChatSession, ChatSessionCreate, ChatSessionUpdate, ChatSessionRead]
):
    """Business service for Chat Session memory and messaging."""

    def __init__(
        self,
        session_crud: CRUDChatSession = chat_session_crud,
        message_crud: CRUDChatMessage = chat_message_crud,
        cache: CacheManager = cache_manager,
    ):
        super().__init__(
            crud=session_crud,
            read_schema=ChatSessionRead,
            namespace="session",
            cache=cache,
            default_ttl=86400,  # 24h conversation memory
            list_ttl=300,
        )
        self.session_crud = session_crud
        self.message_crud = message_crud

    async def get_or_create_session(
        self,
        db: AsyncSession,
        session_id: str,
        preferred_language: str = "en",
        lat: Optional[float] = None,
        lon: Optional[float] = None,
    ) -> ChatSessionRead:
        """Fetch existing session or initialize a new one in PostgreSQL & Redis."""
        session = await self.get_by_id(db, id=session_id)
        if session is not None:
            return session

        # Create new session in DB
        new_session = await self.create(
            db,
            obj_in=ChatSessionCreate(
                session_id=session_id,
                preferred_language=preferred_language,
                last_lat=lat,
                last_lon=lon,
            ),
        )
        return new_session

    async def append_message(
        self,
        db: AsyncSession,
        session_id: str,
        sender: str,
        message: str,
        detected_language: Optional[str] = None,
        detected_script: Optional[str] = None,
        advisory_payload: Optional[Dict[str, Any]] = None,
    ) -> ChatMessageRead:
        """
        Append message to PostgreSQL (Source of Truth) and update Redis session history.
        """
        # Ensure session exists in PostgreSQL
        await self.get_or_create_session(db, session_id=session_id)

        # 1. Commit message to PostgreSQL
        msg = await self.message_crud.append_message(
            db,
            session_id=session_id,
            sender=sender,
            message=message,
            detected_language=detected_language,
            detected_script=detected_script,
            advisory_payload=advisory_payload,
        )
        msg_read = ChatMessageRead.model_validate(msg)

        # 2. Invalidate / Update Redis session cache
        try:
            cache_key = self.cache.build_key(self.namespace, session_id)
            cached_session = await self.cache.get(cache_key)
            if cached_session and isinstance(cached_session, dict):
                msgs = cached_session.setdefault("messages", [])
                msgs.append(msg_read.model_dump(mode="json"))
                cached_session["messages"] = msgs[-20:]  # keep recent 20 turns
                await self.cache.set(cache_key, cached_session, ttl_seconds=self.default_ttl)
            else:
                await self.cache.invalidate_entity(self.namespace, session_id)
        except Exception as exc:
            logger.warning("Failed to sync message to Redis cache: %s", exc)

        return msg_read

    async def get_history(
        self,
        db: AsyncSession,
        session_id: str,
        limit: int = 10,
    ) -> List[ChatMessageRead]:
        """Fetch conversation turn history."""
        # Check cache first
        cache_key = self.cache.build_key(self.namespace, session_id)
        cached = await self.cache.get(cache_key)
        if cached and isinstance(cached, dict) and "messages" in cached:
            raw_msgs = cached["messages"][-limit:]
            return [ChatMessageRead.model_validate(m) for m in raw_msgs]

        # Fallback to PostgreSQL
        db_msgs = await self.message_crud.get_by_session(db, session_id=session_id, limit=limit)
        return [ChatMessageRead.model_validate(m) for m in db_msgs]


chat_session_service = ChatSessionService()
