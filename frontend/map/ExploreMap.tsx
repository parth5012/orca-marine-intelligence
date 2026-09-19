/**
 * ExploreMap — shared live map surface (UI-MIG-T5).
 *
 * Owner: M-D (Frontend & Maps)
 * Module: frontend/map/ExploreMap.tsx
 *
 * Merge of the source `ExploreMapScreen` visuals (floating glass search bar,
 * Find-Nearest + Layers quick actions, slide-down LayerControl, rounded-3xl
 * 1rem canvas, bottom glass drawer card) with OUR live MapInner engine
 * (live PFZ GeoJSON via GET /api/pfz, live weather via
 * GET /api/weather/current, EEZ/MPA/IMBL boundaries, sector filter,
 * parseLocation search, GPS recenter, basemap styles).
 *
 * The source `MapContainer` logic (mock pfzList, hardcoded streamlines) is
 * discarded — MapView/MapInner underneath is the only renderer.
 *
 * Shared by BOTH the `/map` full-screen route and the `/` map tab so the two
 * surfaces stay wired to the same engine. Every legacy id/data-testid/
 * aria-label is preserved (sector-select-dropdown, coord-search-*,
 * map-gps-recenter-button, layer-toggle-* via LayerControl, map-view via
 * MapView, inspector-drawer-toggle/close, nav-home-link/nav-chat-link).
 *
 * Live-only: Find-Nearest fetches live /api/pfz and picks the haversine
 * nearest (no mock pfz-09). No mocks, no new backend.
 */

'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { Search, Layers, Target, X, Navigation, Eye, MessageSquareText } from 'lucide-react';
import MapView from './MapView';
import SafetyBadge from './SafetyBadge';
import {
  bearingLabel,
  chlorophyllLabel,
  distanceLabel,
  geofenceRows,
  sstLabel,
  suitabilityLabel,
  toFiniteNumber,
  waveLabel,
  windLabel,
} from './drawerHonesty';
import LayerControl from './LayerControl';
import { parseLocation, formatDMS, haversineDistance } from './geo';
import type { BasemapStyle } from './carto';
import { filterEngineLayers, isLayerOn } from './layers';
import { fetchPfzCached } from '@/lib/pfzCache';
import { useApp, DEFAULT_ACTIVE_LAYERS, KOCHI_FALLBACK } from '@/context/AppContext';
import type { MapLayerKey } from '@/context/AppContext';

export const SECTORS = [
  { label: 'All India Coastal Sectors', value: 'ALL', center: [13.0, 78.0] as [number, number], zoom: 6 },
  { label: 'Kerala (SEC005)', value: 'KERALA', center: [9.93, 76.27] as [number, number], zoom: 9 },
  { label: 'Maharashtra (SEC002)', value: 'MAHARASHTRA', center: [18.92, 72.83] as [number, number], zoom: 8 },
  { label: 'Tamil Nadu (SEC007)', value: 'TAMIL NADU', center: [11.5, 79.8] as [number, number], zoom: 8 },
  { label: 'Gujarat (SEC001)', value: 'GUJARAT', center: [21.0, 70.0] as [number, number], zoom: 8 },
  { label: 'Karnataka (SEC004)', value: 'KARNATAKA', center: [13.5, 74.5] as [number, number], zoom: 8 },
  { label: 'Goa (SEC003)', value: 'GOA', center: [15.49, 73.82] as [number, number], zoom: 9 },
  { label: 'Andhra Pradesh (SEC008)', value: 'ANDHRA PRADESH', center: [16.5, 82.5] as [number, number], zoom: 8 },
  { label: 'Odisha (SEC009)', value: 'ODISHA', center: [19.8, 86.0] as [number, number], zoom: 8 },
  { label: 'West Bengal (SEC010)', value: 'WEST BENGAL', center: [21.5, 88.0] as [number, number], zoom: 8 },
];

export interface ExploreMapProps {
  center?: [number, number];
  zoom?: number;
  sector?: string;
  highlightFeatures?: any[];
  userLocation?: { lat: number; lon: number } | null;
  onSelectZone?: (feature: any) => void;
  onCenterChange?: (center: [number, number]) => void;
  initialBasemapStyle?: BasemapStyle;
  showNavLinks?: boolean;
}

