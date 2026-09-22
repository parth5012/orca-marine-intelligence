"""
Shared security helpers — ORCA Marine Intelligence (wayfinder #199).

Owner: M-C (Backend API & Platform)
Module: backend/core/security.py

Provides (minimal, stdlib-only, no new deps):
- per-IP sliding-window rate limiter (in-memory; 30/min chat, 10/min voice)
- SecurityHeadersMiddleware (CSP + HSTS + nosniff + frame-ancestors)
- session_id sanitizer (format-validate, else fresh uuid — see tradeoff note)
- CORS preview-regex gate helper

Session tradeoff (documented per ticket, minimal break):
  session_id stays client-controlled (frontend localStorage flow unchanged).
  Mitigations: default is an unguessable uuid4 hex; supplied IDs must match
  ^[A-Za-z0-9_.-]{1,64}$ or a fresh uuid is issued; history TTL is 24h so a
  guessed/fixated session's window is bounded. Full server-issued secret
  (matching-secret-on-read) is deferred post-MVP because it breaks existing
  clients that create their own IDs.
"""

from __future__ import annotations

import logging
import os
import re
import time
import uuid
from collections import deque
from typing import Deque, Dict, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger(__name__)

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")

# bucket -> (limit, window_seconds); env-overridable for tests/ops
_rate_limits: Dict[str, Tuple[int, int]] = {}


def _bucket_config(bucket: str) -> Tuple[int, int]:
    if bucket == "chat":
        limit = int(os.getenv("ORCA_CHAT_RPM", "30"))
        return (limit, 60)
    if bucket == "voice":
        limit = int(os.getenv("ORCA_VOICE_RPM", "10"))
        return (limit, 60)
    return (60, 60)


_MAX_RATE_LIMIT_IPS = int(os.getenv("ORCA_MAX_RATE_LIMIT_IPS", "10000"))

# ip -> bucket -> deque[timestamps]
_hits: Dict[str, Dict[str, Deque[float]]] = {}


def prune_stale_ips(now: float | None = None) -> int:
    """Prune expired timestamps, empty buckets, and stale IPs with no active hits.

    Returns the number of IPs removed.
    """
    ts = now if now is not None else time.monotonic()
    pruned = 0
    for stored_ip, buckets in list(_hits.items()):
        for b_name, b_dq in list(buckets.items()):
            _, b_window = _bucket_config(b_name)
            cutoff = ts - b_window
            while b_dq and b_dq[0] <= cutoff:
                b_dq.popleft()
            if not b_dq:
                buckets.pop(b_name, None)
        if not buckets:
            _hits.pop(stored_ip, None)
            pruned += 1
    return pruned


def get_client_ip(request: Request) -> str:
    """Best-effort client IP (TestClient reports 'testclient').

    Behind Render/Vercel the socket IP is the egress proxy shared by ALL
    users — without proxy headers every user shares one 30/min bucket and
    the chat 429s for everyone after a few messages.

    Trust order (CodeRabbit #229: raw XFF leftmost is client-spoofable —
    Render appends to, not replaces, incoming XFF, so a direct-to-origin
    caller can rotate the first value per request and dodge the bucket):
      1. ``CF-Connecting-IP`` / ``True-Client-IP`` — set (overwritten) by
         the Cloudflare edge in front of Render; not client-forgeable on
         the normal path.
      2. Leftmost ``X-Forwarded-For`` entry — correct behind our proxies,
         spoofable only by direct-to-origin callers (accepted MVP tradeoff;
         full fix = allowlisted proxy ranges / ingress secret, post-MVP).
      3. Socket IP, else ``"unknown"``.
    """
    try:
        headers = request.headers
    except Exception as exc:
        logger.debug("get_client_ip: headers unavailable (%s)", exc)
        headers = {}
    for header in ("cf-connecting-ip", "true-client-ip"):
        try:
            value = headers.get(header) if hasattr(headers, "get") else None
        except Exception as exc:
            logger.debug("get_client_ip: %s read failed (%s)", header, exc)
            continue
        if value and str(value).strip():
            return str(value).strip()
    try:
        xff = headers.get("x-forwarded-for") if hasattr(headers, "get") else None
        if xff:
            first = str(xff).split(",")[0].strip()
            if first:
                return first
    except Exception as exc:
        logger.debug("get_client_ip: x-forwarded-for parse failed (%s)", exc)
    try:
        if request.client is not None and request.client.host:
            return request.client.host
    except Exception as exc:
        logger.debug("get_client_ip: socket ip unavailable (%s)", exc)
    return "unknown"


