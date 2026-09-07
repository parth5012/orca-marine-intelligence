/**
 * CARTO Basemap Styles & Tile URL Builder
 *
 * Owner: M-D (Frontend & Maps)
 * Module: frontend/map/carto.ts
 */

export type BasemapStyle = 'dark_all' | 'voyager' | 'light_all' | 'osm';

export interface BasemapOption {
  id: BasemapStyle;
  label: string;
  icon: string;
  description: string;
}

export const BASEMAP_OPTIONS: BasemapOption[] = [
  {
    id: 'dark_all',
    label: 'Dark Matter',
    icon: '🌙',
    description: 'Tactical night radar & bridge operations',
  },
  {
    id: 'voyager',
    label: 'Voyager',
    icon: '🧭',
    description: 'Daytime nautical & coastal navigation',
  },
  {
    id: 'light_all',
    label: 'Positron',
    icon: '☀️',
    description: 'High-contrast day viewing',
  },
  {
    id: 'osm',
    label: 'OpenStreetMap',
    icon: '🌐',
    description: 'Standard community open cartography fallback',
  },
];

export const CARTO_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions" target="_blank" rel="noopener noreferrer">CARTO</a>';

export const OSM_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors';

/**
 * Builds the tile URL for CARTO or OSM raster tiles.
 * Validates style to prevent unexpected path interpolation.
 * Appends ?api_key=${apiKey} if a valid non-placeholder API key is provided.
 */
export function getBasemapTileUrl(
  style: BasemapStyle = 'dark_all',
  apiKey?: string
): string {
  const validStyles: Record<string, BasemapStyle> = {
    dark_all: 'dark_all',
    dark: 'dark_all',
    voyager: 'voyager',
    light_all: 'light_all',
    positron: 'light_all',
    osm: 'osm',
  };

  const safeStyle = validStyles[style] || 'dark_all';
  if (safeStyle === 'osm') {
    return 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
  }

  const rawKey =
    apiKey ||
    (typeof process !== 'undefined'
      ? process.env.NEXT_PUBLIC_CARTO_API_KEY
      : undefined);

  const key = (rawKey || '').trim();
  const baseUrl = `https://{s}.basemaps.cartocdn.com/rastertiles/${safeStyle}/{z}/{x}/{y}{r}.png`;
  if (key && !key.toLowerCase().startsWith('your_')) {
    return `${baseUrl}?api_key=${encodeURIComponent(key)}`;
  }
  return baseUrl;
}

/**
 * Resolves the default basemap style from environment or falls back to 'dark_all'.
 */
export function getDefaultBasemapStyle(): BasemapStyle {
  if (typeof process !== 'undefined' && process.env.NEXT_PUBLIC_CARTO_BASEMAP_STYLE) {
    const raw = process.env.NEXT_PUBLIC_CARTO_BASEMAP_STYLE.trim().toLowerCase();
    if (raw === 'positron') return 'light_all';
    if (raw === 'dark') return 'dark_all';
    if (raw === 'dark_all' || raw === 'voyager' || raw === 'light_all' || raw === 'osm') {
      return raw as BasemapStyle;
    }
  }
  return 'dark_all';
}
