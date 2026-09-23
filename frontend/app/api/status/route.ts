/**
 * System Status API Route (Next.js Server Handler)
 * Proxies to FastAPI /api/status endpoint with graceful offline degradation.
 */

import { NextRequest, NextResponse } from 'next/server';

export interface SystemServiceStatus {
  weather: boolean;
  pfz: boolean;
  geofence: boolean;
  tiles: boolean;
  chat: boolean;
  backend?: string;
}

export interface SystemStatusResponse {
  status: 'ok' | 'degraded' | 'offline';
  services: SystemServiceStatus;
  timestamp: string;
  source: 'backend' | 'fallback';
}

export async function GET(_request: NextRequest) {
  const envUrl = process.env.BACKEND_API_URL || process.env.NEXT_PUBLIC_API_URL;
  const backendBase =
    envUrl && envUrl.trim().length > 0
      ? envUrl
      : (process.env.NODE_ENV === 'production' || process.env.VERCEL
          ? 'https://orca-marine-intelligence-api.onrender.com'
          : 'http://localhost:8000');

  const backendUrl = `${backendBase.replace(/\/$/, '')}/api/status`;

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 4000);

    const res = await fetch(backendUrl, {
      signal: controller.signal,
      cache: 'no-store',
      headers: {
        Accept: 'application/json',
      },
    });
    clearTimeout(timeoutId);

    if (res.ok) {
      const data = await res.json();
      return NextResponse.json({
        ...data,
        timestamp: new Date().toISOString(),
        source: 'backend',
      });
    }

    return NextResponse.json(
      {
        status: 'degraded',
        services: {
          weather: false,
          pfz: false,
          geofence: false,
          tiles: false,
          chat: false,
          backend: `status_${res.status}`,
        },
        timestamp: new Date().toISOString(),
        source: 'fallback',
      },
      { status: 200 }
    );
  } catch (_err: unknown) {
    return NextResponse.json(
      {
        status: 'degraded',
        services: {
          weather: false,
          pfz: false,
          geofence: false,
          tiles: false,
          chat: false,
          backend: 'offline',
        },
        timestamp: new Date().toISOString(),
        source: 'fallback',
      },
      { status: 200 }
    );
  }
}
