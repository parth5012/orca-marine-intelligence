/**
 * Officer broadcast composer (T6 #176).
 *
 * Owner: M-C shell
 * Module: frontend/officer/BroadcastBox.tsx
 *
 * Drafts an advisory from today's go-no-go override (GET overrides
 * ?port_id=&date=, latest row) + the PFZ top zone (GET /api/pfz proxy,
 * ?sector=port sector, first feature: place/bearing/distance/citation).
 * Template EN: "{GO|HOLD}: {port} {date}. Sea {status}. PFZ {place}
 * {bearing}° {distance} (INCOIS {sector})."
 * Local draft: EN passthrough + translation_warning when the port language
 * (data/ports.json) is not en — no server translate endpoint exists for
 * officer and no SMS gateway, so the officer edits the textarea manually
 * (mirrors the POST /api/chat language field + Redis 1h cache fallback
 * shape on the chat side). Textarea editable, Copy button
 * (navigator.clipboard + fallback), POST /api/officer/broadcasts saves to
 * Postgres (source of truth, no Redis history). History shows 20 latest.
 * No auto-send.
 */

'use client';

import { useCallback, useEffect, useState } from 'react';
import { useApp } from '@/context/AppContext';
import type { OfficerPort } from './ports';
import type { OfficerRole } from './OfficerTopBar';

interface PfzTopZone {
  place: string;
  bearing: string;
  distance: string;
  sector: string;
}

interface BroadcastRow {
  id: string;
  port_id: string;
  text_en: string;
  text_local?: string | null;
  lang: string;
  created_at: string;
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

/** Pure draft renderer (mirrors backend build_broadcast_draft). Exported for tests. */
export function renderDraft(
  decision: string,
  portName: string,
  dateStr: string,
  seaStatus: string,
  zone: PfzTopZone,
): string {
  const dec = decision === 'GO' ? 'GO' : 'HOLD';
  return `${dec}: ${portName} ${dateStr}. Sea ${seaStatus}. PFZ ${zone.place} ${zone.bearing}° ${zone.distance} (INCOIS ${zone.sector}).`;
}

function zoneFromFeature(f: { properties?: Record<string, unknown> }): PfzTopZone {
  const p = f.properties ?? {};
  const str = (v: unknown, fb: string) => (typeof v === 'string' && v.trim() ? v : fb);
  return {
    place: str(p.place, 'nearshore waters'),
    bearing: str(p.bearing ?? p.direction, '—'),
    distance: str(p.distance ?? p.range, '—'),
    sector: str(p.sector, '—'),
  };
}

export default function BroadcastBox({ port, role }: Props) {
  const { themeMode } = useApp();
  const isLight = themeMode === 'light';
  const watch = role === 'watch';
  const today = new Date().toISOString().slice(0, 10);
  const [decision, setDecision] = useState('HOLD');
  const [seaStatus, setSeaStatus] = useState('unknown');
  const [zone, setZone] = useState<PfzTopZone>({ place: 'nearshore waters', bearing: '—', distance: '—', sector: port.incois_sector });
  const [draftEn, setDraftEn] = useState('');
  const [draftLocal, setDraftLocal] = useState('');
  const [history, setHistory] = useState<BroadcastRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [posting, setPosting] = useState(false);

  const translationWarning = port.language !== 'en';

  const load = useCallback(async () => {
    setError(null);
    try {
      const qs = watch ? `date=${today}` : `port_id=${port.id}&date=${today}`;
      const [oRes, pRes, hRes] = await Promise.all([
        fetch(`${apiBase()}/api/officer/overrides?${qs}`, { headers: authHeaders() }),
        fetch(`/api/pfz?sector=${port.incois_sector}&limit=1`),
        fetch(`${apiBase()}/api/officer/broadcasts?${watch ? '' : `port_id=${port.id}`}`, { headers: authHeaders() }),
      ]);
      if (oRes.ok) {
        const o = await oRes.json();
        const latest = o.overrides?.[0];
        if (latest?.decision) setDecision(latest.decision);
      }
      if (pRes.ok) {
        const pfz = await pRes.json();
        const first = pfz.features?.[0];
        if (first) setZone(zoneFromFeature(first));
      }
      if (hRes.status === 401) {
        setError('Not authorized: set the officer_token cookie to PORT_TOKEN (ask your admin).');
      } else if (hRes.ok) {
        const h = await hRes.json();
        setHistory((h.broadcasts ?? []).slice(0, 20));
      }
    } catch {
      setError('Broadcast composer offline (backend unreachable) — draft from last known state.');
    }
  }, [port.id, port.incois_sector, watch, today]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const en = renderDraft(decision, port.name, today, seaStatus, zone);
    setDraftEn(en);
    setDraftLocal(en); // EN fallback: officer edits manually when port language != en
  }, [decision, port.name, today, seaStatus, zone]);

