/**
 * ConditionCard (UI-MIG-T3)
 *
 * Owner: M-E (Frontend Chat & App Shell)
 * Module: frontend/components/common/ConditionCard.tsx
 *
 * Ported visuals from source design common/ConditionCard (READ-ONLY).
 * Pure presentational: every value comes from live `GET /api/weather/current`
 * via HomeScreen. No fetches, no mocks.
 */

import React from 'react';
import { LucideIcon } from 'lucide-react';
import { useApp } from '@/context/AppContext';

interface ConditionCardProps {
  title: string;
  value: string | number;
  subtext?: string;
  icon: LucideIcon;
  color?: string;
  statusBadge?: string;
  testid?: string;
}

export const ConditionCard: React.FC<ConditionCardProps> = ({
  title,
  value,
  subtext,
  icon: Icon,
  color = 'text-cyan-600',
  statusBadge,
  testid,
}) => {
  const { themeMode } = useApp();
  const isLight = themeMode === 'light';

  return (
    <div
      data-testid={testid ?? `condition-card-${String(title).toLowerCase().replace(/[^a-z0-9]+/g, '-')}`}
      className={`rounded-2xl p-4 border transition-all ${
        isLight
          ? 'bg-white border-sky-100 shadow-sm text-slate-900 hover:border-sky-300 hover:shadow-md'
          : 'glass-panel glass-card-interactive border-cyan-900/40 bg-slate-950/80 text-white'
      }`}
    >
      <div className="flex items-center justify-between">
        <span
          className={`text-xs font-semibold tracking-wide uppercase ${isLight ? 'text-slate-500' : 'text-slate-400'}`}
        >
          {title}
        </span>
        <div
          className={`w-8 h-8 rounded-xl flex items-center justify-center ${isLight ? 'bg-sky-50 border border-sky-100' : 'bg-slate-900 border border-slate-800'}`}
        >
          <Icon className={`w-4 h-4 ${color}`} />
        </div>
      </div>

      <div className="mt-3">
        <div
          className={`text-xl sm:text-2xl font-extrabold tracking-tight leading-none ${isLight ? 'text-slate-900' : 'text-white'}`}
        >
          {value}
        </div>
        {subtext && (
          <p
            className={`text-xs mt-1 font-medium ${isLight ? 'text-slate-500' : 'text-slate-400'}`}
          >
            {subtext}
          </p>
        )}
      </div>

      {statusBadge && (
        <div
          className={`mt-3 pt-2 border-t flex items-center ${isLight ? 'border-slate-100' : 'border-slate-800/80'}`}
        >
          <span
            className={`px-2 py-0.5 rounded text-[10px] font-bold ${
              isLight
                ? 'bg-cyan-50 text-cyan-800 border border-cyan-200'
                : 'bg-cyan-950 text-cyan-300 border border-cyan-800'
            }`}
          >
            {statusBadge}
          </span>
        </div>
      )}
    </div>
  );
};
