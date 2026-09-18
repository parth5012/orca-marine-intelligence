/**
 * Officer ports registry (frontend mirror).
 *
 * Owner: M-C shell (T3 #173)
 * Module: frontend/officer/ports.ts
 *
 * Static mirror of repo-root data/ports.json (T1 #171, 12 ports).
 * Kept as an inlined copy so the Next.js build never imports outside
 * frontend/. Re-sync with data/ports.json if T1 changes sectors.
 */

export interface OfficerPort {
  id: string;
  name: string;
  state: string;
  lat: number;
  lon: number;
  incois_sector: string;
  sector_name: string;
  language: string;
  bbox_delta: number;
}

export const DEFAULT_PORT_ID = 'kochi';
export const INDIA_CENTER: [number, number] = [21, 78];
export const PORT_ZOOM = 9;
export const WATCH_ZOOM = 5;

export const PORTS: OfficerPort[] = [
  { id: 'kochi', name: 'Kochi', state: 'Kerala', lat: 9.93, lon: 76.26, incois_sector: 'SEC005', sector_name: 'KERALA', language: 'ml', bbox_delta: 1.0 },
  { id: 'munambam', name: 'Munambam', state: 'Kerala', lat: 10.17, lon: 76.17, incois_sector: 'SEC005', sector_name: 'KERALA', language: 'ml', bbox_delta: 1.0 },
  { id: 'vizhinjam', name: 'Vizhinjam', state: 'Kerala', lat: 8.38, lon: 76.99, incois_sector: 'SEC005', sector_name: 'KERALA', language: 'ml', bbox_delta: 1.0 },
  { id: 'chennai', name: 'Chennai', state: 'Tamil Nadu', lat: 13.1, lon: 80.29, incois_sector: 'SEC007', sector_name: 'TAMILNADU_EAST', language: 'ta', bbox_delta: 1.0 },
  { id: 'cuddalore', name: 'Cuddalore', state: 'Tamil Nadu', lat: 11.75, lon: 79.77, incois_sector: 'SEC007', sector_name: 'TAMILNADU_EAST', language: 'ta', bbox_delta: 1.0 },
  { id: 'visakhapatnam', name: 'Visakhapatnam', state: 'Andhra Pradesh', lat: 17.69, lon: 83.28, incois_sector: 'SEC008', sector_name: 'ANDHRA', language: 'te', bbox_delta: 1.0 },
  { id: 'paradip', name: 'Paradip', state: 'Odisha', lat: 20.26, lon: 86.68, incois_sector: 'SEC008', sector_name: 'ANDHRA', language: 'or', bbox_delta: 1.0 },
  { id: 'digha', name: 'Digha', state: 'West Bengal', lat: 21.62, lon: 87.5, incois_sector: 'SEC008', sector_name: 'ANDHRA', language: 'bn', bbox_delta: 1.0 },
  { id: 'porbandar', name: 'Porbandar', state: 'Gujarat', lat: 21.64, lon: 69.6, incois_sector: 'SEC002', sector_name: 'MAHARASHTRA', language: 'gu', bbox_delta: 1.0 },
  { id: 'okha', name: 'Okha', state: 'Gujarat', lat: 22.47, lon: 69.07, incois_sector: 'SEC002', sector_name: 'MAHARASHTRA', language: 'gu', bbox_delta: 1.0 },
  { id: 'mangalore', name: 'Mangalore', state: 'Karnataka', lat: 12.91, lon: 74.8, incois_sector: 'SEC004', sector_name: 'KARNATAKA', language: 'kn', bbox_delta: 1.0 },
  { id: 'tuticorin', name: 'Tuticorin', state: 'Tamil Nadu', lat: 8.76, lon: 78.2, incois_sector: 'SEC007', sector_name: 'TAMILNADU_EAST', language: 'ta', bbox_delta: 1.0 },
];

export function getPortById(id: string | null): OfficerPort {
  return PORTS.find((p) => p.id === id) ?? PORTS[0];
}

export function groupPortsByState(): { state: string; ports: OfficerPort[] }[] {
  const order: string[] = [];
  const map = new Map<string, OfficerPort[]>();
  for (const p of PORTS) {
    if (!map.has(p.state)) { map.set(p.state, []); order.push(p.state); }
    map.get(p.state)!.push(p);
  }
  return order.map((state) => ({ state, ports: map.get(state)! }));
}
