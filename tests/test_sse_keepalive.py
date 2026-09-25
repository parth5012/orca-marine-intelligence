"""
SSE keepalive comments for the chat stream.

Owner: M-C (Backend API)
Module: tests/test_sse_keepalive.py

Bug: Firefox drops text/event-stream responses that stay silent for
~10-12s (github.com/enisdenjo/graphql-sse/issues/99 — "FireFox: Error in
input stream"), surfaced in the ORCA UI as the red banner
"⚠️ Error in input stream". ORCA's synthesizer routinely stays silent for
~25-30s, so every Firefox chat turn failed after the trace/cards were
already rendered.

Fix under test: backend/routers.chat.with_keepalive() injects SSE comment
frames (": keepalive") during silent gaps. Comment lines are ignored by
the frontend SSE parser (useSSEChat only reads event:/data: lines).
"""

import asyncio
import os
import sys
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.routers.chat import with_keepalive  # noqa: E402


def _run(coro, timeout=5.0):
    return asyncio.run(asyncio.wait_for(coro, timeout))


async def _collect(source, interval):
    out = []
    async for item in with_keepalive(source, interval=interval):
        out.append(item)
    return out


async def slow_source(events, delay):
    """Async generator yielding `events` after `delay` seconds of silence."""
    for ev in events:
        await asyncio.sleep(delay)
        yield ev


def test_keepalive_emitted_during_silent_gap():
    """Silence > interval must produce comment frames, not bare silence."""
    source = slow_source([{"type": "status", "step": "a"}], delay=0.35)
    out = _run(_collect(source, interval=0.05))
    keepalives = [c for c in out if isinstance(c, str) and c.startswith(":")]
    assert keepalives, "no keepalive comment was emitted during the silent gap"
    assert all("data:" not in c for c in keepalives), "keepalive must be a comment"
    last = out[-1]
    assert isinstance(last, dict) and last["type"] == "status", (
        f"real event must still be forwarded after keepalives: {last!r}"
    )


def test_keepalive_preserves_event_order_and_content():
    """Fast sources pass events through unchanged (idempotent wrapper)."""
    events = [{"type": "token", "text": "a"}, {"type": "token", "text": "b"}, {"type": "done"}]
    out = _run(_collect(slow_source(events, delay=0.0), interval=5.0))
    forwarded = [c for c in out if not isinstance(c, str)]
    assert [e.get("type") for e in forwarded] == ["token", "token", "done"]
    assert forwarded[0]["text"] == "a"
    assert forwarded[1]["text"] == "b"


def test_source_error_propagates_to_consumer():
    """Graph failures must still reach chat.py's error handler."""

    async def failing_source():
        yield {"type": "status"}
        raise ValueError("boom")

    raised = {}

    async def run():
        try:
            async for _ in with_keepalive(failing_source(), interval=5.0):
                pass
        except ValueError as exc:
            raised["err"] = exc

    _run(run())
    assert "err" in raised, "source exception was swallowed by keepalive wrapper"
    assert str(raised["err"]) == "boom"


def test_empty_source_terminates():
    async def nothing():
        if False:
            yield {}

    out = _run(_collect(nothing(), interval=0.05))
    assert out == []


def test_chat_stream_contains_keepalive_when_graph_is_slow(monkeypatch=None):
    """End-to-end: POST /api/chat must emit comment frames while the graph
    is silent (the exact condition that broke Firefox)."""
    from backend.routers.chat import SSE_KEEPALIVE_INTERVAL  # noqa: F401

    async def slow_graph(**kwargs):
        await asyncio.sleep(0.4)  # silent gap, well past a patched interval
        yield {"type": "status", "step": "agent", "agent": "weather_agent"}
        yield {"type": "done", "reply": "hello"}

    with patch(
        "backend.routers.chat.orchestrate_stream_via_graph", new=slow_graph
    ), patch("backend.routers.chat.SSE_KEEPALIVE_INTERVAL", 0.05):
        from backend.main import app

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/chat",
                json={"message": "where are fish near Kochi", "session_id": "keepalive-test"},
            )
    assert resp.status_code == 200
    body = resp.text
    assert ": keepalive" in body or ": connected" in body, (
        "no keepalive comment in SSE stream; Firefox would abort mid-stream. "
        f"Got first 300 chars: {body[:300]!r}"
    )
    assert "event: done" in body, "done frame must still arrive after keepalives"
