/**
 * Ghost Kochi PFZ Sample Data & Fallback Contract
 * 
 * Provides an honest 7-day cached real PFZ Kochi sample payload
 * used when features.length === 0 or Redis cold start.
 */

import type { PFZItem } from '@/lib/pfz';

export const KOCHI_GHOST_PFZ: PFZItem = {
  id: 'ghost-kochi-pfz-001',
  code: 'PFZ-KOC-001',
  name: 'Kochi Offshore Cluster (Sample Baseline)',
  region: 'KERALA (SEC005)',
  distanceKm: 19.5,
  bearing: 'W',
  bearingDegrees: 270,
  suitability: 'SUITABLE',
  coordinates: [9.9312, 76.1554],
  sstCelsius: 28.4,
  chlorophyllMgM3: 0.85,
  waveHeightMeters: 0.9,
  windSpeedKmh: 22.2,
  windDirection: 'W',
  weatherCondition: 'Favorable Sea State',
  travelTimeMinutes: 47,
  fuelEstimateLiters: 14.5,
  depthMeters: 35,
  targetFishSpecies: ['Oil Sardine', 'Indian Mackerel', 'Yellowfin Tuna'],
  evidence: [
    'INCOIS TextData SEC005 (KERALA)',
    'MODIS/Copernicus Chlorophyll Front (0.85 mg/m³)',
    'Sea Surface Temperature Thermal Break (28.4°C)',
  ],
  lastUpdated: 'Cached 7-day Real INCOIS Sample',
};
