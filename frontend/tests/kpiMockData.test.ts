/**
 * KPI Trends mock dataset contract.
 *
 * The Marine Intelligence KPI Trends card ships a demo dataset so the chart
 * area is never an empty skeleton. Contract this test locks down:
 *
 * - Deterministic: every dataset is hand-written static data. No Math.random,
 *   no Date.now(), so two renders always produce identical bars.
 * - Complete: all 3 tabs x 3 time ranges resolve to a dataset; unknown keys
 *   return null (the component then falls back to the honest empty state).
 * - Honest: every dataset is flagged isMock + demoDisclaimer so the UI can
 *   label it as demo data rather than live telemetry.
 * - Source guard: neither the data module nor KPITrends.tsx may introduce
 *   Math.random (T1: no generated fake lines).
 *
 * Run: bun test tests/kpiMockData.test.ts
 */
import { describe, expect, it } from 'bun:test';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import {
  KPI_RANGES,
  KPI_TABS,
  getKPIDataset,
} from '../components/analytics/kpiMockData';
import type { KPITab, KPITimeRange } from '../components/analytics/kpiMockData';

const PROJECT_ROOT = join(import.meta.dir, '..');

/** Comments may discuss Math.random; only executable code is guarded. */
const stripComments = (src: string): string =>
  src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '');
const DATA_MODULE_PATH = join(
  PROJECT_ROOT,
  'components',
  'analytics',
  'kpiMockData.ts'
);
const COMPONENT_PATH = join(
  PROJECT_ROOT,
  'components',
  'analytics',
  'KPITrends.tsx'
);

describe('kpiMockData coverage', () => {
  it('exposes exactly the 3 tabs and 3 time ranges used by the card', () => {
    expect(KPI_TABS).toEqual(['ocean', 'catch', 'efficiency']);
    expect(KPI_RANGES).toEqual(['24H', '7D', '30D']);
  });

  it('resolves a dataset for every tab x range combination (9 total)', () => {
    const missing: string[] = [];
    for (const tab of KPI_TABS) {
      for (const range of KPI_RANGES) {
        const ds = getKPIDataset(tab, range);
        if (!ds) missing.push(`${tab}/${range}`);
        else expect(ds.isMock).toBe(true);
      }
    }
    expect(missing).toEqual([]);
  });

  it('returns null for unknown tab or range (component falls back to empty state)', () => {
    expect(getKPIDataset('nope' as KPITab, '24H')).toBeNull();
    expect(getKPIDataset('ocean', '1Y' as KPITimeRange)).toBeNull();
  });

  it('serves point counts that match the range: 24H=12, 7D=7, 30D=30', () => {
    const expected: Record<KPITimeRange, number> = { '24H': 12, '7D': 7, '30D': 30 };
    for (const tab of KPI_TABS) {
      for (const range of KPI_RANGES) {
        const ds = getKPIDataset(tab, range)!;
        expect(`${tab}/${range}:${ds.points.length}`).toBe(
          `${tab}/${range}:${expected[range]}`
        );
      }
    }
  });
});

describe('kpiMockData data quality', () => {
  it('every point has a non-empty label and a finite, in-range value', () => {
    for (const tab of KPI_TABS) {
      for (const range of KPI_RANGES) {
        const ds = getKPIDataset(tab, range)!;
        ds.points.forEach((p, i) => {
          expect(p.label.length).toBeGreaterThan(0);
          expect(Number.isFinite(p.value)).toBe(true);
          expect(p.value).toBeGreaterThanOrEqual(ds.min);
          expect(p.value).toBeLessThanOrEqual(ds.max);
        });
        // Labels are unique within a series so the x-axis never double-prints.
        const labels = ds.points.map((p) => p.label);
        expect(new Set(labels).size).toBe(labels.length);
        expect(ds.points.length).toBeGreaterThan(1);
        expect(ds.title.length).toBeGreaterThan(0);
        expect(ds.unit.length).toBeGreaterThan(0);
        expect(ds.demoDisclaimer.length).toBeGreaterThan(0);
      }
    }
  });

  it('is deterministic — the same tab/range always returns identical numbers', () => {
    for (const tab of KPI_TABS) {
      for (const range of KPI_RANGES) {
        const a = getKPIDataset(tab, range)!;
        const b = getKPIDataset(tab, range)!;
        expect(JSON.stringify(a.points)).toBe(JSON.stringify(b.points));
      }
    }
  });

  it('summary numbers are derived from the series, not hardcoded separately', () => {
    for (const tab of KPI_TABS) {
      for (const range of KPI_RANGES) {
        const ds = getKPIDataset(tab, range)!;
        const values = ds.points.map((p) => p.value);
        const max = Math.max(...values);
        const min = Math.min(...values);
        expect(ds.max).toBe(max);
        expect(ds.min).toBe(min);
        expect(ds.summaryLatest).toBe(values[values.length - 1]);
      }
    }
  });
});

describe('source guard: no generated fake lines (T1)', () => {
  it('kpiMockData.ts uses only static literals', () => {
    const src = stripComments(readFileSync(DATA_MODULE_PATH, 'utf8'));
    expect(src).not.toContain('Math.random');
    expect(src).not.toContain('Date.now');
    expect(src).not.toContain('generateKPIData');
  });

  it('KPITrends.tsx uses only static literals', () => {
    const src = stripComments(readFileSync(COMPONENT_PATH, 'utf8'));
    expect(src).not.toContain('Math.random');
    expect(src).not.toContain('generateKPIData');
  });

  it('KPITrends renders the demo matrix, labels it, and unlocks all ranges', () => {
    const src = stripComments(readFileSync(COMPONENT_PATH, 'utf8'));
    expect(src).toContain('getKPIDataset');
    expect(src).toContain('kpi-demo-badge');
    expect(src).toContain('kpi-demo-chart');
    // Range pills must not be hardcoded to 24H-only any more.
    expect(src).not.toContain("range !== '24H'");
    // Honest fallback survives if a dataset is ever missing.
    expect(src).toContain('kpi-empty-chart');
  });
});
