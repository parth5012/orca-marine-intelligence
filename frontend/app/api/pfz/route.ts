/**
 * PFZ API Route (Next.js Server Handler)
 *
 * Owner: M-D (Frontend & Maps) — Next.js proxy & offline cache for map
 * Module: frontend/app/api/pfz/route.ts
 *
 * Next.js API route that proxies PFZ data to FastAPI backend:
 * GET /api/pfz -> ${BACKEND_API_URL || NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/pfz/today
 *
 * If backend is unavailable or offline, gracefully returns local sample data fallback.
 */

import { NextRequest, NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';

// Static fallback features if backend is offline and filesystem file is not reachable
const FALLBACK_PFZ_GEOJSON = {
  type: 'FeatureCollection',
  source: 'local_sample_fallback',
  timestamp: new Date().toISOString(),
  count: 6,
  sector_count: 5,
  features: [
    {
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [75.98, 9.85] },
      properties: {
        place: 'Kochi Offshore Shelf',
        sector: 'SEC005',
        sector_name: 'KERALA',
        dir: 'SW',
        direction: 'SW',
        bearing: 225,
        distance: '24-30',
        distance_km: 26,
        depth: '35-45',
        depth_m: 40,
        lat_dms: "9°51'00\"N",
        lon_dms: "75°58'48\"E",
        suitability: 'high',
        sst_c: 28.5,
        chlorophyll: '0.85 mg/m³',
        safety: 'safe',
        timestamp: new Date().toISOString(),
      },
    },
    {
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [76.08, 10.12] },
      properties: {
        place: 'Munambam Fishing Ground',
        sector: 'SEC005',
        sector_name: 'KERALA',
        dir: 'W',
        direction: 'W',
        bearing: 270,
        distance: '18-22',
        distance_km: 20,
        depth: '30-40',
        depth_m: 35,
        lat_dms: "10°07'12\"N",
        lon_dms: "76°04'48\"E",
        suitability: 'high',
        sst_c: 28.2,
        chlorophyll: '0.92 mg/m³',
        safety: 'safe',
        timestamp: new Date().toISOString(),
      },
    },
    {
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [69.95, 20.72] },
      properties: {
        place: 'Veraval Coast Front',
        sector: 'SEC001',
        sector_name: 'GUJARAT',
        dir: 'SW',
        direction: 'SW',
        bearing: 235,
        distance: '28-35',
        distance_km: 30,
        depth: '40-50',
        depth_m: 45,
        lat_dms: "20°43'12\"N",
        lon_dms: "69°57'00\"E",
        suitability: 'medium',
        sst_c: 27.8,
        chlorophyll: '0.74 mg/m³',
        safety: 'safe',
        timestamp: new Date().toISOString(),
      },
    },
    {
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [80.45, 13.15] },
      properties: {
        place: 'Chennai Offshore Bank',
        sector: 'SEC007',
        sector_name: 'TAMIL NADU',
        dir: 'E',
        direction: 'E',
        bearing: 85,
        distance: '20-25',
        distance_km: 22,
        depth: '50-60',
        depth_m: 55,
        lat_dms: "13°09'00\"N",
        lon_dms: "80°27'00\"E",
        suitability: 'high',
        sst_c: 29.1,
        chlorophyll: '1.10 mg/m³',
        safety: 'safe',
        timestamp: new Date().toISOString(),
      },
    },
    {
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [74.45, 12.85] },
      properties: {
        place: 'Mangalore Deep Ridge',
        sector: 'SEC004',
        sector_name: 'KARNATAKA',
        dir: 'W',
        direction: 'W',
        bearing: 260,
        distance: '32-38',
        distance_km: 35,
        depth: '45-55',
        depth_m: 50,
        lat_dms: "12°51'00\"N",
        lon_dms: "74°27'00\"E",
        suitability: 'medium',
        sst_c: 28.4,
        chlorophyll: '0.68 mg/m³',
        safety: 'safe',
        timestamp: new Date().toISOString(),
      },
    },
    {
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [72.40, 18.80] },
      properties: {
        place: 'Mumbai Harbour Outer Channel',
        sector: 'SEC002',
        sector_name: 'MAHARASHTRA',
        dir: 'SW',
        direction: 'SW',
        bearing: 230,
        distance: '25-30',
        distance_km: 28,
        depth: '38-48',
        depth_m: 42,
        lat_dms: "18°48'00\"N",
        lon_dms: "72°24'00\"E",
        suitability: 'low',
        sst_c: 28.0,
        chlorophyll: '0.55 mg/m³',
        safety: 'safe',
        timestamp: new Date().toISOString(),
      },
    },
  ],
};

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

  const backendBase =
    process.env.BACKEND_API_URL ||
    process.env.NEXT_PUBLIC_API_URL ||
    'http://localhost:8000';

  const backendUrl = new URL(`${backendBase.replace(/\/$/, '')}/api/pfz/today`);
  if (sector) backendUrl.searchParams.set('sector', sector);
  if (limitStr) backendUrl.searchParams.set('limit', limitStr);
  if (bbox) backendUrl.searchParams.set('bbox', bbox);

  // 1. Attempt to fetch from live FastAPI backend with 3-second timeout
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 3000);

    const response = await fetch(backendUrl.toString(), {
      signal: controller.signal,
      headers: {
        Accept: 'application/json',
      },
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

  // 2. Graceful fallback: Read local sample data from data/pfz-today.geojson
  let localData = readLocalGeoJSONFile();
  let dataSource = 'local_file';

  if (!localData || !Array.isArray(localData.features) || localData.features.length === 0) {
    localData = FALLBACK_PFZ_GEOJSON;
    dataSource = 'static_fallback';
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

  return NextResponse.json(
    {
      type: 'FeatureCollection',
      source: dataSource,
      count: features.length,
      timestamp: localData.timestamp || new Date().toISOString(),
      fallback: true,
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
