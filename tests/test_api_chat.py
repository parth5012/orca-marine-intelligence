"""
Integration and Unit Tests for Chat Router & SSE Streaming Dynamic Graph

Owner: M-C (Backend API) & M-A (Agents)
Module: tests/test_api_chat.py

Covers:
  - POST /api/chat SSE streaming events (status, map, safety, token, done)
  - POST /api/chat/stream alias endpoint
  - Error recovery and graceful degradation in SSE stream
  - Multi-turn conversation persistence in Redis
  - GET /api/chat/history retrieval and pagination
  - POST /api/chat/voice vernacular voice transcription (Groq Whisper & offline fallback)
  - End-to-end integration with LangGraph supervisor
"""

import json
import os
import sys
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Ensure repo root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.db.redis import _memory_expiry, _memory_store, append_message, get_history
from backend.main import app


@pytest.fixture(autouse=True)
def clean_redis_memory():
    """Clear in-memory Redis cache between tests."""
    _memory_store.clear()
    _memory_expiry.clear()
    yield
    _memory_store.clear()
    _memory_expiry.clear()


@pytest.fixture
def client():
    """FastAPI TestClient instance."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def parse_sse_events(response_text: str) -> list[dict]:
    """Parse raw SSE response text into a list of {event: str, data: dict} dicts."""
    events = []
    current_event = None
    current_data = []

    for line in response_text.splitlines():
        if line.startswith("event: "):
            current_event = line[len("event: ") :].strip()
        elif line.startswith("data: "):
            current_data.append(line[len("data: ") :].strip())
        elif line == "":
            if current_event is not None and current_data:
                data_str = "\n".join(current_data)
                try:
                    data_obj = json.loads(data_str)
                except Exception:
                    data_obj = {"raw": data_str}
                events.append({"event": current_event, "data": data_obj})
            current_event = None
            current_data = []

    if current_event is not None and current_data:
        data_str = "\n".join(current_data)
        try:
            data_obj = json.loads(data_str)
        except Exception:
            data_obj = {"raw": data_str}
        events.append({"event": current_event, "data": data_obj})

    return events


class TestChatStreamingEndpoint:
    """Tests for POST /api/chat and POST /api/chat/stream."""

    def test_chat_sse_stream_structure_and_headers(self, client):
        """Verify POST /api/chat returns proper SSE headers and formatted events."""
        mock_events = [
            {"type": "status", "agent": "planner", "state": "running"},
            {
                "type": "map",
                "center": [76.26, 9.93],
                "pfz_features": [{"type": "Feature", "id": "zone-1"}],
                "route": [[76.26, 9.93], [76.38, 9.95]],
            },
            {
                "type": "safety",
                "waves_m": 0.8,
                "wind_kts": 10,
                "danger": "none",
                "badge": "green",
            },
            {"type": "token", "text": "Fish found "},
            {"type": "token", "text": "12km off Kochi."},
            {"type": "evidence", "items": ["INCOIS SEC005 KERALA"]},
            {
                "type": "done",
                "language": "en",
                "confidence": 0.87,
                "session_id": "session-test-1",
            },
        ]

        async def mock_stream(*args, **kwargs) -> AsyncGenerator[dict, None]:
            for ev in mock_events:
                yield ev

        with patch(
            "backend.routers.chat.orchestrate_stream_via_graph",
            side_effect=mock_stream,
        ):
            response = client.post(
                "/api/chat",
                json={
                    "message": "Where can I fish today?",
                    "lat": 9.93,
                    "lon": 76.26,
                    "language": "en",
                    "session_id": "session-test-1",
                },
            )

        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")
        assert response.headers.get("cache-control") == "no-cache"
        assert response.headers.get("x-accel-buffering") == "no"

        parsed = parse_sse_events(response.text)
        assert len(parsed) == 7

        event_types = [p["event"] for p in parsed]
        assert event_types == [
            "status",
            "map",
            "safety",
            "token",
            "token",
            "evidence",
            "done",
        ]

        # Check map event contents
        map_ev = parsed[1]["data"]
        assert map_ev["center"] == [76.26, 9.93]
        assert len(map_ev["pfz_features"]) == 1

        # Check token contents
        assert parsed[3]["data"]["text"] == "Fish found "
        assert parsed[4]["data"]["text"] == "12km off Kochi."

        # Check done event contents
        assert parsed[6]["data"]["session_id"] == "session-test-1"

    def test_chat_stream_alias_endpoint(self, client):
        """Verify POST /api/chat/stream behaves identically as SSE endpoint."""
        async def mock_stream(*args, **kwargs) -> AsyncGenerator[dict, None]:
            yield {"type": "token", "text": "Hello ocean"}
            yield {"type": "done", "session_id": "sess-alias"}

        with patch(
            "backend.routers.chat.orchestrate_stream_via_graph",
            side_effect=mock_stream,
        ):
            response = client.post(
                "/api/chat/stream",
                json={"message": "ping", "session_id": "sess-alias"},
            )

        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        parsed = parse_sse_events(response.text)
        assert len(parsed) == 2
        assert parsed[0]["event"] == "token"
        assert parsed[1]["event"] == "done"

    def test_chat_stream_persists_turn_to_redis(self, client):
        """Verify full reply tokens are accumulated and saved to Redis on done."""
        async def mock_stream(*args, **kwargs) -> AsyncGenerator[dict, None]:
            yield {"type": "token", "text": "Safe to sail. "}
            yield {"type": "token", "text": "Wind 8 kts."}
            yield {"type": "done", "session_id": "persist-sess-100"}

        with patch(
            "backend.routers.chat.orchestrate_stream_via_graph",
            side_effect=mock_stream,
        ):
            client.post(
                "/api/chat",
                json={
                    "message": "Is it safe to sail?",
                    "session_id": "persist-sess-100",
                },
            )

        # Check Redis history retrieval directly via API
        hist_resp = client.get("/api/chat/history?session_id=persist-sess-100")
        assert hist_resp.status_code == 200
        data = hist_resp.json()
        assert data["session_id"] == "persist-sess-100"
        messages = data["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Is it safe to sail?"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "Safe to sail. Wind 8 kts."

    def test_chat_stream_error_recovery(self, client):
        """Verify unhandled stream generator exceptions emit an SSE error event."""
        async def mock_stream(*args, **kwargs) -> AsyncGenerator[dict, None]:
            yield {"type": "status", "agent": "planner", "state": "running"}
            raise RuntimeError("Database connection timeout during planning")

        with patch(
            "backend.routers.chat.orchestrate_stream_via_graph",
            side_effect=mock_stream,
        ):
            response = client.post(
                "/api/chat",
                json={"message": "fail query", "session_id": "err-sess"},
            )

        assert response.status_code == 200
        parsed = parse_sse_events(response.text)
        assert len(parsed) == 2
        assert parsed[0]["event"] == "status"
        assert parsed[1]["event"] == "error"
        assert "Database connection timeout" in parsed[1]["data"]["message"]

    def test_planner_fallback_emits_non_fatal_status_event(self, client):
        """Ticket #78: Verify planner failure emits non-fatal status fallback event instead of error."""
        from backend.agents.planner_service import PlannerTimeoutError

        with patch(
            "backend.agents.planner_service.plan_query",
            side_effect=PlannerTimeoutError("Gemini SLA breached", elapsed_ms=500),
        ):
            response = client.post(
                "/api/chat",
                json={
                    "message": "Fish near Kochi?",
                    "lat": 9.93,
                    "lon": 76.26,
                    "language": "en",
                    "session_id": "fallback-test-sess",
                },
            )

        assert response.status_code == 200
        parsed = parse_sse_events(response.text)

        # Verify status event with state: fallback
        status_events = [p for p in parsed if p["event"] == "status"]
        planner_fallback_events = [
            p
            for p in status_events
            if p["data"].get("agent") == "planner"
            and p["data"].get("state") == "fallback"
        ]
        assert len(planner_fallback_events) == 1
        fb_event = planner_fallback_events[0]["data"]
        assert fb_event["type"] == "status"
        assert fb_event["agent"] == "planner"
        assert fb_event["state"] == "fallback"
        assert fb_event["message"] == "LLM planner unavailable, using fallback advisory"
        assert fb_event["fallback"] is True
        assert fb_event["elapsed_ms"] == 500

        # Verify stream did NOT emit fatal error for planner
        error_events = [p for p in parsed if p["event"] == "error"]
        planner_errors = [
            p for p in error_events if p["data"].get("agent") == "planner"
        ]
        assert len(planner_errors) == 0

        # Verify stream completed with done event
        done_events = [p for p in parsed if p["event"] == "done"]
        assert len(done_events) == 1

    def test_planner_fallback_chunked_replay_emits_status_fallback(self, client):
        """Ticket #78: Verify chunked replay path also emits status fallback event for planner."""
        from unittest.mock import AsyncMock

        class MockGraphWithoutAstream:
            pass

        canned = {
            "planner_error": {
                "type": "status",
                "agent": "planner",
                "state": "fallback",
                "message": "LLM planner unavailable, using fallback advisory",
                "fallback": True,
                "elapsed_ms": 500,
            },
            "map": {"center": [76.26, 9.93], "pfz_features": [], "route": []},
            "safety": {"waves_m": 0.8, "wind_kts": 10.0, "danger": "none", "badge": "green"},
            "reply": "Safe fishing advisory near Kochi.",
            "evidence": ["INCOIS TextData"],
            "language": "en",
            "confidence": 0.62,
            "session_id": "fallback-test-chunked",
        }

        with patch("backend.agents.graph.get_orca_graph", return_value=MockGraphWithoutAstream()):
            with patch(
                "backend.agents.graph.orchestrate_via_graph",
                new=AsyncMock(return_value=dict(canned)),
            ):
                response = client.post(
                    "/api/chat",
                    json={
                        "message": "Fish near Kochi?",
                        "lat": 9.93,
                        "lon": 76.26,
                        "language": "en",
                        "session_id": "fallback-test-chunked",
                    },
                )

        assert response.status_code == 200
        parsed = parse_sse_events(response.text)

        status_events = [p for p in parsed if p["event"] == "status"]
        planner_fallback_events = [
            p
            for p in status_events
            if p["data"].get("agent") == "planner"
            and p["data"].get("state") == "fallback"
        ]
        assert len(planner_fallback_events) == 1
        fb_event = planner_fallback_events[0]["data"]
        assert fb_event["type"] == "status"
        assert fb_event["agent"] == "planner"
        assert fb_event["state"] == "fallback"

        # Verify stream completed with done event and no planner error
        error_events = [p for p in parsed if p["event"] == "error" and p["data"].get("agent") == "planner"]
        assert len(error_events) == 0
        done_events = [p for p in parsed if p["event"] == "done"]
        assert len(done_events) == 1

    def test_planner_fatal_import_error_emits_sse_error_event(self, client):
        """Ticket #78: Verify truly fatal planner failure (ImportError) emits SSE error event."""
        with patch.dict("sys.modules", {"backend.agents.planner_service": None}):
            response = client.post(
                "/api/chat",
                json={
                    "message": "Fish near Kochi?",
                    "lat": 9.93,
                    "lon": 76.26,
                    "language": "en",
                    "session_id": "fatal-planner-sess",
                },
            )

            assert response.status_code == 200
            parsed = parse_sse_events(response.text)
            error_events = [
                p for p in parsed
                if p["event"] == "error" and p["data"].get("agent") == "planner"
            ]
            assert len(error_events) == 1
            assert error_events[0]["data"]["type"] == "error"
            assert error_events[0]["data"]["fallback"] == "none"

