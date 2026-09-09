/**
 * CARTO & Esri Basemap Styles & Tile URL Builder
 *
 * Owner: M-D (Frontend & Maps)
 * Module: frontend/map/carto.ts
 */

export type BasemapStyle =
  | 'dark_all'
  | 'voyager'
  | 'light_all'
  | 'esri_ocean'
  | 'esri_dark'
  | 'osm';

export type BasemapProvider = 'carto' | 'esri' | 'osm';

export interface BasemapOption {
  id: BasemapStyle;
  label: string;
  icon: string;
  description: string;
  provider: BasemapProvider;
}

export const BASEMAP_OPTIONS: BasemapOption[] = [
  {
    id: 'dark_all',
    label: 'Dark Matter',
    icon: '🌙',
    description: 'Tactical night radar bridge operations',
    provider: 'carto',
  },
  {
    id: 'voyager',
    label: 'Voyager',
    icon: '🧭',
    description: 'Daytime nautical coastal navigation',
    provider: 'carto',
  },
  {
    id: 'light_all',
    label: 'Positron',
    icon: '☀️',
    description: 'High-contrast day viewing',
    provider: 'carto',
  },
  {
    id: 'esri_ocean',
    label: 'Esri Ocean',
    icon: '🌊',
    description: 'Bathymetric depth and marine relief',
    provider: 'esri',
  },
  {
    id: 'esri_dark',
    label: 'Esri Dark Gray',
    icon: '🌌',
    description: 'Tactical dark canvas for maritime night ops',
    provider: 'esri',
  },
  {
    id: 'osm',
    label: 'OpenStreetMap',
    icon: '🌐',
    description: 'Standard community open cartography fallback',
    provider: 'osm',
  },
];

export const CARTO_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions" target="_blank" rel="noopener noreferrer">CARTO</a>';

export const OSM_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors';

export const ESRI_OCEAN_ATTRIBUTION =
  '&copy; <a href="https://www.esri.com/" target="_blank" rel="noopener noreferrer">Esri</a> &mdash; Sources: GEBCO, NOAA, CHS, OSU, UNH, CSUMB, National Geographic, DeLorme, NAVTEQ, Esri';

export const ESRI_DARK_ATTRIBUTION =
  '&copy; <a href="https://www.esri.com/" target="_blank" rel="noopener noreferrer">Esri</a> &mdash; Esri, DeLorme, NAVTEQ';

/**
 * Normalizes a user-supplied basemap alias to a canonical BasemapStyle.
 * Single source of truth — reuse in tile URLs, env defaults, and query resolvers.
 * Returns undefined for unrecognized values so callers can fall back.
 */
export function normalizeBasemapStyle(
  raw: string | string[] | undefined | null
): BasemapStyle | undefined {
  if (!raw || Array.isArray(raw)) return undefined;
  const alias = raw.trim().toLowerCase();
  const table: Record<string, BasemapStyle> = {
    dark_all: 'dark_all',
    dark: 'dark_all',
    carto_dark: 'dark_all',
    voyager: 'voyager',
    carto_voyager: 'voyager',
    light_all: 'light_all',
    light: 'light_all',
    positron: 'light_all',
    carto_positron: 'light_all',
    esri_ocean: 'esri_ocean',
    ocean: 'esri_ocean',
    esri_ocean_basemap: 'esri_ocean',
    esri_dark: 'esri_dark',
    dark_gray: 'esri_dark',
    esri_dark_gray: 'esri_dark',
    osm: 'osm',
    openstreetmap: 'osm',
  };
  return table[alias];
}

/**
 * Returns dynamic attribution HTML according to the selected basemap style.
 */
export function getBasemapAttribution(style: BasemapStyle): string {
  switch (style) {
    case 'esri_ocean':
      return ESRI_OCEAN_ATTRIBUTION;
    case 'esri_dark':
      return ESRI_DARK_ATTRIBUTION;
    case 'osm':
      return OSM_ATTRIBUTION;
    case 'dark_all':
    case 'voyager':
    case 'light_all':
    default:
      return CARTO_ATTRIBUTION;
  }
}

/**
 * Returns native zoom limit where higher zooms overzoom/scale tiles without 404s.
 * 13 for Esri Ocean, 16 for Esri Dark Gray, undefined for unrestricted basemaps.
 */
export function getBasemapMaxNativeZoom(style: BasemapStyle): number | undefined {
  switch (style) {
    case 'esri_ocean':
      return 13;
    case 'esri_dark':
      return 16;
    default:
      return undefined;
  }
}

/**
 * Returns max display zoom supported for the basemap style.
 * 18 for Esri endpoints, 19 for CARTO and OpenStreetMap.
 */
export function getBasemapMaxZoom(style: BasemapStyle): number {
  switch (style) {
    case 'esri_ocean':
    case 'esri_dark':
      return 18;
    case 'dark_all':
    case 'voyager':
    case 'light_all':
    case 'osm':
    default:
      return 19;
  }
}

/**
 * Builds tile URL for CARTO, Esri MapServer, or OSM raster tiles.
 * Validates style to prevent unexpected path interpolation.
 * Appends ?api_key=${apiKey} if valid non-placeholder API key provided for CARTO.
 */
export function getBasemapTileUrl(
  style: BasemapStyle = 'dark_all',
  apiKey?: string
): string {
  const safeStyle = normalizeBasemapStyle(style) || 'dark_all';

  if (safeStyle === 'osm') {
    return 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
  }

  if (safeStyle === 'esri_ocean') {
    return 'https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean/MapServer/tile/{z}/{y}/{x}';
  }

  if (safeStyle === 'esri_dark') {
    return 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}';
  }

  const rawKey =
    apiKey ||
    (typeof process !== 'undefined'
      ? process.env.NEXT_PUBLIC_CARTO_API_KEY
      : undefined);

  const key = (rawKey || '').trim();
  const normalizedKey = key.toLowerCase();
  const baseUrl = `https://{s}.basemaps.cartocdn.com/rastertiles/${safeStyle}/{z}/{x}/{y}{r}.png`;

  // Keyless CDN fallback: reject placeholders and null-like literals
  // (matches backend/routers/tiles.py has_carto_key logic).
  if (
    key &&
    normalizedKey !== 'undefined' &&
    normalizedKey !== 'null' &&
    normalizedKey !== 'none' &&
    normalizedKey !== 'your_carto_api_key_here' &&
    !normalizedKey.startsWith('your_')
  ) {
    return `${baseUrl}?api_key=${encodeURIComponent(key)}`;
  }

  return baseUrl;
}

/**
 * Resolves default basemap style from environment or falls back to 'dark_all'.
 */
export function getDefaultBasemapStyle(): BasemapStyle {
  if (
    typeof process !== 'undefined' &&
    process.env.NEXT_PUBLIC_CARTO_BASEMAP_STYLE
  ) {
    return (
      normalizeBasemapStyle(process.env.NEXT_PUBLIC_CARTO_BASEMAP_STYLE) ||
      'dark_all'
    );
  }

  return 'dark_all';
}
