/**
 * Honest map states (ticket #195, lane M-D).
 *
 * - SafetyBadge null/undefined waves/wind -> 'unknown', never 'safe'.
 * - Drawer helpers: missing telemetry -> em-dash, unverified geofence
 *   rows -> "Not verified", zero hardcoded km claims.
 *
 * Run: bun test tests/honestMapStates.test.ts
 */
import { describe, expect, it } from 'bun:test';
import { resolveSeaStatus } from '../map/SafetyBadge';
import {
  MISSING,
  NOT_VERIFIED,
  bearingLabel,
  chlorophyllLabel,
  distanceLabel,
  geofenceRows,
  sstLabel,
  suitabilityLabel,
  waveLabel,
  windLabel,
} from '../map/drawerHonesty';

describe('SafetyBadge null handling (#195)', () => {
  it('null/undefined waves/wind -> unknown, never safe', () => {
    expect(resolveSeaStatus(null, null, 'none', undefined)).toBe('unknown');
    expect(resolveSeaStatus(undefined, undefined, 'none', undefined)).toBe('unknown');
    expect(resolveSeaStatus(0.8, null, 'none', undefined)).toBe('unknown');
    expect(resolveSeaStatus(null, 12, 'none', undefined)).toBe('unknown');
    expect(resolveSeaStatus(NaN, 12, 'none', undefined)).toBe('unknown');
    // Even an explicit green badge cannot make missing data SAFE.
    expect(resolveSeaStatus(undefined, undefined, 'none', 'green')).toBe('unknown');
  });

  it('empty-string telemetry -> unknown, never coerced to 0/SAFE', () => {
    expect(resolveSeaStatus('', '', 'none', undefined)).toBe('unknown');
    expect(resolveSeaStatus('', 12, 'none', undefined)).toBe('unknown');
    expect(resolveSeaStatus(0.8, '', 'none', undefined)).toBe('unknown');
    // Empty strings cannot be rescued by an explicit green badge.
    expect(resolveSeaStatus('', '', 'none', 'green')).toBe('unknown');
  });

  it('explicit danger still wins over missing data', () => {
    expect(resolveSeaStatus(null, null, 'cyclone', undefined)).toBe('danger');
    expect(resolveSeaStatus(null, null, 'danger', undefined)).toBe('danger');
    expect(resolveSeaStatus(null, null, 'none', 'red')).toBe('danger');
    // A breaching finite measurement still trips danger.
    expect(resolveSeaStatus(3.0, null, 'none', undefined)).toBe('danger');
  });

  it('live finite values still classify safe/caution/danger', () => {
    expect(resolveSeaStatus(0.8, 12, 'none', undefined)).toBe('safe');
    expect(resolveSeaStatus(1.8, 12, 'none', undefined)).toBe('caution');
    expect(resolveSeaStatus(0.8, 22, 'none', undefined)).toBe('caution');
    expect(resolveSeaStatus(3.0, 12, 'none', undefined)).toBe('danger');
    expect(resolveSeaStatus(0.8, 35, 'none', undefined)).toBe('danger');
  });
});

describe('Drawer missing-props honesty (#195)', () => {
  it('suitability/distance/SST/chl/waves/wind show em-dash when missing', () => {
    expect(suitabilityLabel({})).toBe(MISSING);
    expect(distanceLabel({})).toBe(MISSING);
    expect(sstLabel({})).toBe(MISSING);
    expect(chlorophyllLabel({})).toBe(MISSING);
    expect(waveLabel({})).toBe(MISSING);
    expect(windLabel({})).toBe(MISSING);
    expect(bearingLabel({})).toBe(MISSING);
    expect(MISSING).toBe('—');
  });

  it('renders real feature values when present (no defaults)', () => {
    const props = {
      suitability: 'HIGH',
      distance_km: 25,
      bearing: 220,
      sst_c: 28.4,
      chl: 0.8,
      wave_m: 1.1,
      wind_kt: 12,
    };
    expect(suitabilityLabel(props)).toBe('HIGH');
    expect(distanceLabel(props)).toBe('25 km');
    expect(bearingLabel(props)).toBe('220°');
    expect(sstLabel(props)).toBe('28.4°C');
    expect(chlorophyllLabel(props)).toBe('0.8 mg/m³');
    expect(waveLabel(props)).toBe('1.1m');
    expect(windLabel(props)).toBe('12kt');
  });

  it('geofence rows read Not verified when props are null', () => {
    const rows = geofenceRows({});
    expect(rows).toHaveLength(3);
    for (const row of rows) {
      expect(row.detail).toBe(NOT_VERIFIED);
      expect(row.verified).toBe(false);
    }
    // Zero hardcoded km claims in the missing-data rendering.
    const joined = rows.map((r) => `${r.label}: ${r.detail}`).join(' | ');
    expect(joined).not.toMatch(/\d+\s?km/);
    expect(joined).not.toContain('>');
  });

  it('geofence rows render live props without invented distances', () => {
    const rows = geofenceRows({ inside_eez: true, inside_mpa: false, imbl_distance_km: 45 });
    expect(rows[0].detail).toBe('Inside India EEZ');
    expect(rows[1].detail).toBe('Clear');
    expect(rows[2].detail).toBe('45 km from IMBL');
    const mpaRows = geofenceRows({ inside_mpa: true, mpa_name: 'Gulf of Mannar' });
    expect(mpaRows[1].detail).toContain('Gulf of Mannar');
  });

  it('inside_eez:false reads Outside EEZ and verifies without km claims', () => {
    const rows = geofenceRows({ inside_eez: false, inside_mpa: false });
    expect(rows[0].detail).toBe('Outside EEZ');
    expect(rows[0].verified).toBe(true);
    const joined = rows.map((r) => `${r.label}: ${r.detail}`).join(' | ');
    expect(joined).not.toMatch(/\d+\s?km/);
  });
});
