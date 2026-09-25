/**
 * KPITrends Component
 *
 * Ocean intelligence temporal analysis.
 *
 * Data contract:
 * - The 4 headline numbers stay live-derived (liveStats prop from HomeScreen);
 *   nulls fall back to the documented snapshot defaults.
 * - The temporal chart renders the static demo matrix from ./kpiMockData for
 *   every tab (ocean / catch / efficiency) x range (24H / 7D / 30D). The
 *   series is hand-written literal data — never Math.random / generateKPIData
 *   — and is labelled "Demo data" on screen so it is never read as live
 *   INCOIS telemetry.
 * - If a tab/range ever has no dataset, the component falls back to the real
 *   SkeletonChart + "7-day trends collecting" empty state instead of drawing
 *   bars it cannot source.
 *
 * Swap path: replace kpiMockData.getKPIDataset with a fetch of the backend's
 * Postgres/Redis rolling window; nothing else in this file changes.
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
  AlertCircle,
} from 'lucide-react';
import {
  Bar,
  BarChart,
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { SkeletonLoader } from '@/components/common/SkeletonLoader';
import { EmptyState } from '@/components/common/EmptyState';
import { useApp } from '@/context/AppContext';
import {
  KPI_RANGES,
  formatKPIValue,
  getKPIDataset,
} from '@/components/analytics/kpiMockData';
import type { KPITab, KPITimeRange } from '@/components/analytics/kpiMockData';

export type { KPITab, KPITimeRange };

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

  const dataset = getKPIDataset(activeTab, timeRange);

  // Bar charts keep a zero baseline (truncated bars would overstate swings);
  // the SST area chart zooms to its own range and prints min/max alongside.
  const yDomain: [number, number] | undefined = dataset
    ? dataset.chartType === 'bar'
      ? [0, Math.ceil(dataset.max * 1.15)]
      : [
          Math.floor((dataset.min - 0.2) * 10) / 10,
          Math.ceil((dataset.max + 0.2) * 10) / 10,
        ]
    : undefined;

  // Thin out x-axis labels on the 30-point range so they stay legible.
  const tickInterval = dataset
    ? Math.max(0, Math.ceil(dataset.points.length / 8) - 1)
    : 0;

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

        {/* Time range pills: all three ranges are backed by the static demo
            matrix (kpiMockData). Copy on hover says demo until the real
            multi-day rolling window lands. */}
        <div className="flex items-center gap-2">
          <div className="flex items-center rounded-xl p-1 bg-slate-100 dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700/60 text-xs">
            {KPI_RANGES.map((range) => {
              const isSelected = timeRange === range;
              return (
                <button
                  key={range}
                  type="button"
                  disabled={!isSelected && !getKPIDataset(activeTab, range)}
                  onClick={() => getKPIDataset(activeTab, range) && setTimeRange(range)}
                  title={`Demo ${range} series — live ${range} history lands with the Postgres/Redis rolling window`}
                  data-testid={`kpi-range-${range}`}
                  className={`px-2.5 py-1 rounded-lg font-medium transition-all ${
                    isSelected
                      ? 'bg-cyan-600 text-white shadow-sm'
                      : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200'
                  }`}
                >
                  {range}
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

      {/* Temporal series: demo dataset when available, honest empty state otherwise */}
      {dataset ? (
        <div className="space-y-3" data-testid="kpi-demo-chart">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <div className="text-sm font-semibold text-slate-800 dark:text-slate-200">
                {dataset.title}
                <span className="text-slate-400 dark:text-slate-500 font-normal ml-2">
                  {dataset.range}
                </span>
              </div>
              <div className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                {dataset.summaryLabel}{' '}
                <span className="font-semibold text-slate-700 dark:text-slate-200">
                  {formatKPIValue(dataset.summaryLatest, dataset.unit)}
                </span>{' '}
                · low {formatKPIValue(dataset.min, dataset.unit)} · high{' '}
                {formatKPIValue(dataset.max, dataset.unit)}
              </div>
            </div>

            <span
              data-testid="kpi-demo-badge"
              title={dataset.demoDisclaimer}
              className="shrink-0 px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide bg-amber-100 text-amber-700 border border-amber-200 dark:bg-amber-500/15 dark:text-amber-300 dark:border-amber-500/30"
            >
              Demo data
            </span>
          </div>

          <div className="h-[190px] w-full" data-testid="kpi-chart-canvas">
            <ResponsiveContainer width="100%" height="100%">
              {dataset.chartType === 'area' ? (
                <AreaChart
                  data={dataset.points}
                  margin={{ top: 8, right: 8, bottom: 0, left: -18 }}
                >
                  <defs>
                    <linearGradient id="kpiSstFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#06b6d4" stopOpacity={0.45} />
                      <stop offset="100%" stopColor="#06b6d4" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.25} vertical={false} />
                  <XAxis
                    dataKey="label"
                    interval={tickInterval}
                    tick={{ fontSize: 10, fill: '#94a3b8' }}
                    tickLine={false}
                    axisLine={{ stroke: 'rgba(148,163,184,0.35)' }}
                  />
                  <YAxis
                    domain={yDomain as [number, number]}
                    tick={{ fontSize: 10, fill: '#94a3b8' }}
                    tickLine={false}
                    axisLine={false}
                    width={44}
                  />
                  <Tooltip
                    formatter={(value) => [
                      value === undefined || value === null
                        ? '—'
                        : formatKPIValue(Number(value), dataset.unit),
                      dataset.summaryLabel,
                    ]}
                    labelStyle={{ fontSize: 11 }}
                    contentStyle={{ fontSize: 12, borderRadius: 8 }}
                  />
                  <Area
                    type="monotone"
                    dataKey="value"
                    stroke="#0891b2"
                    strokeWidth={2}
                    fill="url(#kpiSstFill)"
                    isAnimationActive={false}
                  />
                </AreaChart>
              ) : (
                <BarChart
                  data={dataset.points}
                  margin={{ top: 8, right: 8, bottom: 0, left: -18 }}
                >
                  <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.25} vertical={false} />
                  <XAxis
                    dataKey="label"
                    interval={tickInterval}
                    tick={{ fontSize: 10, fill: '#94a3b8' }}
                    tickLine={false}
                    axisLine={{ stroke: 'rgba(148,163,184,0.35)' }}
                  />
                  <YAxis
                    domain={yDomain as [number, number]}
                    tick={{ fontSize: 10, fill: '#94a3b8' }}
                    tickLine={false}
                    axisLine={false}
                    width={44}
                  />
                  <Tooltip
                    formatter={(value) => [
                      value === undefined || value === null
                        ? '—'
                        : formatKPIValue(Number(value), dataset.unit),
                      dataset.summaryLabel,
                    ]}
                    labelStyle={{ fontSize: 11 }}
                    contentStyle={{ fontSize: 12, borderRadius: 8 }}
                  />
                  <Bar
                    dataKey="value"
                    fill="#0891b2"
                    radius={[4, 4, 0, 0]}
                    maxBarSize={36}
                    isAnimationActive={false}
                  />
                </BarChart>
              )}
            </ResponsiveContainer>
          </div>

          <p className="text-[11px] text-slate-500 dark:text-slate-400 flex items-start gap-1.5">
            <AlertCircle className="w-3.5 h-3.5 mt-px shrink-0 text-amber-500" />
            <span>{dataset.demoDisclaimer}</span>
          </p>
        </div>
      ) : (
        <div className="space-y-3" data-testid="kpi-empty-chart">
          <SkeletonLoader variant="chart" height={190} className="opacity-40" />

          <EmptyState
            variant="minimal"
            title="7-day trends collecting"
            description="Check back tomorrow for temporal Area & Line series. Live snapshot active."
            icon={AlertCircle}
          />
        </div>
      )}
    </div>
  );
};

export default KPITrends;
