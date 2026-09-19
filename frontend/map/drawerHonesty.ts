/**
 * Drawer honesty helpers (ticket #195).
 *
 * Owner: M-D (Frontend & Maps)
 * Module: frontend/map/drawerHonesty.ts
 *
 * Pure, unit-tested formatters for the ExploreMap inspector drawer.
 * Missing telemetry renders an em-dash, unverified geofence rows
 * render "Not verified". No hardcoded distances, suitabilities,
 * or sea-state values live here — every claim comes from feature
 * props or reads as missing.
 */

export const MISSING = '—';
export const NOT_VERIFIED = 'Not verified';

/** Finite number or null when the value is missing/NaN. */
export function toFiniteNumber(v: unknown): number | null {
  if (v == null || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

/** First finite number across candidate keys, else null. */
function pickFinite(props: Record<string, any>, keys: string[]): number | null {
  for (const k of keys) {
    const n = toFiniteNumber(props?.[k]);
    if (n != null) return n;
  }
  return null;
}

/** First non-blank string across candidate keys, else null. */
function pickText(props: Record<string, any>, keys: string[]): string | null {
  for (const k of keys) {
    const v = props?.[k];
    if (v == null) continue;
    const s = String(v).trim();
    if (s.length > 0) return s;
  }
  return null;
}

export function distanceLabel(props: Record<string, any>): string {
  const n = pickFinite(props, ['distance', 'distance_km', 'distance_from_user_km']);
  return n == null ? MISSING : `${n} km`;
}

export function bearingLabel(props: Record<string, any>): string {
  const raw = props?.bearing ?? props?.dir ?? props?.bearingDegrees;
  if (raw == null || String(raw).trim() === '') return MISSING;
  if (typeof raw === 'number' && Number.isFinite(raw)) return `${raw}°`;
  const s = String(raw).trim();
  if (s.includes('°')) return s;
  return /^\d+(\.\d+)?$/.test(s) ? `${s}°` : s;
}

export function sstLabel(props: Record<string, any>): string {
  const n = pickFinite(props, ['sst', 'sst_c', 'temperature_c']);
  return n == null ? MISSING : `${n}°C`;
}

export function chlorophyllLabel(props: Record<string, any>): string {
  const n = pickFinite(props, ['chlorophyll', 'chl', 'chl_mg_m3']);
  return n == null ? MISSING : `${n} mg/m³`;
}

export function waveLabel(props: Record<string, any>): string {
  const n = pickFinite(props, ['wave_m', 'wave_height_m']);
  return n == null ? MISSING : `${n}m`;
}

export function windLabel(props: Record<string, any>): string {
  const n = pickFinite(props, ['wind_kt', 'wind_speed_kt', 'wind_kts']);
  return n == null ? MISSING : `${n}kt`;
}

export function suitabilityLabel(props: Record<string, any>): string {
  return pickText(props, ['suitability', 'status', 'safety']) ?? MISSING;
}

export interface GeofenceRow {
  key: 'eez' | 'mpa' | 'imbl';
  label: string;
  detail: string;
  verified: boolean;
  tone: 'sky' | 'emerald' | 'red' | 'orange' | 'gray';
}

/**
 * EEZ / MPA / IMBL rows strictly from feature props
 * (inside_eez / inside_mpa / imbl_distance_km). Null props yield
 * "Not verified" — never a hardcoded km claim.
 */
export function geofenceRows(props: Record<string, any>): GeofenceRow[] {
  const eez = props?.inside_eez;
  const mpa = props?.inside_mpa;
  const imblKm = pickFinite(props, ['imbl_distance_km', 'imbl_km']);
  const mpaName = pickText(props, ['mpa_name']);

  return [
    {
      key: 'eez',
      label: 'EEZ',
      detail:
        eez === true
          ? 'Inside India EEZ'
          : eez === false
          ? 'Outside EEZ'
          : NOT_VERIFIED,
      verified: typeof eez === 'boolean',
      tone: eez === true ? 'sky' : eez === false ? 'red' : 'gray',
    },
    {
      key: 'mpa',
      label: 'MPA',
      detail:
        mpa === true
          ? mpaName
            ? `Inside ${mpaName} — no-take`
            : 'Inside MPA — no-take'
          : mpa === false
          ? 'Clear'
          : NOT_VERIFIED,
      verified: typeof mpa === 'boolean',
      tone: mpa === true ? 'red' : mpa === false ? 'emerald' : 'gray',
    },
    {
      key: 'imbl',
      label: 'IMBL',
      detail: imblKm == null ? NOT_VERIFIED : `${imblKm} km from IMBL`,
      verified: imblKm != null,
      tone: imblKm == null ? 'gray' : 'orange',
    },
  ];
}
