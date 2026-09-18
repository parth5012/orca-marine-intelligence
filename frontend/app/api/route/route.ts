/**
 * Safe Route API Proxy Route (Next.js Server Handler)
 *
 * Owner: M-C (Backend API & Platform) & M-D (Frontend Map)
 * Module: frontend/app/api/route/route.ts
 *
 * Proxies safe route calculation to FastAPI backend:
 * GET /api/route -> ${BACKEND_API_URL || NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/route/safe
 *
 * If backend is unavailable or times out after 6 seconds, falls back gracefully
 * to client-side great-circle & avoidance calculation using buildSafeRoute.
 */

import { NextRequest, NextResponse } from 'next/server';
import { buildSafeRoute, haversineKm, type PFZItem } from '@/lib/pfz';
import { MPA_GEOJSON } from '@/map/boundaries';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const olatStr = searchParams.get('olat');
  const olonStr = searchParams.get('olon');
  const dlatStr = searchParams.get('dlat');
  const dlonStr = searchParams.get('dlon');
  const waveStr = searchParams.get('wave_height_m') || '1.0';
  const windStr = searchParams.get('wind_speed_kt') || '15.0';

  const olat = Number(olatStr);
  const olon = Number(olonStr);
  const dlat = Number(dlatStr);
  const dlon = Number(dlonStr);

  if (
    !Number.isFinite(olat) ||
    !Number.isFinite(olon) ||
    !Number.isFinite(dlat) ||
    !Number.isFinite(dlon) ||
    olat < -90 ||
    olat > 90 ||
    dlat < -90 ||
    dlat > 90 ||
    olon < -180 ||
    olon > 180 ||
    dlon < -180 ||
    dlon > 180
  ) {
    return NextResponse.json(
      { error: 'Invalid or missing coordinate parameters (olat, olon, dlat, dlon)' },
      { status: 400 }
    );
  }

  const backendBase =
    process.env.BACKEND_API_URL ||
    process.env.NEXT_PUBLIC_API_URL ||
    'http://localhost:8000';

  const backendUrl = new URL(`${backendBase.replace(/\/$/, '')}/api/route/safe`);
  backendUrl.searchParams.set('olat', String(olat));
  backendUrl.searchParams.set('olon', String(olon));
  backendUrl.searchParams.set('dlat', String(dlat));
  backendUrl.searchParams.set('dlon', String(dlon));
  backendUrl.searchParams.set('wave_height_m', waveStr);
  backendUrl.searchParams.set('wind_speed_kt', windStr);

  // 1. Attempt to fetch from live FastAPI backend with 6-second timeout
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 6000);

    const response = await fetch(backendUrl.toString(), {
      method: 'GET',
      headers: {
        Accept: 'application/json',
      },
      signal: controller.signal,
      cache: 'no-store',
    });

    clearTimeout(timeoutId);

    if (response.ok) {
      const data = await response.json();
      return NextResponse.json({
        ...data,
        source: 'backend_live',
      });
    }
  } catch {
    // Backend timeout or unreachable — fall through to local calculation
  }

  // 2. Fallback: compute safe route using local buildSafeRoute
  const mockDest: PFZItem = {
    id: 'route-dest',
    name: 'Target Destination',
    code: 'ROUTE-DEST',
    region: 'Coastal',
    distanceKm: haversineKm(olat, olon, dlat, dlon),
    bearing: 'N',
    bearingDegrees: 0,
    suitability: 'SUITABLE',
    coordinates: [dlat, dlon],
    sstCelsius: 28,
    chlorophyllMgM3: 1.0,
    waveHeightMeters: Number(waveStr) || 1.0,
    windSpeedKmh: (Number(windStr) || 15.0) * 1.852,
    windDirection: 'NW',
    weatherCondition: 'Fair',
    travelTimeMinutes: 60,
    fuelEstimateLiters: 30,
    depthMeters: 40,
    targetFishSpecies: [],
    evidence: [],
    lastUpdated: new Date().toISOString(),
  };

  const safeRoute = buildSafeRoute(
    { lat: olat, lon: olon, name: 'Current GPS Location' },
    mockDest,
    { mpa: MPA_GEOJSON, imblBufferKm: 2.0 }
  );

  const wavePenalty = Number(((Number(waveStr) || 1.0) * 0.5).toFixed(3));
  const windPenalty = Number((((Number(windStr) || 15.0) / 50.0) * 0.3).toFixed(3));
  const forbiddenPenalty = safeRoute.detourOccurred || safeRoute.safetyLabel === 'CAUTION' ? 1000.0 : 0.0;
  const totalCost = Number(
    (safeRoute.totalDistanceKm * (1.0 + wavePenalty + windPenalty + forbiddenPenalty)).toFixed(2)
  );

  return NextResponse.json({
    status: 'ok',
    waypoints: safeRoute.waypoints,
    distance_km: safeRoute.totalDistanceKm,
    distance_nm: safeRoute.totalDistanceNm,
    bearing: safeRoute.bearing,
    bearing_deg: safeRoute.bearingDegrees,
    eta_min: safeRoute.estimatedTimeMinutes,
    safety_index: safeRoute.safetyIndexPercent,
    safety_label: safeRoute.safetyLabel,
    hazards: safeRoute.hazardWarnings,
    cost_breakdown: {
      distance_base: safeRoute.totalDistanceKm,
      wave_penalty: wavePenalty,
      wind_penalty: windPenalty,
      forbidden_penalty: forbiddenPenalty,
      total_cost: totalCost,
    },
    source: 'client_fallback',
  });
}
