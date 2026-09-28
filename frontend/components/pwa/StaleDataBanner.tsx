/**
 * StaleDataBanner Component
 *
 * Owner: M-D (Frontend & Maps)
 * Module: frontend/components/pwa/StaleDataBanner.tsx
 *
 * Persistent warning banner shown when advisory data is stale or when
 * the device is operating offline from snapshot cache.
 */

'use client';

import React from 'react';
import type { FreshnessResult } from '@/lib/advisoryFreshness';

export interface StaleDataBannerProps {
  result: FreshnessResult;
  offline: boolean;
  className?: string;
}

export function StaleDataBanner({
  result,
  offline,
  className = '',
}: StaleDataBannerProps) {
  if (!offline && !result.stale) {
    return null;
  }

  const reasonsAttr = result.reasons && result.reasons.length > 0
    ? result.reasons.join(',')
    : '';

  let message: string;
  if (offline) {
    message = result.ageLabel
      ? `Offline — showing advisory from ${result.ageLabel}`
      : 'Offline — advisory age unknown';
  } else {
    const agePart = result.ageLabel
      ? (result.ageLabel.endsWith('old') ? result.ageLabel : `${result.ageLabel} old`)
      : null;
    message = agePart
      ? `Advisory is ${agePart} — safety shown at CAUTION`
      : 'Advisory age unknown — safety shown at CAUTION';
  }

  return (
    <div
      role="status"
      data-testid="stale-data-banner"
      data-stale-reasons={reasonsAttr}
      className={`w-full px-4 py-2 text-xs sm:text-sm font-medium bg-amber-950/80 border border-amber-500/70 text-amber-200 flex items-center justify-center text-center shadow-sm z-50 ${className}`.trim()}
    >
      <span>{message}</span>
    </div>
  );
}

export default StaleDataBanner;
