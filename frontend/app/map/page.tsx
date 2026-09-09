/**
 * ORCA Standalone Map Page
 *
 * Owner: M-D (Frontend & Maps) — full-screen map page
 * Module: frontend/app/map/page.tsx
 *
 * Full-screen interactive ocean map with:
 * 1. Layer toggle controls (PFZ, EEZ, MPA, IMBL, Weather)
 * 2. Search & sector filter (Kerala, Maharashtra, Tamil Nadu, Gujarat, etc.)
 * 3. Safety & weather inspection drawer / telemetry badge
 * 4. Top bar with navigation back to chat advisory
 */

'use client';

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import Link from 'next/link';
import MapView, {
  SafetyBadge,
  parseLocation,
  formatDMS,
  COASTAL_PORTS,
  MapLayerToggles,
  BasemapStyle,
} from '@/map';

const SECTORS = [
  { label: 'All India Coastal Sectors', value: 'ALL', center: [13.0, 78.0], zoom: 6 },
  { label: 'Kerala (SEC005)', value: 'KERALA', center: [9.93, 76.27], zoom: 9 },
  { label: 'Maharashtra (SEC002)', value: 'MAHARASHTRA', center: [18.92, 72.83], zoom: 8 },
  { label: 'Tamil Nadu (SEC007)', value: 'TAMIL NADU', center: [11.5, 79.8], zoom: 8 },
  { label: 'Gujarat (SEC001)', value: 'GUJARAT', center: [21.0, 70.0], zoom: 8 },
  { label: 'Karnataka (SEC004)', value: 'KARNATAKA', center: [13.5, 74.5], zoom: 8 },
  { label: 'Goa (SEC003)', value: 'GOA', center: [15.49, 73.82], zoom: 9 },
  { label: 'Andhra Pradesh (SEC008)', value: 'ANDHRA PRADESH', center: [16.5, 82.5], zoom: 8 },
  { label: 'Odisha (SEC009)', value: 'ODISHA', center: [19.8, 86.0], zoom: 8 },
  { label: 'West Bengal (SEC010)', value: 'WEST BENGAL', center: [21.5, 88.0], zoom: 8 },
];

export interface MapPageProps {
  initialBasemapStyle?: BasemapStyle;
  searchParams?: {
    basemap?: string;
    style?: string;
    sector?: string;
    [key: string]: string | string[] | undefined;
  };
}