def check_ip_rate_limit(ip: str, bucket: str, *, now: float | None = None) -> Tuple[bool, int]:
    """Sliding-window check. Returns (allowed, retry_after_seconds).

    Records the hit when allowed. Pure in-memory; safe for single-process
    dev/test. Behind multiple replicas each instance enforces locally
    (documented tradeoff vs Redis fixed-window).
    """
    limit, window = _bucket_config(bucket)
    ts = now if now is not None else time.monotonic()

    # Cap _hits map: prune stale IPs when map exceeds/meets cap; clean empty bucket/IP.
    if len(_hits) >= _MAX_RATE_LIMIT_IPS:
        prune_stale_ips(ts)
        while len(_hits) >= _MAX_RATE_LIMIT_IPS and ip not in _hits:
            oldest_ip = next(iter(_hits))
            _hits.pop(oldest_ip, None)

    per_ip = _hits.setdefault(ip, {})

    # Clean empty buckets or expired hits in other buckets for this IP
    for b_name, b_dq in list(per_ip.items()):
        if b_name != bucket:
            _, b_window = _bucket_config(b_name)
            cutoff_b = ts - b_window
            while b_dq and b_dq[0] <= cutoff_b:
                b_dq.popleft()
            if not b_dq:
                per_ip.pop(b_name, None)

    dq = per_ip.setdefault(bucket, deque())
    cutoff = ts - window
    while dq and dq[0] <= cutoff:
        dq.popleft()
    if len(dq) >= limit:
        retry_after = int(dq[0] + window - ts) + 1
        return (False, max(retry_after, 1))
    dq.append(ts)
    return (True, 0)


def clear_rate_limit_state() -> None:
    """Reset limiter (tests only)."""
    _hits.clear()


def sanitize_session_id(raw: object) -> str:
    """Return a safe session id: valid client value or fresh uuid4 hex."""
    if isinstance(raw, str) and _SESSION_ID_RE.match(raw):
        return raw
    return uuid.uuid4().hex


def allow_vercel_preview() -> bool:
    """Preview-regex gate. Default true (preview deploys must work).

    Set ORCA_ALLOW_VERCEL_PREVIEW=false in locked-down prod to restrict
    CORS to the explicit ALLOWED_ORIGINS allowlist only.
    """
    return os.getenv("ORCA_ALLOW_VERCEL_PREVIEW", "true").strip().lower() in (
        "true",
        "1",
        "yes",
    )


CSP_VALUE = (
    "default-src 'self'; "
    "frame-ancestors 'self'; "
    "object-src 'none'; "
    "base-uri 'self'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach baseline security headers (CSP + HSTS + misc) to every response."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        headers = response.headers
        if "content-security-policy" not in headers:
            headers["Content-Security-Policy"] = CSP_VALUE
        if "strict-transport-security" not in headers:
            headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains"
            )
        if "x-content-type-options" not in headers:
            headers["X-Content-Type-Options"] = "nosniff"
        if "x-frame-options" not in headers:
            headers["X-Frame-Options"] = "SAMEORIGIN"
        if "referrer-policy" not in headers:
            headers["Referrer-Policy"] = "no-referrer"
        return response


__all__ = [
    "CSP_VALUE",
    "_MAX_RATE_LIMIT_IPS",
    "SecurityHeadersMiddleware",
    "allow_vercel_preview",
    "check_ip_rate_limit",
    "clear_rate_limit_state",
    "get_client_ip",
    "prune_stale_ips",
    "sanitize_session_id",
]
