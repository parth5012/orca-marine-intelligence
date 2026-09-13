/**
 * EmptyState Component
 * Reusable component for zero-data, empty search, no alerts, or disconnected states.
 * Adheres to ORCA marine aesthetic with clean iconography, informative copy, and actionable buttons.
 */

'use client';

import React from 'react';
import { Waves, LucideIcon } from 'lucide-react';

export interface EmptyStateAction {
  label: string;
  onClick: () => void;
  icon?: LucideIcon | React.ComponentType<{ className?: string }>;
}

export type EmptyStateVariant = 'default' | 'card' | 'minimal' | 'compact';

export interface EmptyStateProps {
  /** Main heading */
  title: string;
  /** Explanatory subtext */
  description?: string;
  /** Lucide icon or custom SVG icon component */
  icon?: LucideIcon | React.ComponentType<{ className?: string }>;
  /** Primary action button */
  action?: EmptyStateAction;
  /** Optional secondary action button */
  secondaryAction?: EmptyStateAction;
  /** Layout style variant (default: 'default') */
  variant?: EmptyStateVariant;
  /** Extra Tailwind classes */
  className?: string;
  /** Optional embedded children elements */
  children?: React.ReactNode;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  title,
  description,
  icon: Icon = Waves,
  action,
  secondaryAction,
  variant = 'default',
  className = '',
  children,
}) => {
  // Minimal variant: inline compact message
  if (variant === 'minimal') {
    return (
      <div
        data-testid="empty-state-minimal"
        className={`flex items-center gap-3 py-4 px-3 text-slate-500 dark:text-slate-400 ${className}`}
      >
        <div className="p-2 rounded-lg bg-slate-100 dark:bg-slate-800/80 text-cyan-600 dark:text-cyan-400">
          <Icon className="w-4 h-4" />
        </div>
        <div className="text-sm">
          <span className="font-medium text-slate-700 dark:text-slate-200">
            {title}
          </span>
          {description && (
            <span className="ml-1 text-slate-500 dark:text-slate-400">
              — {description}
            </span>
          )}
        </div>
        {action && (
          <button
            onClick={action.onClick}
            className="ml-auto text-xs font-medium text-cyan-600 dark:text-cyan-400 hover:underline"
          >
            {action.label}
          </button>
        )}
      </div>
    );
  }

  // Compact variant: smaller padding, stacked
  if (variant === 'compact') {
    return (
      <div
        data-testid="empty-state-compact"
        className={`flex flex-col items-center justify-center p-6 text-center ${className}`}
      >
        <div className="w-10 h-10 rounded-full bg-cyan-50 dark:bg-cyan-950/50 border border-cyan-200 dark:border-cyan-800/60 flex items-center justify-center text-cyan-600 dark:text-cyan-400 mb-2.5">
          <Icon className="w-5 h-5" />
        </div>
        <h4 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
          {title}
        </h4>
        {description && (
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 max-w-xs">
            {description}
          </p>
        )}
        {action && (
          <button
            onClick={action.onClick}
            className="mt-3 px-3 py-1.5 rounded-lg text-xs font-medium bg-cyan-600 hover:bg-cyan-700 text-white transition-colors"
          >
            {action.label}
          </button>
        )}
      </div>
    );
  }

  // Default and Card variants
  const isCard = variant === 'card';
  const containerClasses = isCard
    ? 'p-8 sm:p-10 rounded-2xl border border-slate-200/80 dark:border-slate-800 bg-white/70 dark:bg-slate-900/70 shadow-sm backdrop-blur-md'
    : 'py-12 px-4 sm:px-6';

  return (
    <div
      data-testid="empty-state"
      className={`flex flex-col items-center justify-center text-center ${containerClasses} ${className}`}
    >
      {/* Oceanic Glowing Rings Icon Container */}
      <div className="relative mb-5 flex items-center justify-center">
        <div className="absolute -inset-2 rounded-full bg-cyan-500/10 dark:bg-cyan-400/10 blur-md pointer-events-none" />
        <div className="relative w-16 h-16 rounded-2xl bg-gradient-to-b from-cyan-50 to-blue-50 dark:from-slate-800 dark:to-cyan-950/60 border border-cyan-200/80 dark:border-cyan-700/50 shadow-inner flex items-center justify-center text-cyan-600 dark:text-cyan-300">
          <Icon className="w-8 h-8" />
        </div>
      </div>

      {/* Text Copy */}
      <h3 className="text-base sm:text-lg font-semibold text-slate-900 dark:text-slate-100 max-w-md">
        {title}
      </h3>
      {description && (
        <p className="mt-1.5 text-xs sm:text-sm text-slate-500 dark:text-slate-400 max-w-sm sm:max-w-md leading-relaxed">
          {description}
        </p>
      )}

      {children && <div className="mt-4">{children}</div>}

      {/* Action Buttons */}
      {(action || secondaryAction) && (
        <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
          {action && (
            <button
              onClick={action.onClick}
              data-testid="empty-state-primary-action"
              className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-xs sm:text-sm font-semibold bg-cyan-600 hover:bg-cyan-500 text-white shadow-sm shadow-cyan-600/20 active:scale-[0.98] transition-all"
            >
              {action.icon && <action.icon className="w-4 h-4" />}
              {action.label}
            </button>
          )}

          {secondaryAction && (
            <button
              onClick={secondaryAction.onClick}
              data-testid="empty-state-secondary-action"
              className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-xs sm:text-sm font-medium border border-slate-300 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-200 transition-colors"
            >
              {secondaryAction.icon && (
                <secondaryAction.icon className="w-4 h-4" />
              )}
              {secondaryAction.label}
            </button>
          )}
        </div>
      )}
    </div>
  );
};

export default EmptyState;
