/**
 * ORCA Root Page
 *
 * Owner: M-E (Frontend Chat & App Shell) - Full Shell: ChatPanel, MapView, flyTo, GPS
 * Module: frontend/app/page.tsx
 *
 * Main application shell combining:
 * 1. Top bar: ORCA branding, live GPS badge, SafetyBadge, and LanguageSwitch
 * 2. Left panel: ChatPanel with real-time SSE streaming, subagent reasoning accordion,
 *    structured marine zone cards, and vernacular voice input
 * 3. Right panel: MapView spatial visualization with zone highlights and flyTo
 * 4. Responsive layout: side-by-side on desktop, tabbed/stacked on mobile
 */

'use client';

import React, { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { ChatPanel, LanguageSwitch, SafetyData } from '@/chat';
import { MapView, SafetyBadge } from '@/map';

export default function HomePage() {
  const [userLocation, setUserLocation] = useState<{ lat: number; lon: number } | null>(null);
  const [mapCenter, setMapCenter] = useState<[number, number]>([9.93, 76.27]); // Default: Kochi Coast
  const [mapZoom, setMapZoom] = useState<number>(8);
  const [highlightFeatures, setHighlightFeatures] = useState<any[]>([]);
  const [activeTab, setActiveTab] = useState<'chat' | 'map'>('chat'); // Mobile tab toggle
  const [language, setLanguage] = useState<string>('en');
  const [gpsStatus, setGpsStatus] = useState<'acquiring' | 'locked' | 'default'>('acquiring');

  const [safetyState, setSafetyState] = useState<SafetyData>({
    waves_m: 0.8,
    wind_kts: 12,
    danger: 'none',
    badge: 'green',
    warning_text: 'SAFE',
  });

  // Acquire GPS position on client mount
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const storedLang = localStorage.getItem('orca_language');
      if (storedLang) {
        setLanguage(storedLang);
      }

      if (navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(
          (position) => {
            const lat = position.coords.latitude;
            const lon = position.coords.longitude;
            setUserLocation({ lat, lon });
            setMapCenter([lat, lon]);
            setGpsStatus('locked');
          },
          (err) => {
            console.warn('Geolocation unavailable or denied, defaulting to Kochi:', err.message);
            // Default to Kochi harbor waters
            setUserLocation({ lat: 9.93, lon: 76.27 });
            setMapCenter([9.93, 76.27]);
            setGpsStatus('default');
          },
          { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
        );
      } else {
        setUserLocation({ lat: 9.93, lon: 76.27 });
        setGpsStatus('default');
      }
    }
  }, []);

  const handleLocationUpdate = useCallback((lat: number, lon: number) => {
    // Edge-case guard: fallback to default if invalid coordinates
    if (typeof lat !== 'number' || typeof lon !== 'number' || isNaN(lat) || isNaN(lon) || !isFinite(lat) || !isFinite(lon)) {
      setMapCenter([9.93, 76.27]);
      setMapZoom(11);
      return;
    }
    // Defend against [lon, lat] accidentally passed as [lat, lon]
    const actualLat = lat > 50 && lon < 40 ? lon : lat;
    const actualLon = lat > 50 && lon < 40 ? lat : lon;
    const boundedLat = Math.max(-90, Math.min(90, actualLat));
    const boundedLon = Math.max(-180, Math.min(180, actualLon));
    setMapCenter([boundedLat, boundedLon]);
    setMapZoom(11);
  }, []);

  const handleMapHighlight = useCallback((features: any[]) => {
    setHighlightFeatures(features);
    // If on mobile screen, auto-switch to map tab so user sees highlighted zone
    if (features && features.length > 0 && typeof window !== 'undefined' && window.innerWidth < 768) {
      setActiveTab('map');
    }
    if (features.length > 0) {
      const first = features[0];
      const geom = first?.geometry;
      if (geom?.coordinates) {
        if (geom.type === 'Point') {
          // GeoJSON is [lon, lat]
          setMapCenter([geom.coordinates[1], geom.coordinates[0]]);
          setMapZoom(11);
        } else if (geom.type === 'Polygon' && geom.coordinates[0]?.[0]) {
          setMapCenter([geom.coordinates[0][0][1], geom.coordinates[0][0][0]]);
          setMapZoom(10);
        }
      }
    }
  }, []);

  const handleSafetyUpdate = useCallback((safety: SafetyData) => {
    setSafetyState(safety);
  }, []);

  const handleLanguageChange = useCallback((newLang: string) => {
    setLanguage(newLang);
  }, []);

  return (
    <div className="flex flex-col h-screen w-screen overflow-hidden bg-slate-950 text-slate-100">
      {/* Top Application Header Bar */}
      <header className="h-16 px-4 bg-slate-900/95 border-b border-slate-800 flex items-center justify-between z-30 flex-shrink-0 backdrop-blur">
        {/* Brand & Project Info */}
        <Link
          href="/"
          id="nav-brand-link"
          data-testid="nav-brand-link"
          aria-label="ORCA Home"
          className="flex items-center gap-3 hover:opacity-95 transition-opacity"
        >
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-cyan-600 via-sky-500 to-blue-600 flex items-center justify-center text-xl shadow-lg shadow-cyan-900/40 border border-cyan-400/30">
            🐬
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-base sm:text-lg font-black tracking-tight text-white">
                ORCA
              </h1>
              <span className="text-xs sm:text-sm font-semibold text-cyan-400 tracking-wide">
                Marine Intelligence
              </span>
              <span className="hidden lg:inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold bg-cyan-950 text-cyan-300 border border-cyan-800">
                SIH26176
              </span>
            </div>
            <p className="text-[11px] text-slate-400 hidden sm:block">
              Autonomous Ocean Advisory, PFZ Telemetry & Safety System
            </p>
          </div>
        </Link>

        {/* Center: GPS & System Telemetry Status */}
        <div className="hidden md:flex items-center gap-2.5">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-xs text-slate-300">
            <span
              className={`w-2 h-2 rounded-full ${
                gpsStatus === 'locked'
                  ? 'bg-emerald-400 animate-pulse'
                  : gpsStatus === 'acquiring'
                  ? 'bg-amber-400 animate-ping'
                  : 'bg-cyan-400'
              }`}
            />
            <span className="font-medium text-slate-400">GPS:</span>
            <span className="font-mono text-cyan-300">
              {userLocation
                ? `${userLocation.lat.toFixed(2)}°N, ${userLocation.lon.toFixed(2)}°E`
                : 'Acquiring...'}
            </span>
          </div>
        </div>

        {/* Right Controls: SafetyBadge, LanguageSwitch, Map Navigation */}
        <div className="flex items-center gap-2 sm:gap-3">
          <Link
            href="/map"
            id="nav-map-link"
            data-testid="nav-map-link"
            aria-label="Open Ocean Map"
            className="hidden sm:inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-900/90 hover:bg-slate-800 text-cyan-300 border border-slate-700 text-xs font-semibold transition-colors shadow-sm"
          >
            <span>🗺️</span>
            <span>Ocean Map</span>
          </Link>
          <SafetyBadge
            waves={safetyState.waves_m}
            wind={safetyState.wind_kts}
            danger={safetyState.danger}
            badge={safetyState.badge}
            language={language}
          />

          <LanguageSwitch
            currentLanguage={language}
            onLanguageChange={handleLanguageChange}
          />
        </div>
      </header>

      {/* Mobile Tab Switcher */}
      <div
        role="tablist"
        aria-label="Mobile Navigation"
        className="flex md:hidden bg-slate-900 border-b border-slate-800 p-1"
      >
        <button
          type="button"
          id="mobile-tab-chat"
          data-testid="mobile-tab-chat"
          role="tab"
          aria-selected={activeTab === 'chat'}
          aria-controls="chat-panel-container"
          aria-label="Switch to Chat Advisory Tab"
          onClick={() => setActiveTab('chat')}
          className={`flex-1 py-2 text-xs font-bold rounded-lg transition-all flex items-center justify-center gap-1.5 ${
            activeTab === 'chat'
              ? 'bg-cyan-600 text-white shadow-md'
              : 'text-slate-400 hover:text-slate-200'
          }`}
        >
          <span>💬</span> Chat Advisory
        </button>
        <button
          type="button"
          id="mobile-tab-map"
          data-testid="mobile-tab-map"
          role="tab"
          aria-selected={activeTab === 'map'}
          aria-controls="map-view-container"
          aria-label="Switch to Ocean Map Tab"
          onClick={() => setActiveTab('map')}
          className={`flex-1 py-2 text-xs font-bold rounded-lg transition-all flex items-center justify-center gap-1.5 ${
            activeTab === 'map'
              ? 'bg-cyan-600 text-white shadow-md'
              : 'text-slate-400 hover:text-slate-200'
          }`}
        >
          <span>🗺️</span> Ocean Map {highlightFeatures.length > 0 && `(${highlightFeatures.length})`}
        </button>
      </div>

      {/* Main Content Area: Side-by-Side on Desktop */}
      <div className="flex-1 flex flex-col md:flex-row overflow-hidden relative">
        {/* Left Side: Chat Advisory Panel */}
        <section
          id="chat-panel-container"
          data-testid="chat-panel-container"
          role="tabpanel"
          aria-labelledby="mobile-tab-chat"
          className={`h-full flex-shrink-0 transition-all duration-300 z-10 ${
            activeTab === 'chat' ? 'flex' : 'hidden md:flex'
          } w-full md:w-[440px] lg:w-[480px] xl:w-[520px]`}
        >
          <div className="w-full h-full">
            <ChatPanel
              userLocation={userLocation}
              currentLanguage={language}
              onLanguageChange={handleLanguageChange}
              onLocationUpdate={handleLocationUpdate}
              onMapHighlight={handleMapHighlight}
              onSafetyUpdate={handleSafetyUpdate}
            />
          </div>
        </section>

        {/* Right Side: Map Visualization */}
        <section
          id="map-view-container"
          data-testid="map-view-container"
          role="tabpanel"
          aria-labelledby="mobile-tab-map"
          className={`h-full flex-1 relative bg-slate-950 ${
            activeTab === 'map' ? 'flex' : 'hidden md:flex'
          } flex-col`}
        >
          {/* Map Top Status Bar */}
          <div className="absolute top-3 left-3 right-3 z-20 pointer-events-none flex items-center justify-between">
            <div className="pointer-events-auto px-3 py-1.5 rounded-lg bg-slate-900/90 border border-slate-700/80 backdrop-blur shadow-md flex items-center gap-2 text-xs text-slate-300">
              <span className="w-2 h-2 rounded-full bg-cyan-400" />
              <span className="font-semibold text-white">Spatial View:</span>
              <span className="text-cyan-300 font-mono">
                [{mapCenter[0].toFixed(2)}, {mapCenter[1].toFixed(2)}]
              </span>
              {highlightFeatures.length > 0 && (
                <span className="bg-cyan-950 text-cyan-300 px-2 py-0.5 rounded text-[11px] font-bold border border-cyan-800 ml-1">
                  {highlightFeatures.length} Active Zone{highlightFeatures.length > 1 ? 's' : ''}
                </span>
              )}
            </div>

            <div className="pointer-events-auto hidden sm:flex items-center gap-2">
              <button
                type="button"
                onClick={() => {
                  if (userLocation) {
                    setMapCenter([userLocation.lat, userLocation.lon]);
                    setMapZoom(11);
                  }
                }}
                className="px-2.5 py-1.5 rounded-lg bg-slate-900/90 hover:bg-slate-800 text-cyan-300 border border-slate-700/80 backdrop-blur text-xs font-medium transition-colors shadow flex items-center gap-1.5"
                title="Recenter to your coastal location"
              >
                <span>📍</span> Recenter GPS
              </button>
            </div>
          </div>

          <div className="w-full h-full">
            <MapView
              center={mapCenter}
              zoom={mapZoom}
              highlightFeatures={highlightFeatures}
            />
          </div>
        </section>
      </div>
    </div>
  );
}
