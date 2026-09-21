/**
 * Officer departure register: manual register-book table (T5 #175).
 *
 * Owner: M-C shell
 * Module: frontend/officer/RegisterTable.tsx
 *
 * Form (boat_id, crew, time_out, expected_in, dest_lat/lon) -> POST
 * /api/officer/departures; table GETs per port. Row colours come from
 * server-computed flags only (frontend highlight, no new thresholds):
 * overdue now>expected+2h amber / +6h red, risky-dest red badge
 * (mpa | imbl<2km | outside_eez), weather-flip red banner.
 * Watch role is read-only (no form). 401 shows the token-cookie hint.
 */

'use client';

import { useCallback, useEffect, useState } from 'react';
import { useApp } from '@/context/AppContext';
import type { OfficerPort } from './ports';
import type { OfficerRole } from './OfficerTopBar';

export interface DepartureRow {
  id: string;
  port_id: string;
  boat_id: string;
  crew: number;
  time_out: string;
  expected_in: string;
  dest_lat: number;
  dest_lon: number;
  dest_zone?: string | null;
  status: string;
  overdue_mins: number;
  overdue_status: 'none' | 'amber' | 'red';
  geofence_flag: 'none' | 'mpa' | 'imbl' | 'outside_eez';
  weather_flag: 'none' | 'flip';
}

interface Props {
  port: OfficerPort;
  role: OfficerRole;
  highlightId?: string | null;
}

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

