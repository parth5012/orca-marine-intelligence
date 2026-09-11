/**
 * ORCA Root Page — new app shell (UI-MIG-T2)
 *
 * Owner: M-E (Frontend Chat & App Shell)
 * Module: frontend/app/page.tsx
 *
 * New shell: Navbar + BottomNavigation + 7-tab router (home|chat|map|
 * alerts|pfz-detail|route|profile) with AnimatePresence transitions.
 * LivingOceanBackground stays owned by frontend/app/layout.tsx (T1).
 *
 * Preserved from the previous shell (no behavior regression):
 * - GPS acquire → locked, Kochi fallback, lon-lat swap guard
 * - Mobile auto-switch to map tab on zone highlight
 * - Route "/" + aliases driving activeTab: nav-brand-link (Navbar → home),
 *   mobile-tab-chat / mobile-tab-map (BottomNavigation), nav-map-link
 *   (/map full-screen page, untouched by this ticket — T5 owns it)
 * - Always-mounted chat-panel-container + map-view-container (old testids
 *   stay in the DOM on every tab; ChatPanel/MapView are never remounted so
 *   SSE conversation + Leaflet instance survive tab switches)
 * - SafetyBadge + LanguageSwitch fed from LIVE chat state, never mocks
 *
 * NOTE: tab panels for home/alerts/pfz-detail/route/profile are minimal
 * live-data placeholders; full screens land in later tickets.
 */

'use client';

