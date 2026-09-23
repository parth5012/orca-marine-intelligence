"""
History endpoint tests — Wayfinder T5 (map #232), T1-locked contract.

Owner: M-C (Backend API) + M-A (memory)
Module: backend/tests/test_chat_history.py

T1 #234 (closed): GET /api/chat/history?session_id=<uuid>&limit=20
  Shape minimal+place: 200 {session_id,count,turns:[{role,content,ts,place?,zone_id?}]}
  Semantics: 400 malformed sid (sanitize fail); 200 {count:0,turns:[]} unknown/expired.
  Cap: default 20, clamp 1..20 backend. Voice turns visible as text.
T3 #236 (closed): backend enforces verbatim lang, clarifications plain text,
  redact GPS (no lat/lon/center in payload), veto/allowlist hold (text-only turns,
  no cards/evidence leak).
T4 #233 (closed): live Redis stores {role,content,ts}; get_history serves last-20.
"""

import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.core.security import clear_rate_limit_state
from backend.db.redis import (
    _memory_expiry,
    _memory_store,
    append_message,
    save_turn_batch,
)
from backend.main import app


@pytest.fixture(autouse=True)
def clean_state():
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


def _sid() -> str:
    return uuid.uuid4().hex


class TestChatHistoryRoundtrip:
    """2 turns roundtrip via save_turn_batch, order preserved, T1 shape."""

    @pytest.mark.asyncio
    async def test_two_turns_roundtrip_in_order(self, client):
        sid = _sid()
        await save_turn_batch(sid, "fish near Kochi", "Kochi PFZ active 12km out.")
        await save_turn_batch(sid, "is it safe tomorrow?", "Waves 0.8m, wind 8kts — SAFE.")

        resp = client.get(f"/api/chat/history?session_id={sid}&limit=20")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["session_id"] == sid
        assert body["count"] == 4
        assert len(body["turns"]) == 4
        roles = [t["role"] for t in body["turns"]]
        assert roles == ["user", "assistant", "user", "assistant"]
        assert body["turns"][0]["content"] == "fish near Kochi"
        assert body["turns"][1]["content"] == "Kochi PFZ active 12km out."
        assert body["turns"][2]["content"] == "is it safe tomorrow?"
        assert body["turns"][3]["content"] == "Waves 0.8m, wind 8kts — SAFE."
        for t in body["turns"]:
            assert isinstance(t["ts"], (int, float))
            assert set(t.keys()) <= {"role", "content", "ts", "place", "zone_id"}
            # T3 GPS redaction: never leak coordinates in history payload
            assert "lat" not in t and "lon" not in t and "center" not in t

    @pytest.mark.asyncio
    async def test_single_turn_example_shape(self, client):
        """T1 example: user 'fish near Kochi' + assistant reply, count 2."""
        sid = _sid()
        await append_message(sid, "user", "fish near Kochi")
        await append_message(sid, "assistant", "Nearest zone ...")

        resp = client.get(f"/api/chat/history?session_id={sid}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["session_id"] == sid
        assert body["count"] == 2
        assert body["turns"][0]["role"] == "user"
        assert body["turns"][0]["content"] == "fish near Kochi"
        assert body["turns"][1]["role"] == "assistant"
        assert body["turns"][1]["content"] == "Nearest zone ..."


class TestChatHistoryBadId:
    """T1: 400 malformed sid (sanitize fail)."""

    def test_bad_id_path_traversal_400(self, client):
        resp = client.get("/api/chat/history?session_id=../../etc/passwd")
        assert resp.status_code == 400

    def test_bad_id_empty_400(self, client):
        resp = client.get("/api/chat/history?session_id=")
        assert resp.status_code == 400

    def test_bad_id_missing_400(self, client):
        resp = client.get("/api/chat/history")
        assert resp.status_code == 400

    def test_bad_id_spaces_400(self, client):
        resp = client.get("/api/chat/history?session_id=bad%20id%20here")
        assert resp.status_code == 400


class TestChatHistoryExpired:
    """T1: 200 {count:0,turns:[]} unknown/expired (silent empty)."""

    def test_unknown_session_200_empty(self, client):
        sid = _sid()
        resp = client.get(f"/api/chat/history?session_id={sid}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["session_id"] == sid
        assert body["count"] == 0
        assert body["turns"] == []

    @pytest.mark.asyncio
    async def test_expired_session_200_empty(self, client):
        sid = _sid()
        await save_turn_batch(sid, "hello", "hi there")
        # Simulate 24h TTL expiry: drop the session key entirely
        _memory_store.clear()
        _memory_expiry.clear()
        resp = client.get(f"/api/chat/history?session_id={sid}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["count"] == 0
        assert body["turns"] == []


class TestChatHistoryLimitClamp:
    """T1 cap: default 20, clamp 1..20 backend."""

    @pytest.mark.asyncio
    async def test_limit_clamp(self, client):
        sid = _sid()
        for i in range(5):
            await save_turn_batch(sid, f"q{i}", f"a{i}")

        # 10 messages stored; limit=2 returns last 2 only
        r2 = client.get(f"/api/chat/history?session_id={sid}&limit=2")
        assert r2.status_code == 200
        assert r2.json()["count"] == 2
        assert [t["content"] for t in r2.json()["turns"]] == ["q4", "a4"]

        # limit=0 clamps to 1
        r0 = client.get(f"/api/chat/history?session_id={sid}&limit=0")
        assert r0.status_code == 200
        assert r0.json()["count"] == 1

        # limit=999 clamps to 20 (returns all 10 here, never more than 20)
        rbig = client.get(f"/api/chat/history?session_id={sid}&limit=999")
        assert rbig.status_code == 200
        assert rbig.json()["count"] == 10

        # default (no limit) returns all up to 20
        rdef = client.get(f"/api/chat/history?session_id={sid}")
        assert rdef.status_code == 200
        assert rdef.json()["count"] == 10

    @pytest.mark.asyncio
    async def test_limit_never_exceeds_20(self, client):
        sid = _sid()
        for i in range(15):
            await save_turn_batch(sid, f"q{i}", f"a{i}")
        # 30 messages stored would exceed cap, but store keeps last-20;
        # endpoint additionally clamps limit to 20.
        resp = client.get(f"/api/chat/history?session_id={sid}&limit=20")
        assert resp.status_code == 200
        assert resp.json()["count"] <= 20


class TestChatHistoryAllowlist:
    """T3: allowlist holds on stored items; verbatim; no GPS/cards leak."""

    @pytest.mark.asyncio
    async def test_allowlist_holds_and_verbatim(self, client):
        from backend.agents.graph import filter_human_evidence

        sid = _sid()
        await append_message(sid, "user", "fish near Kochi")
        await append_message(sid, "assistant", "INCOIS SEC005 KERALA 02-Sep-2026")

        resp = client.get(f"/api/chat/history?session_id={sid}")
        assert resp.status_code == 200
        turns = resp.json()["turns"]
        # Verbatim lang: stored reply returned exactly, no re-translate
        assert turns[1]["content"] == "INCOIS SEC005 KERALA 02-Sep-2026"
        # Allowlist: stored human evidence still passes the T3 filter
        assert filter_human_evidence([turns[1]["content"]]) == [
            "INCOIS SEC005 KERALA 02-Sep-2026"
        ]
        # Raw internals never pass the allowlist (guard, not stored)
        assert filter_human_evidence(["SELECT check_weather"]) == []
        assert filter_human_evidence(["open_meteo_live data"]) == []
        # History payload itself carries no cards/evidence/safety blobs
        for t in turns:
            assert "pfz_features" not in t
            assert "evidence" not in t
            assert "safety" not in t
            assert "cards" not in t
