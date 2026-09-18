/**
 * ORCA Officer page shell (T3 #173).
 *
 * Owner: M-C shell — layout + role switch + slots for later cards
 * Module: frontend/app/officer/page.tsx
 *
 * ?role=port (default, one port_id) | ?role=watch (all ports, counts,
 * no per-boat edit). Reads officer_role cookie only — no auth UI
 * (T2 gate owns login). Later cards plug into #gonogo / #register /
 * #alerts. Desktop-first 3-column grid. Never touches fisherman
 * frontend/app/page.tsx.
 */

'use client';

import { Suspense, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import OfficerTopBar, { OfficerRole } from '@/officer/OfficerTopBar';
import SafetyBanner from '@/officer/SafetyBanner';
import OfficerMiniMap from '@/officer/OfficerMiniMap';
import GoNoGoCard from '@/officer/GoNoGoCard';
import RegisterTable from '@/officer/RegisterTable';
import AlertsFeed from '@/officer/AlertsFeed';
import BroadcastBox from '@/officer/BroadcastBox';
import DayClose from '@/officer/DayClose';
import { PORTS, INDIA_CENTER, PORT_ZOOM, WATCH_ZOOM, getPortById } from '@/officer/ports';

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

function resolveRole(param: string | null): OfficerRole {
  if (param === 'port' || param === 'watch') return param;
  const cookie = readCookie('officer_role');
  return cookie === 'watch' ? 'watch' : 'port';
}

function OfficerShell() {
  const searchParams = useSearchParams();
  const role = resolveRole(searchParams.get('role'));
  const watch = role === 'watch';
  const port = getPortById(searchParams.get('port'));
  const gonogoEnabled = !/^(false|0|no|off)$/i.test(process.env.NEXT_PUBLIC_ORCA_ENABLE_GONOGO ?? 'true');
  const states = new Set(PORTS.map((p) => p.state)).size;

  const center: [number, number] = watch ? INDIA_CENTER : [port.lat, port.lon];
  const zoom = watch ? WATCH_ZOOM : PORT_ZOOM;
  const [highlightId, setHighlightId] = useState<string | null>(null);

  return (
    <div className="min-h-screen bg-slate-950 font-sans text-slate-100">
      <OfficerTopBar selectedPort={port} role={role} />
      <SafetyBanner lat={center[0]} lon={center[1]} />
      {watch && (
        <p data-testid="officer-watch-counts" className="px-4 py-2 text-xs text-slate-400">
          All-ports watch: {PORTS.length} ports · {states} states · read-only (no per-boat edit)
        </p>
      )}
      <main className="grid grid-cols-1 gap-4 p-4 lg:grid-cols-[280px_1fr_320px]">
        <div id="gonogo" data-testid="slot-gonogo" className={gonogoEnabled ? '' : 'hidden'}>
          {gonogoEnabled ? <GoNoGoCard port={port} role={role} /> : null}
        </div>
        <section className="flex flex-col gap-4">
          <OfficerMiniMap center={center} zoom={zoom} sector={watch ? undefined : port.incois_sector} />
          <div id="register" data-testid="slot-register">
            <RegisterTable port={port} role={role} highlightId={highlightId} />
          </div>
        </section>
        <div id="alerts" data-testid="slot-alerts" className="flex flex-col gap-4">
          <AlertsFeed portId={watch ? undefined : port.id} role={role} onSelect={setHighlightId} />
          <BroadcastBox port={port} role={role} />
          <DayClose port={port} role={role} />
        </div>
      </main>
    </div>
  );
}

export default function OfficerPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-slate-950" />}>
      <OfficerShell />
    </Suspense>
  );
}
