/**
 * SafetyBadge Component
 *
 * Owner: M-D (Frontend & Maps) - green/amber/red safety badge
 * Module: frontend/map/SafetyBadge.tsx
 *
 * Visual safety indicator showing sea conditions at a glance.
 * Displays wave height, wind speed, danger status with
 * color-coded badges (green/amber/red).
 *
 * Honesty rule (ticket #195): missing wave/wind telemetry reads
 * UNKNOWN (amber), never SEA SAFE. Only finite live measurements
 * can render SAFE. Explicit danger signals (red/cyclone/danger)
 * still win over UNKNOWN.
 */

'use client';

import React from 'react';

export type SeaStatus = 'safe' | 'caution' | 'danger' | 'unknown';

export interface SafetyBadgeProps {
  waves?: number | string | null;
  wind?: number | string | null;
  danger?: 'none' | 'caution' | 'danger' | 'eez' | 'mpa' | 'cyclone' | string;
  badge?: 'green' | 'amber' | 'red' | string;
  language?: string;
  compact?: boolean;
}

function toFinite(v: unknown): number | null {
  if (v == null || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

/**
 * Pure sea-status resolver (ticket #195, unit-tested).
 * null/undefined/NaN waves or wind -> 'unknown' unless an explicit
 * danger signal (red badge, danger/cyclone flag, or a breaching
 * finite measurement) forces 'danger'.
 */
export function resolveSeaStatus(
  waves: unknown,
  wind: unknown,
  danger?: string,
  badge?: string
): SeaStatus {
  const dangerStr = String(danger ?? 'none').toLowerCase();
  const wv = toFinite(waves);
  const wn = toFinite(wind);

  const isDanger =
    badge === 'red' ||
    dangerStr === 'danger' ||
    dangerStr === 'cyclone' ||
    (wv != null && wv >= 2.5) ||
    (wn != null && wn >= 30);
  if (isDanger) return 'danger';

  // Fail open to caution: no measurement, no verdict.
  if (wv == null || wn == null) return 'unknown';

  const isCaution =
    badge === 'amber' ||
    dangerStr === 'caution' ||
    dangerStr === 'eez' ||
    dangerStr === 'mpa' ||
    wv >= 1.5 ||
    wn >= 20;
  if (isCaution) return 'caution';

  return 'safe';
}

export default function SafetyBadge({
  waves,
  wind,
  danger = 'none',
  badge,
  language = 'en',
  compact = false,
}: SafetyBadgeProps) {
  void language;
  const statusType = resolveSeaStatus(waves, wind, danger, badge);
  const wv = toFinite(waves);
  const wn = toFinite(wind);
  const waveDisplay = wv != null ? `${wv}m` : '—';
  const windDisplay = wn != null ? `${wn} kts` : '—';
  const dangerStr = String(danger || 'none').toLowerCase();

  const statusMessage =
    statusType === 'danger'
      ? dangerStr === 'cyclone'
        ? 'CYCLONE ALERT'
        : 'DO NOT SAIL'
      : statusType === 'caution'
      ? 'CAUTION'
      : statusType === 'unknown'
      ? 'UNKNOWN'
      : 'SEA SAFE';

  // Unknown renders amber (fail-open to caution, never green).
  const amber = statusType === 'caution' || statusType === 'unknown';

  const measurements = !compact
    ? ` Waves: ${waveDisplay}, Wind: ${windDisplay}`
    : '';

  return (
    <div
      data-testid="safety-badge"
      data-status={statusType}
      role="status"
      aria-label={`Sea status: ${statusMessage}.${measurements}`}
      className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs sm:text-sm font-medium transition-all shadow-sm ${
        statusType === 'danger'
          ? 'bg-red-950/90 border-red-500/80 text-red-200 animate-pulse'
          : amber
          ? 'bg-amber-950/80 border-amber-500/70 text-amber-200'
          : 'bg-emerald-950/80 border-emerald-500/70 text-emerald-200'
      }`}
      title={`Sea Status: ${statusType.toUpperCase()} | Waves: ${waveDisplay} | Wind: ${windDisplay}`}
    >
      <span className="flex h-2 w-2 relative">
        <span
          className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${
            statusType === 'danger'
              ? 'bg-red-400'
              : amber
              ? 'bg-amber-400'
              : 'bg-emerald-400'
          }`}
        />
        <span
          className={`relative inline-flex rounded-full h-2 w-2 ${
            statusType === 'danger'
              ? 'bg-red-500'
              : amber
              ? 'bg-amber-500'
              : 'bg-emerald-500'
          }`}
        />
      </span>

      <span className="font-bold uppercase tracking-wider text-xs">
        {statusType === 'danger'
          ? dangerStr === 'cyclone'
            ? 'CYCLONE ALERT'
            : 'DO NOT SAIL'
          : statusType === 'caution'
          ? 'CAUTION'
          : statusType === 'unknown'
          ? 'UNKNOWN'
          : 'SEA SAFE'}
      </span>

      {!compact && (
        <span className="hidden md:inline text-[11px] opacity-80 font-mono border-l border-current/30 pl-2">
          🌊 {waveDisplay} • 💨 {windDisplay}
        </span>
      )}
    </div>
  );
}
