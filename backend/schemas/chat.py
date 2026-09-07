"""
Chat Session & Message Pydantic Schemas
Owner: M-B / M-C
Module: backend/schemas/chat.py

Validation and serialization schemas for Chat Sessions and Multi-Turn Messages.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class ChatMessageBase(BaseModel):
    """Shared attributes for ChatMessage."""
    sender: str = Field(..., description="Message author: 'user' or 'orca'")
    message: str = Field(..., description="Text content of the message")
    detected_language: Optional[str] = Field(None, description="ISO language code, e.g. 'ml', 'ta'")
    detected_script: Optional[str] = Field(None, description="Script name, e.g. 'Malayalam'")
    advisory_payload: Optional[Dict[str, Any]] = Field(None, description="Structured cards, coordinates, or safety payload")


class ChatMessageCreate(ChatMessageBase):
    """Schema for appending a message."""
    session_id: str = Field(..., description="Associated session ID")


class ChatMessageRead(ChatMessageBase):
    """Schema for reading a chat message."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: str
    created_at: Optional[datetime] = None


class ChatSessionBase(BaseModel):
    """Shared attributes for ChatSession."""
    preferred_language: str = Field("en", description="Default language code")
    last_lat: Optional[float] = Field(None, ge=-90.0, le=90.0, description="Last known latitude")
    last_lon: Optional[float] = Field(None, ge=-180.0, le=180.0, description="Last known longitude")


class ChatSessionCreate(ChatSessionBase):
    """Schema for creating a new ChatSession."""
    session_id: str = Field(..., description="Unique session identifier (UUID or client-supplied)")


class ChatSessionUpdate(BaseModel):
    """Schema for updating an existing ChatSession."""
    preferred_language: Optional[str] = None
    last_lat: Optional[float] = Field(None, ge=-90.0, le=90.0)
    last_lon: Optional[float] = Field(None, ge=-180.0, le=180.0)


class ChatSessionRead(ChatSessionBase):
    """Schema for reading a ChatSession with messages."""
    model_config = ConfigDict(from_attributes=True)

    session_id: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    messages: List[ChatMessageRead] = Field(default_factory=list)
