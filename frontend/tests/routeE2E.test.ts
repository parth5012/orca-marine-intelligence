import { describe, expect, it } from 'bun:test';

const BASE_URL = 'http://localhost:3000';

describe('PFZ Routing End-to-End API & Integration Verification (T9 #168)', () => {
  it('E2E-1: Live route calculation from Kochi GPS to offshore PFZ', async () => {
    const res = await fetch(
      `${BASE_URL}/api/route?olat=9.9312&olon=76.2673&dlat=9.9312&dlon=75.8500&wave_height_m=1.2&wind_speed_kt=14`
    );
    expect(res.status).toBe(200);
    const data = await res.json();
    expect(data.status).toBe('ok');
    expect(data.distance_km).toBeGreaterThan(40);
    expect(data.distance_nm).toBeGreaterThan(20);
    expect(data.bearing).toBeDefined();
    expect(data.eta_min).toBeGreaterThan(0);
    expect(data.safety_label).toBe('SAFE');
    expect(data.waypoints.length).toBeGreaterThanOrEqual(2);
    expect(data.source).toBe('backend_live');
    expect(data.cost_breakdown).toBeDefined();
    expect(data.cost_breakdown.wave_penalty).toBeCloseTo(0.6, 1);
  });

  it('E2E-2: Route crossing Vembanad MPA triggers safe detour and warning', async () => {
    const res = await fetch(
      `${BASE_URL}/api/route?olat=9.5500&olon=76.4500&dlat=9.7500&dlon=76.4500`
    );
    expect(res.status).toBe(200);
    const data = await res.json();
    expect(data.status).toBe('ok');
    expect(data.waypoints.length).toBeGreaterThan(2);
    expect(data.safety_label).toBe('CAUTION');
    expect(data.hazards.length).toBeGreaterThan(0);
    expect(data.hazards.some((h: string) => h.includes('Marine Protected Area'))).toBe(true);
    expect(data.cost_breakdown.forbidden_penalty).toBe(1000);
  });

  it('E2E-3: Route near IMBL (<2km) triggers border proximity warning', async () => {
    const res = await fetch(
      `${BASE_URL}/api/route?olat=9.0950&olon=79.5250&dlat=9.1050&dlon=79.5400`
    );
    expect(res.status).toBe(200);
    const data = await res.json();
    expect(data.status).toBe('ok');
    expect(data.hazards.some((h: string) => h.includes('International Maritime Boundary Line'))).toBe(true);
    expect(data.safety_label).toBe('CAUTION');
  });

  it('E2E-4: Frontend home page renders with responsive viewport meta', async () => {
    const res = await fetch(`${BASE_URL}/`);
    expect(res.status).toBe(200);
    const html = await res.text();
    expect(html).toContain('viewport');
    expect(html).toContain('width=device-width');
  });

  it('E2E-5: Frontend map page renders successfully', async () => {
    const res = await fetch(`${BASE_URL}/map`);
    expect(res.status).toBe(200);
    const html = await res.text();
    expect(html).toContain('ORCA');
  });
});
