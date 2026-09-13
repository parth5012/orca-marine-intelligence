/**
 * useStatusPolling Hook
 * Polls the Next.js /api/status endpoint periodically.
 * Supports configurable interval, automatic pause when tab is hidden,
 * manual refetch, and error degradation.
 */

'use client';

import { useState, useEffect, useCallback, useRef } from 'react';

export interface ServiceStatusMap {
  weather: boolean;
  pfz: boolean;
  geofence: boolean;
  tiles: boolean;
  chat: boolean;
  [key: string]: boolean | string | undefined;
}

export type HealthStatus = 'ok' | 'degraded' | 'offline' | 'checking';

export interface SystemStatusData {
  status: HealthStatus;
  services: ServiceStatusMap;
  timestamp?: string;
  source?: 'backend' | 'fallback';
}

export interface UseStatusPollingOptions {
  /** Polling interval in ms (default: 12000ms) */
  intervalMs?: number;
  /** Whether to enable automatic polling on mount (default: true) */
  enabled?: boolean;
  /** Whether to pause when document is hidden (default: true) */
  pauseOnHidden?: boolean;
  /** Callback fired on status update */
  onStatusChange?: (data: SystemStatusData) => void;
}

export interface UseStatusPollingResult {
  status: HealthStatus;
  services: ServiceStatusMap;
  isLoading: boolean;
  error: string | null;
  lastChecked: Date | null;
  refetch: () => Promise<void>;
  isPolling: boolean;
  pause: () => void;
  resume: () => void;
}

const DEFAULT_SERVICES: ServiceStatusMap = {
  weather: false,
  pfz: false,
  geofence: false,
  tiles: false,
  chat: false,
};

export function useStatusPolling(
  options: UseStatusPollingOptions = {}
): UseStatusPollingResult {
  const {
    intervalMs = 12000,
    enabled = true,
    pauseOnHidden = true,
    onStatusChange,
  } = options;

  const [status, setStatus] = useState<HealthStatus>('checking');
  const [services, setServices] = useState<ServiceStatusMap>(DEFAULT_SERVICES);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);
  const [isPollingActive, setIsPollingActive] = useState<boolean>(enabled);

  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const onStatusChangeRef = useRef(onStatusChange);
  onStatusChangeRef.current = onStatusChange;

  const fetchStatus = useCallback(async () => {
    try {
      setIsLoading(true);
      const res = await fetch('/api/status', {
        cache: 'no-store',
        headers: { Accept: 'application/json' },
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }

      const data: SystemStatusData = await res.json();
      const resolvedStatus: HealthStatus =
        data.status === 'ok' ? 'ok' : 'degraded';

      setStatus(resolvedStatus);
      if (data.services) {
        setServices(data.services);
      }
      setError(null);
      setLastChecked(new Date());

      if (onStatusChangeRef.current) {
        onStatusChangeRef.current(data);
      }
    } catch (err: any) {
      setStatus('degraded');
      setServices(DEFAULT_SERVICES);
      setError(err?.message || 'Failed to poll /api/status');
      setLastChecked(new Date());
    } finally {
      setIsLoading(false);
    }
  }, []);

  const pause = useCallback(() => {
    setIsPollingActive(false);
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const resume = useCallback(() => {
    setIsPollingActive(true);
  }, []);

  // Main polling effect
  useEffect(() => {
    if (!isPollingActive) {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      return;
    }

    // Immediate initial fetch
    fetchStatus();

    // Setup interval
    timerRef.current = setInterval(() => {
      if (pauseOnHidden && typeof document !== 'undefined' && document.hidden) {
        return;
      }
      fetchStatus();
    }, intervalMs);

    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [fetchStatus, intervalMs, isPollingActive, pauseOnHidden]);

  // Page visibility change listener
  useEffect(() => {
    if (!pauseOnHidden || typeof document === 'undefined') return;

    const handleVisibilityChange = () => {
      if (!document.hidden && isPollingActive) {
        // Tab became visible, fetch immediately to sync state
        fetchStatus();
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [fetchStatus, isPollingActive, pauseOnHidden]);

  return {
    status,
    services,
    isLoading,
    error,
    lastChecked,
    refetch: fetchStatus,
    isPolling: isPollingActive,
    pause,
    resume,
  };
}
