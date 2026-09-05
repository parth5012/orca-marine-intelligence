/**
 * Maritime Boundaries Dataset (EEZ, MPA, IMBL)
 *
 * Owner: M-D (Frontend & Maps)
 * Module: frontend/map/boundaries.ts
 *
 * Provides sovereign boundary geometry for client-side rendering:
 * 1. Indian Exclusive Economic Zone (EEZ) Polygons (MarineRegions)
 * 2. Marine Protected Areas (MPA) Danger Zones (WDPA)
 * 3. International Maritime Boundary Line (IMBL) Waypoints (India-Sri Lanka Bilateral Accords)
 */

export interface BoundaryFeatureProperties {
  boundary_name?: string;
  boundary_type?: string;
  country?: string;
  mpa_name?: string;
  restriction_level?: string;
  state?: string;
  source?: string;
}

export interface GeoJSONFeature {
  type: 'Feature';
  geometry: {
    type: 'Polygon' | 'Point' | 'LineString';
    coordinates: any;
  };
  properties: BoundaryFeatureProperties;
}

export interface GeoJSONFeatureCollection {
  type: 'FeatureCollection';
  features: GeoJSONFeature[];
  metadata?: Record<string, any>;
}

/**
 * Indian EEZ Boundary Polygons (West and East coasts)
 */
export const EEZ_GEOJSON: GeoJSONFeatureCollection = {
  type: 'FeatureCollection',
  features: [
    {
      type: 'Feature',
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [68.0, 5.0],
            [73.0, 5.0],
            [76.0, 7.0],
            [77.5, 9.0],
            [76.5, 12.0],
            [74.5, 18.0],
            [72.5, 22.0],
            [68.0, 22.0],
            [68.0, 5.0],
          ],
        ],
      },
      properties: {
        boundary_name: 'India EEZ West Coast',
        boundary_type: 'EEZ',
        country: 'India',
        source: 'mock_maritime_boundaries',
      },
    },
    {
      type: 'Feature',
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [79.5, 7.0],
            [85.0, 7.0],
            [85.0, 21.0],
            [81.5, 21.0],
            [80.0, 15.0],
            [79.8, 10.0],
            [79.5, 7.0],
          ],
        ],
      },
      properties: {
        boundary_name: 'India EEZ East Coast',
        boundary_type: 'EEZ',
        country: 'India',
        source: 'mock_maritime_boundaries',
      },
    },
  ],
};

/**
 * Marine Protected Areas (MPA) - Restricted / Danger zones
 */
export const MPA_GEOJSON: GeoJSONFeatureCollection = {
  type: 'FeatureCollection',
  features: [
    {
      type: 'Feature',
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [76.4, 9.6],
            [76.5, 9.6],
            [76.5, 9.7],
            [76.4, 9.7],
            [76.4, 9.6],
          ],
        ],
      },
      properties: {
        mpa_name: 'Vembanad Marine Sanctuary',
        restriction_level: 'no-take',
        state: 'Kerala',
        source: 'mock_wdpa',
      },
    },
    {
      type: 'Feature',
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [78.8, 8.8],
            [79.2, 8.8],
            [79.2, 9.2],
            [78.8, 9.2],
            [78.8, 8.8],
          ],
        ],
      },
      properties: {
        mpa_name: 'Gulf of Mannar Biosphere Reserve',
        restriction_level: 'no-take',
        state: 'Tamil Nadu',
        source: 'mock_wdpa',
      },
    },
  ],
};

/**
 * Canonical International Maritime Boundary Line (IMBL) between India and Sri Lanka.
 * Represented as [latitude, longitude] pairs.
 */
export const IMBL_COORDINATES: [number, number][] = [
  [10.0833, 80.0500], // Palk Strait Point 1
  [10.0300, 79.9800], // Point 2
  [9.9500, 79.8800],  // Point 3
  [9.7500, 79.6667],  // Point 4
  [9.6667, 79.5833],  // Point 5
  [9.3667, 79.5333],  // Point 6
  [9.1000, 79.5333],  // Point 7 (Adam's Bridge / Dhanushkodi)
  [9.0000, 79.5167],  // Point 8
  [8.8667, 79.4167],  // Point 9
  [8.4000, 79.0500],  // Point 10
  [8.0000, 78.5000],  // Point 11
  [7.0000, 77.0000],  // Point 12 (Trijunction)
];
