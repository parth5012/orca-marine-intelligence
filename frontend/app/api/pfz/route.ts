/**
 * PFZ API Route (Next.js Server Handler)
 *
 * Owner: M-D (Frontend & Maps) — Next.js proxy & offline cache for map
 * Module: frontend/app/api/pfz/route.ts
 *
 * Next.js API route that proxies PFZ data to FastAPI backend:
 * GET /api/pfz -> ${BACKEND_API_URL || NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/pfz/today
 *
 * If backend is unavailable, reads local data/pfz-today.geojson; returns 503 when neither is available (no static data).
 */

import { NextRequest, NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';


function readLocalGeoJSONFile(): any | null {
  const candidatePaths = [
    path.resolve(process.cwd(), '..', 'data', 'pfz-today.geojson'),
    path.resolve(process.cwd(), 'data', 'pfz-today.geojson'),
    path.resolve(process.cwd(), '..', '..', 'data', 'pfz-today.geojson'),
  ];

  for (const candidate of candidatePaths) {
    try {
      if (fs.existsSync(candidate)) {
        const raw = fs.readFileSync(candidate, 'utf-8');
        return JSON.parse(raw);
      }
    } catch {
      // try next candidate
    }
  }

  return null;
}

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const sector = searchParams.get('sector');
  const limitStr = searchParams.get('limit');
  const bbox = searchParams.get('bbox');
  const place = searchParams.get('place') || 'Kochi';

  const backendBase =
    process.env.BACKEND_API_URL ||
    process.env.NEXT_PUBLIC_API_URL ||
    'http://localhost:8000';

  const backendUrl = new URL(`${backendBase.replace(/\/$/, '')}/api/pfz/today`);
  if (sector) backendUrl.searchParams.set('sector', sector);
  if (limitStr) backendUrl.searchParams.set('limit', limitStr);
  if (bbox) backendUrl.searchParams.set('bbox', bbox);
  if (place) backendUrl.searchParams.set('place', place);

  // 1. Attempt to fetch from live FastAPI backend with 6-second timeout
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 6000);

    const forwardedHeaders: Record<string, string> = {
      Accept: 'application/json',
    };
    const acceptLanguage = request.headers.get('accept-language');
    if (acceptLanguage) forwardedHeaders['Accept-Language'] = acceptLanguage;
    const userAgent = request.headers.get('user-agent');
    if (userAgent) forwardedHeaders['User-Agent'] = userAgent;
    const forwardedFor = request.headers.get('x-forwarded-for');
    if (forwardedFor) forwardedHeaders['X-Forwarded-For'] = forwardedFor;

    const response = await fetch(backendUrl.toString(), {
      signal: controller.signal,
      headers: forwardedHeaders,
      next: { revalidate: 3600 },
    });

    clearTimeout(timeoutId);

    if (response.ok) {
      const data = await response.json();
      return NextResponse.json(data, {
        status: 200,
        headers: {
          'X-Data-Source': 'backend',
          'Cache-Control': 'public, s-maxage=3600, stale-while-revalidate=86400',
        },
      });
    }
  } catch {
    // Backend offline, network error, or timed out - proceed to graceful fallback
  }

  // 2. Local file fallback: Read data/pfz-today.geojson (no static hardcoded zones)
  let localData = readLocalGeoJSONFile();
  let dataSource = 'local_file';

  if (!localData || !Array.isArray(localData.features) || localData.features.length === 0) {
    const validUntil = new Date().toISOString();
    return NextResponse.json(
      {
        type: 'FeatureCollection',
        source: 'unavailable',
        valid_until: validUntil,
        sector_count: 0,
        count: 0,
        timestamp: validUntil,
        fallback: true,
        metadata: {
          valid_until: validUntil,
          source: 'unavailable',
          sector_count: 0,
          count: 0,
        },
        error: 'PFZ data unavailable: backend offline and no local data file.',
        features: [],
      },
      {
        status: 503,
        headers: {
          'X-Data-Source': 'unavailable',
          'Cache-Control': 'no-store',
        },
      }
    );
  }

  // Apply sector and limit filtering to fallback data
  let features = localData.features || [];

  if (sector) {
    const sec = sector.trim().toUpperCase();
    features = features.filter((f: any) => {
      const p = f.properties || {};
      const s = (p.sector || '').toUpperCase();
      const sn = (p.sector_name || '').toUpperCase();
      return s === sec || sn === sec || sn.includes(sec);
    });
  }

  if (limitStr) {
    const limit = parseInt(limitStr, 10);
    if (!isNaN(limit) && limit > 0) {
      features = features.slice(0, limit);
    }
  }

  const validUntil = localData.valid_until || new Date().toISOString();

  return NextResponse.json(
    {
      type: 'FeatureCollection',
      source: dataSource,
      valid_until: validUntil,
      sector_count: features.length,
      count: features.length,
      timestamp: localData.timestamp || new Date().toISOString(),
      fallback: true,
      metadata: {
        valid_until: validUntil,
        source: dataSource,
        sector_count: features.length,
        count: features.length,
      },
      features,
    },
    {
      status: 200,
      headers: {
        'X-Data-Source': dataSource,
        'Cache-Control': 'public, s-maxage=1800, stale-while-revalidate=3600',
      },
    }
  );
}
