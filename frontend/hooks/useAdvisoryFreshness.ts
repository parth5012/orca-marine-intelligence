/**
 * Advisory Freshness Hook
 *
 * Owner: M-D (Frontend & Maps)
 * Module: frontend/hooks/useAdvisoryFreshness.ts
 */

'use client';

import { useState, useEffect } from 'react';
import {
  evaluateFreshness,
  type FreshnessInput,
  type FreshnessResult,
} from '../lib/advisoryFreshness';

const STORAGE_KEY = 'orca-advisory-snapshot';
const TTL_MS = 60_000;

export const ADVISORY_CACHE_TTL_MS = TTL_MS;

export interface AdvisoryFreshnessState extends FreshnessResult {
  offline: boolean;
  loading: boolean;
}

interface StoredSnapshot {
  validUntil?: string | null;
  capturedAt?: string | null;
  weatherAt?: string | null;
}

interface CacheEntry {
  at: number;
  data: StoredSnapshot;
}

let cache: CacheEntry | null = null;
let inflight: Promise<StoredSnapshot> | null = null;

/**
 * Weather measurement time, published by whoever actually fetches weather
 * (MapInner) rather than by the PFZ snapshot fetch. `null` means unknown —
 * never "now": a PFZ fetch time is not a weather measurement time.
 */
let weatherAt: string | null = null;
const weatherListeners = new Set<(ts: string | null) => void>();

export function setWeatherTimestamp(ts: string | null): void {
  weatherAt = typeof ts === 'string' && ts.length > 0 ? ts : null;
  if (typeof window !== 'undefined') {
    try {
      const stored = readStoredSnapshot() ?? {};
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...stored, weatherAt }));
    } catch {
      // Storage quota or privacy restriction
    }
  }
  for (const listener of [...weatherListeners]) {
    listener(weatherAt);
  }
}

export function getWeatherTimestamp(): string | null {
  return weatherAt;
}

export function subscribeWeatherTimestamp(
  listener: (ts: string | null) => void
): () => void {
  weatherListeners.add(listener);
  return () => {
    weatherListeners.delete(listener);
  };
}

export function clearAdvisoryFreshnessCache(): void {
  cache = null;
  inflight = null;
}

function readStoredSnapshot(): StoredSnapshot | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

/**
 * Fetch PFZ advisory metadata with 60s caching + in-flight dedup.
 * Resolves to the parsed snapshot payload, or rejects on fetch failure.
 */
export async function fetchAdvisorySnapshot(): Promise<StoredSnapshot> {
  const now = Date.now();
  if (cache && now - cache.at < TTL_MS) {
    return cache.data;
  }

  if (inflight) return inflight;

  const req = fetch('/api/pfz', { cache: 'no-store' })
    .then(async (res) => {
      if (!res.ok) {
        throw new Error(`PFZ fetch status: ${res.status}`);
      }
      const body = await res.json();
      const validUntil = body?.valid_until ?? null;
      const capturedAt = body?.timestamp ?? null;

      const snapshot: StoredSnapshot = {
        validUntil,
        capturedAt,
        weatherAt: weatherAt ?? readStoredSnapshot()?.weatherAt ?? null,
      };

      cache = { at: Date.now(), data: snapshot };

      if (typeof window !== 'undefined') {
        try {
          localStorage.setItem(STORAGE_KEY, JSON.stringify(snapshot));
        } catch {
          // Storage quota or privacy restriction
        }
      }

      return snapshot;
    })
    .finally(() => {
      inflight = null;
    });

  inflight = req;
  return req;
}

export function useAdvisoryFreshness(): AdvisoryFreshnessState {
  const [offline, setOffline] = useState<boolean>(() => {
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
      return true;
    }
    return false;
  });
  const [loading, setLoading] = useState<boolean>(() => {
    const now = Date.now();
    if (cache && now - cache.at < TTL_MS) {
      return false;
    }
    return true;
  });
  const [input, setInput] = useState<FreshnessInput>(() => {
    const stored = readStoredSnapshot();
    const liveWeatherAt = weatherAt ?? stored?.weatherAt ?? null;
    if (cache) {
      return {
        validUntil: cache.data.validUntil,
        capturedAt: cache.data.capturedAt,
        weatherAt: cache.data.weatherAt ?? liveWeatherAt,
      };
    }
    if (stored) {
      return {
        validUntil: stored.validUntil,
        capturedAt: stored.capturedAt,
        weatherAt: liveWeatherAt,
      };
    }
    return { weatherAt: weatherAt };
  });

  useEffect(() => {
    let mounted = true;
    const unsubscribe = subscribeWeatherTimestamp((ts) => {
      if (mounted) {
        setInput((prev) => ({ ...prev, weatherAt: ts }));
      }
    });

    async function loadFreshness() {
      try {
        const snapshot = await fetchAdvisorySnapshot();
        if (mounted) {
          setInput({
            validUntil: snapshot.validUntil,
            capturedAt: snapshot.capturedAt,
            weatherAt: weatherAt ?? snapshot.weatherAt ?? null,
          });
          setOffline(false);
          setLoading(false);
        }
      } catch {
        const stored = cache?.data ?? readStoredSnapshot();
        if (mounted) {
          if (stored) {
            setInput({
              validUntil: stored.validUntil,
              capturedAt: stored.capturedAt,
              weatherAt: weatherAt ?? stored.weatherAt ?? null,
            });
          } else {
            setInput({ weatherAt: weatherAt });
          }
          setOffline(true);
          setLoading(false);
        }
      }
    }

    loadFreshness();

    return () => {
      mounted = false;
      unsubscribe();
    };
  }, []);

  const result = evaluateFreshness(input);

  return {
    ...result,
    offline,
    loading,
  };
}
