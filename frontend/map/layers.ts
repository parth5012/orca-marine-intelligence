/**
 * Shared map layer registry (UI-MIG-T5).
 *
 * Owner: M-D (Frontend & Maps)
 * Module: frontend/map/layers.ts
 *
 * Union of the 5 LIVE engine keys (pfz/eez/mpa/imbl/weather — the only keys
 * `MapInner` draws from) and the 8 design-system pills copied from the source
 * `LayerControl` (sst/chlorophyll/waves/wind/currents/cyclone/lightning/
 * restricted, plus source `eez`/`pfz` which already exist).
 *
 * LAYER_SOURCE_MAPPING — how each visual-only key reuses EXISTING live
 * sources (zero new backend, zero mocks):
 * - sst:         PFZ feature props (sst/sst_c/temperature_c) + live weather
 *                temperature_c at map center. OFF = markers render neutral
 *                (no suitability tint), drawer hides the SST spec tile.
 * - chlorophyll: PFZ feature props (chlorophyll/chl). OFF = marker glow
 *                suppressed, drawer hides the chlorophyll spec tile.
 * - waves:       live weather wave_height_m (subset of `weather`). OFF =
 *                wave card hidden in the telemetry overlay / drawer.
 * - wind:        live weather wind_speed_kt (subset of `weather`). OFF =
 *                wind card hidden. Master `weather` OFF hides both anyway.
 * - currents:    live weather current_speed_kt + the MapInner nav polyline
 *                (userLocation/center -> target). OFF = nav line hidden.
 * - cyclone:     RESERVED for GET /api/weather/cyclone. No live overlay is
 *                drawn today (DangerAgent internal only); the pill is
 *                accepted and stored but is a documented no-op until wired.
 * - lightning:   RESERVED convective alert. No live source today; pill is a
 *                documented no-op (never mocked with fake strikes).
 * - restricted:  EMPHASIS over the existing mpa+imbl boundary sources. OFF
 *                dims MPA/IMBL opacity; it NEVER hides them while the old
 *                mpa/imbl toggles are on (new pills do not break old).
 *
 * Old callers keep working: MapInner treats every extended key as optional
 * and defaults missing keys to `true` (full visuals), so the 5-key
 * `activeLayers` objects from HomeScreen / page shell render unchanged.
 */

export const OLD_LAYER_KEYS = [
  'pfz',
  'eez',
  'mpa',
  'imbl',
  'weather',
] as const;

export type OldLayerKey = (typeof OLD_LAYER_KEYS)[number];

export const NEW_VISUAL_LAYER_KEYS = [
  'sst',
  'chlorophyll',
  'waves',
  'wind',
  'currents',
  'cyclone',
  'lightning',
  'restricted',
] as const;

export type NewVisualLayerKey = (typeof NEW_VISUAL_LAYER_KEYS)[number];

export const ALL_LAYER_KEYS = [
  ...OLD_LAYER_KEYS,
  ...NEW_VISUAL_LAYER_KEYS,
] as const;

export type AnyLayerKey = (typeof ALL_LAYER_KEYS)[number];

export type LayerSourceKind =
  | 'pfz'
  | 'weather'
  | 'boundaries'
  | 'reserved';

export const LAYER_SOURCE_MAPPING: Record<
  NewVisualLayerKey,
  { source: LayerSourceKind; description: string }
> = {
  sst: {
    source: 'pfz',
    description:
      'Visual tint over live PFZ props + live weather temperature_c. No new fetch.',
  },
  chlorophyll: {
    source: 'pfz',
    description:
      'Visual glow/spec over live PFZ chlorophyll props. No new fetch.',
  },
  waves: {
    source: 'weather',
    description:
      'Subset of the live weather layer (wave_height_m). No new fetch.',
  },
  wind: {
    source: 'weather',
    description:
      'Subset of the live weather layer (wind_speed_kt). No new fetch.',
  },
  currents: {
    source: 'weather',
    description:
      'Nav polyline + live current_speed_kt readout. Same sources, no new fetch.',
  },
  cyclone: {
    source: 'reserved',
    description:
      'Reserved for GET /api/weather/cyclone. Documented no-op until wired; never mocked.',
  },
  lightning: {
    source: 'reserved',
    description:
      'Reserved convective alert. Documented no-op until a live source exists; never mocked.',
  },
  restricted: {
    source: 'boundaries',
    description:
      'Emphasis dim over existing MPA+IMBL geometry. Never hides while mpa/imbl are on.',
  },
};

/** True for the 5 live-engine keys MapInner draws. */
export function isOldLayerKey(key: string): key is OldLayerKey {
  return (OLD_LAYER_KEYS as readonly string[]).includes(key);
}

/**
 * Filter an extended layer bag down to the 5 engine keys for MapInner.
 * Missing keys default to true (unchanged legacy visuals).
 */
export function filterEngineLayers(active?: Record<string, boolean | undefined>): {
  pfz?: boolean;
  eez?: boolean;
  mpa?: boolean;
  imbl?: boolean;
  weather?: boolean;
} {
  if (!active) return { pfz: true, eez: true, mpa: true, imbl: true, weather: true };
  const out: Record<string, boolean> = {};
  for (const k of OLD_LAYER_KEYS) {
    out[k] = active[k] !== false;
  }
  return out as {
    pfz?: boolean;
    eez?: boolean;
    mpa?: boolean;
    imbl?: boolean;
    weather?: boolean;
  };
}

/** Extended key present and not explicitly off (missing => true). */
export function isLayerOn(
  active: Record<string, boolean | undefined> | undefined,
  key: AnyLayerKey
): boolean {
  if (!active) return true;
  return active[key] !== false;
}
