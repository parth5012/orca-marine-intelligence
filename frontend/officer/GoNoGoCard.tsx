/**
 * Officer Go-No-Go decision card (T4 #174).
 *
 * Owner: M-C shell
 * Module: frontend/officer/GoNoGoCard.tsx
 *
 * Fetches GET /api/weather/current + /api/weather/cyclone for the selected
 * port, auto-suggests GO/HOLD from backend/routers/weather.py thresholds
 * (amber: 15kt/1.5m, red: 25kt/2.5m/995hPa), and POSTs the officer's
 * HOLD/GO + reason to /api/officer/overrides. Watch role is read-only.
 * Killable via NEXT_PUBLIC_ORCA_ENABLE_GONOGO=false (no fetch, renders null).
 */

'use client';

import { useEffect, useState } from 'react';
import { useApp } from '@/context/AppContext';
import type { OfficerPort } from './ports';
import type { OfficerRole } from './OfficerTopBar';

export type GoNoGoDecision = 'GO' | 'HOLD';

export interface SeaInputs {
  status?: string;
  wave?: number;
  wind?: number;
  pressure?: number;
  cycloneAlert?: string;
  cycloneActive?: boolean;
}

const CYCLONE_HOLD = new Set(['active', 'warning', 'severe']);

/** Pure auto-suggest: HOLD on red thresholds/cyclone, else GO (caution -> GO + note). */
export function suggestDecision(s: SeaInputs): { decision: GoNoGoDecision; note: string } {
  const cyc = (s.cycloneAlert ?? '').trim().toLowerCase();
  const cycHold = s.cycloneActive === true || CYCLONE_HOLD.has(cyc);
  if ((s.status ?? '') === 'danger' || (s.wave ?? 0) > 2.5 || (s.wind ?? 0) > 25 || (s.pressure ?? 1013) < 995 || cycHold) {
    return { decision: 'HOLD', note: cycHold ? 'HOLD: cyclone alert active.' : 'HOLD: red sea-state threshold breached.' };
  }
  if ((s.status ?? '') === 'caution') {
    return { decision: 'GO', note: 'GO with caution: amber sea state — brief crew before departure.' };
  }
  return { decision: 'GO', note: 'GO: sea state within safe limits.' };
}

interface OverrideRow {
  id: string;
  port_id: string;
  date: string;
  decision: GoNoGoDecision;
  reason: string;
  by_role: string;
}