class TestChatHistoryEndpoint:
    """Tests for GET /api/chat/history."""

    def test_history_empty_session(self, client):
        """Verify empty list is returned for a session with no recorded history."""
        response = client.get("/api/chat/history?session_id=empty-session")
        assert response.status_code == 200
        body = response.json()
        assert body == {"session_id": "empty-session", "messages": []}

    @pytest.mark.asyncio
    async def test_history_populated_session_with_limit(self, client):
        """Verify history returns recorded turns up to limit."""
        sid = "multi-turn-sess"
        await append_message(sid, "user", "turn 1 user")
        await append_message(sid, "assistant", "turn 1 reply")
        await append_message(sid, "user", "turn 2 user")
        await append_message(sid, "assistant", "turn 2 reply")

        # Fetch limit=2
        resp = client.get(f"/api/chat/history?session_id={sid}&limit=2")
        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"] == sid
        assert len(body["messages"]) == 2
        assert body["messages"][0]["content"] == "turn 2 user"
        assert body["messages"][1]["content"] == "turn 2 reply"

        # Fetch all
        resp_all = client.get(f"/api/chat/history?session_id={sid}&limit=10")
        assert resp_all.status_code == 200
        assert len(resp_all.json()["messages"]) == 4

    def test_history_missing_session_id(self, client):
        """Verify missing session_id query param produces 422 Unprocessable Entity."""
        resp = client.get("/api/chat/history")
        assert resp.status_code == 422


