/**
 * Officer day-close audit summary (T6 #176).
 *
 * Owner: M-C shell
 * Module: frontend/officer/DayClose.tsx
 *
 * GETs /api/officer/dayclose?port_id=&date= (JSON) for the selected date
 * (default today) and renders per-port summary cards {departures, holds,
 * overdues_resolved, mpa_hits, broadcasts}. Download CSV hits ?format=csv
 * (text/csv, blob download); Print calls window.print (EN header + port
 * language name in the print view). CSV header is EN only.
 */

'use client';

import { useCallback, useEffect, useState } from 'react';
import type { OfficerPort } from './ports';
import type { OfficerRole } from './OfficerTopBar';

interface DayCloseSummary {
  port_id: string;
  date: string;
  departures: number;
  holds: number;
  overdues_resolved: number;
  mpa_hits: number;
  broadcasts: number;
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

function apiBase(): string {
  return (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').replace(/\/$/, '');
}

function authHeaders(): Record<string, string> {
  const token = readCookie('officer_token');
  return token ? { 'X-Officer-Token': token } : {};
}

const CARDS: { key: keyof Omit<DayCloseSummary, 'port_id' | 'date'>; label: string }[] = [
  { key: 'departures', label: 'Departures' },
  { key: 'holds', label: 'Holds' },
  { key: 'overdues_resolved', label: 'Overdues resolved' },
  { key: 'mpa_hits', label: 'MPA hits' },
  { key: 'broadcasts', label: 'Broadcasts' },
];

export default function DayClose({ port, role }: Props) {
  const watch = role === 'watch';
  const [dateStr, setDateStr] = useState(() => new Date().toISOString().slice(0, 10));
  const [summary, setSummary] = useState<DayCloseSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = watch ? `date=${dateStr}` : `port_id=${port.id}&date=${dateStr}`;
      const res = await fetch(`${apiBase()}/api/officer/dayclose?${qs}`, { headers: authHeaders() });
      if (res.status === 401) {
        setError('Not authorized: set the officer_token cookie to PORT_TOKEN (ask your admin).');
        setSummary(null);
        return;
      }
      if (!res.ok) {
        setError(`Day-close unavailable (${res.status}).`);
        setSummary(null);
        return;
      }
      setSummary((await res.json()) as DayCloseSummary);
    } catch {
      setError('Day-close unavailable (backend offline).');
      setSummary(null);
    } finally {
      setLoading(false);
    }
  }, [port.id, watch, dateStr]);

  useEffect(() => {
    load();
  }, [load]);

  async function downloadCsv() {
    const qs = watch ? `date=${dateStr}` : `port_id=${port.id}&date=${dateStr}`;
    const res = await fetch(`${apiBase()}/api/officer/dayclose?${qs}&format=csv`, { headers: authHeaders() });
    if (!res.ok) {
      setError(`CSV download failed (${res.status}).`);
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `dayclose-${watch ? 'all' : port.id}-${dateStr}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  return (
    <div data-testid="dayclose" className="rounded-xl border border-slate-800 bg-slate-900/60 p-3 text-xs text-slate-200">
      <h2 className="text-sm font-bold text-white">
        Day-close — {watch ? 'all ports' : port.name}
        <span className="ml-2 font-normal text-slate-500">({port.language})</span>
      </h2>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-2 text-slate-400">
          Date
          <input
            aria-label="Day-close date"
            data-testid="dayclose-date"
            type="date"
            value={dateStr}
            onChange={(e) => setDateStr(e.target.value)}
            className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-slate-100"
          />
        </label>
        <button
          type="button"
          data-testid="dayclose-download"
          onClick={downloadCsv}
          className="rounded bg-cyan-600 px-3 py-1.5 font-semibold text-white"
        >
          Download CSV
        </button>
        <button
          type="button"
          data-testid="dayclose-print"
          onClick={() => window.print()}
          className="rounded bg-slate-700 px-3 py-1.5 font-semibold text-white"
        >
          Print
        </button>
      </div>
      {loading && <p className="mt-2 text-slate-500">Loading…</p>}
      {error && <p data-testid="dayclose-error" className="mt-2 text-red-400">{error}</p>}
      {summary && (
        <dl data-testid="dayclose-summary" className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-5">
          {CARDS.map((c) => (
            <div key={c.key} className="rounded-lg border border-slate-800 bg-slate-950 px-2 py-1.5">
              <dt className="text-slate-500">{c.label}</dt>
              <dd data-testid={`dayclose-${c.key}`} className="text-lg font-bold text-white">{summary[c.key]}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}
