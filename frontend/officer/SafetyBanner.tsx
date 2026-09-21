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
import { useApp } from '@/context/AppContext';
import SafetyBadge from '@/map/SafetyBadge';

interface Weather {
  waves: number | null;
  wind: number | null;
  danger: string;
  badge: string;
  status: string;
}

interface Props {
  lat: number;
  lon: number;
}

// Ticket #195: backend-down reads UNKNOWN (amber), never SAFE-looking numbers.
const FALLBACK: Weather = { waves: null, wind: null, danger: 'unknown', badge: 'amber', status: 'Sea state unavailable (backend offline)' };

export default function SafetyBanner({ lat, lon }: Props) {
  const { themeMode } = useApp();
  const isLight = themeMode === 'light';
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
    <div
      data-testid="officer-safety-banner"
      className={`flex items-center gap-3 px-4 py-2 text-xs transition-colors ${
        isLight
          ? 'glass-panel-light border-b border-cyan-100 text-slate-700'
          : 'glass-panel-dark border-b border-cyan-900/40 text-slate-300'
      }`}
    >
      <SafetyBadge waves={w.waves} wind={w.wind} danger={w.danger} badge={w.badge} compact />
      <span className={isLight ? 'text-slate-600' : 'text-slate-300'}>{w.status}</span>
    </div>
  );
}
