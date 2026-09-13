/**
 * SystemStatusBadge Component
 * Displays live backend system health based on periodic /api/status polling.
 * Includes interactive dropdown/tooltip detailing each service subsystem (Weather, PFZ, Geofence, Tiles, Chat).
 */

'use client';

import React, { useState, useRef, useEffect } from 'react';
import {
  Activity,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  Server,
  CloudSun,
  Fish,
  Shield,
  Layers,
  MessageSquare,
} from 'lucide-react';
import { useStatusPolling } from '@/hooks/useStatusPolling';

interface SystemStatusBadgeProps {
  /** Optional custom polling interval in ms */
  intervalMs?: number;
  /** Whether to show a compact icon-only badge */
  compact?: boolean;
  className?: string;
}

export const SystemStatusBadge: React.FC<SystemStatusBadgeProps> = ({
  intervalMs = 15000,
  compact = false,
  className = '',
}) => {
  const { status, services, isLoading, lastChecked, refetch } =
    useStatusPolling({ intervalMs });

  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Close popup on outside click
  useEffect(() => {
    const handleOutsideClick = (e: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setIsOpen(false);
      }
    };
    if (isOpen) {
      document.addEventListener('mousedown', handleOutsideClick);
    }
    return () => {
      document.removeEventListener('mousedown', handleOutsideClick);
    };
  }, [isOpen]);

  const isOk = status === 'ok';
  const isDegraded = status === 'degraded';

  const dotColor = isOk
    ? 'bg-emerald-500 shadow-emerald-500/50'
    : isDegraded
    ? 'bg-amber-500 shadow-amber-500/50'
    : 'bg-rose-500 shadow-rose-500/50';

  const badgeText = isOk
    ? 'Systems OK'
    : isDegraded
    ? 'Degraded'
    : 'Connecting...';

  const badgeStyle = isOk
    ? 'text-emerald-700 dark:text-emerald-400 bg-emerald-500/10 border-emerald-500/30'
    : isDegraded
    ? 'text-amber-700 dark:text-amber-400 bg-amber-500/10 border-amber-500/30'
    : 'text-slate-600 dark:text-slate-400 bg-slate-500/10 border-slate-500/30';

  const serviceList = [
    { key: 'weather', label: 'Weather Telemetry', icon: CloudSun },
    { key: 'pfz', label: 'PFZ Advisory Feed', icon: Fish },
    { key: 'geofence', label: 'Geofence Boundaries', icon: Shield },
    { key: 'tiles', label: 'Marine Vector Tiles', icon: Layers },
    { key: 'chat', label: 'ORCA Agent Engine', icon: MessageSquare },
  ];

  return (
    <div
      ref={containerRef}
      className={`relative inline-block ${className}`}
      data-testid="system-status-container"
    >
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        data-testid="system-status-trigger"
        aria-expanded={isOpen}
        title="Live System Status"
        className={`flex items-center gap-2 px-2.5 py-1 rounded-full text-xs font-medium border backdrop-blur-sm transition-all hover:scale-105 active:scale-95 ${badgeStyle}`}
      >
        <span className="relative flex h-2 w-2">
          {isOk && (
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
          )}
          <span
            className={`relative inline-flex rounded-full h-2 w-2 shadow-sm ${dotColor}`}
          />
        </span>
        {!compact && <span>{badgeText}</span>}
      </button>

      {/* Details Dropdown Popover */}
      {isOpen && (
        <div
          data-testid="system-status-popover"
          className="absolute right-0 mt-2 w-72 p-3.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-white/95 dark:bg-slate-900/95 shadow-xl backdrop-blur-md z-50 animate-in fade-in zoom-in-95 duration-150"
        >
          <div className="flex items-center justify-between pb-2 mb-2.5 border-b border-slate-200 dark:border-slate-800">
            <div className="flex items-center gap-1.5 font-semibold text-xs text-slate-800 dark:text-slate-200">
              <Server className="w-3.5 h-3.5 text-cyan-600 dark:text-cyan-400" />
              <span>ORCA Subsystem Status</span>
            </div>
            <button
              onClick={() => refetch()}
              disabled={isLoading}
              title="Refresh status now"
              className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 hover:text-cyan-600 dark:hover:text-cyan-400 transition-colors disabled:opacity-50"
            >
              <RefreshCw
                className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`}
              />
            </button>
          </div>

          <div className="space-y-2">
            {serviceList.map(({ key, label, icon: SvcIcon }) => {
              const active = Boolean(services[key]);
              return (
                <div
                  key={key}
                  className="flex items-center justify-between text-xs py-1 px-1.5 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-800/50"
                >
                  <div className="flex items-center gap-2 text-slate-700 dark:text-slate-300">
                    <SvcIcon className="w-3.5 h-3.5 text-slate-400 dark:text-slate-500" />
                    <span>{label}</span>
                  </div>
                  <div className="flex items-center gap-1">
                    {active ? (
                      <span className="inline-flex items-center gap-1 text-[11px] font-medium text-emerald-600 dark:text-emerald-400">
                        <CheckCircle2 className="w-3 h-3" />
                        <span>Live</span>
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-[11px] font-medium text-amber-600 dark:text-amber-400">
                        <AlertTriangle className="w-3 h-3" />
                        <span>Degraded</span>
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          <div className="mt-3 pt-2.5 border-t border-slate-200 dark:border-slate-800 flex items-center justify-between text-[10px] text-slate-500 dark:text-slate-400">
            <span>
              Last checked:{' '}
              {lastChecked ? lastChecked.toLocaleTimeString() : 'Just now'}
            </span>
            <span className="font-mono text-cyan-600 dark:text-cyan-400">
              /api/status
            </span>
          </div>
        </div>
      )}
    </div>
  );
};

export default SystemStatusBadge;
