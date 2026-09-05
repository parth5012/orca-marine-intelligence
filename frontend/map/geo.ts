/**
 * Geo Utilities
 *
 * Owner: M-D (Frontend & Maps) — haversine/bearing helpers
 * Module: frontend/map/geo.ts
 *
 * Client-side geographic calculation utilities for map rendering,
 * MapView distance/bearing calculations, and ChatPanel location extraction.
 */

export interface GeoCoordinate {
  lat: number;
  lon: number;
}

/**
 * Common Indian coastal ports and fishing harbours registry.
 * Approximate WGS84 coordinates.
 */
export const COASTAL_PORTS: Record<string, GeoCoordinate> = {
  kochi: { lat: 9.9312, lon: 76.2673 },
  cochin: { lat: 9.9312, lon: 76.2673 },
  veraval: { lat: 20.9000, lon: 70.3667 },
  chennai: { lat: 13.0827, lon: 80.2707 },
  madras: { lat: 13.0827, lon: 80.2707 },
  mangalore: { lat: 12.9141, lon: 74.8560 },
  mangaluru: { lat: 12.9141, lon: 74.8560 },
  mumbai: { lat: 18.9220, lon: 72.8347 },
  bombay: { lat: 18.9220, lon: 72.8347 },
  visakhapatnam: { lat: 17.6868, lon: 83.2185 },
  vizag: { lat: 17.6868, lon: 83.2185 },
  kanyakumari: { lat: 8.0883, lon: 77.5385 },
  goa: { lat: 15.4909, lon: 73.8278 },
  panaji: { lat: 15.4909, lon: 73.8278 },
  'port blair': { lat: 11.6234, lon: 92.7265 },
  portblair: { lat: 11.6234, lon: 92.7265 },
  munambam: { lat: 10.1800, lon: 76.1700 },
  beypore: { lat: 11.1600, lon: 75.8000 },
  kollam: { lat: 8.8800, lon: 76.5700 },
  porbandar: { lat: 21.6417, lon: 69.6293 },
  tuticorin: { lat: 8.7642, lon: 78.1348 },
  thoothukudi: { lat: 8.7642, lon: 78.1348 },
  paradip: { lat: 20.3167, lon: 86.6167 },
  digha: { lat: 21.6266, lon: 87.5074 },
};

/**
 * Calculate haversine distance between two points in kilometers.
 */
