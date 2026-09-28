/**
 * Advisory Freshness & Caution-Floor Tests
 *
 * Owner: M-D (Frontend & Maps)
 * Module: frontend/tests/advisoryFreshness.test.ts
 *
 * Verifies staleness calculation, age formatting, caution flooring,
 * and integration with resolveSeaStatus, SafetyBadge, and StaleDataBanner.
 *
 * Run: bun test tests/advisoryFreshness.test.ts
 */

import React from 'react';
import path from 'path';
import { describe, expect, it } from 'bun:test';
import { renderToStaticMarkup } from 'react-dom/server';
import {
  evaluateFreshness,
  applyCautionFloor,
  formatAge,
  PFZ_STALE_FALLBACK_MS,
  WEATHER_STALE_MS,
  type AdvisoryTier,
} from '../lib/advisoryFreshness';
import SafetyBadge, { resolveSeaStatus } from '../map/SafetyBadge';
import StaleDataBanner from '../components/pwa/StaleDataBanner';
import {
  fetchAdvisorySnapshot,
  clearAdvisoryFreshnessCache,
  ADVISORY_CACHE_TTL_MS,
} from '../hooks/useAdvisoryFreshness';

describe('Advisory Freshness & Caution Floor Core', () => {
  it('exports expected constants', () => {
    expect(PFZ_STALE_FALLBACK_MS).toBe(86_400_000);
    expect(WEATHER_STALE_MS).toBe(10_800_000);
  });

  it('1. Fresh valid_until in the future -> not stale, reasons = ["fresh"]', () => {
    const now = 1_700_000_000_000;
    const future = new Date(now + 2 * 3_600_000).toISOString();
    const res = evaluateFreshness({ validUntil: future, now });

    expect(res.stale).toBe(false);
    expect(res.pfzStale).toBe(false);
    expect(res.weatherStale).toBe(false);
    expect(res.reasons).toEqual(['fresh']);
  });

  it('2. now past valid_until -> pfzStale, stale, reason pfz_expired', () => {
    const now = 1_700_000_000_000;
    const past = new Date(now - 30 * 60_000).toISOString();
    const res = evaluateFreshness({ validUntil: past, now });

    expect(res.stale).toBe(true);
    expect(res.pfzStale).toBe(true);
    expect(res.reasons).toContain('pfz_expired');
  });

  it('3. No validUntil but capturedAt 23h ago -> not stale; 25h ago -> stale with reason pfz_no_validity_window', () => {
    const now = 1_700_000_000_000;
    const captured23h = new Date(now - 23 * 3_600_000).toISOString();
    const res23 = evaluateFreshness({ capturedAt: captured23h, now });

    expect(res23.stale).toBe(false);
    expect(res23.pfzStale).toBe(false);
    expect(res23.reasons).toEqual(['fresh']);

    const captured25h = new Date(now - 25 * 3_600_000).toISOString();
    const res25 = evaluateFreshness({ capturedAt: captured25h, now });

    expect(res25.stale).toBe(true);
    expect(res25.pfzStale).toBe(true);
    expect(res25.reasons).toContain('pfz_no_validity_window');
  });

  it('4. Neither validUntil nor capturedAt -> stale, pfz_no_validity_window, ageMs === null, ageLabel === null', () => {
    const now = 1_700_000_000_000;
    const res = evaluateFreshness({ now });

    expect(res.stale).toBe(true);
    expect(res.pfzStale).toBe(true);
    expect(res.reasons).toContain('pfz_no_validity_window');
    expect(res.ageMs).toBeNull();
    expect(res.ageLabel).toBeNull();
  });

  it('5. weatherAt 4h ago -> weatherStale, reason weather_stale; 2h ago -> not stale; weatherAt: null -> not stale', () => {
    const now = 1_700_000_000_000;
    const futureValid = new Date(now + 3_600_000).toISOString();

    const w4h = new Date(now - 4 * 3_600_000).toISOString();
    const res4h = evaluateFreshness({ validUntil: futureValid, weatherAt: w4h, now });
    expect(res4h.stale).toBe(true);
    expect(res4h.weatherStale).toBe(true);
    expect(res4h.reasons).toContain('weather_stale');

    const w2h = new Date(now - 2 * 3_600_000).toISOString();
    const res2h = evaluateFreshness({ validUntil: futureValid, weatherAt: w2h, now });
    expect(res2h.stale).toBe(false);
    expect(res2h.weatherStale).toBe(false);
    expect(res2h.reasons).toEqual(['fresh']);

    const resNull = evaluateFreshness({ validUntil: futureValid, weatherAt: null, now });
    expect(resNull.stale).toBe(false);
    expect(resNull.weatherStale).toBe(false);
    expect(resNull.reasons).toEqual(['fresh']);
  });

  it('6. Both stale -> reasons contains both reasons, stale === true', () => {
    const now = 1_700_000_000_000;
    const pastValid = new Date(now - 3_600_000).toISOString();
    const w4h = new Date(now - 4 * 3_600_000).toISOString();
    const res = evaluateFreshness({ validUntil: pastValid, weatherAt: w4h, now });

    expect(res.stale).toBe(true);
    expect(res.pfzStale).toBe(true);
    expect(res.weatherStale).toBe(true);
    expect(res.reasons).toContain('pfz_expired');
    expect(res.reasons).toContain('weather_stale');
    expect(res.reasons.length).toBe(2);
  });

  it('7. ageLabel formatting: 30s -> "just now"; 45min -> "45m old"; 6h -> "6h old"; 3d -> "3d old"', () => {
    expect(formatAge(30_000)).toBe('just now');
    expect(formatAge(45 * 60_000)).toBe('45m old');
    expect(formatAge(6 * 3_600_000)).toBe('6h old');
    expect(formatAge(3 * 86_400_000)).toBe('3d old');
  });

  it('8. Negative age (future validUntil) clamps to 0 and yields "just now"', () => {
    const now = 1_700_000_000_000;
    const future = new Date(now + 3_600_000).toISOString();
    const res = evaluateFreshness({ validUntil: future, now });

    expect(res.ageMs).toBe(0);
    expect(res.ageLabel).toBe('just now');
  });

  it('9. Invalid date strings ("not-a-date") behave as absent (no throw)', () => {
    const now = 1_700_000_000_000;
    const res = evaluateFreshness({
      validUntil: 'not-a-date',
      capturedAt: 'not-a-date',
      weatherAt: 'not-a-date',
      now,
    });

    expect(res.stale).toBe(true);
    expect(res.pfzStale).toBe(true);
    expect(res.weatherStale).toBe(false);
    expect(res.reasons).toContain('pfz_no_validity_window');
    expect(res.ageMs).toBeNull();
    expect(res.ageLabel).toBeNull();
  });

  it('10. applyCautionFloor: "safe" -> "caution", and invariant that flooring never yields "safe"', () => {
    expect(applyCautionFloor('safe')).toBe('caution');
    expect(applyCautionFloor('caution')).toBe('caution');
    expect(applyCautionFloor('danger')).toBe('danger');
    expect(applyCautionFloor('unknown')).toBe('unknown');

    const tiers: AdvisoryTier[] = ['safe', 'caution', 'danger', 'unknown'];
    for (const tier of tiers) {
      expect(applyCautionFloor(tier)).not.toBe('safe');
    }
  });

  it('11. Integration with real badge resolveSeaStatus', () => {
    const freshVerdict = resolveSeaStatus('1.0', '10');
    expect(freshVerdict).toBe('safe');
    expect(applyCautionFloor(freshVerdict)).toBe('caution');

    const dangerVerdict = resolveSeaStatus('3.0', '10');
    expect(dangerVerdict).toBe('danger');
    expect(applyCautionFloor(dangerVerdict)).toBe('danger');

    const unknownVerdict = resolveSeaStatus(null, null);
    expect(unknownVerdict).toBe('unknown');
    expect(applyCautionFloor(unknownVerdict)).toBe('unknown');
  });

  it('evaluates age from capturedAt when validUntil is missing', () => {
    const now = 1_700_000_000_000;
    const captured2h = new Date(now - 2 * 3_600_000).toISOString();
    const res = evaluateFreshness({ capturedAt: captured2h, now });

    expect(res.ageMs).toBe(2 * 3_600_000);
    expect(res.ageLabel).toBe('2h old');
    expect(res.stale).toBe(false);
  });

  it('defaults to Date.now() when now input is omitted', () => {
    const future = new Date(Date.now() + 60_000).toISOString();
    const res = evaluateFreshness({ validUntil: future });
    expect(res.stale).toBe(false);
  });

  it('renders SafetyBadge with stale prop floored to CAUTION with data-stale', () => {
    const freshHtml = renderToStaticMarkup(
      React.createElement(SafetyBadge, {
        waves: 1.0,
        wind: 10,
        stale: false,
      })
    );
    expect(freshHtml).toContain('data-status="safe"');
    expect(freshHtml).toContain('SEA SAFE');
    expect(freshHtml).not.toContain('data-stale="true"');

    const staleHtml = renderToStaticMarkup(
      React.createElement(SafetyBadge, {
        waves: 1.0,
        wind: 10,
        stale: true,
      })
    );
    expect(staleHtml).toContain('data-status="caution"');
    expect(staleHtml).toContain('CAUTION');
    expect(staleHtml).not.toContain('SEA SAFE');
    expect(staleHtml).toContain('data-stale="true"');
    expect(staleHtml).toContain('(stale advisory)');
  });

  it('StaleDataBanner renders null when online and fresh', () => {
    const html = renderToStaticMarkup(
      React.createElement(StaleDataBanner, {
        result: {
          stale: false,
          pfzStale: false,
          weatherStale: false,
          ageMs: 0,
          ageLabel: 'just now',
          reasons: ['fresh'],
        },
        offline: false,
      })
    );
    expect(html).toBe('');
  });

  it('StaleDataBanner renders stale-but-online copy with age and CAUTION', () => {
    const html = renderToStaticMarkup(
      React.createElement(StaleDataBanner, {
        result: {
          stale: true,
          pfzStale: true,
          weatherStale: false,
          ageMs: 6 * 3_600_000,
          ageLabel: '6h old',
          reasons: ['pfz_expired'],
        },
        offline: false,
      })
    );
    expect(html).toContain('data-testid="stale-data-banner"');
    expect(html).toContain('role="status"');
    expect(html).toContain('data-stale-reasons="pfz_expired"');
    expect(html).toContain('Advisory is 6h old — safety shown at CAUTION');
    expect(html).toContain('bg-amber-950/80');
  });

  it('StaleDataBanner renders offline copy with ageLabel', () => {
    const html = renderToStaticMarkup(
      React.createElement(StaleDataBanner, {
        result: {
          stale: true,
          pfzStale: true,
          weatherStale: false,
          ageMs: 6 * 3_600_000,
          ageLabel: '6h old',
          reasons: ['pfz_expired'],
        },
        offline: true,
      })
    );
    expect(html).toContain('Offline — showing advisory from 6h old');
  });

  it('StaleDataBanner renders offline copy when ageLabel is null', () => {
    const html = renderToStaticMarkup(
      React.createElement(StaleDataBanner, {
        result: {
          stale: true,
          pfzStale: true,
          weatherStale: false,
          ageMs: null,
          ageLabel: null,
          reasons: ['pfz_no_validity_window'],
        },
        offline: true,
      })
    );
    expect(html).toContain('Offline — advisory age unknown');
  });

  it('StaleDataBanner renders stale-but-online copy when ageLabel is null', () => {
    const html = renderToStaticMarkup(
      React.createElement(StaleDataBanner, {
        result: {
          stale: true,
          pfzStale: true,
          weatherStale: false,
          ageMs: null,
          ageLabel: null,
          reasons: ['pfz_no_validity_window'],
        },
        offline: false,
      })
    );
    expect(html).toContain('Advisory age unknown — safety shown at CAUTION');
  });
});

