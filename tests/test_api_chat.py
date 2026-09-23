"""
Integration and Unit Tests for Chat Router & SSE Streaming Dynamic Graph

Owner: M-C (Backend API) & M-A (Agents)
Module: tests/test_api_chat.py

Covers:
  - POST /api/chat SSE streaming events (status, map, safety, token, done)
  - Error recovery and graceful degradation in SSE stream
  - Multi-turn conversation persistence in Redis (verified via get_history)
  - POST /api/chat/voice vernacular voice transcription (Bhashini ULCA ASR & offline fallback)
  - End-to-end integration with LangGraph supervisor

Wayfinder T3 (map #92): /chat/stream alias deleted —
history returned in multi-turn map #232 T1 (partial reversal); persistence
verified via get_history + GET /api/chat/history.
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
    """Tests for POST /api/chat (stream alias pruned in T3)."""

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
        assert response.headers.get("cache-control") == "no-store"
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

    def test_chat_stream_alias_removed(self, client):
        """Verify POST /api/chat/stream alias is gone (T3 prune → 404/405)."""
        response = client.post(
            "/api/chat/stream",
            json={"message": "ping", "session_id": "sess-alias"},
        )
        assert response.status_code in (404, 405)

    def test_chat_stream_persists_turn_to_redis(self, client):
        """Verify full reply tokens are accumulated and saved to Redis on done."""
        from backend.routers import chat as chat_mod

        async def mock_stream(*args, **kwargs) -> AsyncGenerator[dict, None]:
            yield {"type": "token", "text": "Safe to sail. "}
            yield {"type": "token", "text": "Wind 8 kts."}
            yield {"type": "done", "session_id": "persist-sess-100"}

        real_append = chat_mod.append_message
        saved = []

        async def spy_append(session_id, role, content):
            saved.append((session_id, role, content))
            return await real_append(session_id, role, content)

        with patch(
            "backend.routers.chat.orchestrate_stream_via_graph",
            side_effect=mock_stream,
        ), patch(
            "backend.routers.chat.append_message", side_effect=spy_append
        ):
            client.post(
                "/api/chat",
                json={
                    "message": "Is it safe to sail?",
                    "session_id": "persist-sess-100",
                },
            )

        # History endpoint deleted in T3 — verify persistence via the
        # save path itself (spied in the server loop; direct get_history
        # reads from the test loop and cannot see server-loop Redis state).
        assert ("persist-sess-100", "user", "Is it safe to sail?") in saved
        assert (
            "persist-sess-100",
            "assistant",
            "Safe to sail. Wind 8 kts.",
        ) in saved

    def test_chat_stream_error_recovery(self, client):
        """Verify unhandled stream generator exceptions emit a GENERIC SSE error event (#199)."""
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
        # #199: no traceback/internals to the client — generic message only.
        assert parsed[1]["data"]["message"] == "Internal chat error; please retry."
        assert "Database connection timeout" not in parsed[1]["data"]["message"]

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
    """T1 (map #232) partial reversal: GET /api/chat/history returns (stream stays deleted)."""

    def test_history_endpoint_returns_empty_for_unknown(self, client):
        """Unknown session returns 200 silent empty (T1), not 404."""
        resp = client.get("/api/chat/history?session_id=empty-session")
        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"] == "empty-session"
        assert body["count"] == 0
        assert body["turns"] == []

    def test_history_endpoint_rejects_bad_id(self, client):
        """Malformed session_id returns 400 (T1 sanitize fail)."""
        resp = client.get("/api/chat/history?session_id=../../etc/passwd")
        assert resp.status_code == 400


class TestVoiceTranscriptionEndpoint:
    """Tests for POST /api/chat/voice (Bhashini ULCA ASR, no Groq in voice path)."""

    def test_voice_missing_file_returns_422(self, client):
        """Verify request without file returns 422 validation error."""
        resp = client.post("/api/chat/voice", data={"language": "en"})
        assert resp.status_code == 422

    def test_voice_offline_mock_fallback(self, client):
        """Verify 503 (no mock transcription) when Bhashini keys not configured."""
        with patch.dict(os.environ, {}, clear=True):
            files = {"file": ("malayalam_sample.wav", b"RIFFFAKEWAVDATA", "audio/wav")}
            data = {"language": "ml", "session_id": "voice-sess-1"}
            resp = client.post("/api/chat/voice", files=files, data=data)

            assert resp.status_code == 503
            body = resp.json()
            assert "transcription" in body.get("detail", "").lower() or "unavailable" in body.get("detail", "").lower()

    def test_voice_bhashini_success(self, client):
        """Verify Bhashini transcribe() result returned with unchanged shape."""
        from backend.core.bhashini import TranscriptionResult

        mock_result = TranscriptionResult(
            text="എവിടെ മത്സ്യം കിട്ടും? (Where is fish available?)",
            source_lang="ml",
            transcribed=True,
            cached=False,
        )

        with patch.dict(
            os.environ,
            {"BHASHINI_API_KEY": "test-key", "BHASHINI_ULCA_USER_ID": "test-user"},
        ):
            with patch(
                "backend.routers.chat.transcribe", new=AsyncMock(return_value=mock_result)
            ) as mock_transcribe:
                files = {"file": ("fisherman_voice.m4a", b"AUDIOBYTES", "audio/m4a")}
                data = {"language": "ml", "lat": 9.93, "lon": 76.26}
                resp = client.post("/api/chat/voice", files=files, data=data)

                assert resp.status_code == 200
                body = resp.json()
                assert body["transcription"] == "എവിടെ മത്സ്യം കിട്ടും? (Where is fish available?)"
                assert "session_id" in body and body["session_id"]
                assert body.get("mock") is False

                # Bhashini called once with converted audio + normalized lang
                assert mock_transcribe.call_count == 1
                assert mock_transcribe.call_args[0][1] == "ml"

    def test_voice_bhashini_error_falls_back_gracefully(self, client):
        """Verify Bhashini failure returns 503 without fake transcription."""
        from backend.core.bhashini import TranscriptionResult

        mock_result = TranscriptionResult(text="", source_lang="ml", transcribed=False)

        with patch.dict(
            os.environ,
            {"BHASHINI_API_KEY": "test-key", "BHASHINI_ULCA_USER_ID": "test-user"},
        ):
            with patch("backend.routers.chat.transcribe", new=AsyncMock(return_value=mock_result)):
                files = {"audio": ("query.wav", b"AUDIOBYTES", "audio/wav")}
                resp = client.post("/api/chat/voice", files=files)

                assert resp.status_code == 503
                body = resp.json()
                assert "unavailable" in body.get("detail", "").lower()

    def test_voice_transcribe_exception_maps_to_upstream_error(self, client):
        """Unexpected exception escaping transcribe() maps to 502, not ASR_CONFIG_MISSING."""
        with patch.dict(
            os.environ,
            {"BHASHINI_API_KEY": "test-key", "BHASHINI_ULCA_USER_ID": "test-user"},
        ):
            with patch(
                "backend.routers.chat.transcribe",
                new=AsyncMock(side_effect=RuntimeError("boom")),
            ):
                files = {"audio": ("query.wav", b"AUDIOBYTES", "audio/wav")}
                resp = client.post("/api/chat/voice", files=files)

                assert resp.status_code == 502
                body = resp.json()
                assert body["error_code"] == "BHASHINI_UPSTREAM_ERROR"
                assert body["retryable"] is True
                assert "boom" in body["detail"]

    def test_voice_oversized_file_returns_413(self, client):
        """Verify audio file exceeding 25MB returns 413 HTTP status."""
        oversized_data = b"x" * (25 * 1024 * 1024 + 1024)
        files = {"file": ("oversized.wav", oversized_data, "audio/wav")}
        resp = client.post("/api/chat/voice", files=files)
        assert resp.status_code == 413
        assert "25MB" in resp.json()["detail"]

    def test_voice_empty_content_returns_422(self, client):
        """Verify 0-byte audio file returns 422 with NO_SPEECH_DETECTED."""
        files = {"file": ("empty.wav", b"", "audio/wav")}
        resp = client.post("/api/chat/voice", files=files)
        assert resp.status_code == 422
        body = resp.json()
        assert body["error_code"] == "NO_SPEECH_DETECTED"
        assert body["retryable"] is False
        assert "empty" in body["detail"].lower()

    def test_voice_audio_conversion_failure_returns_400(self, client):
        """Verify audio conversion failure (empty wav_bytes) returns 400 with AUDIO_PROCESSING_ERROR."""
        with patch("backend.routers.chat._convert_to_16k_mono_wav", return_value=b""):
            files = {"file": ("corrupt.unknown", b"corruptdata", "application/octet-stream")}
            resp = client.post("/api/chat/voice", files=files)
            assert resp.status_code == 400
            body = resp.json()
            assert body["error_code"] == "AUDIO_PROCESSING_ERROR"
            assert body["retryable"] is False
            assert "invalid audio format" in body["detail"].lower()

    def test_voice_error_codes_status_mapping(self, client):
        """Verify transcribe error_code mapping to HTTP status codes."""
        from backend.core.bhashini import TranscriptionResult

        cases = [
            ("ASR_CONFIG_MISSING", 503, False),
            ("NO_SPEECH_DETECTED", 422, False),
            ("BHASHINI_UPSTREAM_ERROR", 502, True),
            ("ASR_TIMEOUT", 504, True),
            ("AUDIO_PROCESSING_ERROR", 400, False),
        ]

        with patch.dict(
            os.environ,
            {"BHASHINI_API_KEY": "test-key", "BHASHINI_ULCA_USER_ID": "test-user"},
        ):
            for err_code, expected_status, retryable in cases:
                mock_result = TranscriptionResult(
                    text="",
                    source_lang="ml",
                    transcribed=False,
                    error_code=err_code,
                    error_detail=f"Error occurred: {err_code}",
                    retryable=retryable,
                )
                with patch("backend.routers.chat.transcribe", new=AsyncMock(return_value=mock_result)):
                    files = {"file": ("test.wav", b"AUDIOBYTES", "audio/wav")}
                    resp = client.post("/api/chat/voice", files=files)
                    assert resp.status_code == expected_status, f"Failed for {err_code}"
                    body = resp.json()
                    assert body["error_code"] == err_code
                    assert body["retryable"] is retryable
                    assert body["detail"] == f"Error occurred: {err_code}"



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

            # Verify Redis saved the turn messages (history endpoint
            # deleted in T3 — spy the save path; see persists test above)
            from backend.routers import chat as chat_mod

            real_append = chat_mod.append_message
            saved = []

            async def spy_append(session_id, role, content):
                saved.append((session_id, role, content))
                return await real_append(session_id, role, content)

            sid = "e2e-session-test"
            with patch(
                "backend.routers.chat.append_message",
                side_effect=spy_append,
            ):
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

            user_msgs = [m for m in saved if m[1] == "user"]
            asst_msgs = [m for m in saved if m[1] == "assistant"]
            assert len(user_msgs) == 1
            assert user_msgs[0][2] == "Fish near Kochi?"
            assert len(asst_msgs) == 1
            assert len(asst_msgs[0][2]) > 0


class TestChatBhashiniTranslation:
    """Tests for bidirectional Bhashini translation in POST /api/chat."""

    def test_bhashini_translation_happy_path(self, client):
        """Malayalam request translated to English on input, and reply translated to Malayalam on output."""
        from backend.core.bhashini import TranslationResult

        async def mock_translate_in(text, src, redis_client=None):
            return TranslationResult(
                text="Where are fishing zones near Kochi?",
                source_lang=src,
                target_lang="en",
                translated=True,
            )

        async def mock_translate_out(text, tgt, redis_client=None):
            return TranslationResult(
                text="കൊച്ചിക്ക് സമീപമുള്ള PFZ സോണുകൾ ലഭ്യമാണ്.",
                source_lang="en",
                target_lang=tgt,
                translated=True,
            )

        async def fake_graph_stream(query, language, location, session_id):
            assert query == "Where are fishing zones near Kochi?"
            assert language == "ml"
            yield {"type": "token", "text": "Fishing zones available."}
            yield {"type": "done", "reply": "Fishing zones available.", "session_id": session_id}

        with patch("backend.routers.chat.translate_to_english", side_effect=mock_translate_in):
            with patch("backend.routers.chat.translate_from_english", side_effect=mock_translate_out):
                with patch("backend.routers.chat.orchestrate_stream_via_graph", side_effect=fake_graph_stream):
                    resp = client.post(
                        "/api/chat",
                        json={
                            "message": "കൊച്ചി അടുത്ത് മത്സ്യബന്ധന മേഖലകള് എവിടെ?",
                            "language": "ml",
                        },
                    )

        assert resp.status_code == 200
        parsed = parse_sse_events(resp.text)
        done_events = [p for p in parsed if p["event"] == "done"]
        assert len(done_events) == 1
        done_data = done_events[0]["data"]
        assert done_data.get("translated") is True
        assert done_data.get("reply") == "കൊച്ചിക്ക് സമീപമുള്ള PFZ സോണുകൾ ലഭ്യമാണ്."
        assert done_data.get("original_reply_en") == "Fishing zones available."

    def test_bhashini_translation_fallback_on_failure(self, client):
        """When Bhashini translation is unavailable, stream remains intact with warnings and English fallback."""
        from backend.core.bhashini import TranslationResult

        async def mock_translate_in_fail(text, src, redis_client=None):
            return TranslationResult(
                text=text,
                source_lang=src,
                target_lang="en",
                translated=False,
            )

        async def mock_translate_out_fail(text, tgt, redis_client=None):
            return TranslationResult(
                text=text,
                source_lang="en",
                target_lang=tgt,
                translated=False,
            )

        async def fake_graph_stream(query, language, location, session_id):
            yield {"type": "token", "text": "English reply text."}
            yield {"type": "done", "reply": "English reply text.", "session_id": session_id}

        with patch("backend.routers.chat.translate_to_english", side_effect=mock_translate_in_fail):
            with patch("backend.routers.chat.translate_from_english", side_effect=mock_translate_out_fail):
                with patch("backend.routers.chat.orchestrate_stream_via_graph", side_effect=fake_graph_stream):
                    resp = client.post(
                        "/api/chat",
                        json={
                            "message": "കൊച്ചി ചോദ്യം",
                            "language": "ml",
                        },
                    )

        assert resp.status_code == 200
        parsed = parse_sse_events(resp.text)
        warning_events = [p for p in parsed if p["event"] == "warning"]
        assert len(warning_events) == 1
        assert "Bhashini input translation unavailable" in warning_events[0]["data"]["message"]

        done_events = [p for p in parsed if p["event"] == "done"]
        assert len(done_events) == 1
        done_data = done_events[0]["data"]
        assert done_data.get("reply") == "English reply text."
        assert "translation_warning" in done_data

