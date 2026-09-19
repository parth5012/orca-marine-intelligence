"""
Security hardening tests — wayfinder #199.

Covers: CORS allowlist/preview/disallowed, CSP+HSTS headers, chat caps
(2k → 422), per-IP rate limits (30/min chat → 429 on 31st; 10/min voice),
oversize voice 413 without traceback, generic SSE errors, secret scrubbing
(gsk_/xox/Bearer), session sanitization, PII log redaction, Redis bound.
"""

import json
import os
import sys
from typing import AsyncGenerator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.core.middleware import redact_pii_path
from backend.core.security import clear_rate_limit_state, sanitize_session_id
from backend.db.redis import _memory_expiry, _memory_store
from backend.main import app


@pytest.fixture(autouse=True)
def _clean_state():
    _memory_store.clear()
    _memory_expiry.clear()
    clear_rate_limit_state()
    yield
    _memory_store.clear()
    _memory_expiry.clear()
    clear_rate_limit_state()


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _parse_sse(text: str) -> list[dict]:
    events, cur_ev, cur_data = [], None, []
    for line in text.splitlines():
        if line.startswith("event: "):
            cur_ev = line[len("event: "):].strip()
        elif line.startswith("data: "):
            cur_data.append(line[len("data: "):].strip())
        elif line == "":
            if cur_ev is not None and cur_data:
                events.append({"event": cur_ev, "data": json.loads("\n".join(cur_data))})
            cur_ev, cur_data = None, []
    if cur_ev is not None and cur_data:
        events.append({"event": cur_ev, "data": json.loads("\n".join(cur_data))})
    return events