describe('Advisory Freshness Fetch De-duplication & Caching', () => {
  it('deduplicates concurrent fetches into a single network call', async () => {
    clearAdvisoryFreshnessCache();
    const originalFetch = globalThis.fetch;
    let fetchCount = 0;

    globalThis.fetch = (async (url: string) => {
      fetchCount++;
      await new Promise((r) => setTimeout(r, 20));
      return {
        ok: true,
        status: 200,
        json: async () => ({
          valid_until: new Date(Date.now() + 3_600_000).toISOString(),
          timestamp: new Date().toISOString(),
        }),
      } as any;
    }) as any;

    try {
      const results = await Promise.all([
        fetchAdvisorySnapshot(),
        fetchAdvisorySnapshot(),
        fetchAdvisorySnapshot(),
        fetchAdvisorySnapshot(),
        fetchAdvisorySnapshot(),
      ]);

      expect(fetchCount).toBe(1);
      expect(results.length).toBe(5);
      expect(results[0].validUntil).toBeDefined();
      expect(results[1]).toEqual(results[0]);

      // Subsequent call within TTL reuses cache
      const cached = await fetchAdvisorySnapshot();
      expect(fetchCount).toBe(1);
      expect(cached).toEqual(results[0]);
    } finally {
      globalThis.fetch = originalFetch;
      clearAdvisoryFreshnessCache();
    }
  });

  it('rejects without unhandled error and clears inflight on network failure', async () => {
    clearAdvisoryFreshnessCache();
    const originalFetch = globalThis.fetch;

    globalThis.fetch = (async () => {
      throw new Error('Network failure');
    }) as any;

    try {
      let threw = false;
      try {
        await fetchAdvisorySnapshot();
      } catch (err: any) {
        threw = true;
        expect(err.message).toBe('Network failure');
      }
      expect(threw).toBe(true);

      // Inflight was cleared
      let threwSecond = false;
      try {
        await fetchAdvisorySnapshot();
      } catch {
        threwSecond = true;
      }
      expect(threwSecond).toBe(true);
    } finally {
      globalThis.fetch = originalFetch;
      clearAdvisoryFreshnessCache();
    }
  });
});

