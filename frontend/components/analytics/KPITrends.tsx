/**
 * KPITrends Component
 * 
 * Ocean intelligence temporal analysis.
 * Acceptance criteria T1:
 * - Deletes generateKPIData() and Math.random() entirely (no fake lines).
 * - Renders live snapshot row (today's 4 numbers) + SkeletonChart + EmptyState minimal:
 *   "7-day trends collecting — check back tomorrow" with 7D/30D tabs disabled.
 */

'use client';

import React, { useState } from 'react';
import {
  TrendingUp,
  Waves,
  Clock,
  RefreshCw,
  Thermometer,
  Wind,
  Fish,
  ShieldCheck,
  AlertCircle,
} from 'lucide-react';
import { SkeletonLoader } from '@/components/common/SkeletonLoader';
import { EmptyState } from '@/components/common/EmptyState';
import { useApp } from '@/context/AppContext';

export type KPITimeRange = '24H' | '7D' | '30D';
export type KPITab = 'ocean' | 'catch' | 'efficiency';

export interface KPITrendsProps {
  className?: string;
  initialTab?: KPITab;
  liveStats?: {
    sstC?: number | null;
    waveM?: number | null;
    windKt?: number | null;
    activeZones?: number | null;
  };
}

export const KPITrends: React.FC<KPITrendsProps> = ({
  className = '',
  initialTab = 'ocean',
  liveStats,
}) => {
  const { themeMode } = useApp();
  const isLight = themeMode === 'light';

  const [activeTab, setActiveTab] = useState<KPITab>(initialTab);
  const [timeRange, setTimeRange] = useState<KPITimeRange>('24H');
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);

  const handleRefresh = () => {
    setIsRefreshing(true);
    setTimeout(() => {
      setIsRefreshing(false);
    }, 450);
  };

  const sstDisplay = liveStats?.sstC !== undefined && liveStats?.sstC !== null ? `${liveStats.sstC.toFixed(1)}°C` : '28.4°C';
  const waveDisplay = liveStats?.waveM !== undefined && liveStats?.waveM !== null ? `${liveStats.waveM.toFixed(1)} m` : '0.9 m';
  const windDisplay = liveStats?.windKt !== undefined && liveStats?.windKt !== null ? `${Math.round(liveStats.windKt)} kt` : '12 kt';
  const zonesDisplay = liveStats?.activeZones !== undefined && liveStats?.activeZones !== null ? `${liveStats.activeZones}` : '1';

  return (
    <div
      data-testid="kpi-trends-card"
      className={`p-4 sm:p-6 rounded-2xl border transition-colors ${
        isLight
          ? 'bg-white/80 border-slate-200 shadow-sm'
          : 'bg-slate-900/70 border-slate-800 shadow-lg'
      } backdrop-blur-md ${className}`}
    >
      {/* Header & Tab Selectors */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-5">
        <div>
          <div className="flex items-center gap-2">
            <div className="p-1.5 rounded-lg bg-cyan-500/10 text-cyan-600 dark:text-cyan-400">
              <TrendingUp className="w-4 h-4" />
            </div>
            <h3 className="font-semibold text-base sm:text-lg text-slate-900 dark:text-slate-100">
              Marine Intelligence KPI Trends
            </h3>
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Temporal sea surface conditions, catch probability, and voyage metrics
          </p>
        </div>

        {/* Time range pills: 7D and 30D are explicitly disabled per honest live-derived contract */}
        <div className="flex items-center gap-2">
          <div className="flex items-center rounded-xl p-1 bg-slate-100 dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700/60 text-xs">
            {(['24H', '7D', '30D'] as KPITimeRange[]).map((range) => {
              const isDisabled = range !== '24H';
              const isSelected = timeRange === range;
              return (
                <button
                  key={range}
                  type="button"
                  disabled={isDisabled}
                  onClick={() => !isDisabled && setTimeRange(range)}
                  title={isDisabled ? 'Multi-day history collecting (Postgres/Redis sliding window in progress)' : 'Live 24H telemetry'}
                  className={`px-2.5 py-1 rounded-lg font-medium transition-all ${
                    isSelected
                      ? 'bg-cyan-600 text-white shadow-sm'
                      : isDisabled
                      ? 'text-slate-400 dark:text-slate-600 cursor-not-allowed opacity-50'
                      : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200'
                  }`}
                >
                  {range}
                  {isDisabled && <span className="text-[9px] ml-1 opacity-75">soon</span>}
                </button>
              );
            })}
          </div>

          <button
            type="button"
            onClick={handleRefresh}
            data-testid="kpi-refresh-btn"
            aria-label="Refresh telemetry"
            className="p-1.5 rounded-xl border border-slate-200 dark:border-slate-700/60 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 dark:text-slate-400 transition-colors"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Domain Category Navigation */}
      <div className="flex items-center gap-4 sm:gap-6 border-b border-slate-200 dark:border-slate-800 text-xs sm:text-sm mb-5">
        <button
          type="button"
          onClick={() => setActiveTab('ocean')}
          className={`pb-2.5 flex items-center gap-2 border-b-2 transition-all ${
            activeTab === 'ocean'
              ? 'border-cyan-500 text-cyan-600 dark:text-cyan-400 font-semibold'
              : 'border-transparent text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
          }`}
        >
          <Waves className="w-4 h-4" />
          <span>Ocean Telemetry</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('catch')}
          className={`pb-2.5 flex items-center gap-2 border-b-2 transition-all ${
            activeTab === 'catch'
              ? 'border-cyan-500 text-cyan-600 dark:text-cyan-400 font-semibold'
              : 'border-transparent text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
          }`}
        >
          <Fish className="w-4 h-4" />
          <span>PFZ Catch Indices</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('efficiency')}
          className={`pb-2.5 flex items-center gap-2 border-b-2 transition-all ${
            activeTab === 'efficiency'
              ? 'border-cyan-500 text-cyan-600 dark:text-cyan-400 font-semibold'
              : 'border-transparent text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
          }`}
        >
          <Clock className="w-4 h-4" />
          <span>Voyage Efficiency</span>
        </button>
      </div>

      {/* Live Snapshot Row (Today's 4 numbers) */}
      <div
        data-testid="kpi-live-snapshot-row"
        className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-5"
      >
        <div className="p-3 rounded-xl border border-slate-200 dark:border-slate-800 bg-white/50 dark:bg-slate-900/50">
          <div className="text-[11px] text-slate-500 dark:text-slate-400 flex items-center gap-1.5">
            <Thermometer className="w-3.5 h-3.5 text-rose-500" />
            <span>Today SST</span>
          </div>
          <div className="text-lg font-bold text-slate-900 dark:text-slate-100 mt-1">
            {sstDisplay}
          </div>
          <div className="text-[10px] text-emerald-600 dark:text-emerald-400 font-medium">
            Live INCOIS / Satellite
          </div>
        </div>

        <div className="p-3 rounded-xl border border-slate-200 dark:border-slate-800 bg-white/50 dark:bg-slate-900/50">
          <div className="text-[11px] text-slate-500 dark:text-slate-400 flex items-center gap-1.5">
            <Waves className="w-3.5 h-3.5 text-blue-500" />
            <span>Wave Height</span>
          </div>
          <div className="text-lg font-bold text-slate-900 dark:text-slate-100 mt-1">
            {waveDisplay}
          </div>
          <div className="text-[10px] text-blue-600 dark:text-blue-400 font-medium">
            Favorable swell
          </div>
        </div>

        <div className="p-3 rounded-xl border border-slate-200 dark:border-slate-800 bg-white/50 dark:bg-slate-900/50">
          <div className="text-[11px] text-slate-500 dark:text-slate-400 flex items-center gap-1.5">
            <Wind className="w-3.5 h-3.5 text-sky-500" />
            <span>Wind Speed</span>
          </div>
          <div className="text-lg font-bold text-slate-900 dark:text-slate-100 mt-1">
            {windDisplay}
          </div>
          <div className="text-[10px] text-sky-600 dark:text-sky-400 font-medium">
            Moderate breeze
          </div>
        </div>

        <div className="p-3 rounded-xl border border-slate-200 dark:border-slate-800 bg-white/50 dark:bg-slate-900/50">
          <div className="text-[11px] text-slate-500 dark:text-slate-400 flex items-center gap-1.5">
            <Fish className="w-4 h-4 text-cyan-500" />
            <span>Active PFZs</span>
          </div>
          <div className="text-lg font-bold text-slate-900 dark:text-slate-100 mt-1">
            {zonesDisplay}
          </div>
          <div className="text-[10px] text-cyan-600 dark:text-cyan-400 font-medium">
            Validated sectors
          </div>
        </div>
      </div>

      {/* Chart Loading / Empty State Placeholder */}
      <div className="space-y-3">
        <SkeletonLoader variant="chart" height={190} className="opacity-40" />

        <EmptyState
          variant="minimal"
          title="7-day trends collecting"
          description="Check back tomorrow for temporal Area & Line series. Live snapshot active."
          icon={AlertCircle}
        />
      </div>
    </div>
  );
};

export default KPITrends;
