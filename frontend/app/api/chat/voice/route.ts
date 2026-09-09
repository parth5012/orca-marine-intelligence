/**
 * Chat Voice API Proxy (Next.js Server Handler)
 *
 * Owner: M-E (Frontend & Chat)
 * Module: frontend/app/api/chat/voice/route.ts
 *
 * Proxies vernacular voice upload to backend:
 *   POST /api/chat/voice → ${backendBase}/api/chat/voice (multipart/form-data)
 *
 * Forwards FormData fields intact: file, session_id, lat, lon, language.
 * SSE/JSON passthrough without buffering.
 */
import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";

const TIMEOUT_MS = 10000; // voice transcription may take longer

function getBackendBase(): string {
  return (
    process.env.BACKEND_API_URL ||
    process.env.NEXT_PUBLIC_API_URL ||
    "http://localhost:8000"
  ).replace(/\/$/, "");
}

export async function POST(request: NextRequest) {
  const backendBase = getBackendBase();
  const backendUrl = `${backendBase}/api/chat/voice`;

  const controller = new AbortController();
  const t = setTimeout(() => controller.abort(), TIMEOUT_MS);

  let backendRes: Response;
  try {
    // Read FormData from incoming request and forward as-is
    const formData = await request.formData();
    backendRes = await fetch(backendUrl, {
      method: "POST",
      body: formData,
      signal: controller.signal,
    });
  } catch (e: any) {
    clearTimeout(t);
    if (e?.name === "AbortError") {
      return NextResponse.json({ detail: "Backend timeout" }, { status: 504 });
    }
    // If formData parsing failed, it may be that request has no multipart body
    return NextResponse.json({ detail: "Backend unavailable" }, { status: 504 });
  } finally {
    clearTimeout(t);
  }

  // Backend may return SSE stream or JSON — passthrough
  if (backendRes.body) {
    const ct = backendRes.headers.get("content-type") || "";
    if (ct.includes("text/event-stream")) {
      return new Response(backendRes.body, {
        status: backendRes.status,
        headers: {
          "content-type": ct,
          "cache-control": backendRes.headers.get("cache-control") || "no-cache",
        },
      });
    }
  }

  const text = await backendRes.text();
  return new Response(text, {
    status: backendRes.status,
    headers: {
      "content-type": backendRes.headers.get("content-type") || "application/json",
    },
  });
}
