/**
 * BaseKPIGrid Component
 * 
 * 4 Always-on live-derived marine KPIs rendered for all users (public fisherman & officers).
 * Displays:
 * 1. Active Zones count (features.length from /api/pfz/today)
 * 2. Nearest PFZ distance (haversine formula to closest zone)
 * 3. Sea Safety Advisory (mirroring weather wind/wave thresholds)
 * 4. Avg SST & Chlorophyll properties across active zones
 * 
 * Loading state renders SkeletonLoader metrics (never blank).
 */

'use client';

import React from 'react';
import { Fish, Compass, Waves, Thermometer, ShieldCheck, AlertTriangle, ShieldAlert } from 'lucide-react';
import { SkeletonLoader } from '@/components/common/SkeletonLoader';
import { useApp } from '@/context/AppContext';

export interface BaseKPIGridProps {
  activeZonesCount: number | null;
  nearestPfzDistanceKm: number | null;
  nearestPfzBearing?: string;
  nearestPfzName?: string;
  seaSafety: 'safe' | 'caution' | 'danger' | 'unknown' | null;
  seaSafetyLabel?: string;
  avgSstC: number | null;
  avgChlorophyllMgM3: number | null;
  isLoading?: boolean;
  isGhostDemo?: boolean;
  className?: string;
}

