/**
 * SkeletonLoader Component
 * Reusable animated skeleton loader for data fetching, fallback, and loading states.
 * Supports multiple variants (text, rect, circle, badge, card, metric, chart, table-row)
 * with dark/light theme awareness and customizable dimensions.
 */

'use client';

import React from 'react';

export type SkeletonVariant =
  | 'text'
  | 'rect'
  | 'circle'
  | 'badge'
  | 'card'
  | 'metric'
  | 'chart'
  | 'table-row';

export interface SkeletonLoaderProps {
  /** Visual variant of the skeleton */
  variant?: SkeletonVariant;
  /** Width in css units (e.g. '100%', '240px', 24) */
  width?: string | number;
  /** Height in css units (e.g. '16px', '120px', 48) */
  height?: string | number;
  /** Additional custom Tailwind or css classes */
  className?: string;
  /** Number of repeated skeleton elements (default: 1) */
  count?: number;
  /** Whether to apply shimmer pulse animation (default: true) */
  animated?: boolean;
}

export const SkeletonLoader: React.FC<SkeletonLoaderProps> = ({
  variant = 'rect',
  width,
  height,
  className = '',
  count = 1,
  animated = true,
}) => {
  const baseAnimation = animated ? 'animate-pulse' : '';
  const baseBg =
    'bg-slate-200/80 dark:bg-slate-800/70 border border-slate-300/40 dark:border-slate-700/50';

  const formatDimension = (val?: string | number): string | undefined => {
    if (val === undefined) return undefined;
    return typeof val === 'number' ? `${val}px` : val;
  };

  const styleDimension: React.CSSProperties = {
    width: formatDimension(width),
    height: formatDimension(height),
  };

  // Pre-composed card variant
  if (variant === 'card') {
    return (
      <div className="space-y-4 w-full" data-testid="skeleton-card-container">
        {Array.from({ length: count }).map((_, idx) => (
          <div
            key={idx}
            data-testid="skeleton-card"
            className={`p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white/50 dark:bg-slate-900/50 backdrop-blur-sm ${baseAnimation} ${className}`}
            style={styleDimension}
          >
            <div className="flex items-center justify-between gap-3 mb-3">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-slate-300 dark:bg-slate-800" />
                <div className="space-y-1.5">
                  <div className="w-28 h-3.5 rounded bg-slate-300 dark:bg-slate-800" />
                  <div className="w-16 h-2.5 rounded bg-slate-200 dark:bg-slate-800/60" />
                </div>
              </div>
              <div className="w-16 h-6 rounded-full bg-slate-200 dark:bg-slate-800" />
            </div>
            <div className="space-y-2 mt-3">
              <div className="w-full h-3 rounded bg-slate-200 dark:bg-slate-800/80" />
              <div className="w-4/5 h-3 rounded bg-slate-200 dark:bg-slate-800/60" />
            </div>
            <div className="flex items-center justify-between pt-3 mt-3 border-t border-slate-200/60 dark:border-slate-800/60">
              <div className="w-20 h-3 rounded bg-slate-200 dark:bg-slate-800" />
              <div className="w-12 h-3 rounded bg-slate-200 dark:bg-slate-800" />
            </div>
          </div>
        ))}
      </div>
    );
  }

  // Pre-composed metric variant
  if (variant === 'metric') {
    return (
      <div
        className="grid grid-cols-2 sm:grid-cols-4 gap-3 w-full"
        data-testid="skeleton-metric-container"
      >
        {Array.from({ length: count }).map((_, idx) => (
          <div
            key={idx}
            data-testid="skeleton-metric"
            className={`p-3.5 rounded-xl border border-slate-200 dark:border-slate-800/80 bg-white/60 dark:bg-slate-900/60 backdrop-blur-sm ${baseAnimation} ${className}`}
            style={styleDimension}
          >
            <div className="flex items-center justify-between mb-2">
              <div className="w-16 h-2.5 rounded bg-slate-300 dark:bg-slate-700" />
              <div className="w-5 h-5 rounded-full bg-slate-200 dark:bg-slate-800" />
            </div>
            <div className="w-24 h-6 rounded bg-slate-300 dark:bg-slate-700 mb-1.5" />
            <div className="w-12 h-2 rounded bg-slate-200 dark:bg-slate-800" />
          </div>
        ))}
      </div>
    );
  }

  // Pre-composed chart variant
  if (variant === 'chart') {
    return (
      <div
        data-testid="skeleton-chart"
        className={`w-full p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white/60 dark:bg-slate-900/60 backdrop-blur-sm ${baseAnimation} ${className}`}
        style={styleDimension}
      >
        <div className="flex items-center justify-between mb-4">
          <div className="space-y-1">
            <div className="w-32 h-4 rounded bg-slate-300 dark:bg-slate-700" />
            <div className="w-20 h-2.5 rounded bg-slate-200 dark:bg-slate-800" />
          </div>
          <div className="flex gap-2">
            <div className="w-12 h-6 rounded-md bg-slate-200 dark:bg-slate-800" />
            <div className="w-12 h-6 rounded-md bg-slate-200 dark:bg-slate-800" />
          </div>
        </div>
        <div className="h-44 w-full flex items-end gap-2 pt-4 border-b border-l border-slate-300 dark:border-slate-800 px-2 pb-2">
          {Array.from({ length: 12 }).map((_, barIdx) => {
            const h = 25 + ((barIdx * 19) % 65);
            return (
              <div
                key={barIdx}
                className="flex-1 bg-slate-200 dark:bg-slate-800/80 rounded-t"
                style={{ height: `${h}%` }}
              />
            );
          })}
        </div>
      </div>
    );
  }

  // Pre-composed table-row variant
  if (variant === 'table-row') {
    return (
      <div className="w-full space-y-2" data-testid="skeleton-table-container">
        {Array.from({ length: count }).map((_, idx) => (
          <div
            key={idx}
            data-testid="skeleton-table-row"
            className={`flex items-center justify-between p-3 rounded-lg border border-slate-200 dark:border-slate-800/80 bg-white/40 dark:bg-slate-900/40 ${baseAnimation} ${className}`}
            style={styleDimension}
          >
            <div className="w-1/4 h-3 rounded bg-slate-300 dark:bg-slate-700" />
            <div className="w-1/6 h-3 rounded bg-slate-200 dark:bg-slate-800" />
            <div className="w-1/5 h-3 rounded bg-slate-200 dark:bg-slate-800" />
            <div className="w-12 h-5 rounded-full bg-slate-200 dark:bg-slate-800" />
          </div>
        ))}
      </div>
    );
  }

  // Basic variants: text, circle, badge, rect
  const variantStyles: Record<string, string> = {
    text: 'h-3.5 w-full rounded',
    circle: 'rounded-full aspect-square w-8 h-8',
    badge: 'h-5 w-16 rounded-full',
    rect: 'rounded-xl h-24 w-full',
  };

  const appliedClass = variantStyles[variant] || variantStyles.rect;

  return (
    <div className="w-full space-y-2.5" data-testid="skeleton-basic-container">
      {Array.from({ length: count }).map((_, idx) => (
        <div
          key={idx}
          data-testid="skeleton-element"
          className={`${appliedClass} ${baseBg} ${baseAnimation} ${className}`}
          style={styleDimension}
        />
      ))}
    </div>
  );
};

/** Standalone convenience helper for cards */
export const SkeletonCard: React.FC<Omit<SkeletonLoaderProps, 'variant'>> = (
  props
) => <SkeletonLoader variant="card" {...props} />;

/** Standalone convenience helper for metrics/stat cards */
export const SkeletonMetric: React.FC<Omit<SkeletonLoaderProps, 'variant'>> = (
  props
) => <SkeletonLoader variant="metric" {...props} />;

/** Standalone convenience helper for charts */
export const SkeletonChart: React.FC<Omit<SkeletonLoaderProps, 'variant'>> = (
  props
) => <SkeletonLoader variant="chart" {...props} />;

export default SkeletonLoader;
