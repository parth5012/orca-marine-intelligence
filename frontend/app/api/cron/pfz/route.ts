/**
 * Vercel Cron handler — daily PFZ refresh trigger.
 *
 * Owner: M-C (Backend API & Platform)
 * Module: frontend/app/api/cron/pfz/route.ts
 *
 * Vercel Cron (see infra/vercel.json `crons`) calls GET /api/cron/pfz daily
 * at 06:30 UTC (= 12:00 IST, 30 min after INCOIS ~11:30 IST publish).
 * Handler forwards to backend POST /api/pfz/refresh with CRON_SECRET,
 * returning an observable envelope {status, summary, next_actions, artifacts}.
 *
 * Security: Vercel sends `Authorization: Bearer <CRON_SECRET>`.
 * Backend enforces the same secret. If CRON_SECRET is unset (local dev),
 * both sides allow open refresh.
 */

import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';
export const maxDuration = 120;

export async function GET(request: Request) {
  const backendBase =
    process.env.BACKEND_API_URL ||
    process.env.NEXT_PUBLIC_API_URL ||
    'http://localhost:8000';

  const cronSecret = process.env.CRON_SECRET || '';
  const authHeader = request.headers.get('authorization') || '';

  // Verify caller when secret is configured (Vercel sends it automatically
  // if you set the same CRON_SECRET env on both sides)
  if (cronSecret && authHeader !== `Bearer ${cronSecret}`) {
    return NextResponse.json(
      {
        status: 'error',
        summary: 'Unauthorized cron caller',
        next_actions: ['configure CRON_SECRET on Vercel + backend'],
        artifacts: [],
      },
      { status: 401 },
    );
  }

  const url = `${backendBase.replace(/\/$/, '')}/api/pfz/refresh`;
  try {
    const resp = await fetch(url, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        ...(cronSecret ? { Authorization: `Bearer ${cronSecret}` } : {}),
      },
    });
    const data = await resp.json().catch(() => ({}));
    return NextResponse.json(
      {
        status: resp.ok ? data.status || 'success' : 'error',
        summary: data.summary || `Backend refresh HTTP ${resp.status}`,
        next_actions: data.next_actions || ['check backend logs'],
        artifacts: data.artifacts || ['data/pfz-today.geojson'],
        count: data.count ?? 0,
        source: data.source ?? 'unknown',
      },
      { status: resp.ok ? 200 : 502 },
    );
  } catch (err) {
    return NextResponse.json(
      {
        status: 'error',
        summary: `PFZ cron forward failed: ${err instanceof Error ? err.message : String(err)}`,
        next_actions: ['verify BACKEND_API_URL reachable', 'retry manually'],
        artifacts: ['data/pfz-today.geojson'],
      },
      { status: 502 },
    );
  }
}