import React, { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { motion, AnimatePresence } from 'framer-motion';
import { ChatPanel, SafetyData } from '@/chat';
import { MapView } from '@/map';
import { AppProvider, useApp, KOCHI_FALLBACK } from '@/context/AppContext';
import { Navbar } from '@/components/layout/Navbar';
import { BottomNavigation } from '@/components/layout/BottomNavigation';
import { AuthOnboardingOverlay } from '@/components/auth/AuthOnboardingOverlay';
import { HomeScreen } from '@/components/screens/HomeScreen';

function TabPlaceholderPanel({
  onAskOrca,
  onExploreMap,
}: {
  onAskOrca: () => void;
  onExploreMap: () => void;
}) {
  const {
    activeTab,
    setActiveTab,
    alertsList,
    selectedPFZ,
    startRouteNavigation,
    userProfile,
    selectedLanguage,
    toggleThemeMode,
    themeMode,
  } = useApp();

  const panelShell = (testid: string, children: React.ReactNode) => (
    <div
      data-testid={testid}
      className={`w-full rounded-2xl border p-5 sm:p-6 shadow-sm backdrop-blur ${
        themeMode === 'light'
          ? 'bg-white/90 border-cyan-100 text-slate-800'
          : 'glass-panel bg-slate-950/90 border-cyan-900/40 text-slate-100'
      }`}
    >
      {children}
    </div>
  );

  if (activeTab === 'home') {
    // UI-MIG-T3: full HomeScreen (hero + AskOrcaInput + live map preview +
    // live ConditionCards + featured live PFZ card). The tab-panel-home
    // testid wrapper is preserved for existing smoke tests.
    return (
      <div data-testid="tab-panel-home">
        <HomeScreen />
      </div>
    );
  }

  if (activeTab === 'alerts') {
    const redCount = alertsList.filter(
      (a) => String(a.severity).toUpperCase() === 'RED'
    ).length;
    return panelShell(
      'tab-panel-alerts',
      <div className="space-y-2">
        <h2 className="text-xl font-extrabold tracking-tight">Alerts</h2>
        <p className="text-sm opacity-70">
          {alertsList.length === 0
            ? 'No alerts in the live feed right now. Full alert wiring lands with the alerts screen.'
            : `${alertsList.length} alert(s), ${redCount} red.`}
        </p>
        <button
          type="button"
          onClick={onExploreMap}
          className="px-4 py-2 rounded-xl border border-cyan-500/40 text-sm font-bold hover:bg-cyan-50 dark:hover:bg-slate-800 transition-colors"
        >
          View on map
        </button>
      </div>
    );
  }

  if (activeTab === 'pfz-detail') {
    return panelShell(
      'tab-panel-pfz-detail',
      <div className="space-y-3">
        <h2 className="text-xl font-extrabold tracking-tight">PFZ Detail</h2>
        {selectedPFZ ? (
          <>
            <p className="text-sm opacity-80">
              Zone:{' '}
              <span className="font-bold">
                {String(selectedPFZ.name ?? selectedPFZ.id ?? 'Selected zone')}
              </span>
            </p>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() =>
                  startRouteNavigation(
                    selectedPFZ as Exclude<typeof selectedPFZ, null>
                  )
                }
                className="px-4 py-2 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white text-sm font-bold transition-colors"
              >
                Start route
              </button>
              <button
                type="button"
                onClick={onAskOrca}
                className="px-4 py-2 rounded-xl border border-cyan-500/40 text-sm font-bold hover:bg-cyan-50 dark:hover:bg-slate-800 transition-colors"
              >
                Back to chat
              </button>
            </div>
          </>
        ) : (
          <p className="text-sm opacity-70">
            No zone selected yet. Pick a zone from chat or the map.
          </p>
        )}
      </div>
    );
  }

  if (activeTab === 'route') {
    return panelShell(
      'tab-panel-route',
      <div className="space-y-3">
        <h2 className="text-xl font-extrabold tracking-tight">Route</h2>
        {selectedPFZ ? (
          <p className="text-sm opacity-80">
            Route to{' '}
            <span className="font-bold">
              {String(selectedPFZ.name ?? selectedPFZ.id ?? 'selected zone')}
            </span>{' '}
            — full turn-by-turn navigation lands with the route screen.
          </p>
        ) : (
          <p className="text-sm opacity-70">
            No destination set. Select a PFZ first, then start navigation.
          </p>
        )}
        <button
          type="button"
          onClick={onExploreMap}
          className="px-4 py-2 rounded-xl border border-cyan-500/40 text-sm font-bold hover:bg-cyan-50 dark:hover:bg-slate-800 transition-colors"
        >
          Back to map
        </button>
      </div>
    );
  }

  if (activeTab === 'profile') {
    return panelShell(
      'tab-panel-profile',
      <div className="space-y-2">
        <h2 className="text-xl font-extrabold tracking-tight">Profile</h2>
        <p className="text-sm font-bold">{userProfile.name}</p>
        <p className="text-xs opacity-70">{userProfile.roleTitle}</p>
        {userProfile.org && (
          <p className="text-xs opacity-70">{userProfile.org}</p>
        )}
        <p className="text-xs opacity-70">Language: {selectedLanguage}</p>
        <button
          type="button"
          onClick={toggleThemeMode}
          data-testid="theme-toggle-profile"
          className="px-4 py-2 rounded-xl border border-cyan-500/40 text-sm font-bold hover:bg-cyan-50 dark:hover:bg-slate-800 transition-colors"
        >
          Toggle theme
        </button>
      </div>
    );
  }

  return null;
}

