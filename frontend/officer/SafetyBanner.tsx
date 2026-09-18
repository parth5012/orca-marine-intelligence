/**
 * Officer safety banner: live weather, props-only SafetyBadge.
 *
 * Owner: M-C shell (T3 #173)
 * Module: frontend/officer/SafetyBanner.tsx
 *
 * Fetches GET ${NEXT_PUBLIC_API_URL}/api/weather/current directly
 * (T5 live-only rule). Backend-down safe: keeps a neutral fallback
 * and never breaks the shell.
 */

'use client';

import { useEffect, useState } from 'react';
import SafetyBadge from '@/map/SafetyBadge';

interface Weather {
  waves: number;
  wind: number;
  danger: string;
  badge: string;
  status: string;
}

interface Props {
  lat: number;
  lon: number;
}

const FALLBACK: Weather = { waves: 0.8, wind: 10, danger: 'none', badge: 'amber', status: 'Sea state unavailable (backend offline)' };

export default function SafetyBanner({ lat, lon }: Props) {
  const [w, setW] = useState<Weather>(FALLBACK);

  useEffect(() => {
    let cancelled = false;
    const base = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
    fetch(`${base.replace(/\/$/, '')}/api/weather/current?lat=${lat}&lon=${lon}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (cancelled || !d) return;
        setW({
          waves: d.wave_height_m ?? FALLBACK.waves,
          wind: d.wind_speed_kt ?? FALLBACK.wind,
          danger: d.status ?? d.danger ?? 'none',
          badge: d.status === 'danger' ? 'red' : d.status === 'caution' ? 'amber' : (d.badge ?? 'green'),
          status: d.status ? `Live sea state: ${d.status}` : 'Live sea state',
        });
      })
      .catch(() => { if (!cancelled) setW(FALLBACK); });
    return () => { cancelled = true; };
  }, [lat, lon]);

  return (
    <div data-testid="officer-safety-banner" className="flex items-center gap-3 px-4 py-2 bg-slate-900/60 border-b border-slate-800 text-xs text-slate-300">
      <SafetyBadge waves={w.waves} wind={w.wind} danger={w.danger} badge={w.badge} compact />
      <span>{w.status}</span>
    </div>
  );
}