class TestVoiceTranscriptionEndpoint:
    """Tests for POST /api/chat/voice."""

    def test_voice_missing_file_returns_422(self, client):
        """Verify request without file returns 422 validation error."""
        resp = client.post("/api/chat/voice", data={"language": "en"})
        assert resp.status_code == 422

    def test_voice_offline_mock_fallback(self, client):
        """Verify fallback transcription when GROQ_API_KEY not configured."""
        with patch.dict(os.environ, {}, clear=True):
            files = {"file": ("malayalam_sample.wav", b"RIFFFAKEWAVDATA", "audio/wav")}
            data = {"language": "ml", "session_id": "voice-sess-1"}
            resp = client.post("/api/chat/voice", files=files, data=data)

            assert resp.status_code == 200
            body = resp.json()
            assert body["session_id"] == "voice-sess-1"
            assert "malayalam_sample.wav" in body["transcription"]
            assert body.get("mock") is True

    def test_voice_groq_whisper_success(self, client):
        """Verify Groq Whisper transcription API called when GROQ_API_KEY present."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "text": "എവിടെ മത്സ്യം കിട്ടും? (Where is fish available?)"
        }

        with patch.dict(os.environ, {"GROQ_API_KEY": "gsk_test_mock_key"}):
            with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_response)) as mock_post:
                files = {"file": ("fisherman_voice.m4a", b"AUDIOBYTES", "audio/m4a")}
                data = {"language": "ml", "lat": 9.93, "lon": 76.26}
                resp = client.post("/api/chat/voice", files=files, data=data)

                assert resp.status_code == 200
                body = resp.json()
                assert body["transcription"] == "എവിടെ മത്സ്യം കിട്ടും? (Where is fish available?)"
                assert "session_id" in body and body["session_id"]
                assert body.get("mock") is False

                # Verify httpx call parameters
                assert mock_post.called
                call_kwargs = mock_post.call_args[1]
                assert "Authorization" in call_kwargs["headers"]
                assert call_kwargs["headers"]["Authorization"] == "Bearer gsk_test_mock_key"
                assert call_kwargs["data"]["model"] == "whisper-large-v3"
                assert call_kwargs["data"]["language"] == "ml"

    def test_voice_groq_whisper_error_falls_back_gracefully(self, client):
        """Verify Groq API failure falls back to informative mock transcription without crashing."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Groq Error"

        with patch.dict(os.environ, {"GROQ_API_KEY": "gsk_test_mock_key"}):
            with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_response)):
                files = {"audio": ("query.wav", b"AUDIOBYTES", "audio/wav")}
                resp = client.post("/api/chat/voice", files=files)

                assert resp.status_code == 200
                body = resp.json()
                assert "transcription" in body
                assert "query.wav" in body["transcription"]
                assert "session_id" in body
                assert body.get("mock") is True

    def test_voice_oversized_file_returns_413(self, client):
        """Verify audio file exceeding 25MB returns 413 HTTP status."""
        oversized_data = b"x" * (25 * 1024 * 1024 + 1024)
        files = {"file": ("oversized.wav", oversized_data, "audio/wav")}
        resp = client.post("/api/chat/voice", files=files)
        assert resp.status_code == 413
        assert "25MB" in resp.json()["detail"]


