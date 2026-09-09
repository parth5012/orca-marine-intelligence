"""
Unit Tests for Groq Dynamic Query Planner
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.agents.planner_schema import PLANNER_MODEL, PlannerOutput, TargetLocation
from backend.agents.planner_service import (
    PlannerAPIError,
    PlannerConfigError,
    _generate_structured_json,
    _get_or_create_client,
    _resolve_api_key,
    plan_query,
)


def test_resolve_api_key_prioritizes_groq(monkeypatch):
    """GROQ_API_KEY is prioritized over GEMINI_API_KEY."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_groq_key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini_test_key")
    assert _resolve_api_key() == "gsk_test_groq_key"


def test_resolve_api_key_falls_back_to_gemini(monkeypatch):
    """Falls back to GEMINI_API_KEY if GROQ_API_KEY is not set."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "gemini_test_key")
    assert _resolve_api_key() == "gemini_test_key"


def test_get_or_create_client_groq(monkeypatch):
    """Creates Groq client when GROQ_API_KEY is present."""
    import backend.agents.planner_service as ps
    ps._DEFAULT_CLIENT = None

    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_groq_key")
    client = _get_or_create_client()
    assert client is not None
    # Client should be Groq SDK client or _HttpxGroqClient
    assert hasattr(client, "chat") or hasattr(client, "generate_content")
    ps._DEFAULT_CLIENT = None


def test_generate_structured_json_with_groq_client():
    """_generate_structured_json successfully parses response from Groq client."""
    mock_client = MagicMock()
    mock_completion = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = '{"selected_tools": ["find_fishing_zones"], "target_location": {"lat": 9.93, "lon": 76.26, "port_name": "Kochi", "confidence": 0.95}, "reasoning_trace": ["User asked for fish near Kochi"], "confidence": 0.95}'
    mock_completion.choices = [mock_choice]
    mock_client.chat.completions.create.return_value = mock_completion

    result = _generate_structured_json("Where to fish near Kochi?", client=mock_client)
    assert "find_fishing_zones" in result
    assert "Kochi" in result


def test_generate_structured_json_groq_failure_raises_planner_api_error():
    """When Groq API call fails, PlannerAPIError is raised."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = RuntimeError("Groq rate limit 429")

    with pytest.raises(PlannerAPIError) as exc_info:
        _generate_structured_json("test prompt", client=mock_client)
    assert "groq" in str(exc_info.value).lower()
    assert "call failed" in str(exc_info.value).lower()
