/**
 * Shared live PFZ helpers (UI-MIG-T6).
 *
 * Single GeoJSON -> PFZItem mapper for the whole frontend. HomeScreen (T3)
 * owned the first copy; T6 extracts it here verbatim so PFZDetailScreen,
 * RouteViewScreen and PFZRecommendationCard all map the SAME live
 * `/api/pfz` feature properties. Do not fork — import from `@/lib/pfz`.
 *
 * Live-only: no mock imports, no stub zones. Backend-down callers render
 * empty states, never synthetic zones.
 */

import { MPA_GEOJSON, IMBL_COORDINATES, type GeoJSONFeatureCollection } from '../map/boundaries';

export interface PFZItem {
  id: string;
  name: string;
  code: string;
  [key: string]: unknown;
  region: string;
  distanceKm: number;
  bearing: string;
  bearingDegrees: number;
  suitability: 'SUITABLE' | 'MODERATE' | 'UNSUITABLE';
  coordinates: [number, number]; // [lat, lon]
  sstCelsius: number;
  chlorophyllMgM3: number;
  waveHeightMeters: number;
  windSpeedKmh: number;
  windDirection: string;
  weatherCondition: string;
  travelTimeMinutes: number;
  fuelEstimateLiters: number;
  depthMeters: number;
  targetFishSpecies: string[];
  evidence: string[];
  lastUpdated: string;
}

export interface LiveRouteInfo {
  originName: string;
  destinationName: string;
  totalDistanceKm: number;
  totalDistanceNm: number;
  bearing: string;
  bearingDegrees: number;
  estimatedTimeMinutes: number;
  safetyIndexPercent: number;
  safetyLabel: 'SAFE' | 'CAUTION' | 'AVOID';
  waypoints: [number, number][]; // [lat, lon]
  hazardWarnings: string[];
  detourOccurred?: boolean;
  detourWaypoints?: [number, number][];
  offlineCalculated?: boolean;
}

export interface SafeRouteOptions {
  mpa?: GeoJSONFeatureCollection;
  imblBufferKm?: number;
  seaLevel?: 'safe' | 'caution' | 'danger';
}

export const KT_TO_KMH = 1.852;
export const KM_TO_NM = 1.852;
export const CRUISE_KMH = 25;

export function getBackendBaseUrl(): string {
  const envUrl = process.env.NEXT_PUBLIC_API_URL;
  if (envUrl && envUrl.trim().length > 0) return envUrl.trim().replace(/\/+$/, '');
  // No env: resolve at runtime instead of hardcoding a host. Deployed pages
  // hit their own origin (frontend/vercel.json rewrites /api/* to the live
  // backend); only local http dev talks straight to FastAPI on :8000.
  if (typeof window !== 'undefined' && window.location) {
    const { protocol, hostname, origin } = window.location;
    const isLocal = protocol === 'http:' && (hostname === 'localhost' || hostname === '127.0.0.1');
    if (!isLocal && origin) return origin.replace(/\/+$/, '');
    if (isLocal) return 'http://localhost:8000';
  }
  return 'http://localhost:8000';
}

export function num(v: unknown, fallback: number): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