class TestCorsAllowlist:
    def test_allowed_localhost_gets_acau(self, client):
        r = client.get("/health", headers={"Origin": "http://localhost:3000"})
        assert r.status_code == 200
        assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"

    def test_allowed_preview_gets_acau(self, client):
        origin = "https://orca-marine-intelligence-abc123.vercel.app"
        r = client.get("/health", headers={"Origin": origin})
        assert r.status_code == 200
        assert r.headers.get("access-control-allow-origin") == origin

    def test_disallowed_origin_blocked(self, client):
        r = client.get("/health", headers={"Origin": "https://evil.example.com"})
        assert r.status_code == 200
        # Blocked = no reflected ACAO header (browser will refuse the read).
        assert r.headers.get("access-control-allow-origin") in (None, "")

        for bad_origin in (
            "https://preview.vercel.app.evil.com",
            "https://evil-site.com/foo.vercel.app",
        ):
            r = client.get("/health", headers={"Origin": bad_origin})
            assert r.headers.get("access-control-allow-origin") in (None, "")

    def test_security_headers_present(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert "default-src 'self'" in r.headers.get("content-security-policy", "")
        assert "max-age=63072000" in r.headers.get("strict-transport-security", "")
        assert r.headers.get("x-content-type-options") == "nosniff"


class TestChatCapsAndRateLimit:
    def test_oversize_message_422_no_traceback(self, client):
        r = client.post("/api/chat", json={"message": "x" * 2001})
        assert r.status_code == 422
        body = r.text.lower()
        assert "traceback" not in body
        # 422 echoes the offending input per FastAPI default (own input only);
        # must not leak server internals.
        assert "orchestrate" not in body and "redis" not in body

    def test_31st_rapid_chat_429(self, client):
        async def mock_stream(*args, **kwargs) -> AsyncGenerator[dict, None]:
            yield {"type": "done", "session_id": "rl-sess"}

        with patch(
            "backend.routers.chat.orchestrate_stream_via_graph",
            side_effect=mock_stream,
        ):
            statuses = [
                client.post("/api/chat", json={"message": f"hi {i}"}).status_code
                for i in range(31)
            ]
        assert statuses[:30] == [200] * 30
        assert statuses[30] == 429
        # 429 carries Retry-After and no traceback
        r = client.post("/api/chat", json={"message": "one more"})
        assert r.status_code == 429
        assert r.headers.get("retry-after") is not None
        assert "traceback" not in r.text.lower()

    def test_generic_sse_error_no_leak(self, client):
        secret = "gsk_live_SUPERSECRET1234567890"
        leaked_exc = RuntimeError(f"groq boom api_key={secret}")

        async def mock_stream(*args, **kwargs) -> AsyncGenerator[dict, None]:
            raise leaked_exc

        with patch(
            "backend.routers.chat.orchestrate_stream_via_graph",
            side_effect=mock_stream,
        ):
            r = client.post("/api/chat", json={"message": "fail please"})
        assert r.status_code == 200
        errs = [e for e in _parse_sse(r.text) if e["event"] == "error"]
        assert len(errs) == 1
        assert errs[0]["data"]["message"] == "Internal chat error; please retry."
        assert secret not in r.text
        assert "traceback" not in r.text.lower()

    def test_rate_limiter_pruning_and_cap(self, monkeypatch):
        import backend.core.security as sec

        sec.clear_rate_limit_state()
        assert sec._MAX_RATE_LIMIT_IPS == 10000

        # 1. Prune stale hits and clean empty bucket/IP
        t0 = 1000.0
        allowed, _ = sec.check_ip_rate_limit("1.2.3.4", "chat", now=t0)
        assert allowed is True
        assert "1.2.3.4" in sec._hits
        assert "chat" in sec._hits["1.2.3.4"]

        # Prune at t0 + 61 (chat window is 60s)
        pruned = sec.prune_stale_ips(now=t0 + 61)
        assert pruned == 1
        assert "1.2.3.4" not in sec._hits

        # 2. Cap enforcement with stale IP pruning
        monkeypatch.setattr(sec, "_MAX_RATE_LIMIT_IPS", 5)
        sec.clear_rate_limit_state()

        # Insert 5 IPs at t0
        for i in range(5):
            ok, _ = sec.check_ip_rate_limit(f"10.0.0.{i}", "chat", now=t0)
            assert ok is True
        assert len(sec._hits) == 5

        # At t0 + 61, add a new IP: old 5 are stale and should be pruned
        ok, _ = sec.check_ip_rate_limit("10.0.0.99", "chat", now=t0 + 61)
        assert ok is True
        assert len(sec._hits) == 1
        assert "10.0.0.99" in sec._hits

        # 3. Cap enforcement with active IPs (hard eviction of oldest)
        sec.clear_rate_limit_state()
        t1 = 2000.0
        for i in range(8):
            ok, _ = sec.check_ip_rate_limit(f"192.168.1.{i}", "chat", now=t1)
            assert ok is True
        assert len(sec._hits) <= 5
        assert len(sec._hits) == 5
        # Most recent IPs present, earliest evicted
        assert "192.168.1.7" in sec._hits
        assert "192.168.1.0" not in sec._hits


class TestVoiceCaps:
    def test_oversize_voice_413_no_traceback(self, client):
        big = b"x" * (25 * 1024 * 1024 + 1024)
        r = client.post(
            "/api/chat/voice", files={"file": ("big.wav", big, "audio/wav")}
        )
        assert r.status_code == 413
        assert "traceback" not in r.text.lower()

    def test_voice_rate_limit_429(self, client):
        from unittest.mock import AsyncMock

        from backend.core.bhashini import TranscriptionResult

        ok = TranscriptionResult(text="hi", source_lang="en", transcribed=True)
        with patch(
            "backend.routers.chat.transcribe",
            new=AsyncMock(return_value=ok),
        ):
            codes = [
                client.post(
                    "/api/chat/voice",
                    files={"file": (f"v{i}.wav", b"RIFFDATA", "audio/wav")},
                ).status_code
                for i in range(11)
            ]
        # first 10 admitted (transcription path), 11th must be rate-limited
        assert 429 not in codes[:10]
        assert codes[10] == 429


class TestScrubSecrets:
    def test_scrub_gsk_xox_bearer(self):
        from backend.agents.synthesizer_service import _scrub_secrets

        assert "gsk_live_ABCDEF1234567890" not in _scrub_secrets(
            "groq failed: gsk_live_ABCDEF1234567890"
        )
        assert "xoxb-12345-secret" not in _scrub_secrets(
            "slack token xoxb-12345-secret leaked"
        )
        scrubbed = _scrub_secrets("401: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig")
        assert "eyJhbGciOiJIUzI1NiJ9" not in scrubbed
        assert "Bearer [REDACTED]" in scrubbed

    def test_no_key_in_sse_error_event(self):
        from backend.agents.synthesizer_service import synthesizer_error_to_sse_event

        exc = RuntimeError("gemini blew up with gsk_live_ABCDEF1234567890 key")
        ev = synthesizer_error_to_sse_event(exc)
        assert ev["type"] == "error"
        assert "gsk_live_ABCDEF1234567890" not in ev["message"]


class TestSessionAndPii:
    def test_sanitize_session_id(self):
        assert sanitize_session_id("session-test-1") == "session-test-1"
        fresh = sanitize_session_id("../../etc/passwd")
        assert fresh != "../../etc/passwd"
        assert len(fresh) == 32
        assert sanitize_session_id(None) is not None
        # Exactly 64 valid chars matches VARCHAR(64)
        assert sanitize_session_id("s" * 64) == "s" * 64
        # >64 chars sanitized to fresh uuid
        over_64 = sanitize_session_id("s" * 65)
        assert over_64 != "s" * 65
        assert len(over_64) == 32

    def test_pii_redacted_from_logged_path(self):
        red = redact_pii_path("/api/weather/current?lat=9.93&lon=76.26&days=7")
        assert "9.93" not in red
        assert "76.26" not in red
        assert "days=7" in red
        red2 = redact_pii_path("/api/chat?session_id=abc123")
        assert "abc123" not in red2

    @pytest.mark.asyncio
    async def test_memory_fallback_bounded(self):
        import backend.db.redis as rmod

        assert int(os.getenv("ORCA_MEMORY_CACHE_MAX", "1000")) >= 1
        assert hasattr(rmod, "_enforce_memory_bound")

        orig_client = rmod._redis_client
        rmod._redis_client = None
        rmod._memory_store.clear()
        rmod._memory_expiry.clear()
        try:
            for i in range(1050):
                await rmod.set_json(f"cache_key_{i}", {"v": i})
            assert len(rmod._memory_store) <= 1000
            assert len(rmod._memory_store) == 1000
            assert len(rmod._memory_expiry) <= 1000
            assert "cache_key_0" not in rmod._memory_store
            assert "cache_key_1049" in rmod._memory_store
        finally:
            rmod._redis_client = orig_client