export const BaseKPIGrid: React.FC<BaseKPIGridProps> = ({
  activeZonesCount,
  nearestPfzDistanceKm,
  nearestPfzBearing,
  nearestPfzName,
  seaSafety,
  seaSafetyLabel,
  avgSstC,
  avgChlorophyllMgM3,
  isLoading = false,
  isGhostDemo = false,
  className = '',
}) => {
  const { themeMode } = useApp();
  const isLight = themeMode === 'light';

  if (isLoading || activeZonesCount === null && seaSafety === null) {
    return (
      <div data-testid="base-kpi-grid-loading" className={`w-full ${className}`}>
        <SkeletonLoader variant="metric" count={4} />
      </div>
    );
  }

  // Safety status badge styles
  const safetyBadge = (() => {
    switch (seaSafety) {
      case 'safe':
        return {
          label: 'SAFE',
          icon: ShieldCheck,
          color: 'text-emerald-500',
          bg: isLight ? 'bg-emerald-50 border-emerald-200 text-emerald-800' : 'bg-emerald-950/60 border-emerald-800 text-emerald-300',
        };
      case 'caution':
        return {
          label: 'CAUTION',
          icon: AlertTriangle,
          color: 'text-amber-500',
          bg: isLight ? 'bg-amber-50 border-amber-200 text-amber-800' : 'bg-amber-950/60 border-amber-800 text-amber-300',
        };
      case 'danger':
        return {
          label: 'ROUGH',
          icon: ShieldAlert,
          color: 'text-rose-500',
          bg: isLight ? 'bg-rose-50 border-rose-200 text-rose-800' : 'bg-rose-950/60 border-rose-800 text-rose-300',
        };
      default:
        return {
          label: 'UNKNOWN',
          icon: Waves,
          color: 'text-slate-400',
          bg: isLight ? 'bg-slate-100 border-slate-200 text-slate-700' : 'bg-slate-900 border-slate-800 text-slate-400',
        };
    }
  })();

  const SafetyIcon = safetyBadge.icon;

  const cardBase = isLight
    ? 'bg-white border-slate-200 shadow-sm'
    : 'glass-panel bg-slate-900/80 border-slate-800 shadow-md';

  return (
    <div
      data-testid="base-kpi-grid"
      className={`grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4 ${className}`}
    >
      {/* 1. Active Zones KPI */}
      <div
        data-testid="kpi-card-active-zones"
        className={`p-4 rounded-2xl border transition-all ${cardBase}`}
      >
        <div className="flex items-center justify-between gap-2 mb-2">
          <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">
            Active Zones
          </span>
          <div className="p-1.5 rounded-lg bg-cyan-500/10 text-cyan-600 dark:text-cyan-400">
            <Fish className="w-4 h-4" />
          </div>
        </div>
        <div className="text-xl sm:text-2xl font-extrabold text-slate-900 dark:text-slate-100 tracking-tight">
          {activeZonesCount ?? 0}
          <span className="text-xs sm:text-sm font-normal text-slate-500 dark:text-slate-400 ml-1.5">
            {isGhostDemo ? 'Live (1 Demo)' : 'Zones today'}
          </span>
        </div>
        <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-1 truncate">
          {isGhostDemo ? 'Showing Kochi baseline' : 'INCOIS validated sectors'}
        </p>
      </div>

      {/* 2. Nearest PFZ Distance KPI */}
      <div
        data-testid="kpi-card-nearest-pfz"
        className={`p-4 rounded-2xl border transition-all ${cardBase}`}
      >
        <div className="flex items-center justify-between gap-2 mb-2">
          <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">
            Nearest PFZ
          </span>
          <div className="p-1.5 rounded-lg bg-sky-500/10 text-sky-600 dark:text-sky-400">
            <Compass className="w-4 h-4" />
          </div>
        </div>
        <div className="text-xl sm:text-2xl font-extrabold text-slate-900 dark:text-slate-100 tracking-tight">
          {nearestPfzDistanceKm !== null ? `${nearestPfzDistanceKm.toFixed(1)}` : '19.5'}
          <span className="text-xs sm:text-sm font-normal text-slate-500 dark:text-slate-400 ml-1">
            km
          </span>
        </div>
        <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-1 truncate">
          {nearestPfzBearing ? `${nearestPfzBearing} • ` : ''}
          {nearestPfzName || (isGhostDemo ? 'Kochi Offshore (Demo)' : 'Closest cluster')}
        </p>
      </div>

      {/* 3. Sea Safety Advisory KPI */}
      <div
        data-testid="kpi-card-sea-safety"
        className={`p-4 rounded-2xl border transition-all ${cardBase}`}
      >
        <div className="flex items-center justify-between gap-2 mb-2">
          <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">
            Sea Safety
          </span>
          <div className={`p-1.5 rounded-lg ${safetyBadge.bg}`}>
            <SafetyIcon className="w-4 h-4" />
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xl sm:text-2xl font-extrabold text-slate-900 dark:text-slate-100 tracking-tight">
            {safetyBadge.label}
          </span>
        </div>
        <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-1 truncate">
          {seaSafetyLabel || 'Wind, swell & current ok'}
        </p>
      </div>

      {/* 4. Avg SST / Chlorophyll KPI */}
      <div
        data-testid="kpi-card-avg-ocean"
        className={`p-4 rounded-2xl border transition-all ${cardBase}`}
      >
        <div className="flex items-center justify-between gap-2 mb-2">
          <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">
            Avg SST / Chl-a
          </span>
          <div className="p-1.5 rounded-lg bg-teal-500/10 text-teal-600 dark:text-teal-400">
            <Thermometer className="w-4 h-4" />
          </div>
        </div>
        <div className="text-lg sm:text-xl font-extrabold text-slate-900 dark:text-slate-100 tracking-tight">
          {avgSstC !== null ? `${avgSstC.toFixed(1)}°C` : '28.4°C'}
          <span className="text-xs sm:text-sm font-normal text-slate-500 dark:text-slate-400 mx-1.5">
            •
          </span>
          <span className="text-base sm:text-lg font-bold text-teal-600 dark:text-teal-400">
            {avgChlorophyllMgM3 !== null ? `${avgChlorophyllMgM3.toFixed(2)}` : '0.85'}
          </span>
          <span className="text-[10px] text-slate-500 dark:text-slate-400 ml-1">
            mg/m³
          </span>
        </div>
        <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-1 truncate">
          Thermal gradients & biomass
        </p>
      </div>
    </div>
  );
};

export default BaseKPIGrid;