function apiBase(): string {
  return (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').replace(/\/$/, '');
}

function authHeaders(): Record<string, string> {
  const token = readCookie('officer_token');
  return token ? { 'X-Officer-Token': token } : {};
}

const GEOFENCE_LABEL: Record<DepartureRow['geofence_flag'], string | null> = {
  none: null,
  mpa: 'MPA',
  imbl: 'IMBL <2km',
  outside_eez: 'OUTSIDE EEZ',
};

function rowTone(d: DepartureRow, isLight: boolean): string {
  if (d.overdue_status === 'red') {
    return isLight ? 'border-rose-300 bg-rose-50/70 text-slate-800' : 'border-rose-900/60 bg-rose-950/40 text-slate-200';
  }
  if (d.overdue_status === 'amber') {
    return isLight ? 'border-amber-300 bg-amber-50/70 text-slate-800' : 'border-amber-900/60 bg-amber-950/30 text-slate-200';
  }
  return isLight ? 'border-cyan-100 bg-white/70 text-slate-800' : 'border-cyan-900/40 bg-slate-800/40 text-slate-200';
}

function toLocalInput(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

export default function RegisterTable({ port, role, highlightId }: Props) {
  const { themeMode } = useApp();
  const isLight = themeMode === 'light';
  const watch = role === 'watch';
  const [rows, setRows] = useState<DepartureRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [posting, setPosting] = useState(false);
  const [form, setForm] = useState({ boat_id: '', crew: '4', time_out: '', expected_in: '', dest_lat: '', dest_lon: '' });

  const load = useCallback(async () => {
    setError(null);
    try {
      const qs = watch ? '' : `?port_id=${port.id}`;
      const res = await fetch(`${apiBase()}/api/officer/departures${qs}`, { headers: authHeaders() });
      if (res.status === 401) {
        setError('Not authorized: set the officer_token cookie to PORT_TOKEN (ask your admin).');
        return;
      }
      if (!res.ok) {
        setError(`Register unavailable (${res.status}).`);
        return;
      }
      const data = await res.json();
      setRows(data.departures ?? []);
    } catch {
      setError('Register unavailable (backend offline).');
    }
  }, [port.id, watch]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!highlightId) return;
    const prefersReduced =
      typeof window !== 'undefined' &&
      window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
    document.getElementById(`departure-${highlightId}`)?.scrollIntoView({
      block: 'nearest',
      behavior: prefersReduced ? 'auto' : 'smooth',
    });
  }, [highlightId]);

  function set<K extends keyof typeof form>(key: K, value: string) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function submit() {
    if (posting) return;
    setPosting(true);
    setError(null);
    try {
      const res = await fetch(`${apiBase()}/api/officer/departures`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          port_id: port.id,
          boat_id: form.boat_id.trim(),
          crew: Number(form.crew),
          time_out: new Date(form.time_out).toISOString(),
          expected_in: new Date(form.expected_in).toISOString(),
          dest_lat: Number(form.dest_lat),
          dest_lon: Number(form.dest_lon),
        }),
      });
      if (res.status === 401) {
        setError('Not authorized: set the officer_token cookie to PORT_TOKEN (ask your admin).');
        return;
      }
      if (!res.ok) {
        const detail = await res.json().catch(() => null);
        setError(detail?.detail ?? `Log failed (${res.status}).`);
        return;
      }
      const created = (await res.json()) as DepartureRow;
      setRows((prev) => [created, ...prev]);
      setForm({ boat_id: '', crew: '4', time_out: '', expected_in: '', dest_lat: '', dest_lon: '' });
    } finally {
      setPosting(false);
    }
  }

  const formOk =
    form.boat_id.trim().length > 0 &&
    Number(form.crew) >= 1 &&
    !Number.isNaN(new Date(form.time_out).getTime()) &&
    !Number.isNaN(new Date(form.expected_in).getTime()) &&
    Number.isFinite(Number(form.dest_lat)) &&
    Number.isFinite(Number(form.dest_lon));

  const inputClass = `rounded-lg border px-2.5 py-1.5 transition-colors focus:outline-none focus:ring-1 focus:ring-cyan-500 focus-visible:ring-2 focus-visible:ring-cyan-500 ${
    isLight
      ? 'border-cyan-200 bg-white/90 text-slate-900 placeholder:text-slate-400'
      : 'border-cyan-900/40 bg-slate-800/60 text-slate-100 placeholder:text-slate-500'
  }`;

  return (
    <div
      data-testid="register-table"
      className={`rounded-2xl p-4 text-xs transition-colors border shadow-sm ${
        isLight
          ? 'glass-panel border-cyan-100 text-slate-800'
          : 'glass-panel-dark border-cyan-900/40 text-slate-200'
      }`}
    >
      <h2 className={`text-sm font-bold ${isLight ? 'text-slate-900' : 'text-white'}`}>
        Departure register — {watch ? 'all ports' : port.name}
      </h2>
      {!watch && (
        <form
          data-testid="register-form"
          className="mt-2 grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (formOk) submit();
          }}
        >
          <div>
            <label htmlFor="register-boat" className="sr-only">Boat ID</label>
            <input id="register-boat" aria-label="Boat ID" data-testid="register-boat" value={form.boat_id} onChange={(e) => set('boat_id', e.target.value)} placeholder="Boat ID" className={`w-full ${inputClass}`} />
          </div>
          <div>
            <label htmlFor="register-crew" className="sr-only">Crew</label>
            <input id="register-crew" aria-label="Crew" data-testid="register-crew" value={form.crew} onChange={(e) => set('crew', e.target.value)} placeholder="Crew" inputMode="numeric" className={`w-full ${inputClass}`} />
          </div>
          <div>
            <label htmlFor="register-timeout" className="sr-only">Time out</label>
            <input id="register-timeout" aria-label="Time out" data-testid="register-timeout" type="datetime-local" value={form.time_out} onChange={(e) => set('time_out', e.target.value)} className={`w-full ${inputClass}`} />
          </div>
          <div>
            <label htmlFor="register-expected" className="sr-only">Expected in</label>
            <input id="register-expected" aria-label="Expected in" data-testid="register-expected" type="datetime-local" value={form.expected_in} onChange={(e) => set('expected_in', e.target.value)} className={`w-full ${inputClass}`} />
          </div>
          <div>
            <label htmlFor="register-lat" className="sr-only">Dest lat</label>
            <input id="register-lat" aria-label="Dest lat" data-testid="register-lat" value={form.dest_lat} onChange={(e) => set('dest_lat', e.target.value)} placeholder="Dest lat" inputMode="decimal" className={`w-full ${inputClass}`} />
          </div>
          <div>
            <label htmlFor="register-lon" className="sr-only">Dest lon</label>
            <input id="register-lon" aria-label="Dest lon" data-testid="register-lon" value={form.dest_lon} onChange={(e) => set('dest_lon', e.target.value)} placeholder="Dest lon" inputMode="decimal" className={`w-full ${inputClass}`} />
          </div>
          <button type="submit" data-testid="register-submit" disabled={!formOk || posting} className="col-span-1 sm:col-span-2 md:col-span-3 rounded-lg bg-cyan-600 hover:bg-cyan-500 px-3 py-1.5 font-semibold text-white transition-colors disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500">
            {posting ? 'Logging…' : 'Log departure'}
          </button>
        </form>
      )}
      {watch && <p className={`mt-1 ${isLight ? 'text-slate-500' : 'text-slate-400'}`}>Watch role: read-only.</p>}
      {error && <p data-testid="register-error" className={`mt-2 ${isLight ? 'text-rose-600' : 'text-red-400'}`}>{error}</p>}
      <ul data-testid="register-rows" className="mt-2 flex flex-col gap-2">
        {rows.length === 0 && <li className={isLight ? 'text-slate-500' : 'text-slate-400'}>No departures logged.</li>}
        {rows.map((d) => {
          const badge = GEOFENCE_LABEL[d.geofence_flag];
          const hot = highlightId === d.id;
          return (
            <li
              key={d.id}
              id={`departure-${d.id}`}
              data-testid={`departure-${d.id}`}
              className={`rounded-lg border p-2.5 transition-colors ${rowTone(d, isLight)} ${hot ? 'ring-2 ring-cyan-400' : ''}`}
            >
              {d.weather_flag === 'flip' && (
                <p data-testid={`weather-banner-${d.id}`} className="mb-1 rounded bg-rose-600 px-2 py-1 font-semibold text-white">
                  Weather flipped green→red after departure
                </p>
              )}
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className={`font-bold ${isLight ? 'text-slate-900' : 'text-white'}`}>{d.boat_id}</span>
                <span className={isLight ? 'text-slate-500' : 'text-slate-400'}>crew {d.crew}</span>
                <span className={isLight ? 'text-slate-500' : 'text-slate-400'}>
                  out {toLocalInput(d.time_out)} → in {toLocalInput(d.expected_in)}
                </span>
                {d.overdue_status !== 'none' && (
                  <span data-testid={`overdue-${d.id}`} className={d.overdue_status === 'red' ? (isLight ? 'font-semibold text-rose-600' : 'font-semibold text-red-400') : (isLight ? 'font-semibold text-amber-700' : 'font-semibold text-amber-400')}>
                    overdue {d.overdue_mins}m
                  </span>
                )}
              </div>
              <div className={`mt-1 flex flex-wrap items-center gap-2 ${isLight ? 'text-slate-500' : 'text-slate-400'}`}>
                <span>
                  dest {d.dest_lat.toFixed(3)}, {d.dest_lon.toFixed(3)}
                </span>
                {badge && (
                  <span data-testid={`geofence-${d.id}`} title="Risky destination flagged at log time" className="rounded bg-rose-600 px-1.5 py-0.5 font-semibold text-white text-[10px]">
                    {badge}
                  </span>
                )}
                <span className={isLight ? 'text-slate-400' : 'text-slate-500'}>{d.port_id}</span>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