export function haversineKm(
  lat1: number,
  lon1: number,
  lat2: number,
  lon2: number
): number {
  const R = 6371;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLon = ((lon2 - lon1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos((lat1 * Math.PI) / 180) *
      Math.cos((lat2 * Math.PI) / 180) *
      Math.sin(dLon / 2) *
      Math.sin(dLon / 2);
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

export function compassFromDegrees(deg: number): string {
  const dirs = [
    'N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
    'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW',
  ];
  const norm = ((deg % 360) + 360) % 360;
  return dirs[Math.round(norm / 22.5) % 16];
}

/** Safety class mirroring backend/routers/weather.py composite status
 * (canonical bands: backend/agents/safety_thresholds.py #196). */
export function classifySea(
  windKt: number,
  waveM: number,
  currentKt: number,
  pressureHpa: number
): 'safe' | 'caution' | 'danger' {
  if (
    windKt > 25.0 ||
    waveM > 2.5 ||
    currentKt > 2.5 ||
    pressureHpa < 995.0
  ) {
    return 'danger';
  }
  if (
    windKt > 15.0 ||
    waveM > 1.5 ||
    currentKt > 1.5 ||
    pressureHpa < 1005.0
  ) {
    return 'caution';
  }
  return 'safe';
}

/** Live safety index from the same thresholds (safe 96 / caution 78 / danger 42). */
export function safetyIndexFromSea(
  level: 'safe' | 'caution' | 'danger'
): { percent: number; label: 'SAFE' | 'CAUTION' | 'AVOID' } {
  if (level === 'danger') return { percent: 42, label: 'AVOID' };
  if (level === 'caution') return { percent: 78, label: 'CAUTION' };
  return { percent: 96, label: 'SAFE' };
}

/**
 * Map ONE live PFZ GeoJSON feature -> design PFZItem. Verbatim T3 logic.
 * Detail values shown on screen therefore equal the live /api/pfz
 * feature properties (plus haversine distance/bearing from the GPS fix).
 */
export function mapFeatureToPFZItem(
  feature: any,
  userLat: number,
  userLon: number
): PFZItem | null {
  const coords = feature?.geometry?.coordinates;
  if (!Array.isArray(coords) || coords.length < 2) return null;
  const lon = Number(coords[0]);
  const lat = Number(coords[1]);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  const p = feature?.properties ?? {};

  const rawSuit = String(
    p.suitability ?? p.safety ?? p.danger ?? p.danger_status ?? 'safe'
  ).toLowerCase();
  const suitability: PFZItem['suitability'] = rawSuit.includes('danger') ||
    rawSuit.includes('red') ||
    rawSuit.includes('unsuitable') ||
    rawSuit.includes('avoid')
    ? 'UNSUITABLE'
    : rawSuit.includes('caution') ||
        rawSuit.includes('amber') ||
        rawSuit.includes('moderate') ||
        rawSuit.includes('medium') ||
        rawSuit.includes('warn')
      ? 'MODERATE'
      : 'SUITABLE';

  const distRaw =
    p.distance_km ?? p.distance_from_user_km ?? p.distance ?? p.distanceKm;
  const distanceKm =
    distRaw != null && distRaw !== ''
      ? Number(Number(distRaw).toFixed(1))
      : Number(haversineKm(userLat, userLon, lat, lon).toFixed(1));

  const bearingDegRaw =
    p.bearing_degrees ?? p.bearingDegrees ?? p.bearing ?? p.dir_deg;
  let bearingDegrees = Number(bearingDegRaw);
  if (!Number.isFinite(bearingDegrees)) {
    const dLon = ((lon - userLon) * Math.PI) / 180;
    const y = Math.sin(dLon) * Math.cos((lat * Math.PI) / 180);
    const x =
      Math.cos((userLat * Math.PI) / 180) * Math.sin((lat * Math.PI) / 180) -
      Math.sin((userLat * Math.PI) / 180) *
        Math.cos((lat * Math.PI) / 180) *
        Math.cos(dLon);
    bearingDegrees = Math.round((((Math.atan2(y, x) * 180) / Math.PI + 360) % 360) * 10) / 10;
  }
  const compass = compassFromDegrees(bearingDegrees);
  const bearingLabel =
    typeof p.bearing === 'string' && /[NSEW]/.test(p.bearing)
      ? p.bearing
      : `${compass} ${String(Math.round(bearingDegrees)).padStart(3, '0')}°`;

  const windKt = num(
    p.wind_kt ?? p.wind_speed_kt ?? p.wind_kts ?? p.wind,
    10
  );
  const windKmh =
    p.wind_kph != null &&
    p.wind_kt == null &&
    p.wind_speed_kt == null &&
    p.wind_kts == null
      ? num(p.wind_kph, 18.5)
      : Number((windKt * KT_TO_KMH).toFixed(1));

  const depthRaw = p.depth_m ?? p.depth;
  let depthMeters = 40;
  if (typeof depthRaw === 'number' && Number.isFinite(depthRaw)) {
    depthMeters = depthRaw;
  } else if (typeof depthRaw === 'string') {
    const nums = depthRaw.match(/\d+(?:\.\d+)?/g);
    if (nums && nums.length >= 2) {
      depthMeters = (Number(nums[0]) + Number(nums[1])) / 2;
    } else if (nums && nums.length === 1) {
      depthMeters = Number(nums[0]);
    }
  }

  const code =
    String(p.zone_id ?? p.code ?? p.id ?? 'PFZ').toUpperCase().length <= 12
      ? String(p.zone_id ?? p.code ?? p.id ?? 'PFZ')
      : String(p.zone_id ?? p.code ?? 'PFZ');
  const name = String(p.place ?? p.name ?? 'Fishing Zone');
  const region = String(p.sector_name ?? p.sector ?? p.region ?? 'Indian Coast');
  const travelTimeMinutes = Math.max(
    5,
    Math.round((distanceKm / CRUISE_KMH) * 60)
  );

  return {
    id: String(p.zone_id ?? feature?.id ?? `${lat},${lon}`),
    name,
    code,
    region,
    distanceKm,
    bearing: bearingLabel,
    bearingDegrees,
    suitability,
    coordinates: [lat, lon],
    sstCelsius: num(p.sst ?? p.sst_c ?? p.temperature_c, 28.4),
    chlorophyllMgM3: num(p.chlorophyll ?? p.chl ?? p.chlorophyll_mg_m3, 0.8),
    waveHeightMeters: num(p.wave_m ?? p.wave_height_m ?? p.wave, 1.1),
    windSpeedKmh: windKmh,
    windDirection: String(p.wind_direction ?? p.wind_dir ?? 'NE'),
    weatherCondition: String(p.weather ?? 'Partly Cloudy'),
    travelTimeMinutes,
    fuelEstimateLiters: Number((distanceKm * 0.9).toFixed(1)),
    depthMeters,
    targetFishSpecies:
      Array.isArray(p.species) && p.species.length > 0
        ? p.species.map(String)
        : Array.isArray(p.target_species) && p.target_species.length > 0
          ? p.target_species.map(String)
          : ['Mackerel', 'Sardine'],
    evidence: [
      `INCOIS ${region} ${String(p.valid_until ?? p.date ?? 'today')}`,
    ],
    lastUpdated: String(
      p.updated ?? p.valid_until ?? new Date().toISOString()
    ),
  };
}

function isPFZItemLike(v: any): v is PFZItem {
  return (
    v != null &&
    typeof v === 'object' &&
    Array.isArray((v as PFZItem).coordinates) &&
    (v as PFZItem).coordinates.length >= 2 &&
    typeof (v as PFZItem).distanceKm === 'number' &&
    typeof (v as PFZItem).bearingDegrees === 'number'
  );
}

/**
 * Normalize AppContext.selectedPFZ (opaque: live GeoJSON feature OR a
 * mapped PFZItem from PFZRecommendationCard) into a PFZItem for screens.
 * PFZItem input passes through untouched (no recompute); feature input
 * goes through the shared mapper. Returns null when unmappable.
 */
export function toPFZItem(
  selected: unknown,
  userLat: number,
  userLon: number
): PFZItem | null {
  if (selected == null) return null;
  if (isPFZItemLike(selected)) return selected as PFZItem;
  return mapFeatureToPFZItem(selected, userLat, userLon);
}

/**
 * Convert a PFZItem back to a live GeoJSON Point feature ([lon, lat] —
 * the same SSE `map.route` convention MapInner guards handle) so
 * View-on-Map / Navigate can flyTo + highlight + draw the route line.
 * Pass-through when already a feature.
 */
export function pfzItemToFeature(pfz: PFZItem | any): any {
  if (
    pfz != null &&
    typeof pfz === 'object' &&
    (pfz as any).type === 'Feature' &&
    (pfz as any).geometry?.coordinates
  ) {
    return pfz;
  }
  const item = pfz as PFZItem;
  const lat = Number(item?.coordinates?.[0]);
  const lon = Number(item?.coordinates?.[1]);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  return {
    type: 'Feature',
    id: (item as any)?.id,
    properties: {
      zone_id: (item as any)?.code ?? (item as any)?.id,
      code: (item as any)?.code,
      place: (item as any)?.name,
      name: (item as any)?.name,
      sector: (item as any)?.region,
      sector_name: (item as any)?.region,
      suitability: (item as any)?.suitability,
      distance_km: (item as any)?.distanceKm,
      bearing_degrees: (item as any)?.bearingDegrees,
      bearing: (item as any)?.bearing,
    },
    geometry: { type: 'Point', coordinates: [lon, lat] },
  };
}

/**
 * Live route math: haversine distance, bearing label, ETA at cruise
 * speed, safety index from the live sea class. Waypoints are
 * origin -> mid-channel -> destination [lat, lon] (drawn by MapInner's
 * guarded nav polyline from the same lon/lat feature).
 */
export function computeLiveRoute(
  originLat: number,
  originLon: number,
  originName: string,
  dest: PFZItem,
  seaLevel: 'safe' | 'caution' | 'danger' = 'safe',
  hazardWarnings: string[] = []
): LiveRouteInfo {
  const [dLat, dLon] = dest.coordinates;
  const distKm = Number(haversineKm(originLat, originLon, dLat, dLon).toFixed(1));
  const y = Math.sin(((dLon - originLon) * Math.PI) / 180) * Math.cos((dLat * Math.PI) / 180);
  const x =
    Math.cos((originLat * Math.PI) / 180) * Math.sin((dLat * Math.PI) / 180) -
    Math.sin((originLat * Math.PI) / 180) *
      Math.cos((dLat * Math.PI) / 180) *
      Math.cos(((dLon - originLon) * Math.PI) / 180);
  const bearingDegrees = Math.round((((Math.atan2(y, x) * 180) / Math.PI + 360) % 360) * 10) / 10;
  const bearingLabel = `${compassFromDegrees(bearingDegrees)} ${String(Math.round(bearingDegrees)).padStart(3, '0')}°`;
  const { percent, label } = safetyIndexFromSea(seaLevel);
  const mid: [number, number] = [
    Number(((originLat + dLat) / 2).toFixed(4)),
    Number(((originLon + dLon) / 2).toFixed(4)),
  ];
  return {
    originName,
    destinationName: `${dest.code} (${dest.name})`,
    totalDistanceKm: distKm,
    totalDistanceNm: Number((distKm / KM_TO_NM).toFixed(1)),
    bearing: bearingLabel,
    bearingDegrees,
    estimatedTimeMinutes: Math.max(5, Math.round((distKm / CRUISE_KMH) * 60)),
    safetyIndexPercent: percent,
    safetyLabel: label,
    waypoints: [
      [originLat, originLon],
      mid,
      [dLat, dLon],
    ],
    hazardWarnings,
  };
}

/**
 * Great-circle spherical interpolation between two [lat, lon] points.
 */
export function interpolateGreatCircle(
  start: [number, number],
  end: [number, number],
  numPoints: number = 5
): [number, number][] {
  if (numPoints <= 2) return [start, end];

  const toRad = Math.PI / 180;
  const toDeg = 180 / Math.PI;

  const lat1 = start[0] * toRad;
  const lon1 = start[1] * toRad;
  const lat2 = end[0] * toRad;
  const lon2 = end[1] * toRad;

  const dLat = lat2 - lat1;
  const dLon = lon2 - lon1;

  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
  const d = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));

  if (d < 1e-6) {
    return Array(numPoints).fill(start);
  }

  const points: [number, number][] = [];
  for (let i = 0; i < numPoints; i++) {
    const f = i / (numPoints - 1);
    const A = Math.sin((1 - f) * d) / Math.sin(d);
    const B = Math.sin(f * d) / Math.sin(d);

    const x = A * Math.cos(lat1) * Math.cos(lon1) + B * Math.cos(lat2) * Math.cos(lon2);
    const y = A * Math.cos(lat1) * Math.sin(lon1) + B * Math.cos(lat2) * Math.sin(lon2);
    const z = A * Math.sin(lat1) + B * Math.sin(lat2);

    const lat = Math.atan2(z, Math.sqrt(x * x + y * y)) * toDeg;
    const lon = Math.atan2(y, x) * toDeg;
    points.push([Number(lat.toFixed(5)), Number(lon.toFixed(5))]);
  }
  return points;
}

/**
 * Checks if 2D line segments (p1-p2) and (p3-p4) intersect. Points are [lat, lon].
 */
export function segmentsIntersect(
  p1: [number, number],
  p2: [number, number],
  p3: [number, number],
  p4: [number, number]
): boolean {
  const ccw = (A: [number, number], B: [number, number], C: [number, number]): boolean => {
    return (C[1] - A[1]) * (B[0] - A[0]) > (B[1] - A[1]) * (C[0] - A[0]);
  };
  return (
    ccw(p1, p3, p4) !== ccw(p2, p3, p4) &&
    ccw(p1, p2, p3) !== ccw(p1, p2, p4)
  );
}

/**
 * Checks if a point [lat, lon] is inside a polygon [[lat, lon], ...] (Ray-casting).
 */
export function pointInPolygon(
  point: [number, number],
  polygon: [number, number][]
): boolean {
  const [lat, lon] = point;
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [xi, yi] = polygon[i];
    const [xj, yj] = polygon[j];
    const intersect =
      yi > lon !== yj > lon && lat < ((xj - xi) * (lon - yi)) / (yj - yi) + xi;
    if (intersect) inside = !inside;
  }
  return inside;
}

