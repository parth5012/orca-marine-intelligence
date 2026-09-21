/**
 * Officer silent alerts feed (T5 #175).
 *
 * Owner: M-C shell
 * Module: frontend/officer/AlertsFeed.tsx
 *
 * Polls GET /api/officer/departures every 60s and surfaces the three
 * deterministic rules as a silent feed (no siren, no autoplay — header
 * counts + clickable rows only). Clicking a row calls onSelect(id) so the
 * parent can highlight the matching register row.
 */

'use client';

import { useCallback, useEffect, useState } from 'react';
import { useApp } from '@/context/AppContext';
import type { OfficerRole } from './OfficerTopBar';
import type { DepartureRow } from './RegisterTable';

interface Props {
  portId?: string;
  role: OfficerRole;
  onSelect?: (id: string) => void;
}

const POLL_MS = 60000;

function readCookie(name: string): string | null {
  if (typeof document === 'undefined') return null;
  const m = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  if (!m) return null;
  try {
    return decodeURIComponent(m[1]);
  } catch {
    return null;
  }
}

function isAlert(d: DepartureRow): boolean {
  return d.overdue_status !== 'none' || d.geofence_flag !== 'none' || d.weather_flag !== 'none';
}

export default function AlertsFeed({ portId, role, onSelect }: Props) {
  const { themeMode } = useApp();
  const isLight = themeMode === 'light';
  const [rows, setRows] = useState<DepartureRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const base = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').replace(/\/$/, '');
      const token = readCookie('officer_token');
      const headers = token ? { 'X-Officer-Token': token } : undefined;
      const qs = role === 'watch' && !portId ? '' : portId ? `?port_id=${portId}` : '';
      const res = await fetch(`${base}/api/officer/departures${qs}`, { headers });
      if (!res.ok) return; // silent feed: keep last good state, never alarm on fetch failure
      const data = await res.json();
      setRows(data.departures ?? []);
      setError(null);
    } catch {
      setError('Alerts feed offline — showing last known state.');
    }
  }, [portId, role]);

  useEffect(() => {
    load();
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, [load]);

  const overdue = rows.filter((d) => d.overdue_status !== 'none').length;
  const mpa = rows.filter((d) => d.geofence_flag === 'mpa').length;
  const weatherFlip = rows.filter((d) => d.weather_flag === 'flip').length;
  const alerts = rows.filter(isAlert);

  return (
    <div
      data-testid="alerts-feed"
      className={`rounded-2xl p-4 text-xs transition-colors border shadow-sm ${
        isLight
          ? 'glass-panel border-cyan-100 text-slate-800'
          : 'glass-panel-dark border-cyan-900/40 text-slate-200'
      }`}
    >
      <h2 className={`text-sm font-bold ${isLight ? 'text-slate-900' : 'text-white'}`}>Alerts (silent)</h2>
      <dl className="mt-1 flex gap-4">
        <div>
          <dt className={`inline ${isLight ? 'text-slate-500' : 'text-slate-400'}`}>Overdue </dt>
          <dd data-testid="alert-count-overdue" className={`inline font-bold ${isLight ? 'text-slate-900' : 'text-white'}`}>{overdue}</dd>
        </div>
        <div>
          <dt className={`inline ${isLight ? 'text-slate-500' : 'text-slate-400'}`}>MPA </dt>
          <dd data-testid="alert-count-mpa" className={`inline font-bold ${isLight ? 'text-slate-900' : 'text-white'}`}>{mpa}</dd>
        </div>
        <div>
          <dt className={`inline ${isLight ? 'text-slate-500' : 'text-slate-400'}`}>Weather-flip </dt>
          <dd data-testid="alert-count-weather" className={`inline font-bold ${isLight ? 'text-slate-900' : 'text-white'}`}>{weatherFlip}</dd>
        </div>
      </dl>
      {error && <p className={`mt-1 ${isLight ? 'text-slate-500' : 'text-slate-400'}`}>{error}</p>}
      <ul data-testid="alerts-rows" className="mt-2 flex flex-col gap-1">
        {alerts.length === 0 && <li className={isLight ? 'text-slate-500' : 'text-slate-400'}>No active alerts.</li>}
        {alerts.map((d) => (
          <li key={d.id}>
            <button
              type="button"
              data-testid={`alert-row-${d.id}`}
              onClick={() => onSelect?.(d.id)}
              className={`w-full rounded-lg border px-2.5 py-1.5 text-left transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500 ${
                isLight
                  ? 'border-cyan-100 bg-white/80 hover:border-cyan-400 hover:bg-white text-slate-800'
                  : 'border-cyan-900/40 bg-slate-800/60 hover:border-cyan-500 hover:bg-slate-800/80 text-slate-200'
              }`}
            >
              <span className={`font-semibold ${isLight ? 'text-slate-900' : 'text-white'}`}>{d.boat_id}</span>
              <span className={`ml-2 ${isLight ? 'text-slate-500' : 'text-slate-400'}`}>
                {[d.overdue_status !== 'none' ? `overdue ${d.overdue_mins}m` : null,
                  d.geofence_flag !== 'none' ? d.geofence_flag : null,
                  d.weather_flag === 'flip' ? 'weather-flip' : null].filter(Boolean).join(' · ')}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