class TestChatIntegrationEndToEnd:
    """End-to-end integration test with dynamic agent graph streaming."""

    def test_end_to_end_chat_stream_and_history(self, client):
        """Verify end-to-end chat query through orchestrate_stream_via_graph and Redis persistence."""
        from backend.ingest.mock_fetchers import (
            SimulationScenario,
            mock_fetch_all,
        )

        KOCHI_LAT = 9.93
        KOCHI_LON = 76.26

        batch = mock_fetch_all(
            sector="SEC005",
            center_lat=KOCHI_LAT,
            center_lon=KOCHI_LON,
            count=3,
            scenario=SimulationScenario.NORMAL,
        )

        def _flat_fish(features, lat, lon):
            res = []
            for f in features:
                props = f.get("properties", {})
                coords = f.get("geometry", {}).get("coordinates", [lon, lat])
                res.append({
                    "zone_id": props.get("zone_id", "Z1"),
                    "title": props.get("title", "Kochi Zone"),
                    "distance_km": 12.0,
                    "bearing_deg": 270.0,
                    "lat": coords[1] if len(coords) > 1 else lat,
                    "lon": coords[0] if len(coords) > 0 else lon,
                    "score": 0.9,
                    "source": "INCOIS SEC005",
                })
            return res

        flat_fish = _flat_fish(batch["pfz"]["features"], KOCHI_LAT, KOCHI_LON)

        with patch("backend.agents.fish_finder.find_fishing_zones", new=AsyncMock(return_value=flat_fish)), \
             patch("backend.agents.sea_checker.check_sea_conditions", new=AsyncMock(return_value=batch["ocean"]["results"])), \
             patch("backend.agents.weather_agent.check_weather", new=AsyncMock(return_value=batch["weather"]["results"])), \
             patch("backend.agents.danger_agent.check_safety_batch", new=AsyncMock(return_value=batch["geofence"]["results"])):

            sid = "e2e-session-test"
            response = client.post(
                "/api/chat",
                json={
                    "message": "Fish near Kochi?",
                    "lat": KOCHI_LAT,
                    "lon": KOCHI_LON,
                    "language": "en",
                    "session_id": sid,
                },
            )

            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]

            parsed = parse_sse_events(response.text)
            event_types = [p["event"] for p in parsed]

            # Verify core event types emitted
            assert "map" in event_types
            assert "safety" in event_types
            assert "token" in event_types
            assert "done" in event_types

            # Verify Redis saved the turn messages
            hist_resp = client.get(f"/api/chat/history?session_id={sid}")
            assert hist_resp.status_code == 200
            msgs = hist_resp.json()["messages"]
            user_msgs = [m for m in msgs if m.get("role") == "user"]
            asst_msgs = [m for m in msgs if m.get("role") == "assistant"]
            assert len(user_msgs) == 1
            assert user_msgs[0]["content"] == "Fish near Kochi?"
            assert len(asst_msgs) == 1
            assert len(asst_msgs[0]["content"]) > 0