/**
 * Checks if a segment [lat, lon]->[lat, lon] crosses a polygon boundary or passes through it.
 */
export function segmentCrossesPolygon(
  p1: [number, number],
  p2: [number, number],
  polygon: [number, number][]
): boolean {
  if (polygon.length < 3) return false;
  for (let i = 0; i < polygon.length; i++) {
    const nextIdx = (i + 1) % polygon.length;
    if (segmentsIntersect(p1, p2, polygon[i], polygon[nextIdx])) {
      return true;
    }
  }
  const mid: [number, number] = [(p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2];
  return pointInPolygon(p1, polygon) || pointInPolygon(p2, polygon) || pointInPolygon(mid, polygon);
}

/**
 * Distance from a point [lat, lon] to the closest point on segment s1-s2 in kilometers.
 */
export function pointToSegmentDistanceKm(
  pt: [number, number],
  s1: [number, number],
  s2: [number, number]
): number {
  const dTotal = haversineKm(s1[0], s1[1], s2[0], s2[1]);
  if (dTotal === 0) return haversineKm(pt[0], pt[1], s1[0], s1[1]);

  const denom = (s2[0] - s1[0]) ** 2 + (s2[1] - s1[1]) ** 2;
  if (denom === 0) return haversineKm(pt[0], pt[1], s1[0], s1[1]);

  const t = Math.max(
    0,
    Math.min(
      1,
      ((pt[0] - s1[0]) * (s2[0] - s1[0]) + (pt[1] - s1[1]) * (s2[1] - s1[1])) / denom
    )
  );
  const projLat = s1[0] + t * (s2[0] - s1[0]);
  const projLon = s1[1] + t * (s2[1] - s1[1]);
  return haversineKm(pt[0], pt[1], projLat, projLon);
}

/**
 * Minimum distance from a point to a polyline in kilometers.
 */
export function pointToPolylineDistanceKm(
  pt: [number, number],
  polyline: [number, number][]
): number {
  let minD = Infinity;
  for (let i = 0; i < polyline.length - 1; i++) {
    const d = pointToSegmentDistanceKm(pt, polyline[i], polyline[i + 1]);
    if (d < minD) minD = d;
  }
  return minD;
}

/**
 * True when no leg of the waypoint polyline crosses the polygon.
 */
export function routeLegsClear(
  waypoints: [number, number][],
  polygon: [number, number][]
): boolean {
  for (let i = 0; i < waypoints.length - 1; i++) {
    if (segmentCrossesPolygon(waypoints[i], waypoints[i + 1], polygon)) {
      return false;
    }
  }
  return true;
}

/**
 * Minimum distance between segments a1-a2 and b1-b2 in km (0 when intersecting).
 */
export function segSegDistanceKm(
  a1: [number, number],
  a2: [number, number],
  b1: [number, number],
  b2: [number, number]
): number {
  if (segmentsIntersect(a1, a2, b1, b2)) return 0;
  return Math.min(
    pointToSegmentDistanceKm(a1, b1, b2),
    pointToSegmentDistanceKm(a2, b1, b2),
    pointToSegmentDistanceKm(b1, a1, a2),
    pointToSegmentDistanceKm(b2, a1, a2)
  );
}

/**
 * Minimum distance between two polylines in km, evaluated leg-by-leg.
 */
export function polylineToPolylineDistanceKm(
  route: [number, number][],
  other: [number, number][]
): number {
  let minD = Infinity;
  for (let i = 0; i < route.length - 1; i++) {
    for (let j = 0; j < other.length - 1; j++) {
      const d = segSegDistanceKm(route[i], route[i + 1], other[j], other[j + 1]);
      if (d < minD) minD = d;
    }
  }
  return minD;
}

/**
 * Safe marine route calculator (T5 #164).
 * Calculates direct great-circle route with MPA polygon avoidance and IMBL proximity checks.
 */
export function buildSafeRoute(
  origin: { lat: number; lon: number; name?: string },
  dest: PFZItem,
  options: SafeRouteOptions = {}
): LiveRouteInfo {
  const originLat = origin.lat;
  const originLon = origin.lon;
  const originName = origin.name || 'Current GPS Location';
  const [dLat, dLon] = dest.coordinates;
  const seaLevel = options.seaLevel || 'safe';
  const imblBufferKm = options.imblBufferKm ?? 2.0;

  const mpaCollection = options.mpa || MPA_GEOJSON;
  const warnings: string[] = [];
  let detourOccurred = false;
  let detourWaypoints: [number, number][] = [];

  const startPt: [number, number] = [originLat, originLon];
  const endPt: [number, number] = [dLat, dLon];

  // 1. Check for MPA intersection with corner-based detour.
  // A single midpoint waypoint can leave legs crossing the polygon, so route
  // around the buffered bbox corners, validate every leg, and keep the
  // shortest fully-clear side (both corner orders evaluated).
  let unavoidedMpaName: string | null = null;

  for (const feature of mpaCollection.features) {
    if (feature.geometry.type !== 'Polygon') continue;
    const ring = feature.geometry.coordinates[0];
    // GeoJSON coordinates are [lon, lat] -> convert to [lat, lon]
    const polyLatLon: [number, number][] = ring.map((pt: [number, number]) => [pt[1], pt[0]]);

    if (!segmentCrossesPolygon(startPt, endPt, polyLatLon)) continue;
    const crossedName = feature.properties.mpa_name || 'Protected Marine Reserve';

    let minLat = Infinity, maxLat = -Infinity, minLon = Infinity, maxLon = -Infinity;
    for (const [pLat, pLon] of polyLatLon) {
      if (pLat < minLat) minLat = pLat;
      if (pLat > maxLat) maxLat = pLat;
      if (pLon < minLon) minLon = pLon;
      if (pLon > maxLon) maxLon = pLon;
    }

    // Buffer offset in degrees (~2.2 km)
    const bufDeg = 0.02;
    const r4 = (v: number): number => Number(v.toFixed(4));
    const sw: [number, number] = [r4(minLat - bufDeg), r4(minLon - bufDeg)];
    const nw: [number, number] = [r4(maxLat + bufDeg), r4(minLon - bufDeg)];
    const se: [number, number] = [r4(minLat - bufDeg), r4(maxLon + bufDeg)];
    const ne: [number, number] = [r4(maxLat + bufDeg), r4(maxLon + bufDeg)];
    const sides: [number, number][][] = [[sw, nw], [se, ne], [sw, se], [nw, ne]];

    const routeLen = (pts: [number, number][]): number => {
      let total = 0;
      for (let i = 0; i < pts.length - 1; i++) {
        total += haversineKm(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1]);
      }
      return total;
    };

    let best: [number, number][] | null = null;
    let bestDist = Infinity;
    for (const [cornerA, cornerB] of sides) {
      for (const ordered of [[cornerA, cornerB], [cornerB, cornerA]]) {
        const candidate: [number, number][] = [startPt, ordered[0], ordered[1], endPt];
        if (!routeLegsClear(candidate, polyLatLon)) continue;
        const legDist = routeLen(candidate);
        if (legDist < bestDist) {
          bestDist = legDist;
          best = [ordered[0], ordered[1]];
        }
      }
    }

    if (best) {
      detourOccurred = true;
      detourWaypoints = best;
      warnings.push(`Route passes through Marine Protected Area: ${crossedName}. Detour applied around protected zone.`);
    } else {
      unavoidedMpaName = crossedName;
      warnings.push(`Route passes through Marine Protected Area: ${crossedName}. No safe detour available — avoid entry.`);
    }
    break;
  }

  const waypoints: [number, number][] = [];
  waypoints.push(startPt);

  if (detourOccurred && detourWaypoints.length > 0) {
    for (const wp of detourWaypoints) waypoints.push(wp);
  } else {
    // Standard mid waypoint
    const mid: [number, number] = [
      Number(((originLat + dLat) / 2).toFixed(4)),
      Number(((originLon + dLon) / 2).toFixed(4)),
    ];
    waypoints.push(mid);
  }
  waypoints.push(endPt);

  // 2. Check IMBL proximity across the full route polyline, leg-by-leg.
  const minImblDist = polylineToPolylineDistanceKm(waypoints, IMBL_COORDINATES);

  let safetyLabel: 'SAFE' | 'CAUTION' | 'AVOID' = 'SAFE';
  let { percent } = safetyIndexFromSea(seaLevel);

  if (unavoidedMpaName) {
    safetyLabel = 'AVOID';
    percent = Math.min(percent, 30);
  } else if (minImblDist <= imblBufferKm) {
    warnings.push(
      `Warning: Proximity to International Maritime Boundary Line (<${imblBufferKm}km). Risk of border crossing.`
    );
    safetyLabel = 'CAUTION';
    percent = Math.min(percent, 55);
  } else if (detourOccurred) {
    safetyLabel = 'CAUTION';
    percent = Math.min(percent, 70);
  }

  // Calculate total route distance across waypoints
  let totalDistKm = 0;
  for (let i = 0; i < waypoints.length - 1; i++) {
    totalDistKm += haversineKm(waypoints[i][0], waypoints[i][1], waypoints[i + 1][0], waypoints[i + 1][1]);
  }
  totalDistKm = Number(totalDistKm.toFixed(1));

  const y = Math.sin(((dLon - originLon) * Math.PI) / 180) * Math.cos((dLat * Math.PI) / 180);
  const x =
    Math.cos((originLat * Math.PI) / 180) * Math.sin((dLat * Math.PI) / 180) -
    Math.sin((originLat * Math.PI) / 180) *
      Math.cos((dLat * Math.PI) / 180) *
      Math.cos(((dLon - originLon) * Math.PI) / 180);
  const bearingDegrees = Math.round((((Math.atan2(y, x) * 180) / Math.PI + 360) % 360) * 10) / 10;
  const bearingLabel = `${compassFromDegrees(bearingDegrees)} ${String(Math.round(bearingDegrees)).padStart(3, '0')}°`;

  return {
    originName,
    destinationName: `${dest.code} (${dest.name})`,
    totalDistanceKm: totalDistKm,
    totalDistanceNm: Number((totalDistKm / KM_TO_NM).toFixed(1)),
    bearing: bearingLabel,
    bearingDegrees,
    estimatedTimeMinutes: Math.max(5, Math.round((totalDistKm / CRUISE_KMH) * 60)),
    safetyIndexPercent: percent,
    safetyLabel,
    waypoints,
    hazardWarnings: warnings,
    detourOccurred,
    detourWaypoints,
    offlineCalculated: true,
  };
}
