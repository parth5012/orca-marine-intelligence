/**
 * ExploreMapScreen — reference UI with live backend engine.
 *
 * Owner: M-D (Frontend & Maps)
 * Module: frontend/components/screens/ExploreMapScreen.tsx
 *
 * Matches reference `ExploreMapScreen` visual 1:1 (floating search bar,
 * Find Nearest PFZ, Layers toggle, bottom drawer) via shared live
 * `ExploreMap` engine (GET /api/pfz, GET /api/weather/current,
 * EEZ/MPA/IMBL boundaries). No mocks.
 */

'use client';

import React, { useCallback, useMemo } from 'react';
import { ExploreMap } from '@/map';
import { useApp } from '@/context/AppContext';

export const ExploreMapScreen: React.FC = () => {
  const {
    userLocation,
    setSelectedPFZ,
    mapFocusFeature,
    mapFocusNonce,
    requestMapFocus,
  } = useApp();

  const center = useMemo<[number, number]>(
    () => [userLocation.lat, userLocation.lon],
    [userLocation.lat, userLocation.lon]
  );

  // Map focus requests (chat zone flyTo, detail View-on-Map) arrive via
  // AppContext nonce; ExploreMap picks up highlightFeatures prop change.
  const highlightFeatures = useMemo(() => {
    if (mapFocusFeature && mapFocusNonce > 0) return [mapFocusFeature];
    return undefined;
  }, [mapFocusFeature, mapFocusNonce]);

  const handleSelectZone = useCallback(
    (feature: any) => {
      setSelectedPFZ(feature);
      requestMapFocus(feature);
    },
    [setSelectedPFZ, requestMapFocus]
  );

  return (
    // Reference sizing: the inner ExploreMap engine is h-full, so this
    // wrapper must own a real height or the Leaflet canvas collapses to 0px.
    <div
      data-testid="explore-map-screen"
      className="relative w-full h-[calc(100vh-100px)] min-h-[580px]"
    >
      <ExploreMap
        center={center}
        zoom={8}
        highlightFeatures={highlightFeatures}
        userLocation={{ lat: userLocation.lat, lon: userLocation.lon }}
        onSelectZone={handleSelectZone}
        showNavLinks={false}
      />
    </div>
  );
};

export default ExploreMapScreen;
