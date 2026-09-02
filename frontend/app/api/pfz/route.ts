/**
 * PFZ API Route (Next.js Server Component)
 *
 * Owner: M-C (Maps) — frontend data proxy for the map (owns map data fetching + offline cache; moved from M-D)
 * Module: frontend/app/api/pfz/route.ts
 *
 * Next.js API route that proxies PFZ data from the FastAPI backend.
 * Provides a server-side fetch to avoid CORS issues in development.
 *
 * Endpoints:
 *     GET /api/pfz — Returns today's PFZ GeoJSON FeatureCollection
 *
 * TODO:
 *     - [ ] Implement GET handler fetching from backend /api/pfz/today
 *     - [ ] Add caching with Next.js unstable_cache (6h TTL)
 *     - [ ] Handle backend unavailability gracefully
 *     - [ ] Add response transformation if needed
 */

import { NextResponse } from 'next/server';

export async function GET() {
  // TODO: Implement PFZ data proxy
  return NextResponse.json({ error: 'PFZ proxy not yet implemented' }, { status: 501 });
}
