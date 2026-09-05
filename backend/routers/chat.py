"""
Chat Endpoint Router — ORCA Brain Interface

Owner: M-C (Backend API & Platform) — POST /api/chat wrapper
Module: backend/routers/chat.py

Provides the conversational interface to ORCA's multi-agent system.
Handles user queries, language detection, agent dispatch, and response streaming.

Endpoints:
    POST /api/chat — Send query, receive advisory response
    GET /api/chat/history — Retrieve conversation history

Request:
    {
        "message": "എവിടെ മത്സ്യം?",       // User query (any of 22 languages)
        "lat": 9.9312,                        // Optional GPS latitude
        "lon": 76.2673,                       // Optional GPS longitude
        "session_id": "abc-123"               // Optional multi-turn session
    }

Response:
    {
        "reply": "Fish found 12km NE of Kochi...",
        "map": { "center": [76.38, 9.95], "pfz_features": [...] },
        "safety": { "waves": "1.2m", "wind": "15kts", "danger": "none" },
        "language": "ml",
        "confidence": 0.87
    }

Dependencies:
    - Orchestrator agent for multi-agent dispatch
    - Bhashini for language detection
    - Redis for conversation memory

TODO:
    - [ ] Implement POST /api/chat with orchestrator integration
    - [ ] Add request validation with Pydantic models
    - [ ] Implement streaming response with SSE
    - [ ] Add session management with Redis
    - [ ] Implement GET /api/chat/history with pagination
"""

from fastapi import APIRouter

router = APIRouter(tags=["chat"])


@router.post("/chat")
async def chat():
    """Process a chat query through the ORCA multi-agent system."""
    # TODO: Implement chat endpoint
    raise NotImplementedError("Chat endpoint not yet implemented")


@router.get("/chat/history")
async def chat_history(session_id: str):
    """Retrieve conversation history for a session."""
    # TODO: Implement chat history retrieval
    raise NotImplementedError("Chat history endpoint not yet implemented")
