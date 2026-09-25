/**
 * kpiMockData — deterministic demo dataset for the Marine Intelligence KPI
 * Trends card.
 *
 * Why this file exists: the KPI chart area used to be a permanent skeleton
 * ("7-day trends collecting") because there is no multi-day series in the
 * backend yet. This module supplies a hand-written, static dataset so the card
 * can be demonstrated end-to-end (3 tabs x 3 time ranges) without inventing
 * numbers at render time.
 *
 * Honesty contract (T1, unchanged in spirit):
 * - Values are literals in this file. No Math.random(), no Date.now(),
 *   no generateKPIData(). Calling getKPIData twice returns byte-identical
 *   points, so a re-render or the refresh button can never "reshuffle" bars.
 * - Every dataset carries isMock: true + demoDisclaimer; the UI must label the
 *   chart as demo data so it is never mistaken for live INCOIS telemetry.
 * - Unknown tab/range returns null and the caller keeps the real empty state.
 *
 * Swap path: replace RAW with a fetch against the Postgres/Redis rolling
 * window once the backend ships temporal series — the KPIDataset shape is the
 * contract the component consumes, so only this module changes.
 */

export type KPITab = 'ocean' | 'catch' | 'efficiency';
export type KPITimeRange = '24H' | '7D' | '30D';

export const KPI_TABS = ['ocean', 'catch', 'efficiency'] as const;
export const KPI_RANGES = ['24H', '7D', '30D'] as const;

export type KPIChartType = 'area' | 'bar';

export interface KPIPoint {
  label: string;
  value: number;
}

export interface KPIDataset {
  tab: KPITab;
  range: KPITimeRange;
  title: string;
  unit: string;
  summaryLabel: string;
  chartType: KPIChartType;
  points: KPIPoint[];
  min: number;
  max: number;
  summaryLatest: number;
  isMock: true;
  demoDisclaimer: string;
}

/** Shared axis labels — fixed so 24H/7D/30D read the same everywhere. */
const HOURS_24H = [
  '00:00', '02:00', '04:00', '06:00', '08:00', '10:00',
  '12:00', '14:00', '16:00', '18:00', '20:00', '22:00',
];
const DAYS_7D = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const DAYS_30D = [
  '01', '02', '03', '04', '05', '06', '07', '08', '09', '10',
  '11', '12', '13', '14', '15', '16', '17', '18', '19', '20',
  '21', '22', '23', '24', '25', '26', '27', '28', '29', '30',
];

const DEMO_DISCLAIMER =
  'Demo dataset — not live telemetry. Static values until the 7-day Postgres/Redis rolling window ships.';

interface SeriesSpec {
  title: string;
  unit: string;
  summaryLabel: string;
  chartType: KPIChartType;
  values: number[];
}

/**
 * Static literals only. Each `values` array is aligned 1:1 with the matching
 * label array (12 / 7 / 30 entries) and the last value is what the summary
 * badge shows, so the chart and the headline can never disagree.
 */
