/**
 * Chat API Proxy (Next.js Server Handler)
 *
 * Owner: M-E (Frontend & Chat)
 * Module: frontend/app/api/chat/route.ts
 *
 * Next.js API route that proxies chat requests to FastAPI backend.
 * Follows PFZ precedent (frontend/app/api/pfz/route.ts): 35s chat budget
 * (planner 5s + synth 12s + single retry 12s + overhead),
 * BACKEND_API_URL → NEXT_PUBLIC_API_URL → localhost:8000 fallback.
 *
 * Handles:
 *   POST /api/chat → ${backendBase}/api/chat (JSON, SSE stream)
 *
 * SSE passthrough: forwards text/event-stream without buffering.
 *
 * Wayfinder T3 (map #92): no /stream suffix, no history passthrough —
 * backend aliases deleted; single primary only.
 */
import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";

const TIMEOUT_MS = 35000;

function getBackendBase(): string {
  return (
    process.env.BACKEND_API_URL ||
    process.env.NEXT_PUBLIC_API_URL ||
    "http://localhost:8000"
  ).replace(/\/$/, "");
}

async function proxyWithTimeout(
  url: string,
  init: RequestInit
): Promise<Response> {
  const controller = new AbortController();
  const t = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(t);
  }
}

export async function POST(request: NextRequest) {
  const backendBase = getBackendBase();
  const backendUrl = `${backendBase}/api/chat`;

  const contentType = request.headers.get("content-type") || "";

  // For JSON bodies, forward raw body text to preserve exact payload
  const rawBody = await request.text();
  const headers: Record<string, string> = {};
  if (contentType) headers["content-type"] = contentType;
  // Ask backend for SSE stream
  headers["accept"] = request.headers.get("accept") || "text/event-stream";

  let backendRes: Response;
  try {
    backendRes = await proxyWithTimeout(backendUrl, {
      method: "POST",
      headers,
      body: rawBody || undefined,
    });
  } catch (e: any) {
    const isAbort = e?.name === "AbortError";
    // Client-safe message only: backendBase may be a private origin
    // (server-only BACKEND_API_URL). Log the target server-side.
    console.error(`[api/chat] proxy ${isAbort ? "timeout" : "failure"} -> ${backendUrl}:`, e?.message || e);
    return NextResponse.json(
      {
        detail: isAbort
          ? "Backend timeout (no SSE response within 35s)"
          : "Backend unavailable — the chat proxy could not reach the FastAPI backend",
      },
      { status: 504 }
    );
  }

  // Passthrough SSE stream without buffering — critical for chat
  if (backendRes.body) {
    const streamHeaders: Record<string, string> = {};
    const ct = backendRes.headers.get("content-type");
    if (ct) streamHeaders["content-type"] = ct;
    const cache = backendRes.headers.get("cache-control");
    if (cache) streamHeaders["cache-control"] = cache;
    return new Response(backendRes.body, {
      status: backendRes.status,
      headers: streamHeaders,
    });
  }

  // Fallback: no body (should not happen for SSE)
  const text = await backendRes.text();
  return new Response(text, {
    status: backendRes.status,
    headers: { "content-type": backendRes.headers.get("content-type") || "application/json" },
  });
}
