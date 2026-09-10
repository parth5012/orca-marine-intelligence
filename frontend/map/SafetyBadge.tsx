/**
 * SafetyBadge Component
 *
 * Owner: M-D (Frontend & Maps) - green/amber/red safety badge
 * Module: frontend/map/SafetyBadge.tsx
 *
 * Visual safety indicator showing sea conditions at a glance.
 * Displays wave height, wind speed, danger status with
 * color-coded badges (green/amber/red).
 */

'use client';

import React from 'react';

export interface SafetyBadgeProps {
  waves?: number | null;
  wind?: number | null;
  danger?: 'none' | 'caution' | 'danger' | 'eez' | 'mpa' | 'cyclone' | string;
  badge?: 'green' | 'amber' | 'red' | string;
  language?: string;
  compact?: boolean;
}

export default function SafetyBadge({
  waves = 0,
  wind = 0,
  danger = 'none',
  badge,
  language = 'en',
  compact = false,
}: SafetyBadgeProps) {
  const safeWaves = waves ?? 0.8;
  const safeWind = wind ?? 10;
  const dangerStr = String(danger || 'none').toLowerCase();

  const isDanger =
    badge === 'red' ||
    dangerStr === 'danger' ||
    dangerStr === 'cyclone' ||
    safeWaves >= 2.5 ||
    safeWind >= 30;

  const isCaution =
    !isDanger &&
    (badge === 'amber' ||
      dangerStr === 'caution' ||
      dangerStr === 'eez' ||
      dangerStr === 'mpa' ||
      safeWaves >= 1.5 ||
      safeWind >= 20);

  const statusType: 'safe' | 'caution' | 'danger' = isDanger
    ? 'danger'
    : isCaution
    ? 'caution'
    : 'safe';

  return (
    <div
      data-testid="safety-badge"
      data-status={statusType}
      role="status"
      aria-label={`Sea status: ${statusType}`}
      className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs sm:text-sm font-medium transition-all shadow-sm ${
        statusType === 'danger'
          ? 'bg-red-950/90 border-red-500/80 text-red-200 animate-pulse'
          : statusType === 'caution'
          ? 'bg-amber-950/80 border-amber-500/70 text-amber-200'
          : 'bg-emerald-950/80 border-emerald-500/70 text-emerald-200'
      }`}
      title={`Sea Status: ${statusType.toUpperCase()} | Waves: ${safeWaves}m | Wind: ${safeWind} kts`}
    >
      <span className="flex h-2 w-2 relative">
        <span
          className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${
            statusType === 'danger'
              ? 'bg-red-400'
              : statusType === 'caution'
              ? 'bg-amber-400'
              : 'bg-emerald-400'
          }`}
        />
        <span
          className={`relative inline-flex rounded-full h-2 w-2 ${
            statusType === 'danger'
              ? 'bg-red-500'
              : statusType === 'caution'
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
          : 'SEA SAFE'}
      </span>

      {!compact && (
        <span className="hidden md:inline text-[11px] opacity-80 font-mono border-l border-current/30 pl-2">
          🌊 {safeWaves}m • 💨 {safeWind}kts
        </span>
      )}
    </div>
  );
}