export function haversineDistance(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const R = 6371; // Earth radius in km
  const toRad = (deg: number) => (deg * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const rLat1 = toRad(lat1);
  const rLat2 = toRad(lat2);

  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(rLat1) * Math.cos(rLat2) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  const distance = R * c;
  return Math.round(distance * 100) / 100;
}

/**
 * Calculate initial bearing from point 1 to point 2 in degrees (0 - 360).
 */
export function bearing(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const toRad = (deg: number) => (deg * Math.PI) / 180;
  const toDeg = (rad: number) => (rad * 180) / Math.PI;

  const φ1 = toRad(lat1);
  const φ2 = toRad(lat2);
  const Δλ = toRad(lon2 - lon1);

  const y = Math.sin(Δλ) * Math.cos(φ2);
  const x =
    Math.cos(φ1) * Math.sin(φ2) -
    Math.sin(φ1) * Math.cos(φ2) * Math.cos(Δλ);

  const θ = Math.atan2(y, x);
  const brng = (toDeg(θ) + 360) % 360;
  return Math.round(brng * 10) / 10;
}

/**
 * Convert 0-360 degree bearing to compass cardinal direction (e.g. N, NE, E).
 */
export function getCompassDirection(bearingDeg: number): string {
  const directions = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
  const index = Math.round(((bearingDeg % 360) / 22.5)) % 16;
  return directions[index];
}

/**
 * Convert decimal degrees to DMS (degrees, minutes, seconds) string.
 * Example: 9.9312, true -> 9°55'52"N
 */
export function formatDMS(decimal: number, isLat: boolean): string {
  const dir = isLat
    ? decimal >= 0 ? 'N' : 'S'
    : decimal >= 0 ? 'E' : 'W';
  const absVal = Math.abs(decimal);
  let degrees = Math.floor(absVal);
  const minutesDec = (absVal - degrees) * 60;
  let minutes = Math.floor(minutesDec);
  let seconds = Math.round((minutesDec - minutes) * 60);

  if (seconds === 60) {
    seconds = 0;
    minutes += 1;
  }
  if (minutes === 60) {
    minutes = 0;
    degrees += 1;
  }

  return `${degrees}°${minutes}'${seconds}"${dir}`;
}

/**
 * Extract coordinates from free-form text or port names.
 * Matches common port/city names (Kochi, Veraval, Chennai, Mangalore, Mumbai, Visakhapatnam, Kanyakumari, Goa, Port Blair)
 * or decimal coordinate patterns like "9.93, 76.27" or "lat 9.93 lon 76.27".
 * Returns null if no location found.
 */
export function parseLocation(text: string): GeoCoordinate | null {
  if (!text || typeof text !== 'string') {
    return null;
  }

  const cleanText = text.trim();
  const lower = cleanText.toLowerCase();

  // 1. Check known port and city names
  for (const [name, coord] of Object.entries(COASTAL_PORTS)) {
    const regex = new RegExp(`\\b${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'i');
    if (regex.test(lower)) {
      return { lat: coord.lat, lon: coord.lon };
    }
  }

  // 2. Check DMS format in text (e.g. 9°55'52"N 76°16'12"E or 9 55 19 N, 72 13 45 E)
  const dmsRegex = /(\d{1,2})\s*[°\s]\s*(\d{1,2})['\s]\s*(\d{1,2}(?:\.\d+)?)["\s]?\s*([NSns])[,;\s]+(\d{1,3})\s*[°\s]\s*(\d{1,2})['\s]\s*(\d{1,2}(?:\.\d+)?)["\s]?\s*([EWew])/;
  const dmsMatch = cleanText.match(dmsRegex);
  if (dmsMatch) {
    const [, latD, latM, latS, latH, lonD, lonM, lonS, lonH] = dmsMatch;
    let lat = parseInt(latD, 10) + parseInt(latM, 10) / 60 + parseFloat(latS) / 3600;
    if (latH.toUpperCase() === 'S') lat = -lat;
    let lon = parseInt(lonD, 10) + parseInt(lonM, 10) / 60 + parseFloat(lonS) / 3600;
    if (lonH.toUpperCase() === 'W') lon = -lon;
    if (lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180) {
      return { lat: Math.round(lat * 10000) / 10000, lon: Math.round(lon * 10000) / 10000 };
    }
  }

  // 3. Check labeled coordinates (e.g. lat: 9.93, lon: 76.27 or latitude=9.93, longitude=76.27)
  const labeledRegex = /(?:lat(?:itude)?[:\s=]+)([+-]?\d+(?:\.\d+)?)[,\s]+(?:lon(?:gitude)?|lng)[:\s=]+([+-]?\d+(?:\.\d+)?)/i;
  const labeledMatch = cleanText.match(labeledRegex);
  if (labeledMatch) {
    const lat = parseFloat(labeledMatch[1]);
    const lon = parseFloat(labeledMatch[2]);
    if (lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180) {
      return { lat, lon };
    }
  }

  // 4. Check decimal coordinates with cardinal letters (e.g. "9.93N, 76.27E" or "9.93° N, 76.27° E")
  const cardinalRegex = /([+-]?\d+(?:\.\d+)?)\s*°?\s*([NSns])[,\s]+([+-]?\d+(?:\.\d+)?)\s*°?\s*([EWew])/;
  const cardMatch = cleanText.match(cardinalRegex);
  if (cardMatch) {
    let lat = parseFloat(cardMatch[1]);
    if (cardMatch[2].toUpperCase() === 'S') lat = -lat;
    let lon = parseFloat(cardMatch[3]);
    if (cardMatch[4].toUpperCase() === 'W') lon = -lon;
    if (lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180) {
      return { lat, lon };
    }
  }

  // 5. Check raw decimal pairs (e.g. "9.93, 76.27" or "[9.93, 76.27]")
  const pairRegex = /(?:\[|\()?\s*([+-]?\d{1,2}(?:\.\d+)?)\s*[,;\s]\s*([+-]?\d{1,3}(?:\.\d+)?)\s*(?:\]|\))?/;
  const pairMatch = cleanText.match(pairRegex);
  if (pairMatch) {
    const num1 = parseFloat(pairMatch[1]);
    const num2 = parseFloat(pairMatch[2]);
    // In India maritime context: Lat ~ 5 to 25, Lon ~ 65 to 95
    if (num1 >= -90 && num1 <= 90 && num2 >= -180 && num2 <= 180) {
      return { lat: num1, lon: num2 };
    }
  }

  return null;
}

/**
 * Calculate bounding box [southWest, northEast] from an array of [lat, lon] coordinates.
 */
export function calculateBoundingBox(
  coordinates: [number, number][]
): [[number, number], [number, number]] | null {
  if (!coordinates || coordinates.length === 0) {
    return null;
  }

  let minLat = Infinity;
  let maxLat = -Infinity;
  let minLon = Infinity;
  let maxLon = -Infinity;

  for (const [lat, lon] of coordinates) {
    if (lat < minLat) minLat = lat;
    if (lat > maxLat) maxLat = lat;
    if (lon < minLon) minLon = lon;
    if (lon > maxLon) maxLon = lon;
  }

  return [
    [minLat, minLon],
    [maxLat, maxLon],
  ];
}
