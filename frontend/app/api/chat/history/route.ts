/**
 * Chat History API Proxy (Next.js Server Handler)
 *
 * Owner: M-E (Frontend & Chat)
 * Module: frontend/app/api/chat/history/route.ts
 *
 * Next.js API route that proxies history reads to FastAPI backend.
 * Follows chat precedent (frontend/app/api/chat/route.ts): 10s budget,
 * BACKEND_API_URL → NEXT_PUBLIC_API_URL → localhost:8000 fallback.
 *
 * Handles:
 *   GET /api/chat/history?session_id=&limit= →
 *     ${backendBase}/api/chat/history?session_id=&limit= (JSON)
 *
 * T1-locked (map #232): minimal+place {role,content,ts,place?,zone_id?},
 * 400 malformed sid passthrough, 200 count:0 empty passthrough, limit
 * default 20 clamp 1..20 backend. No local file fallback (unlike PFZ):
 * 504 client-safe JSON on timeout/unavailable.
 */
import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";

const TIMEOUT_MS = 10000;

function getBackendBase(): string {
  const envUrl = process.env.BACKEND_API_URL || process.env.NEXT_PUBLIC_API_URL;
  if (envUrl && envUrl.trim().length > 0) {
    return envUrl.replace(/\/$/, "");
  }
  if (process.env.NODE_ENV === "production" || process.env.VERCEL) {
    return "https://orca-marine-intelligence-backend.vercel.app";
  }
  return "http://localhost:8000";
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

export async function GET(request: NextRequest) {
  const backendBase = getBackendBase();
  const { searchParams } = new URL(request.url);
  const sessionId = searchParams.get("session_id");
  const limit = searchParams.get("limit");

  const backendUrl = new URL(`${backendBase}/api/chat/history`);
  if (sessionId !== null) backendUrl.searchParams.set("session_id", sessionId);
  if (limit !== null) backendUrl.searchParams.set("limit", limit);

  const headers: Record<string, string> = {
    accept: "application/json",
  };
  const acceptLanguage = request.headers.get("accept-language");
  if (acceptLanguage) headers["accept-language"] = acceptLanguage;

  let backendRes: Response;
  try {
    backendRes = await proxyWithTimeout(backendUrl.toString(), {
      method: "GET",
      headers,
    });
  } catch (e: any) {
    const isAbort = e?.name === "AbortError";
    // Client-safe message only: backendBase may be a private origin
    // (server-only BACKEND_API_URL). Log the target server-side.
    console.error(
      `[api/chat/history] proxy ${isAbort ? "timeout" : "failure"} -> ${backendUrl.origin}${backendUrl.pathname}:`,
      e?.message || e
    );
    return NextResponse.json(
      {
        detail: isAbort
          ? "Backend timeout (no history response within 10s)"
          : "Backend unavailable — the history proxy could not reach the FastAPI backend",
      },
      { status: 504 }
    );
  }

  // Passthrough JSON without buffering semantics change — preserve
  // backend statuses (200 empty, 400 malformed, 429 rate-limit).
  const text = await backendRes.text();
  return new Response(text, {
    status: backendRes.status,
    headers: {
      "content-type":
        backendRes.headers.get("content-type") || "application/json",
    },
  });
}
