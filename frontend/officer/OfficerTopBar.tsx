/**
 * Officer top bar: port selector + role switcher.
 *
 * Owner: M-C shell (T3 #173)
 * Module: frontend/officer/OfficerTopBar.tsx
 *
 * Props-only. Selector grouped by state; locked (disabled) in watch
 * role. Role switch preserves the selected port. No auth UI (T2 gate
 * owns login; shell reads the officer_role cookie only).
 */

'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import type { OfficerPort } from './ports';
import { groupPortsByState } from './ports';

export type OfficerRole = 'port' | 'watch';

interface Props {
  selectedPort: OfficerPort;
  role: OfficerRole;
}

export default function OfficerTopBar({ selectedPort, role }: Props) {
  const router = useRouter();
  const groups = groupPortsByState();
  const watch = role === 'watch';

  return (
    <header className="flex flex-wrap items-center gap-3 border-b border-slate-800 bg-slate-950 px-4 py-3">
      <span className="text-sm font-bold tracking-wider text-cyan-300">ORCA OFFICER</span>
      <select
        aria-label="Port selector"
        data-testid="officer-port-select"
        disabled={watch}
        value={watch ? '' : selectedPort.id}
        onChange={(e) => router.push(`/officer?role=port&port=${e.target.value}`)}
        className="rounded bg-slate-900 px-2 py-1.5 text-xs text-slate-100 border border-slate-700 disabled:opacity-50"
      >
        {watch && <option value="">All ports</option>}
        {groups.map((g) => (
          <optgroup key={g.state} label={g.state}>
            {g.ports.map((p: OfficerPort) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </optgroup>
        ))}
      </select>
      <nav aria-label="Role switcher" className="ml-auto flex gap-1 text-xs">
        <Link
          href={`/officer?role=port&port=${selectedPort.id}`}
          aria-current={watch ? undefined : 'page'}
          className={`rounded px-3 py-1.5 font-semibold ${watch ? 'text-slate-400 hover:text-white' : 'bg-cyan-600 text-white'}`}
        >
          Port
        </Link>
        <Link
          href="/officer?role=watch"
          aria-current={watch ? 'page' : undefined}
          className={`rounded px-3 py-1.5 font-semibold ${watch ? 'bg-cyan-600 text-white' : 'text-slate-400 hover:text-white'}`}
        >
          Watch
        </Link>
      </nav>
    </header>
  );
}