  async function copy() {
    const text = translationWarning && draftLocal ? draftLocal : draftEn;
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  async function save() {
    if (posting) return;
    setPosting(true);
    setError(null);
    try {
      const res = await fetch(`${apiBase()}/api/officer/broadcasts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          port_id: port.id,
          text_en: draftEn,
          text_local: translationWarning ? draftLocal : null,
          lang: port.language,
        }),
      });
      if (res.status === 401) {
        setError('Not authorized: set the officer_token cookie to PORT_TOKEN (ask your admin).');
        return;
      }
      if (!res.ok) {
        const detail = await res.json().catch(() => null);
        setError(detail?.detail ?? `Broadcast save failed (${res.status}).`);
        return;
      }
      const created = (await res.json()) as BroadcastRow;
      setHistory((prev) => [created, ...prev].slice(0, 20));
    } finally {
      setPosting(false);
    }
  }

  return (
    <div
      data-testid="broadcast-box"
      className={`rounded-2xl p-4 text-xs transition-colors border shadow-sm ${
        isLight
          ? 'glass-panel border-cyan-100 text-slate-800'
          : 'glass-panel-dark border-cyan-900/40 text-slate-200'
      }`}
    >
      <h2 className={`text-sm font-bold ${isLight ? 'text-slate-900' : 'text-white'}`}>
        Broadcast — {port.name}
      </h2>
      <div className="mt-2 flex gap-2">
        <label className={`flex flex-1 flex-col gap-1 ${isLight ? 'text-slate-600' : 'text-slate-400'}`}>
          Decision
          <select
            aria-label="Broadcast decision"
            data-testid="broadcast-decision"
            value={decision}
            onChange={(e) => setDecision(e.target.value)}
            className={`rounded-lg border px-2.5 py-1.5 transition-colors focus:outline-none focus:ring-1 focus:ring-cyan-500 ${
              isLight
                ? 'border-cyan-200 bg-white/90 text-slate-900'
                : 'border-cyan-900/40 bg-slate-800/60 text-slate-100'
            }`}
          >
            <option value="GO">GO</option>
            <option value="HOLD">HOLD</option>
          </select>
        </label>
        <label className={`flex flex-1 flex-col gap-1 ${isLight ? 'text-slate-600' : 'text-slate-400'}`}>
          Sea status
          <select
            aria-label="Broadcast sea status"
            data-testid="broadcast-sea"
            value={seaStatus}
            onChange={(e) => setSeaStatus(e.target.value)}
            className={`rounded-lg border px-2.5 py-1.5 transition-colors focus:outline-none focus:ring-1 focus:ring-cyan-500 ${
              isLight
                ? 'border-cyan-200 bg-white/90 text-slate-900'
                : 'border-cyan-900/40 bg-slate-800/60 text-slate-100'
            }`}
          >
            {['safe', 'caution', 'danger', 'unknown'].map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </label>
      </div>
      <label className={`mt-2 flex flex-col gap-1 ${isLight ? 'text-slate-600' : 'text-slate-400'}`}>
        English draft (editable)
        <textarea
          aria-label="Broadcast English draft"
          data-testid="broadcast-en"
          value={draftEn}
          onChange={(e) => setDraftEn(e.target.value)}
          rows={3}
          className={`rounded-lg border px-2.5 py-1.5 text-xs transition-colors focus:outline-none focus:ring-1 focus:ring-cyan-500 ${
            isLight
              ? 'border-cyan-200 bg-white/90 text-slate-900 placeholder:text-slate-400'
              : 'border-cyan-900/40 bg-slate-800/60 text-slate-100 placeholder:text-slate-500'
          }`}
        />
      </label>
      {translationWarning && (
        <label className={`mt-2 flex flex-col gap-1 ${isLight ? 'text-slate-600' : 'text-slate-400'}`}>
          Local draft ({port.language}, editable — no auto-translation)
          <textarea
            aria-label="Broadcast local draft"
            data-testid="broadcast-local"
            value={draftLocal}
            onChange={(e) => setDraftLocal(e.target.value)}
            rows={3}
            className={`rounded-lg border px-2.5 py-1.5 text-xs transition-colors focus:outline-none focus:ring-1 focus:ring-cyan-500 ${
              isLight
                ? 'border-cyan-200 bg-white/90 text-slate-900 placeholder:text-slate-400'
                : 'border-cyan-900/40 bg-slate-800/60 text-slate-100 placeholder:text-slate-500'
            }`}
          />
          <span
            data-testid="broadcast-translation-warning"
            className={isLight ? 'text-amber-700' : 'text-amber-400'}
          >
            translation_warning: showing English fallback — edit manually before copying.
          </span>
        </label>
      )}
      <div className="mt-2 flex gap-2">
        <button
          type="button"
          data-testid="broadcast-copy"
          onClick={copy}
          className={`rounded-lg px-3 py-1.5 font-semibold transition-colors ${
            isLight
              ? 'bg-slate-200 hover:bg-slate-300 text-slate-800'
              : 'bg-slate-700 hover:bg-slate-600 text-white'
          }`}
        >
          {copied ? 'Copied!' : 'Copy'}
        </button>
        {!watch && (
          <button
            type="button"
            data-testid="broadcast-save"
            disabled={posting || !draftEn.trim()}
            onClick={save}
            className="rounded-lg bg-cyan-600 hover:bg-cyan-500 px-3 py-1.5 font-semibold text-white transition-colors disabled:opacity-50"
          >
            {posting ? 'Saving…' : 'Save broadcast'}
          </button>
        )}
      </div>
      {error && (
        <p data-testid="broadcast-error" className={`mt-2 ${isLight ? 'text-rose-600' : 'text-red-400'}`}>
          {error}
        </p>
      )}
      <ul
        data-testid="broadcast-history"
        className={`mt-2 flex flex-col gap-1 border-t pt-2 ${
          isLight ? 'border-cyan-100' : 'border-cyan-900/40'
        }`}
      >
        {history.length === 0 && (
          <li className={isLight ? 'text-slate-500' : 'text-slate-400'}>No broadcasts yet.</li>
        )}
        {history.map((b) => (
          <li
            key={b.id}
            className={`rounded-lg border px-2.5 py-1.5 ${
              isLight
                ? 'border-cyan-100 bg-white/80'
                : 'border-cyan-900/40 bg-slate-800/60'
            }`}
          >
            <span className={isLight ? 'text-slate-900' : 'text-slate-100'}>{b.text_en}</span>
            {b.text_local && (
              <span className={`block ${isLight ? 'text-slate-500' : 'text-slate-400'}`}>
                {b.text_local}
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
