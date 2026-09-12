/**
 * ORCA Root Page — reference UI with live backend engine.
 *
 * Matches reference `D:\downloads\ORCA (3)\ORCA` src/app/page.tsx 1:1:
 * Navbar + BottomNavigation + 7-tab router (home|chat|map|alerts|
 * pfz-detail|route|profile) with AnimatePresence transitions,
 * LivingOceanBackground owned by frontend/app/layout.tsx.
 *
 * Live-only wiring (no mocks):
 * - GPS acquire → locked, Kochi fallback, lon-lat swap guard (synced to context)
 * - Chat tab renders live SSE ChatScreen (POST /api/chat) with GPS/language/
 *   safety/map-focus callbacks
 * - Map tab renders live ExploreMapScreen (GET /api/pfz + weather + boundaries)
 * - Home/alerts/pfz-detail/route/profile render full live screens
 * - SafetyBadge fed from live chat safety state; LanguageSwitch from live state
 */

'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import type { SafetyData } from '@/chat';
import { useApp, KOCHI_FALLBACK } from '@/context/AppContext';
import { Navbar } from '@/components/layout/Navbar';
import { BottomNavigation } from '@/components/layout/BottomNavigation';
import { HomeScreen } from '@/components/screens/HomeScreen';
import { ChatScreen } from '@/components/screens/ChatScreen';
import { ExploreMapScreen } from '@/components/screens/ExploreMapScreen';
import { AlertsScreen } from '@/components/screens/AlertsScreen';
import { PFZDetailScreen } from '@/components/screens/PFZDetailScreen';
import { RouteViewScreen } from '@/components/screens/RouteViewScreen';
import { ProfileScreen } from '@/components/screens/ProfileScreen';
import { VoiceModal } from '@/components/voice/VoiceModal';
import { AuthOnboardingOverlay } from '@/components/auth/AuthOnboardingOverlay';

function MainContent({
  onSafetyUpdate,
  onLocationUpdate,
  onMapHighlight,
}: {
  onSafetyUpdate: (safety: SafetyData) => void;
  onLocationUpdate: (lat: number, lon: number) => void;
  onMapHighlight: (features: any[]) => void;
}) {
  const {
    activeTab,
    selectedLanguage,
    setSelectedLanguage,
    userLocation,
  } = useApp();

  return (
    <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 relative z-10">
      <AnimatePresence mode="wait">
        <motion.div
          key={activeTab}
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -12 }}
          transition={{ duration: 0.22, ease: 'easeOut' }}
        >
          {activeTab === 'home' && (
            <div data-testid="tab-panel-home">
              <HomeScreen />
            </div>
          )}
          {activeTab === 'chat' && (
            <div data-testid="tab-panel-chat">
              <ChatScreen
                userLocation={{ lat: userLocation.lat, lon: userLocation.lon }}
                currentLanguage={selectedLanguage}
                onLanguageChange={setSelectedLanguage}
                onLocationUpdate={onLocationUpdate}
                onMapHighlight={onMapHighlight}
                onSafetyUpdate={onSafetyUpdate}
              />
            </div>
          )}
          {activeTab === 'map' && (
            <div data-testid="tab-panel-map">
              <ExploreMapScreen />
            </div>
          )}
          {activeTab === 'alerts' && <AlertsScreen />}
          {activeTab === 'pfz-detail' && (
            <div data-testid="tab-panel-pfz-detail">
              <PFZDetailScreen />
            </div>
          )}
          {activeTab === 'route' && (
            <div data-testid="tab-panel-route">
              <RouteViewScreen />
            </div>
          )}
          {activeTab === 'profile' && <ProfileScreen />}
        </motion.div>
      </AnimatePresence>
    </main>
  );
}

function Shell() {
  const {
    themeMode,
    selectedLanguage,
    setSelectedLanguage,
    userLocation,
    setUserLocation,
    setGpsStatus,
    requestMapFocus,
    setSelectedPFZ,
  } = useApp();

  const [safetyState, setSafetyState] = useState<SafetyData>({
    waves_m: 0.8,
    wind_kts: 12,
    danger: 'none',
    badge: 'green',
    warning_text: 'SAFE',
  });

  // Acquire GPS position on client mount (Kochi fallback).
  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (!navigator.geolocation) {
      setUserLocation(KOCHI_FALLBACK);
      setGpsStatus('default');
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setUserLocation({
          lat: position.coords.latitude,
          lon: position.coords.longitude,
          name: 'Current position',
        });
        setGpsStatus('locked');
      },
      (err) => {
        console.warn(
          'Geolocation unavailable or denied, defaulting to Kochi:',
          err.message
        );
        setUserLocation(KOCHI_FALLBACK);
        setGpsStatus('default');
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleLocationUpdate = useCallback(
    (lat: number, lon: number) => {
      if (
        typeof lat !== 'number' ||
        typeof lon !== 'number' ||
        isNaN(lat) ||
        isNaN(lon) ||
        !isFinite(lat) ||
        !isFinite(lon)
      ) {
        return;
      }
      // Defend against [lon, lat] accidentally passed as [lat, lon]
      const actualLat = lat > 50 && lon < 40 ? lon : lat;
      const actualLon = lat > 50 && lon < 40 ? lat : lon;
      const boundedLat = Math.max(-90, Math.min(90, actualLat));
      const boundedLon = Math.max(-180, Math.min(180, actualLon));
      requestMapFocus({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [boundedLon, boundedLat] },
        properties: { place: 'Chat fix' },
      });
    },
    [requestMapFocus]
  );

  const handleMapHighlight = useCallback(
    (features: any[]) => {
      if (features && features.length > 0) {
        setSelectedPFZ(features[0]);
        requestMapFocus(features[0]);
      }
    },
    [setSelectedPFZ, requestMapFocus]
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

  // Leaflet caches container size: nudge it after the map container
  // becomes visible again on tab switches.
  const { activeTab } = useApp();
  useEffect(() => {
    if (activeTab !== 'map') return;
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
  void selectedLanguage;
  void handleLanguageChange;

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
      <div className="flex-1 relative z-10">
        <MainContent
          onSafetyUpdate={handleSafetyUpdate}
          onLocationUpdate={handleLocationUpdate}
          onMapHighlight={handleMapHighlight}
        />
      </div>
      <BottomNavigation />
      <VoiceModal />
      <AuthOnboardingOverlay />
    </div>
  );
}

export default function HomePage() {
  return <Shell />;
}