const RAW: Record<KPITab, Record<KPITimeRange, SeriesSpec>> = {
  ocean: {
    '24H': {
      title: 'Sea Surface Temperature',
      unit: '°C',
      summaryLabel: 'Latest SST',
      chartType: 'area',
      // Ends on 28.4 to match the live "Today SST 28.4°C" snapshot card.
      values: [27.9, 27.7, 27.5, 27.6, 28.1, 28.6, 28.9, 29.1, 28.9, 28.6, 28.3, 28.4],
    },
    '7D': {
      title: 'Sea Surface Temperature',
      unit: '°C',
      summaryLabel: 'Latest SST',
      chartType: 'area',
      values: [28.1, 28.3, 28.0, 27.8, 28.2, 28.6, 28.4],
    },
    '30D': {
      title: 'Sea Surface Temperature',
      unit: '°C',
      summaryLabel: 'Latest SST',
      chartType: 'area',
      values: [
        27.8, 28.0, 28.2, 28.1, 27.9, 27.7, 27.6, 27.8, 28.1, 28.4,
        28.6, 28.5, 28.3, 28.0, 27.9, 27.7, 27.8, 28.0, 28.3, 28.5,
        28.7, 28.6, 28.4, 28.2, 28.1, 28.3, 28.5, 28.6, 28.5, 28.4,
      ],
    },
  },
  catch: {
    '24H': {
      title: 'PFZ Catch Probability',
      unit: '%',
      summaryLabel: 'Latest probability',
      chartType: 'bar',
      values: [52, 49, 47, 50, 55, 61, 66, 70, 72, 68, 63, 64],
    },
    '7D': {
      title: 'PFZ Catch Probability',
      unit: '%',
      summaryLabel: 'Latest probability',
      chartType: 'bar',
      values: [58, 62, 55, 51, 60, 67, 64],
    },
    '30D': {
      title: 'PFZ Catch Probability',
      unit: '%',
      summaryLabel: 'Latest probability',
      chartType: 'bar',
      values: [
        44, 46, 45, 48, 50, 52, 49, 47, 46, 48,
        51, 54, 56, 55, 53, 50, 49, 52, 55, 58,
        60, 62, 59, 57, 58, 61, 64, 66, 65, 64,
      ],
    },
  },
  efficiency: {
    '24H': {
      title: 'Voyage Efficiency Score',
      unit: '%',
      summaryLabel: 'Latest score',
      chartType: 'bar',
      values: [61, 63, 60, 58, 62, 66, 70, 73, 71, 69, 67, 68],
    },
    '7D': {
      title: 'Voyage Efficiency Score',
      unit: '%',
      summaryLabel: 'Latest score',
      chartType: 'bar',
      values: [64, 67, 63, 60, 66, 71, 68],
    },
    '30D': {
      title: 'Voyage Efficiency Score',
      unit: '%',
      summaryLabel: 'Latest score',
      chartType: 'bar',
      values: [
        58, 60, 59, 61, 63, 62, 60, 58, 57, 59,
        62, 65, 67, 66, 64, 62, 61, 63, 66, 69,
        71, 70, 68, 67, 69, 72, 74, 73, 71, 70,
      ],
    },
  },
};

const LABELS: Record<KPITimeRange, string[]> = {
  '24H': HOURS_24H,
  '7D': DAYS_7D,
  '30D': DAYS_30D,
};

/**
 * Resolve the demo series for a tab + time range.
 * Returns null for anything outside the supported matrix so callers can keep
 * an honest empty state instead of rendering fabricated bars.
 */
export function getKPIDataset(
  tab: KPITab,
  range: KPITimeRange
): KPIDataset | null {
  const byTab: Record<string, Record<string, SeriesSpec> | undefined> = RAW;
  const tabSeries = byTab[tab];
  if (!tabSeries) return null;

  const spec: SeriesSpec | undefined = tabSeries[range];
  const labels = LABELS[range];
  if (!spec || !labels) return null;
  if (spec.values.length !== labels.length) return null;

  const points: KPIPoint[] = labels.map((label, i) => ({
    label,
    value: spec.values[i],
  }));

  const values = points.map((p) => p.value);

  return {
    tab,
    range,
    title: spec.title,
    unit: spec.unit,
    summaryLabel: spec.summaryLabel,
    chartType: spec.chartType,
    points,
    min: Math.min(...values),
    max: Math.max(...values),
    summaryLatest: values[values.length - 1],
    isMock: true,
    demoDisclaimer: DEMO_DISCLAIMER,
  };
}

/** Format a value with the dataset unit (°C keeps 1 decimal, % rounds). */
export function formatKPIValue(value: number, unit: string): string {
  return unit === '°C' ? `${value.toFixed(1)}°C` : `${Math.round(value)}${unit}`;
}

export default getKPIDataset;