function Shell() {
  const {
    activeTab,
    setActiveTab,
    themeMode,
    selectedLanguage,
    setSelectedLanguage,
    userLocation,
    setUserLocation,
    gpsStatus,
    setGpsStatus,
    voiceModalOpen,
    setVoiceModalOpen,
  } = useApp();

  const [mapCenter, setMapCenter] = useState<[number, number]>([
    KOCHI_FALLBACK.lat,
    KOCHI_FALLBACK.lon,
  ]);
  const [mapZoom, setMapZoom] = useState<number>(8);
  const [highlightFeatures, setHighlightFeatures] = useState<any[]>([]);

  const [safetyState, setSafetyState] = useState<SafetyData>({
    waves_m: 0.8,
    wind_kts: 12,
    danger: 'none',
    badge: 'green',
    warning_text: 'SAFE',
  });

  // Acquire GPS position on client mount (preserved + synced to context for the Navbar pill)
  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (!navigator.geolocation) {
      setUserLocation(KOCHI_FALLBACK);
      setMapCenter([KOCHI_FALLBACK.lat, KOCHI_FALLBACK.lon]);
      setGpsStatus('default');
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const lat = position.coords.latitude;
        const lon = position.coords.longitude;
        setUserLocation({ lat, lon, name: 'Current position' });
        setMapCenter([lat, lon]);
        setGpsStatus('locked');
      },
      (err) => {
        console.warn(
          'Geolocation unavailable or denied, defaulting to Kochi:',
          err.message
        );
        setUserLocation(KOCHI_FALLBACK);
        setMapCenter([KOCHI_FALLBACK.lat, KOCHI_FALLBACK.lon]);
        setGpsStatus('default');
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleLocationUpdate = useCallback((lat: number, lon: number) => {
    // Edge-case guard: fallback to default if invalid coordinates
    if (
      typeof lat !== 'number' ||
      typeof lon !== 'number' ||
      isNaN(lat) ||
      isNaN(lon) ||
      !isFinite(lat) ||
      !isFinite(lon)
    ) {
      setMapCenter([KOCHI_FALLBACK.lat, KOCHI_FALLBACK.lon]);
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

  const handleMapHighlight = useCallback(
    (features: any[]) => {
      setHighlightFeatures(features);
      // If on mobile screen, auto-switch to map tab so user sees highlighted zone
      if (
        features &&
        features.length > 0 &&
        typeof window !== 'undefined' &&
        window.innerWidth < 768
      ) {
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
    },
    [setActiveTab]
  );

  const handleSafetyUpdate = useCallback((safety: SafetyData) => {
    setSafetyState(safety);
  }, []);

  const handleLanguageChange = useCallback(
    (newLang: string) => {
      setSelectedLanguage(newLang);
    },
    [setSelectedLanguage]
  );

  // Leaflet caches container size (trackResize): nudge it after the map
  // container becomes visible again on tab switches.
  useEffect(() => {
    if (activeTab !== 'chat' && activeTab !== 'map') return;
    if (typeof window === 'undefined') return;
    const frame = requestAnimationFrame(() =>
      window.dispatchEvent(new Event('resize'))
    );
    const timer = setTimeout(
      () => window.dispatchEvent(new Event('resize')),
      350
    );
    return () => {
      cancelAnimationFrame(frame);
      clearTimeout(timer);
    };
  }, [activeTab]);

  const isLight = themeMode === 'light';
  const isChatTab = activeTab === 'chat';
  const isMapTab = activeTab === 'map';
  const showSplit = isChatTab || isMapTab;

  return (
    <div
      className={`min-h-screen flex flex-col font-sans transition-colors duration-300 relative ${
        isLight
          ? 'bg-[#edf6ff] text-slate-900 selection:bg-cyan-200 selection:text-cyan-900'
          : 'bg-[#070d18] text-slate-100 selection:bg-cyan-500 selection:text-slate-950'
      }`}
    >
      <Navbar
        safety={{
          waves_m: safetyState.waves_m,
          wind_kts: safetyState.wind_kts,
          danger: safetyState.danger,
          badge: safetyState.badge,
        }}
      />

      <main
        className={`max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 relative z-10 ${
          showSplit
            ? 'flex-1 flex flex-col overflow-hidden h-[calc(100vh-4rem)] pb-16 md:pb-0'
            : 'flex-1 py-6 pb-24 md:pb-6'
        }`}
      >
        {/* Animated tab panels for home/alerts/pfz-detail/route/profile.
            Chat + map tabs render the persistent split below (never remounted). */}
        {!showSplit && (
          <AnimatePresence mode="wait">
            <motion.div
              key={activeTab}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -12 }}
              transition={{ duration: 0.22, ease: 'easeOut' }}
            >
              <TabPlaceholderPanel
                onAskOrca={() => setActiveTab('chat')}
                onExploreMap={() => setActiveTab('map')}
              />
            </motion.div>
          </AnimatePresence>
        )}

        {/* Persistent split: ChatPanel + MapView stay mounted on every tab
            (CSS-toggled) so SSE state and the Leaflet instance survive. */}
        <div
          className={`flex-1 flex-col md:flex-row overflow-hidden relative ${
            showSplit ? 'flex' : 'hidden'
          }`}
        >
          {/* Left Side: Chat Advisory Panel */}
          <section
            id="chat-panel-container"
            data-testid="chat-panel-container"
            role="tabpanel"
            aria-labelledby="mobile-tab-chat"
            className={`h-full flex-shrink-0 transition-all duration-300 z-10 ${
              isChatTab ? 'flex' : 'hidden'
            } w-full md:w-[440px] lg:w-[480px] xl:w-[520px]`}
          >
            <div className="w-full h-full">
              <ChatPanel
                userLocation={
                  gpsStatus === 'acquiring'
                    ? null
                    : { lat: userLocation.lat, lon: userLocation.lon }
                }
                currentLanguage={selectedLanguage}
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
            className={`h-full flex-1 relative ${
              isLight ? 'bg-[#edf6ff]' : 'bg-[#070d18]'
            } ${isChatTab || isMapTab ? 'flex' : 'hidden'} flex-col`}
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
                    {highlightFeatures.length} Active Zone
                    {highlightFeatures.length > 1 ? 's' : ''}
                  </span>
                )}
              </div>

              <div className="pointer-events-auto hidden sm:flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => {
                    if (gpsStatus !== 'acquiring') {
                      setMapCenter([userLocation.lat, userLocation.lon]);
                      setMapZoom(11);
                    }
                  }}
                  className="px-2.5 py-1.5 rounded-lg bg-slate-900/90 hover:bg-slate-800 text-cyan-300 border border-slate-700/80 backdrop-blur text-xs font-medium transition-colors shadow flex items-center gap-1.5"
                  title="Recenter to your coastal location"
                >
                  <span>📍</span> Recenter GPS
                </button>
                <Link
                  href="/map"
                  id="nav-map-link"
                  data-testid="nav-map-link"
                  aria-label="Open full Ocean Map page"
                  className="px-2.5 py-1.5 rounded-lg bg-slate-900/90 hover:bg-slate-800 text-cyan-300 border border-slate-700/80 backdrop-blur text-xs font-medium transition-colors shadow flex items-center gap-1.5"
                >
                  <span>🗺️</span> Full map
                </Link>
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
      </main>

      <BottomNavigation />

      {/* Minimal voice-modal shell (full voice UI lands with its ticket) */}
      {voiceModalOpen && (
        <div
          data-testid="voice-modal"
          role="dialog"
          aria-label="Voice input"
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/60 backdrop-blur-sm"
          onClick={() => setVoiceModalOpen(false)}
        >
          <div
            className={`w-full max-w-sm rounded-2xl border p-5 shadow-2xl ${
              isLight
                ? 'bg-white border-cyan-100 text-slate-800'
                : 'bg-slate-950 border-cyan-900/40 text-slate-100'
            }`}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-base font-extrabold">Voice input</h3>
            <p className="text-sm opacity-70 mt-1">
              Vernacular voice input lives in the chat panel (Bhashini). The
              full voice modal lands with its ticket.
            </p>
            <div className="flex justify-end gap-2 mt-4">
              <button
                type="button"
                onClick={() => {
                  setVoiceModalOpen(false);
                  setActiveTab('chat');
                }}
                className="px-4 py-2 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white text-sm font-bold transition-colors"
              >
                Open chat
              </button>
              <button
                type="button"
                onClick={() => setVoiceModalOpen(false)}
                className="px-4 py-2 rounded-xl border border-cyan-500/40 text-sm font-bold transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      <AuthOnboardingOverlay />
    </div>
  );
}

export default function HomePage() {
  return (
    <AppProvider>
      <Shell />
    </AppProvider>
  );
}
