/**
 * Advisory Freshness & Caution Floor
 *
 * Owner: M-D (Frontend & Maps)
 * Module: frontend/lib/advisoryFreshness.ts
 */

export const PFZ_STALE_FALLBACK_MS = 86_400_000; // 24h
export const WEATHER_STALE_MS = 10_800_000;      // 3h

export type AdvisoryTier = 'safe' | 'caution' | 'danger' | 'unknown';

export interface FreshnessInput {
  validUntil?: string | null;  // PFZ payload `valid_until`
  capturedAt?: string | null;  // when the PFZ payload was received
  weatherAt?: string | null;   // when wave/wind was last measured
  now?: number;                // epoch ms, defaults to Date.now()
}

export type FreshnessReason = 'fresh' | 'pfz_expired' | 'pfz_no_validity_window' | 'weather_stale';

export interface FreshnessResult {
  stale: boolean;
  pfzStale: boolean;
  weatherStale: boolean;
  ageMs: number | null;
  ageLabel: string | null;
  reasons: FreshnessReason[];
}

function parseTimestamp(value?: string | null): number | null {
  if (value == null) return null;
  const str = String(value).trim();
  if (!str) return null;
  const parsed = Date.parse(str);
  return Number.isNaN(parsed) ? null : parsed;
}

export function formatAge(ms: number): string {
  const clamped = Math.max(0, ms);
  if (clamped < 60_000) {
    return 'just now';
  }
  if (clamped < 3_600_000) {
    const mins = Math.floor(clamped / 60_000);
    return `${mins}m old`;
  }
  if (clamped < 86_400_000) {
    const hours = Math.floor(clamped / 3_600_000);
    return `${hours}h old`;
  }
  const days = Math.floor(clamped / 86_400_000);
  return `${days}d old`;
}

export function applyCautionFloor(tier: AdvisoryTier): AdvisoryTier {
  if (tier === 'safe') {
    return 'caution';
  }
  return tier;
}

export function evaluateFreshness(input: FreshnessInput): FreshnessResult {
  const now = typeof input.now === 'number' && Number.isFinite(input.now)
    ? input.now
    : Date.now();

  const validUntilMs = parseTimestamp(input.validUntil);
  const capturedAtMs = parseTimestamp(input.capturedAt);
  const weatherAtMs = parseTimestamp(input.weatherAt);

  let pfzStale = false;
  let pfzReason: FreshnessReason | null = null;

  if (validUntilMs != null) {
    if (now > validUntilMs) {
      pfzStale = true;
      pfzReason = 'pfz_expired';
    }
  } else if (capturedAtMs != null) {
    if (now - capturedAtMs > PFZ_STALE_FALLBACK_MS) {
      pfzStale = true;
      pfzReason = 'pfz_no_validity_window';
    }
  } else {
    pfzStale = true;
    pfzReason = 'pfz_no_validity_window';
  }

  let weatherStale = false;
  let weatherReason: FreshnessReason | null = null;

  if (weatherAtMs != null && now - weatherAtMs > WEATHER_STALE_MS) {
    weatherStale = true;
    weatherReason = 'weather_stale';
  }

  const stale = pfzStale || weatherStale;

  const reasons: FreshnessReason[] = [];
  if (!stale) {
    reasons.push('fresh');
  } else {
    if (pfzStale && pfzReason) {
      reasons.push(pfzReason);
    }
    if (weatherStale && weatherReason) {
      reasons.push(weatherReason);
    }
  }

  let ageMs: number | null = null;
  if (capturedAtMs != null) {
    ageMs = Math.max(0, now - capturedAtMs);
  } else if (validUntilMs != null) {
    ageMs = Math.max(0, now - validUntilMs);
  }

  const ageLabel = ageMs != null ? formatAge(ageMs) : null;

  return {
    stale,
    pfzStale,
    weatherStale,
    ageMs,
    ageLabel,
    reasons,
  };
}
