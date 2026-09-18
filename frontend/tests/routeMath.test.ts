import { describe, expect, it } from 'bun:test';
import {
  interpolateGreatCircle,
  segmentCrossesPolygon,
  buildSafeRoute,
  computeLiveRoute,
  haversineKm,
  polylineToPolylineDistanceKm,
  pointToPolylineDistanceKm,
  type PFZItem,
} from '../lib/pfz';
import { MPA_GEOJSON, IMBL_COORDINATES } from '../map/boundaries';

const mockPFZ: PFZItem = {
  id: 'pfz-kc-01',
  name: 'Kochi Offshore Shelf',
  code: 'KC-01',
  region: 'Kerala',
  distanceKm: 35.5,
  bearing: 'WNW 285°',
  bearingDegrees: 285,
  suitability: 'SUITABLE',
  coordinates: [9.9312, 75.8500], // [lat, lon]
  sstCelsius: 28.5,
  chlorophyllMgM3: 0.85,
  waveHeightMeters: 1.2,
  windSpeedKmh: 18,
  windDirection: 'NW',
  weatherCondition: 'Fair',
  travelTimeMinutes: 85,
  fuelEstimateLiters: 42,
  depthMeters: 45,
  targetFishSpecies: ['Tuna', 'Mackerel'],
  evidence: ['Thermal front', 'Chlorophyll gradient'],
  lastUpdated: new Date().toISOString(),
};

describe('Route Math Library (T5 #164)', () => {
  it('haversine parity: calculates distance accurately', () => {
    // Kochi (9.9312, 76.2673) to KC-01 (9.9312, 75.8500) ~ 45.7 km
    const dist = haversineKm(9.9312, 76.2673, 9.9312, 75.8500);
    expect(dist).toBeGreaterThan(40);
    expect(dist).toBeLessThan(50);
  });

  it('interpolateGreatCircle generates intermediate points', () => {
    const start: [number, number] = [9.9312, 76.2673];
    const end: [number, number] = [9.9312, 75.8500];
    const points = interpolateGreatCircle(start, end, 5);
    expect(points.length).toBe(5);
    expect(points[0][0]).toBeCloseTo(start[0], 2);
    expect(points[0][1]).toBeCloseTo(start[1], 2);
    expect(points[4][0]).toBeCloseTo(end[0], 2);
    expect(points[4][1]).toBeCloseTo(end[1], 2);
  });

  it('segmentCrossesPolygon detects polygon intersection', () => {
    // Vembanad polygon bounds: lat 9.6 to 9.7, lon 76.4 to 76.5
    const vembanadCoords: [number, number][] = [
      [9.6, 76.4],
      [9.6, 76.5],
      [9.7, 76.5],
      [9.7, 76.4],
      [9.6, 76.4],
    ];

    // Segment cutting through: (9.65, 76.3) to (9.65, 76.6)
    const cutsThrough = segmentCrossesPolygon([9.65, 76.3], [9.65, 76.6], vembanadCoords);
    expect(cutsThrough).toBe(true);

    // Segment completely outside: (9.8, 76.3) to (9.8, 76.6)
    const outside = segmentCrossesPolygon([9.8, 76.3], [9.8, 76.6], vembanadCoords);
    expect(outside).toBe(false);
  });

  it('buildSafeRoute generates detour and warning when crossing MPA', () => {
    // Origin south of Vembanad, destination north of Vembanad so line cuts through
    const origin = { lat: 9.55, lon: 76.45, name: 'South Port' };
    const mpaTarget: PFZItem = {
      ...mockPFZ,
      coordinates: [9.75, 76.45],
    };

    const route = buildSafeRoute(origin, mpaTarget, {
      mpa: MPA_GEOJSON,
      imblBufferKm: 2.0,
      seaLevel: 'safe',
    });

    expect(route).toBeDefined();
    expect(route.waypoints.length).toBeGreaterThan(2);
    expect(route.detourOccurred).toBe(true);
    expect(route.hazardWarnings.length).toBeGreaterThan(0);
    expect(route.hazardWarnings.some(w => w.includes('Marine Protected Area'))).toBe(true);

    const ring = MPA_GEOJSON.features[0].geometry.coordinates[0];
    const poly: [number, number][] = ring.map((pt: [number, number]) => [pt[1], pt[0]]);
    for (let i = 0; i < route.waypoints.length - 1; i++) {
      expect(segmentCrossesPolygon(route.waypoints[i], route.waypoints[i + 1], poly)).toBe(false);
    }
  });

  it('buildSafeRoute flags IMBL proximity warning within 2km buffer', () => {
    // Palk Strait near IMBL: Point 7 is [9.1000, 79.5333]
    const origin = { lat: 9.0950, lon: 79.5250, name: 'Dhanushkodi' };
    const imblTarget: PFZItem = {
      ...mockPFZ,
      coordinates: [9.1050, 79.5400],
    };

    const route = buildSafeRoute(origin, imblTarget, {
      mpa: MPA_GEOJSON,
      imblBufferKm: 2.0,
      seaLevel: 'safe',
    });

    expect(route.hazardWarnings.some(w => w.includes('International Maritime Boundary Line'))).toBe(true);
  });

  it('polylineToPolylineDistanceKm is zero when a leg crosses the border line', () => {
    // Vertical route leg crosses a horizontal border segment; both endpoints
    // sit ~5.5 km from the border, but the intervening leg intersects it.
    const route: [number, number][] = [[8.95, 79.55], [9.05, 79.55]];
    const border: [number, number][] = [[9.0, 79.5], [9.0, 79.6]];
    for (const pt of route) {
      expect(pointToPolylineDistanceKm(pt, border)).toBeGreaterThan(2.0);
    }
    expect(polylineToPolylineDistanceKm(route, border)).toBe(0);
  });

  it('buildSafeRoute keeps computeLiveRoute as fallback when no obstacles', () => {
    const origin = { lat: 9.9312, lon: 76.2673, name: 'Kochi Port' };
    const route = buildSafeRoute(origin, mockPFZ);
    expect(route.totalDistanceKm).toBeGreaterThan(0);
    expect(route.safetyLabel).toBe('SAFE');
    expect(route.waypoints.length).toBeGreaterThanOrEqual(2);
  });
});
