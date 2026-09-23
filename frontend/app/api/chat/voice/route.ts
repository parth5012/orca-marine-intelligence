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

const TIMEOUT_MS = 35000; // voice transcription with ASR retries may take up to 30-35s

function getBackendBase(): string {
  const envUrl = process.env.BACKEND_API_URL || process.env.NEXT_PUBLIC_API_URL;
  if (envUrl && envUrl.trim().length > 0) {
    return envUrl.replace(/\/$/, "");
  }
  if (process.env.NODE_ENV === "production" || process.env.VERCEL) {
    return "https://orca-marine-intelligence-api.onrender.com";
  }
  return "http://localhost:8000";
}

export async function POST(request: NextRequest) {
  const backendBase = getBackendBase();
  const backendUrl = `${backendBase}/api/chat/voice`;

  const controller = new AbortController();
  const t = setTimeout(() => controller.abort(), TIMEOUT_MS);

  let formData: FormData;
  try {
    formData = await request.formData();
  } catch {
    clearTimeout(t);
    return NextResponse.json(
      {
        detail: "Invalid voice upload.",
        error_code: "AUDIO_PROCESSING_ERROR",
        retryable: false,
      },
      { status: 400 }
    );
  }

  let backendRes: Response;
  try {
    backendRes = await fetch(backendUrl, {
      method: "POST",
      body: formData,
      signal: controller.signal,
    });
  } catch (e: any) {
    clearTimeout(t);
    // Client-safe message only: backendBase may be a private origin.
    console.error(`[api/chat/voice] proxy failure -> ${backendUrl}:`, e?.message || e);
    if (e?.name === "AbortError") {
      return NextResponse.json(
        {
          detail: "Voice transcription timed out.",
          error_code: "ASR_TIMEOUT",
          retryable: true,
        },
        { status: 504 }
      );
    }
    return NextResponse.json(
      {
        detail: "Failed to connect to backend voice service.",
        error_code: "PROXY_CONNECTION_FAILED",
        retryable: true,
      },
      {
        status: 502,
        headers: {
          "x-orca-proxy-error": "connection-failed",
        },
      }
    );
  } finally {
    clearTimeout(t);
  }

  // Forward backend non-200 response and parse/forward JSON error body directly
  if (!backendRes.ok) {
    try {
      const errorJson = await backendRes.clone().json();
      const payload =
        errorJson && typeof errorJson.detail === "object" && errorJson.detail !== null
          ? { ...errorJson.detail }
          : errorJson;
      return NextResponse.json(payload, { status: backendRes.status });
    } catch {
      const text = await backendRes.text().catch(() => "");
      const retryable = backendRes.status === 502 || backendRes.status === 504;
      const errorCode =
        backendRes.status === 504
          ? "ASR_TIMEOUT"
          : backendRes.status === 502
            ? "BHASHINI_UPSTREAM_ERROR"
            : "AUDIO_PROCESSING_ERROR";
      return NextResponse.json(
        {
          detail: text || "Voice transcription failed.",
          error_code: errorCode,
          retryable,
        },
        { status: backendRes.status }
      );
    }
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
