"""
Chat Session & Message Database Repositories
Owner: M-B (Data Extractors & Storage)
Module: backend/crud/chat.py

Handles PostgreSQL database operations for conversational sessions and advisory message histories.
"""

from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from backend.crud.base import CRUDBase
from backend.db.models import ChatMessage, ChatSession
from backend.schemas.chat import (
    ChatMessageCreate,
    ChatSessionCreate,
    ChatSessionUpdate,
)


class CRUDChatSession(CRUDBase[ChatSession, ChatSessionCreate, ChatSessionUpdate]):
    """Specialized CRUD repository for ChatSession entities."""

    async def get_with_messages(
        self,
        db: AsyncSession,
        *,
        session_id: str,
        limit_messages: int = 50,
    ) -> Optional[ChatSession]:
        """Fetch chat session along with messages without mutating the ORM relationship collection."""
        session = await self.get(db, session_id)
        if session is None:
            return None

        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit_messages)
        )
        result = await db.execute(stmt)
        ordered_msgs = list(reversed(list(result.scalars().all())))
        # Store on non-persisted attribute to avoid triggering delete-orphan cascades
        session.messages_history = ordered_msgs
        return session

    async def update_location(
        self,
        db: AsyncSession,
        *,
        session_id: str,
        lat: float,
        lon: float,
    ) -> Optional[ChatSession]:
        """Update last known GPS position for a session."""
        session = await self.get(db, session_id)
        if session:
            session.last_lat = lat
            session.last_lon = lon
            db.add(session)
            await db.commit()
            await db.refresh(session)
        return session


class CRUDChatMessage(CRUDBase[ChatMessage, ChatMessageCreate, ChatMessageCreate]):
    """Specialized CRUD repository for ChatMessage entities."""

    async def get_by_session(
        self,
        db: AsyncSession,
        *,
        session_id: str,
        limit: int = 20,
    ) -> List[ChatMessage]:
        """Fetch most recent messages for a session."""
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        msgs = list(result.scalars().all())
        return list(reversed(msgs))

    async def append_message(
        self,
        db: AsyncSession,
        *,
        session_id: str,
        sender: str,
        message: str,
        detected_language: Optional[str] = None,
        detected_script: Optional[str] = None,
        advisory_payload: Optional[Dict[str, Any]] = None,
    ) -> ChatMessage:
        """Create and append a message to a session."""
        msg = ChatMessage(
            session_id=session_id,
            sender=sender,
            message=message,
            detected_language=detected_language,
            detected_script=detected_script,
            advisory_payload=advisory_payload,
        )
        db.add(msg)
        await db.commit()
        await db.refresh(msg)
        return msg


chat_session_crud = CRUDChatSession(ChatSession)
chat_message_crud = CRUDChatMessage(ChatMessage)