describe('SafetyBadge stale prop regression guard (source-level check)', () => {
  const CALL_SITE_FILES = [
    'officer/OfficerTopBar.tsx',
    'officer/SafetyBanner.tsx',
    'components/layout/Navbar.tsx',
    'map/MapInner.tsx',
    'map/ExploreMap.tsx',
  ];

  for (const relativePath of CALL_SITE_FILES) {
    it(`ensures all <SafetyBadge> call sites in ${relativePath} pass stale prop`, async () => {
      const fullPath = path.resolve(__dirname, '..', relativePath);
      const content = await Bun.file(fullPath).text();
      const badgeRegex = /<SafetyBadge[\s\S]*?(?:\/>|>)/g;
      const matches = content.match(badgeRegex);

      expect(matches).not.toBeNull();
      expect(matches!.length).toBeGreaterThan(0);

      for (const match of matches!) {
        expect(match).toMatch(/\bstale\s*=/);
      }
    });
  }
});

describe('MapInner Offline Weather Preservation & Caution Invariant (Gap B)', () => {
  it('floors prior safe measurements to CAUTION when source is stale_cache', () => {
    // Simulating prior live measurement: waves 1.0m, wind 10kt (which would normally be SAFE)
    const prior = {
      wave_height_m: 1.0,
      wind_speed_kt: 10,
      danger: 'none',
      badge: 'green',
      source: 'stale_cache',
    };

    const isStale = prior.source === 'stale_cache';
    const html = renderToStaticMarkup(
      React.createElement(SafetyBadge, {
        waves: prior.wave_height_m,
        wind: prior.wind_speed_kt,
        danger: prior.danger,
        badge: prior.badge,
        stale: isStale,
      })
    );

    expect(html).toContain('data-status="caution"');
    expect(html).toContain('CAUTION');
    expect(html).not.toContain('SEA SAFE');
    expect(html).toContain('data-stale="true"');
    expect(html).toContain('Waves: 1m, Wind: 10 kts');
  });

  it('preserves unknown/amber verdict when no prior measurements exist', () => {
    const offlineFallback = {
      wave_height_m: undefined,
      wind_speed_kt: undefined,
      danger: 'unknown',
      badge: 'amber',
      source: 'offline_fallback',
    };

    const isStale = false;
    const html = renderToStaticMarkup(
      React.createElement(SafetyBadge, {
        waves: offlineFallback.wave_height_m,
        wind: offlineFallback.wind_speed_kt,
        danger: offlineFallback.danger,
        badge: offlineFallback.badge,
        stale: isStale,
      })
    );

    expect(html).toContain('data-status="unknown"');
    expect(html).toContain('UNKNOWN');
    expect(html).not.toContain('SEA SAFE');
    expect(html).not.toContain('CAUTION');
  });
});