export default function MapPage({ initialBasemapStyle, searchParams }: MapPageProps = {}) {
  const resolvedBasemapStyle = useMemo<BasemapStyle | undefined>(() => {
    if (initialBasemapStyle) return initialBasemapStyle;
    const candidate = searchParams?.basemap || searchParams?.style;
    if (candidate && typeof candidate === 'string') {
      const raw = candidate.trim().toLowerCase();
      if (
        raw === 'dark_all' ||
        raw === 'voyager' ||
        raw === 'light_all' ||
        raw === 'esri_ocean' ||
        raw === 'esri_dark' ||
        raw === 'osm'
      ) {
        return raw as BasemapStyle;
      }
      if (raw === 'dark' || raw === 'carto_dark') return 'dark_all';
      if (raw === 'positron' || raw === 'light') return 'light_all';
      if (raw === 'ocean' || raw === 'esri_ocean_basemap') return 'esri_ocean';
      if (raw === 'dark_gray' || raw === 'esri_dark_gray') return 'esri_dark';
      if (raw === 'openstreetmap') return 'osm';
    }
    return undefined;
  }, [initialBasemapStyle, searchParams]);
  const [mapCenter, setMapCenter] = useState<[number, number]>([9.93, 76.27]);
  const [mapZoom, setMapZoom] = useState<number>(8);
  const [selectedSector, setSelectedSector] = useState<string>('ALL');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [searchError, setSearchError] = useState<string | null>(null);

  const [layers, setLayers] = useState<MapLayerToggles>({
    pfz: true,
    eez: true,
    mpa: true,
    imbl: true,
    weather: true,
  });

  const [userLocation, setUserLocation] = useState<{ lat: number; lon: number } | null>(null);
  const [selectedZone, setSelectedZone] = useState<any | null>(null);
  const [drawerOpen, setDrawerOpen] = useState<boolean>(true);

  // Weather telemetry state
  const [weatherTelemetry, setWeatherTelemetry] = useState<{
    waves: number;
    wind: number;
    danger: string;
    badge: string;
  }>({
    waves: 0.8,
    wind: 12,
    danger: 'none',
    badge: 'green',
  });

  // Acquire user GPS on mount
  useEffect(() => {
    if (typeof window !== 'undefined' && navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          const lat = pos.coords.latitude;
          const lon = pos.coords.longitude;
          setUserLocation({ lat, lon });
        },
        () => {
          // GPS denied/unavailable - fall back to Kochi
          setUserLocation({ lat: 9.9312, lon: 76.2673 });
        },
        { timeout: 8000, enableHighAccuracy: true }
      );
    }
  }, []);

  // Fetch geofence status from backend if available
  useEffect(() => {
    const backendBase =
      process.env.NEXT_PUBLIC_API_URL ||
      (typeof window !== 'undefined' && window.location.protocol === 'https:' ? '' : 'http://localhost:8000');
    fetch(`${backendBase}/api/geofence/status`)
      .then((res) => res.json())
      .then((data) => {
        if (data && data.status === 'ok') {
          // Geofence status loaded
        }
      })
      .catch(() => {
        // backend offline, offline boundaries used
      });
  }, []);

  // Sector selection handler
  const handleSectorChange = (value: string) => {
    setSelectedSector(value);
    const sectorConfig = SECTORS.find((s) => s.value === value);
    if (sectorConfig) {
      setMapCenter(sectorConfig.center as [number, number]);
      setMapZoom(sectorConfig.zoom);
    }
  };

  // Search input handler using parseLocation
  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setSearchError(null);
    if (!searchQuery.trim()) return;

    const loc = parseLocation(searchQuery);
    if (loc && typeof loc.lat === 'number' && typeof loc.lon === 'number' && !isNaN(loc.lat) && !isNaN(loc.lon) && isFinite(loc.lat) && isFinite(loc.lon)) {
      let safeLat = loc.lat;
      let safeLon = loc.lon;
      // In Indian maritime waters: defend against [lon, lat] accidentally swapped
      if (safeLat > 50 && safeLon < 40) {
        const tmp = safeLat;
        safeLat = safeLon;
        safeLon = tmp;
      }
      safeLat = Math.max(-90, Math.min(90, safeLat));
      safeLon = Math.max(-180, Math.min(180, safeLon));
      setMapCenter([safeLat, safeLon]);
      setMapZoom(10);
    } else {
      setSearchError('Location not recognized. Try "Kochi", "Veraval", or coordinates "9.93, 76.27".');
    }
  };

  // Toggle individual layer
  const toggleLayer = (key: keyof MapLayerToggles) => {
    setLayers((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  return (
    <div className="flex flex-col h-screen w-screen overflow-hidden bg-slate-950 text-slate-100 font-sans">
      {/* 1. Header Bar */}
      <header className="h-16 px-4 bg-slate-900/95 border-b border-slate-800 flex items-center justify-between z-30 flex-shrink-0 backdrop-blur">
        {/* Brand & Title */}
        <div className="flex items-center gap-3">
          <Link
            href="/"
            className="w-10 h-10 rounded-xl bg-gradient-to-tr from-cyan-600 via-sky-500 to-blue-600 flex items-center justify-center text-xl shadow-lg shadow-cyan-900/40 border border-cyan-400/30 hover:scale-105 transition-transform"
            id="nav-home-link"
            data-testid="nav-home-link"
            aria-label="Back to ORCA Home"
            title="Back to ORCA Home"
          >
            🌊
          </Link>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-base sm:text-lg font-black tracking-tight text-white">
                ORCA Ocean Map
              </h1>
              <span className="hidden sm:inline-block text-xs font-semibold text-cyan-400 tracking-wide">
                Spatial Telemetry & Geofencing
              </span>
              <span className="hidden md:inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold bg-cyan-950 text-cyan-300 border border-cyan-800">
                SIH26176
              </span>
            </div>
            <p className="text-[11px] text-slate-400 hidden sm:block">
              Potential Fishing Zones (PFZ) · EEZ & MPA Geofence Protection · IMBL Watch
            </p>
          </div>
        </div>

        {/* Search & Sector Controls */}
        <div className="hidden lg:flex items-center gap-2">
          {/* Sector Selector */}
          <div className="relative">
            <select
              id="sector-select-dropdown"
            data-testid="sector-select-dropdown"
            aria-label="Select Coastal Sector"
            value={selectedSector}
              onChange={(e) => handleSectorChange(e.target.value)}
              className="px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-700 text-xs text-cyan-300 font-medium focus:outline-none focus:border-cyan-500 transition-colors cursor-pointer"
            >
              {SECTORS.map((sec) => (
                <option key={sec.value} id={`sector-option-${sec.value.toLowerCase().replace(/\s+/g, '-')}`} data-testid={`sector-option-${sec.value.toLowerCase().replace(/\s+/g, '-')}`} value={sec.value} className="bg-slate-900 text-slate-200">
                  {sec.label}
                </option>
              ))}
            </select>
          </div>

          {/* Quick Search Form */}
          <form id="coord-search-form" data-testid="coord-search-form" onSubmit={handleSearch} className="relative flex items-center">
            <input
              type="text"
              id="coord-search-input"
            data-testid="coord-search-input"
            aria-label="Search port or coordinates (lat, lon)"
            placeholder="Search port or lat, lon..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-48 xl:w-56 px-3 py-1.5 rounded-l-lg bg-slate-950 border border-r-0 border-slate-700 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500"
            />
            <button
              type="submit"
              id="coord-search-button"
            data-testid="coord-search-button"
            aria-label="Search coordinates or port"
            className="px-3 py-1.5 rounded-r-lg bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-bold transition-colors border border-cyan-500"
            >
              Go
            </button>
          </form>
        </div>

        {/* Right Actions */}
        <div className="flex items-center gap-2.5">
          {/* GPS Recenter */}
          {userLocation && (
            <button
              type="button"
              onClick={() => {
                setMapCenter([userLocation.lat, userLocation.lon]);
                setMapZoom(11);
              }}
              className="hidden sm:flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-slate-950 hover:bg-slate-800 text-cyan-300 border border-slate-700 text-xs font-medium transition-colors"
              id="map-gps-recenter-button"
            data-testid="map-gps-recenter-button"
            aria-label="Center on vessel location"
            title="Center on vessel location"
            >
              <span>📍</span> GPS Recenter
            </button>
          )}

          {/* Back to Chat Advisory */}
          <Link
            href="/"
            id="nav-chat-link"
            data-testid="nav-chat-link"
            aria-label="Back to Chat Advisory"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-bold shadow-md shadow-cyan-900/30 transition-all"
          >
            <span>💬</span> Back to Chat
          </Link>
        </div>
      </header>

      {/* 2. Layer Toggle Controls Subbar */}
      <div className="h-10 px-4 bg-slate-900/90 border-b border-slate-800/80 flex items-center justify-between z-20 flex-shrink-0 text-xs overflow-x-auto">
        <div className="flex items-center gap-1.5 sm:gap-2">
          <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider mr-1 hidden sm:inline">
            Layers:
          </span>

          <button
            type="button"
            id="layer-toggle-pfz"
          data-testid="layer-toggle-pfz"
          aria-label="Toggle PFZ Zones Layer"
          aria-pressed={layers.pfz}
          onClick={() => toggleLayer('pfz')}
            className={`px-2.5 py-1 rounded-md text-xs font-semibold flex items-center gap-1 transition-all ${
              layers.pfz
                ? 'bg-emerald-950/80 text-emerald-300 border border-emerald-500/60 shadow-sm'
                : 'bg-slate-950 text-slate-400 border border-slate-800 opacity-60'
            }`}
          >
            <span>🐟</span> PFZ Zones
          </button>

          <button
            type="button"
            id="layer-toggle-eez"
          data-testid="layer-toggle-eez"
          aria-label="Toggle EEZ Boundary Layer"
          aria-pressed={layers.eez}
          onClick={() => toggleLayer('eez')}
            className={`px-2.5 py-1 rounded-md text-xs font-semibold flex items-center gap-1 transition-all ${
              layers.eez
                ? 'bg-sky-950/80 text-sky-300 border border-sky-500/60 shadow-sm'
                : 'bg-slate-950 text-slate-400 border border-slate-800 opacity-60'
            }`}
          >
            <span>🌐</span> EEZ Boundary
          </button>

          <button
            type="button"
            id="layer-toggle-mpa"
          data-testid="layer-toggle-mpa"
          aria-label="Toggle MPA Sanctuaries Layer"
          aria-pressed={layers.mpa}
          onClick={() => toggleLayer('mpa')}
            className={`px-2.5 py-1 rounded-md text-xs font-semibold flex items-center gap-1 transition-all ${
              layers.mpa
                ? 'bg-red-950/80 text-red-300 border border-red-500/60 shadow-sm'
                : 'bg-slate-950 text-slate-400 border border-slate-800 opacity-60'
            }`}
          >
            <span>🛡️</span> MPA Sanctuaries
          </button>

          <button
            type="button"
            id="layer-toggle-imbl"
          data-testid="layer-toggle-imbl"
          aria-label="Toggle IMBL Border Layer"
          aria-pressed={layers.imbl}
          onClick={() => toggleLayer('imbl')}
            className={`px-2.5 py-1 rounded-md text-xs font-semibold flex items-center gap-1 transition-all ${
              layers.imbl
                ? 'bg-orange-950/80 text-orange-300 border border-orange-500/60 shadow-sm'
                : 'bg-slate-950 text-slate-400 border border-slate-800 opacity-60'
            }`}
          >
            <span>⚠️</span> IMBL Border
          </button>

          <button
            type="button"
            id="layer-toggle-weather"
          data-testid="layer-toggle-weather"
          aria-label="Toggle Weather Telemetry Layer"
          aria-pressed={layers.weather}
          onClick={() => toggleLayer('weather')}
            className={`px-2.5 py-1 rounded-md text-xs font-semibold flex items-center gap-1 transition-all ${
              layers.weather
                ? 'bg-cyan-950/80 text-cyan-300 border border-cyan-500/60 shadow-sm'
                : 'bg-slate-950 text-slate-400 border border-slate-800 opacity-60'
            }`}
          >
            <span>⛅</span> Weather Telemetry
          </button>
        </div>

        {/* Drawer Toggle */}
        <button
          type="button"
          id="inspector-drawer-toggle"
          data-testid="inspector-drawer-toggle"
          aria-label="Toggle Safety Inspector Drawer"
          aria-expanded={drawerOpen}
          onClick={() => setDrawerOpen((prev) => !prev)}
          className="px-2.5 py-1 rounded-md bg-slate-950 hover:bg-slate-800 text-cyan-300 border border-slate-700 text-xs font-medium flex items-center gap-1 transition-colors"
        >
          <span>📋</span> Inspector {drawerOpen ? '▶' : '◀'}
        </button>
      </div>

      {searchError && (
        <div id="coord-search-error"
          data-testid="coord-search-error"
          role="alert"
          className="bg-red-950/90 text-red-200 border-b border-red-800 text-xs px-4 py-1.5 flex items-center justify-between">
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

      {/* 3. Main Map Body */}
      <div className="flex-1 relative overflow-hidden flex">
        {/* Interactive Map View */}
        <div className="flex-1 h-full w-full relative">
          <MapView
            center={mapCenter}
            zoom={mapZoom}
            sector={selectedSector}
            activeLayers={layers}
            highlightFeatures={selectedZone ? [selectedZone] : []}
            userLocation={userLocation}
            initialBasemapStyle={resolvedBasemapStyle}
            onSelectZone={(zone) => {
              setSelectedZone(zone);
              setDrawerOpen(true);
            }}
            onCenterChange={(newCenter) => setMapCenter(newCenter)}
          />
        </div>

        {/* 4. Safety & Telemetry Drawer (Right Side) */}
        {drawerOpen && (
          <aside className="w-80 lg:w-96 h-full bg-slate-900/95 border-l border-slate-800 p-4 flex flex-col gap-4 overflow-y-auto z-20 backdrop-blur">
            <div className="flex items-center justify-between border-b border-slate-800 pb-2">
              <h2 className="text-xs font-bold uppercase tracking-wider text-slate-300 flex items-center gap-2">
                <span>🛡️</span> Marine Safety & Geofence
              </h2>
              <button
                type="button"
                id="inspector-drawer-close"
                data-testid="inspector-drawer-close"
                aria-label="Close Safety Inspector Drawer"
                onClick={() => setDrawerOpen(false)}
                className="text-slate-400 hover:text-white text-xs"
              >
                ✕ Close
              </button>
            </div>

            {/* Live Safety Badge */}
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-400">Current Advisory:</span>
                <SafetyBadge
                  waves={weatherTelemetry.waves}
                  wind={weatherTelemetry.wind}
                  danger={weatherTelemetry.danger}
                  badge={weatherTelemetry.badge}
                />
              </div>

              <div className="grid grid-cols-2 gap-2 text-xs mt-1">
                <div className="bg-slate-950 p-2.5 rounded-lg border border-slate-800">
                  <span className="text-[10px] text-slate-400 block uppercase">Wave Height</span>
                  <span className="text-cyan-300 font-black text-lg">
                    {weatherTelemetry.waves} m
                  </span>
                  <span className="text-[10px] text-emerald-400 block mt-0.5">Calm - Normal</span>
                </div>
                <div className="bg-slate-950 p-2.5 rounded-lg border border-slate-800">
                  <span className="text-[10px] text-slate-400 block uppercase">Wind Speed</span>
                  <span className="text-cyan-300 font-black text-lg">
                    {weatherTelemetry.wind} kts
                  </span>
                  <span className="text-[10px] text-emerald-400 block mt-0.5">Safe Breeze</span>
                </div>
              </div>
            </div>

            {/* Geofence Perimeter Status */}
            <div className="bg-slate-950/80 p-3 rounded-xl border border-slate-800/80 space-y-2 text-xs">
              <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">
                Maritime Legal Boundaries
              </span>

              <div className="flex items-center justify-between text-[11px]">
                <span className="text-slate-300 flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-sky-400" />
                  Sovereign EEZ Status:
                </span>
                <span className="text-sky-300 font-bold">Inside India EEZ</span>
              </div>

              <div className="flex items-center justify-between text-[11px]">
                <span className="text-slate-300 flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-emerald-400" />
                  MPA Distance:
                </span>
                <span className="text-emerald-300 font-bold">&gt; 12 km clear</span>
              </div>

              <div className="flex items-center justify-between text-[11px]">
                <span className="text-slate-300 flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-orange-400" />
                  IMBL Clearance:
                </span>
                <span className="text-orange-300 font-bold">&gt; 45 km buffer</span>
              </div>
            </div>

            {/* Selected Zone Inspector */}
            {selectedZone ? (
              <div className="bg-slate-950 p-3.5 rounded-xl border border-cyan-500/40 space-y-3 text-xs">
                <div className="flex items-center justify-between border-b border-slate-800 pb-2">
                  <span className="font-black text-sm text-cyan-300">
                    {selectedZone.properties?.place || 'Selected Zone'}
                  </span>
                  <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-emerald-950 text-emerald-300 border border-emerald-700">
                    {selectedZone.properties?.suitability || 'HIGH'}
                  </span>
                </div>

                <div className="grid grid-cols-2 gap-2 text-[11px]">
                  <div>
                    <span className="text-slate-400 block text-[10px]">Sector:</span>
                    <span className="font-semibold text-white">
                      {selectedZone.properties?.sector_name || selectedZone.properties?.sector || 'N/A'}
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-400 block text-[10px]">Bearing:</span>
                    <span className="font-semibold text-white">
                      {selectedZone.properties?.bearing ? `${selectedZone.properties.bearing}°` : 'N/A'} ({selectedZone.properties?.dir || 'SW'})
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-400 block text-[10px]">Distance:</span>
                    <span className="font-semibold text-white">
                      {selectedZone.properties?.distance || selectedZone.properties?.distance_km || '25'} km
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-400 block text-[10px]">Depth:</span>
                    <span className="font-semibold text-white">
                      {selectedZone.properties?.depth || selectedZone.properties?.depth_m || '40'} m
                    </span>
                  </div>
                </div>

                <div className="p-2 rounded bg-slate-900 border border-slate-800 text-[10px] font-mono text-cyan-200">
                  {selectedZone.properties?.lat_dms ||
                    (selectedZone.geometry?.coordinates &&
                      formatDMS(selectedZone.geometry.coordinates[1], true))}{' '}
                  |{' '}
                  {selectedZone.properties?.lon_dms ||
                    (selectedZone.geometry?.coordinates &&
                      formatDMS(selectedZone.geometry.coordinates[0], false))}
                </div>

                <Link
                  href={`/?zone=${encodeURIComponent(selectedZone.properties?.place || '')}`}
                  className="w-full py-2 px-3 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white font-bold text-xs transition-colors shadow flex items-center justify-center gap-1.5"
                >
                  <span>💬</span> Consult Advisory in Chat
                </Link>
              </div>
            ) : (
              <div className="p-4 rounded-xl border border-dashed border-slate-800 text-center text-slate-400 text-xs">
                <span>🎯 Click any PFZ marker on the map to inspect zone telemetry and navigation details.</span>
              </div>
            )}
          </aside>
        )}
      </div>
    </div>
  );
}
