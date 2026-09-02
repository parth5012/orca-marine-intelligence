/**
 * Geo Utilities
 *
 * Owner: M-D (Frontend & Maps) � haversine/bearing helpers
 * Module: frontend/map/geo.ts
 *
 * Client-side geographic calculation utilities for map rendering.
 * Used by MapView for distance/bearing calculations and
 * by ChatPanel for location extraction.
 *
 * TODO:
 *     - [ ] Implement haversineDistance(lat1, lon1, lat2, lon2) → km
 *     - [ ] Implement bearing(lat1, lon1, lat2, lon2) → degrees
 *     - [ ] Implement formatDMS(decimal) → "9°55'52\"N"
 *     - [ ] Implement parseLocation(text) → {lat, lon} or null
 *     - [ ] Add bounding box calculation for feature collections
 */

/**
 * Calculate haversine distance between two points in kilometers.
 */
export function haversineDistance(lat1: number, lon1: number, lat2: number, lon2: number): number {
  // TODO: Implement haversine formula
  throw new Error('haversineDistance not yet implemented');
}

/**
 * Calculate initial bearing from point 1 to point 2 in degrees.
 */
export function bearing(lat1: number, lon1: number, lat2: number, lon2: number): number {
  // TODO: Implement bearing calculation
  throw new Error('bearing not yet implemented');
}

/**
 * Convert decimal degrees to DMS (degrees, minutes, seconds) string.
 */
export function formatDMS(decimal: number, isLat: boolean): string {
  // TODO: Implement DMS formatting
  throw new Error('formatDMS not yet implemented');
}

/**
 * Extract coordinates from text like "near Kochi" or "9.93, 76.27".
 * Returns null if no location found.
 */
export function parseLocation(text: string): { lat: number; lon: number } | null {
  // TODO: Implement location extraction from text
  throw new Error('parseLocation not yet implemented');
}