function readCtx() {
  try {
    return useApp();
  } catch {
    return null;
  }
}

export const ExploreMap: React.FC<ExploreMapProps> = ({
  center: controlledCenter,
  zoom: controlledZoom,
  sector: controlledSector,
  highlightFeatures: controlledHighlight,
  userLocation: controlledUserLocation,
  onSelectZone,
  onCenterChange,
  initialBasemapStyle,
  showNavLinks = true,
}) => {
  const ctx = readCtx();
  const themeMode = ctx?.themeMode ?? 'light';
  const isLight = themeMode === 'light';

  const ctxLayers = (ctx?.activeLayers as Record<MapLayerKey, boolean> | undefined) ?? DEFAULT_ACTIVE_LAYERS;
  const toggleCtxLayer =
    ctx?.toggleLayer ??
    ((_key: MapLayerKey) => {
      /* no provider — LayerControl owns its internal bag */
    });

  const [mapCenter, setMapCenter] = useState<[number, number]>(
    controlledCenter ?? [KOCHI_FALLBACK.lat, KOCHI_FALLBACK.lon]
  );
  const [mapZoom, setMapZoom] = useState<number>(controlledZoom ?? 8);
  const [selectedSector, setSelectedSector] = useState<string>(controlledSector ?? 'ALL');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [searchError, setSearchError] = useState<string | null>(null);
  const [showLayerPanel, setShowLayerPanel] = useState<boolean>(false);
  const [selectedZone, setSelectedZone] = useState<any | null>(null);
  const [drawerOpen, setDrawerOpen] = useState<boolean>(true);
  const [internalUserLocation, setInternalUserLocation] = useState<{
    lat: number;
    lon: number;
  } | null>(null);
  const [nearestLoading, setNearestLoading] = useState<boolean>(false);
  // Perf #198: debounce rapid search resubmits (Enter spam / double tap).
  const lastSearchAt = useRef<number>(0);

  // Sync controlled props (map tab drives center/zoom/highlight from chat).
  // applyCenter is declared first: the sector sync below recenters the map
  // on ?sector= (same as a user sector pick), not just the filter value.
  const applyCenter = useCallback(
    (c: [number, number], z?: number) => {
      setMapCenter(c);
      if (typeof z === 'number') setMapZoom(z);
      onCenterChange?.(c);
    },
    [onCenterChange]
  );
  useEffect(() => {
    if (controlledCenter) setMapCenter(controlledCenter);
  }, [controlledCenter]);
  useEffect(() => {
    if (typeof controlledZoom === 'number') setMapZoom(controlledZoom);
  }, [controlledZoom]);
  useEffect(() => {
    if (typeof controlledSector === 'string') {
      setSelectedSector(controlledSector);
      const cfg = SECTORS.find((s) => s.value === controlledSector);
      if (cfg) applyCenter(cfg.center, cfg.zoom);
    }
  }, [controlledSector, applyCenter]);
  useEffect(() => {
    if (controlledHighlight && controlledHighlight.length > 0) {
      setSelectedZone(controlledHighlight[0]);
      setDrawerOpen(true);
    }
  }, [controlledHighlight]);

  const userLocation = useMemo(
    () => controlledUserLocation ?? internalUserLocation,
    [controlledUserLocation, internalUserLocation]
  );

  // Acquire GPS when the parent does not supply a location (mirrors /map legacy).
  useEffect(() => {
    if (controlledUserLocation) return;
    if (typeof window === 'undefined' || !navigator.geolocation) {
      setInternalUserLocation({ lat: KOCHI_FALLBACK.lat, lon: KOCHI_FALLBACK.lon });
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => setInternalUserLocation({ lat: pos.coords.latitude, lon: pos.coords.longitude }),
      () => setInternalUserLocation({ lat: KOCHI_FALLBACK.lat, lon: KOCHI_FALLBACK.lon }),
      { timeout: 8000, enableHighAccuracy: true }
    );
  }, [controlledUserLocation]);

  const handleSectorChange = useCallback(
    (value: string) => {
      setSelectedSector(value);
      const cfg = SECTORS.find((s) => s.value === value);
      if (cfg) applyCenter(cfg.center, cfg.zoom);
    },
    [applyCenter]
  );

  const handleSearch = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      const now = Date.now();
      if (now - lastSearchAt.current < 300) return;
      lastSearchAt.current = now;
      setSearchError(null);
      if (!searchQuery.trim()) return;
      const loc = parseLocation(searchQuery);
      if (
        loc &&
        typeof loc.lat === 'number' &&
        typeof loc.lon === 'number' &&
        !isNaN(loc.lat) &&
        !isNaN(loc.lon) &&
        isFinite(loc.lat) &&
        isFinite(loc.lon)
      ) {
        let safeLat = loc.lat;
        let safeLon = loc.lon;
        if (safeLat > 50 && safeLon < 40) {
          const tmp = safeLat;
          safeLat = safeLon;
          safeLon = tmp;
        }
        safeLat = Math.max(-90, Math.min(90, safeLat));
        safeLon = Math.max(-180, Math.min(180, safeLon));
        applyCenter([safeLat, safeLon], 10);
      } else {
        setSearchError('Location not recognized. Try "Kochi", "Veraval", or coordinates "9.93, 76.27".');
      }
    },
    [searchQuery, applyCenter]
  );

  const handleMarkerSelect = useCallback(
    (feature: any) => {
      setSelectedZone(feature);
      setDrawerOpen(true);
      if (ctx?.setSelectedPFZ) {
        ctx.setSelectedPFZ(feature);
      }
      onSelectZone?.(feature);
    },
    [onSelectZone, ctx]
  );

  // Live Find-Nearest: nearest live PFZ feature to GPS/center (no mocks).
  // Perf #198: cached /api/pfz?limit=200 per sector (60s SWR) — repeated
  // clicks reuse one payload instead of refetching every click.
  const handleFindNearest = useCallback(async () => {
    setNearestLoading(true);
    try {
      const params = new URLSearchParams();
      if (selectedSector && selectedSector !== 'ALL') params.set('sector', selectedSector);
      params.set('limit', '200');
      const data = await fetchPfzCached(`/api/pfz?${params.toString()}`);
      const features = Array.isArray(data?.features) ? data.features : [];
      if (features.length === 0) return;
      const origin = userLocation ?? { lat: mapCenter[0], lon: mapCenter[1] };
      let best: any = features[0];
      let bestDist = Infinity;
      for (const f of features) {
        const c = f?.geometry?.coordinates;
        if (!Array.isArray(c) || c.length < 2) continue;
        const d = haversineDistance(origin.lat, origin.lon, Number(c[1]), Number(c[0]));
        if (d < bestDist) {
          bestDist = d;
          best = f;
        }
      }
      if (best) handleMarkerSelect(best);
    } catch {
      // backend/file both unavailable — stay put, never mock a zone.
    } finally {
      setNearestLoading(false);
    }
  }, [selectedSector, userLocation, mapCenter, handleMarkerSelect]);

  const highlightFeatures = useMemo(
    () => controlledHighlight ?? (selectedZone ? [selectedZone] : []),
    [controlledHighlight, selectedZone]
  );

  const engineLayers = useMemo(() => filterEngineLayers(ctxLayers as Record<string, boolean | undefined>), [ctxLayers]);
  // Stable identity: MapInner re-applies `activeLayers` in an effect keyed on
  // identity, so a fresh literal every render would reset user toggles.
  const mapLayers = useMemo(
    () => ({ ...engineLayers, ...(ctxLayers as object) }),
    [engineLayers, ctxLayers]
  );
  const showSst = isLayerOn(ctxLayers as Record<string, boolean | undefined>, 'sst');
  const showChl = isLayerOn(ctxLayers as Record<string, boolean | undefined>, 'chlorophyll');
  const showWaves = isLayerOn(ctxLayers as Record<string, boolean | undefined>, 'waves');
  const showWind = isLayerOn(ctxLayers as Record<string, boolean | undefined>, 'wind');

  const zoneProps = selectedZone?.properties ?? {};
  const zoneCoords = selectedZone?.geometry?.coordinates;
  const zoneLat = Array.isArray(zoneCoords) ? Number(zoneCoords[1]) : NaN;
  const zoneLon = Array.isArray(zoneCoords) ? Number(zoneCoords[0]) : NaN;
  const zoneName = String(zoneProps.place ?? zoneProps.name ?? 'Selected Zone');
  const zoneCode = String(zoneProps.zone_id ?? zoneProps.code ?? zoneProps.id ?? 'PFZ');
  // Ticket #195: every drawer claim comes from feature props; missing
  // values render as em-dash / Not verified, never hardcoded defaults.
  const zoneSuitability = suitabilityLabel(zoneProps);
  const zonePlaceParam = String(zoneProps.place ?? zoneName);

  return (
    <div
      data-testid="explore-map"
      className={`relative w-full h-full min-h-[580px] rounded-3xl overflow-hidden border shadow-2xl flex flex-col ${
        isLight ? 'border-cyan-200 bg-[#edf6ff]' : 'border-cyan-900/40 bg-slate-950'
      }`}
    >
      {/* Top Floating Control Bar (new design; legacy testids preserved) */}
      <div className="absolute top-4 left-4 right-4 z-[1000] flex flex-wrap items-center justify-between gap-3 pointer-events-none">
        <div className="pointer-events-auto flex flex-wrap items-center gap-2 max-w-full">
          <form
            id="coord-search-form"
            data-testid="coord-search-form"
            onSubmit={handleSearch}
            className={`flex items-center gap-2 rounded-2xl p-1.5 border shadow-xl w-64 sm:w-80 ${
              isLight
                ? 'bg-white/95 border-cyan-200'
                : 'glass-panel border-cyan-500/40 bg-slate-950/95'
            }`}
          >
            <Search className="w-4 h-4 text-cyan-500 ml-2 shrink-0" />
            <input
              type="text"
              id="coord-search-input"
              data-testid="coord-search-input"
              aria-label="Search port or coordinates (lat, lon)"
              placeholder="Search port, coordinate or zone..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className={`w-full bg-transparent text-xs sm:text-sm focus:outline-none px-1 py-1 font-medium ${
                isLight ? 'text-slate-900 placeholder-slate-400' : 'text-slate-100 placeholder-slate-400'
              }`}
            />
            <button
              type="submit"
              id="coord-search-button"
              data-testid="coord-search-button"
              aria-label="Search coordinates or port"
              className="px-3 py-1.5 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-bold transition-colors shrink-0"
            >
              Go
            </button>
          </form>

          <select
            id="sector-select-dropdown"
            data-testid="sector-select-dropdown"
            aria-label="Select Coastal Sector"
            value={selectedSector}
            onChange={(e) => handleSectorChange(e.target.value)}
            className={`px-3 py-2 rounded-2xl border text-xs font-medium focus:outline-none cursor-pointer shadow-xl ${
              isLight
                ? 'bg-white/95 border-cyan-200 text-cyan-800'
                : 'bg-slate-950/95 border-cyan-500/40 text-cyan-200'
            }`}
          >
            {SECTORS.map((sec) => (
              <option
                key={sec.value}
                id={`sector-option-${sec.value.toLowerCase().replace(/\s+/g, '-')}`}
                data-testid={`sector-option-${sec.value.toLowerCase().replace(/\s+/g, '-')}`}
                value={sec.value}
                className="bg-slate-900 text-slate-200"
              >
                {sec.label}
              </option>
            ))}
          </select>
        </div>

        <div className="pointer-events-auto flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={handleFindNearest}
            disabled={nearestLoading}
            className="px-3.5 py-2 rounded-xl bg-gradient-to-r from-cyan-400 to-teal-500 text-slate-950 font-extrabold text-xs shadow-lg shadow-cyan-500/30 hover:scale-105 transition-transform flex items-center gap-1.5 disabled:opacity-60"
          >
            <Target className="w-4 h-4 stroke-[2.5]" />
            <span>{nearestLoading ? 'Locating…' : 'Find Nearest PFZ'}</span>
          </button>

          <button
            type="button"
            id="explore-layers-toggle"
            data-testid="explore-layers-toggle"
            aria-label="Toggle Marine Layers Panel"
            aria-expanded={showLayerPanel}
            onClick={() => setShowLayerPanel((p) => !p)}
            className={`px-3.5 py-2 rounded-xl text-xs font-semibold flex items-center gap-1.5 transition-all border ${
              showLayerPanel
                ? 'bg-cyan-500 text-slate-950 font-bold border-cyan-400'
                : isLight
                  ? 'bg-white/95 text-cyan-800 border-cyan-200 hover:bg-cyan-50'
                  : 'bg-slate-950/90 text-cyan-200 border-cyan-500/40 hover:bg-slate-800'
            }`}
          >
            <Layers className="w-4 h-4" />
            <span>Layers</span>
          </button>

          {userLocation && (
            <button
              type="button"
              id="map-gps-recenter-button"
              data-testid="map-gps-recenter-button"
              aria-label="Center on vessel location"
              title="Center on vessel location"
              onClick={() => applyCenter([userLocation.lat, userLocation.lon], 11)}
              className={`px-3 py-2 rounded-xl text-xs font-medium transition-colors border flex items-center gap-1.5 ${
                isLight
                  ? 'bg-white/95 hover:bg-cyan-50 text-cyan-800 border-cyan-200'
                  : 'bg-slate-950/90 hover:bg-slate-800 text-cyan-200 border-cyan-500/40'
              }`}
            >
              <span>📍</span> GPS Recenter
            </button>
          )}

          <button
            type="button"
            id="inspector-drawer-toggle"
            data-testid="inspector-drawer-toggle"
            aria-label="Toggle Safety Inspector Drawer"
            aria-expanded={drawerOpen}
            onClick={() => setDrawerOpen((prev) => !prev)}
            className={`px-3 py-2 rounded-xl text-xs font-medium flex items-center gap-1 transition-colors border ${
              isLight
                ? 'bg-white/95 hover:bg-cyan-50 text-cyan-800 border-cyan-200'
                : 'bg-slate-950/90 hover:bg-slate-800 text-cyan-200 border-cyan-500/40'
            }`}
          >
            <span>📋</span> Inspector {drawerOpen ? '▶' : '◀'}
          </button>

          {showNavLinks && (
            <>
              <Link
                href="/"
                id="nav-home-link"
                data-testid="nav-home-link"
                aria-label="Back to ORCA Home"
                title="Back to ORCA Home"
                className="px-3 py-2 rounded-xl bg-slate-950/90 hover:bg-slate-800 text-cyan-200 border border-cyan-500/40 text-xs font-medium transition-colors"
              >
                🌊 Home
              </Link>
              <Link
                href="/"
                id="nav-chat-link"
                data-testid="nav-chat-link"
                aria-label="Back to Chat Advisory"
                className="px-3 py-2 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-bold transition-colors"
              >
                💬 Chat
              </Link>
            </>
          )}
        </div>
      </div>

      {searchError && (
        <div
          id="coord-search-error"
          data-testid="coord-search-error"
          role="alert"
          className="absolute top-16 left-4 right-4 z-[1001] bg-red-950/90 text-red-200 border border-red-800 text-xs px-4 py-1.5 rounded-xl flex items-center justify-between"
        >
          <span>⚠️ {searchError}</span>
          <button
            type="button"
            id="coord-search-error-dismiss"
            data-testid="coord-search-error-dismiss"
            aria-label="Dismiss search error"
            onClick={() => setSearchError(null)}
            className="text-red-300 font-bold ml-4"
          >
            ✕
          </button>
        </div>
      )}

      {/* Slide-down Layers Control Panel (new design pills, legacy testids inside) */}
      {showLayerPanel && (
        <div className="absolute top-16 left-4 right-4 z-[1001]">
          <div className="relative">
            <button
              type="button"
              aria-label="Close layers panel"
              onClick={() => setShowLayerPanel(false)}
              className="absolute top-2 right-2 z-10 p-1.5 rounded-lg bg-slate-900 text-slate-400 hover:text-white"
            >
              <X className="w-4 h-4" />
            </button>
            <LayerControl
              activeLayers={ctxLayers as Partial<Record<MapLayerKey, boolean>>}
              onToggle={ctx ? toggleCtxLayer : undefined}
            />
          </div>
        </div>
      )}

        {/* Main Live Marine Map (1rem canvas, glow markers via MapInner) */}
        <div className="w-full h-full flex-1">
          <MapView
            center={mapCenter}
            zoom={mapZoom}
            sector={selectedSector}
            activeLayers={mapLayers}
            highlightFeatures={highlightFeatures}
            userLocation={userLocation}
            route={ctx?.activeRoute}
            routeMeta={
              ctx?.activeRouteInfo
                ? {
                    detourOccurred: ctx.activeRouteInfo.detourOccurred,
                    safetyLabel: ctx.activeRouteInfo.safetyLabel,
                  }
                : null
            }
            themeMode={themeMode}
            initialBasemapStyle={initialBasemapStyle}
            onSelectZone={handleMarkerSelect}
            onCenterChange={(c) => {
              setMapCenter(c);
              onCenterChange?.(c);
            }}
          />
        </div>

      {/* Bottom Drawer Card (new glass design; legacy inspector testids kept) */}
      {drawerOpen && selectedZone && (
        <div className="absolute bottom-4 left-4 right-4 z-[1000] max-w-xl mx-auto">
          <div
            id="inspector-drawer"
            data-testid="inspector-drawer"
            className={`rounded-2xl p-4 sm:p-5 border-2 shadow-2xl ${
              isLight
                ? 'bg-white/95 border-cyan-300 shadow-cyan-900/10'
                : 'glass-panel border-cyan-500/50 bg-slate-950/95 shadow-slate-950/90'
            }`}
          >
            <div className="flex items-center justify-between pb-3 border-b border-slate-200 dark:border-slate-800">
              <div className="flex items-center gap-2">
                <span className="px-2.5 py-0.5 rounded bg-cyan-950 text-cyan-300 font-mono text-xs font-bold border border-cyan-800">
                  {zoneCode}
                </span>
                <h3 className={`font-extrabold text-base ${isLight ? 'text-slate-900' : 'text-white'}`}>
                  {zoneName}
                </h3>
              </div>
              <div className="flex items-center gap-2">
                <SafetyBadge
                  waves={toFiniteNumber(zoneProps.wave_m ?? zoneProps.wave_height_m)}
                  wind={toFiniteNumber(zoneProps.wind_kt ?? zoneProps.wind_speed_kt)}
                  danger={zoneProps.danger ?? undefined}
                  badge={zoneProps.badge ?? undefined}
                  compact
                />
                <button
                  type="button"
                  id="inspector-drawer-close"
                  data-testid="inspector-drawer-close"
                  aria-label="Close Safety Inspector Drawer"
                  onClick={() => {
                    setDrawerOpen(false);
                    setSelectedZone(null);
                  }}
                  className={`p-1 rounded-lg ${isLight ? 'bg-slate-100 text-slate-500 hover:text-slate-900' : 'bg-slate-900 text-slate-400 hover:text-white'}`}
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 my-3 text-xs">
              <div className={`p-2 rounded-xl border ${isLight ? 'bg-cyan-50/80 border-cyan-100' : 'bg-slate-900/80 border-slate-800'}`}>
                <span className="text-[11px] text-slate-400">Distance</span>
                <div className="font-bold text-cyan-600 dark:text-cyan-200 text-sm mt-0.5">
                  {distanceLabel(zoneProps)}
                </div>
                <div className="text-[10px] text-slate-400">
                  {bearingLabel(zoneProps)}
                </div>
              </div>
              {showSst && (
                <div className={`p-2 rounded-xl border ${isLight ? 'bg-amber-50/80 border-amber-100' : 'bg-slate-900/80 border-slate-800'}`}>
                  <span className="text-[11px] text-slate-400">SST Temp</span>
                  <div className="font-bold text-amber-600 dark:text-amber-300 text-sm mt-0.5">
                    {sstLabel(zoneProps)}
                  </div>
                  <div className="text-[10px] text-slate-400">Surface Temp</div>
                </div>
              )}
              {showChl && (
                <div className={`p-2 rounded-xl border ${isLight ? 'bg-teal-50/80 border-teal-100' : 'bg-slate-900/80 border-slate-800'}`}>
                  <span className="text-[11px] text-slate-400">Chlorophyll</span>
                  <div className="font-bold text-teal-600 dark:text-teal-300 text-sm mt-0.5">
                    {chlorophyllLabel(zoneProps)}
                  </div>
                  <div className="text-[10px] text-slate-400">Plankton</div>
                </div>
              )}
              {(showWaves || showWind) && (
                <div className={`p-2 rounded-xl border ${isLight ? 'bg-sky-50/80 border-sky-100' : 'bg-slate-900/80 border-slate-800'}`}>
                  <span className="text-[11px] text-slate-400">Waves & Wind</span>
                  <div className="font-bold text-sky-600 dark:text-blue-300 text-sm mt-0.5">
                    {showWaves ? waveLabel(zoneProps) : '—'}
                    {' / '}
                    {showWind ? windLabel(zoneProps) : '—'}
                  </div>
                  <div className="text-[10px] text-slate-400">Sea state</div>
                </div>
              )}
            </div>

            {/* Ticket #195: geofence rows strictly from feature props
                (inside_eez / inside_mpa / imbl_distance_km); missing props
                read "Not verified", never a hardcoded km claim. */}
            <div className={`flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] mb-2 ${isLight ? 'text-slate-500' : 'text-slate-400'}`}>
              {geofenceRows(zoneProps).map((row) => (
                <span key={row.key} className="flex items-center gap-1.5">
                  <span
                    className={`w-2 h-2 rounded-full ${
                      row.tone === 'sky'
                        ? 'bg-sky-400'
                        : row.tone === 'emerald'
                        ? 'bg-emerald-400'
                        : row.tone === 'red'
                        ? 'bg-red-400'
                        : row.tone === 'orange'
                        ? 'bg-orange-400'
                        : 'bg-slate-400'
                    }`}
                  />{' '}
                  {row.label}: {row.detail}
                </span>
              ))}
              <span className="font-mono">
                {Number.isFinite(zoneLat) ? formatDMS(zoneLat, true) : ''} |{' '}
                {Number.isFinite(zoneLon) ? formatDMS(zoneLon, false) : ''} · {zoneSuitability}
              </span>
            </div>

            <div className="flex items-center gap-2 pt-2 border-t border-slate-200 dark:border-slate-800">
              {ctx ? (
                <>
                  <button
                    type="button"
                    onClick={() => ctx.openPFZDetail(selectedZone)}
                    className={`flex-1 px-3 py-2 rounded-xl border text-xs font-semibold flex items-center justify-center gap-1.5 ${
                      isLight
                        ? 'bg-slate-50 border-slate-200 text-cyan-800 hover:text-cyan-950'
                        : 'bg-slate-900 border-slate-800 text-cyan-200 hover:text-white'
                    }`}
                  >
                    <Eye className="w-3.5 h-3.5 text-cyan-500" />
                    <span>View Details</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => ctx.startRouteNavigation(selectedZone)}
                    className="flex-1 px-3 py-2 rounded-xl bg-gradient-to-r from-cyan-400 to-teal-500 text-slate-950 text-xs font-extrabold flex items-center justify-center gap-1.5 shadow-md shadow-cyan-500/20 hover:scale-[1.02] transition-transform"
                  >
                    <Navigation className="w-3.5 h-3.5 fill-slate-950" />
                    <span>Navigate</span>
                  </button>
                </>
              ) : (
                <span className={`flex-1 text-[11px] ${isLight ? 'text-slate-500' : 'text-slate-400'}`}>
                  Sector: {String(zoneProps.sector_name ?? zoneProps.sector ?? selectedSector)}
                </span>
              )}
              <Link
                href={`/?zone=${encodeURIComponent(zonePlaceParam)}`}
                id="consult-chat-link"
                data-testid="consult-chat-link"
                aria-label="Consult Advisory in Chat"
                className="px-3 py-2 rounded-xl bg-cyan-950 border border-cyan-800 text-cyan-300 text-xs font-semibold flex items-center justify-center gap-1 hover:bg-cyan-900"
              >
                <MessageSquareText className="w-3.5 h-3.5" />
                <span className="hidden sm:inline">Ask ORCA</span>
              </Link>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ExploreMap;