interface Props {
  port: OfficerPort;
  role: OfficerRole;
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

export function isGoNoGoEnabled(): boolean {
  return !/^(false|0|no|off)$/i.test(process.env.NEXT_PUBLIC_ORCA_ENABLE_GONOGO ?? 'true');
}

export default function GoNoGoCard({ port, role }: Props) {
  const { themeMode } = useApp();
  const isLight = themeMode === 'light';
  const enabled = isGoNoGoEnabled();
  const watch = role === 'watch';
  const today = new Date().toISOString().slice(0, 10);
  const [sea, setSea] = useState<SeaInputs | null>(null);
  const [seaError, setSeaError] = useState<string | null>(null);
  const [rows, setRows] = useState<OverrideRow[]>([]);
  const [choice, setChoice] = useState<GoNoGoDecision>('HOLD');
  const [reason, setReason] = useState('');
  const [postError, setPostError] = useState<string | null>(null);
  const [posting, setPosting] = useState(false);

  useEffect(() => {
    if (!enabled) return; // kill switch: no weather fetch from this card
    let cancelled = false;
    const base = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').replace(/\/$/, '');
    const token = readCookie('officer_token');
    const headers = token ? { 'X-Officer-Token': token } : undefined;
    Promise.all([
      fetch(`${base}/api/weather/current?lat=${port.lat}&lon=${port.lon}`).then((r) => (r.ok ? r.json() : null)),
      fetch(`${base}/api/weather/cyclone?lat=${port.lat}&lon=${port.lon}`).then((r) => (r.ok ? r.json() : null)),
      fetch(`${base}/api/officer/overrides?${watch ? '' : `port_id=${port.id}&`}date=${today}`, { headers }).then((r) => (r.ok ? r.json() : null)),
    ])
      .then(([w, c, o]) => {
        if (cancelled) return;
        if (!w && !c) {
          setSeaError('Sea state unavailable (backend offline) — default HOLD until confirmed.');
          return;
        }
        setSea({
          status: w?.status,
          wave: w?.wave_height_m,
          wind: w?.wind_speed_kt,
          pressure: w?.pressure_hpa,
          cycloneAlert: c?.alert_level,
          cycloneActive: c?.active,
        });
        if (o?.overrides) setRows(o.overrides);
      })
      .catch(() => {
        if (!cancelled) setSeaError('Sea state unavailable (backend offline) — default HOLD until confirmed.');
      });
    return () => { cancelled = true; };
  }, [enabled, port.lat, port.lon, port.id, watch, today]);

  if (!enabled) return null;

  const suggestion = sea ? suggestDecision(sea) : { decision: 'HOLD' as GoNoGoDecision, note: seaError ?? 'Loading sea state…' };
  const overriding = choice !== suggestion.decision;
  const reasonOk = reason.trim().length > 0; // required always (400 on empty), esp. when overriding

  async function submit() {
    if (!reasonOk || posting) return;
    setPosting(true);
    setPostError(null);
    try {
      const base = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').replace(/\/$/, '');
      const token = readCookie('officer_token');
      const res = await fetch(`${base}/api/officer/overrides`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(token ? { 'X-Officer-Token': token } : {}) },
        body: JSON.stringify({ port_id: port.id, date: today, decision: choice, reason: reason.trim() }),
      });
      if (res.status === 401) {
        setPostError('Not authorized: set the officer_token cookie to PORT_TOKEN (ask your admin).');
        return;
      }
      if (!res.ok) {
        const detail = await res.json().catch(() => null);
        setPostError(detail?.detail ?? `Override failed (${res.status}).`);
        return;
      }
      const created = (await res.json()) as OverrideRow;
      setRows((prev) => [created, ...prev]);
      setReason('');
    } finally {
      setPosting(false);
    }
  }

  return (
    <div
      data-testid="gonogo-card"
      className={`rounded-2xl p-4 text-xs transition-colors border shadow-sm ${
        isLight
          ? 'glass-panel border-cyan-100 text-slate-800'
          : 'glass-panel-dark border-cyan-900/40 text-slate-200'
      }`}
    >
      <h2 className={`text-sm font-bold ${isLight ? 'text-slate-900' : 'text-white'}`}>
        Go / No-Go — {port.name}
      </h2>
      <p
        data-testid="gonogo-suggest"
        className={`mt-1 font-semibold ${
          suggestion.decision === 'HOLD'
            ? isLight ? 'text-rose-600' : 'text-red-400'
            : isLight ? 'text-emerald-600' : 'text-green-400'
        }`}
      >
        Auto-suggest: {suggestion.decision}
      </p>
      <p className={`mt-0.5 ${isLight ? 'text-slate-500' : 'text-slate-400'}`}>{suggestion.note}</p>
      {sea && (
        <dl
          data-testid="gonogo-numbers"
          className={`mt-2 grid grid-cols-2 gap-x-3 gap-y-1 ${isLight ? 'text-slate-700' : 'text-slate-300'}`}
        >
          <div><dt className={`inline ${isLight ? 'text-slate-500' : 'text-slate-400'}`}>Wave </dt><dd className="inline">{sea.wave ?? '—'} m</dd></div>
          <div><dt className={`inline ${isLight ? 'text-slate-500' : 'text-slate-400'}`}>Wind </dt><dd className="inline">{sea.wind ?? '—'} kt</dd></div>
          <div><dt className={`inline ${isLight ? 'text-slate-500' : 'text-slate-400'}`}>Pressure </dt><dd className="inline">{sea.pressure ?? '—'} hPa</dd></div>
          <div><dt className={`inline ${isLight ? 'text-slate-500' : 'text-slate-400'}`}>Cyclone </dt><dd className="inline">{sea.cycloneAlert ?? 'none'}</dd></div>
        </dl>
      )}
      {!watch ? (
        <div className="mt-2 flex flex-col gap-2">
          <div className="flex gap-2" role="group" aria-label="Override decision">
            {(['GO', 'HOLD'] as GoNoGoDecision[]).map((d) => (
              <button
                key={d}
                type="button"
                data-testid={`gonogo-${d.toLowerCase()}`}
                aria-pressed={choice === d}
                onClick={() => setChoice(d)}
                className={`rounded-lg px-3 py-1.5 font-semibold transition-all ${
                  choice === d
                    ? d === 'HOLD'
                      ? 'bg-rose-600 text-white shadow-sm'
                      : 'bg-emerald-600 text-white shadow-sm'
                    : isLight
                    ? 'bg-slate-100 hover:bg-slate-200 text-slate-700 border border-slate-200'
                    : 'bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700'
                }`}
              >
                {d}
              </button>
            ))}
          </div>
          <textarea
            aria-label="Override reason"
            data-testid="gonogo-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder={overriding ? 'Reason required — you are overriding the auto-suggest' : 'Reason required'}
            rows={2}
            className={`rounded-lg border px-2.5 py-1.5 text-xs transition-colors focus:outline-none focus:ring-1 focus:ring-cyan-500 ${
              isLight
                ? 'border-cyan-200 bg-white/90 text-slate-900 placeholder:text-slate-400'
                : 'border-cyan-900/40 bg-slate-800/60 text-slate-100 placeholder:text-slate-500'
            }`}
          />
          <button
            type="button"
            data-testid="gonogo-submit"
            disabled={!reasonOk || posting}
            onClick={submit}
            className="rounded-lg bg-cyan-600 hover:bg-cyan-500 px-3 py-1.5 font-semibold text-white transition-colors disabled:opacity-50"
          >
            {posting ? 'Saving…' : `Record ${choice}`}
          </button>
          {postError && (
            <p data-testid="gonogo-error" className={`text-xs ${isLight ? 'text-rose-600' : 'text-red-400'}`}>
              {postError}
            </p>
          )}
        </div>
      ) : (
        <p className={`mt-2 ${isLight ? 'text-slate-500' : 'text-slate-400'}`}>Watch role: read-only.</p>
      )}
      <ul
        data-testid="gonogo-overrides"
        className={`mt-2 flex flex-col gap-1 border-t pt-2 ${
          isLight ? 'border-cyan-100' : 'border-cyan-900/40'
        }`}
      >
        {rows.length === 0 && (
          <li className={isLight ? 'text-slate-500' : 'text-slate-400'}>
            No overrides recorded for {today}.
          </li>
        )}
        {rows.map((r) => (
          <li key={r.id} className="flex justify-between gap-2">
            <span
              className={
                r.decision === 'HOLD'
                  ? isLight ? 'text-rose-600 font-semibold' : 'text-red-300 font-semibold'
                  : isLight ? 'text-emerald-600 font-semibold' : 'text-green-300 font-semibold'
              }
            >
              {r.decision}
            </span>
            <span className={`flex-1 truncate ${isLight ? 'text-slate-600' : 'text-slate-400'}`}>
              {r.reason}{' '}
              <span className={isLight ? 'text-slate-400' : 'text-slate-500'}>({r.by_role})</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
