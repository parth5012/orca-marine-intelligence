/**
 * MarineMap (UI-MIG-T5).
 *
 * Owner: M-D (Frontend & Maps)
 * Module: frontend/map/MarineMap.tsx
 *
 * Source-compatible dynamic ssr:false wrapper (same props shape as the
 * read-only source `MarineMap`: onMarkerClick/showRoute/centerOverride/
 * zoomOverride/heightClass) but rendering OUR live MapInner engine
 * underneath. The source MapContainer logic (mock pfzList, hardcoded
 * streamlines) is deliberately discarded — markers come from live
 * GET /api/pfz, weather from live GET /api/weather/current.
 *
 * Leaflet stays inside the ssr:false chunk (MapInner via MapView's dynamic
 * import path). This file itself imports no Leaflet code.
 */

'use client';

import React from 'react';
import dynamic from 'next/dynamic';

const MapInner = dynamic(() => import('./MapInner'), {
  ssr: false,
  loading: () => (
    <div className="w-full h-full min-h-[380px] rounded-2xl glass-panel bg-slate-950/80 flex flex-col items-center justify-center gap-3 border border-cyan-900/40 text-cyan-400">
      <div className="w-8 h-8 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin" />
      <span className="text-sm font-medium tracking-wide">
        Loading Interactive Marine Map...
      </span>
    </div>
  ),
});

export interface MarineMapProps {
  onMarkerClick?: (feature: any) => void;
  showRoute?: boolean;
  centerOverride?: [number, number];
  zoomOverride?: number;
  heightClass?: string;
  sector?: string;
  userLocation?: { lat: number; lon: number } | null;
}

export const MarineMap: React.FC<MarineMapProps> = ({
  onMarkerClick,
  showRoute: _showRoute = false,
  centerOverride,
  zoomOverride = 8,
  heightClass = 'h-full min-h-[380px]',
  sector,
  userLocation,
}) => {
  return (
    <div
      data-testid="marine-map"
      className={`relative w-full ${heightClass} rounded-2xl overflow-hidden border border-cyan-900/40 shadow-2xl`}
    >
      <MapInner
        center={centerOverride ?? [9.93, 76.27]}
        zoom={zoomOverride}
        sector={sector}
        userLocation={userLocation}
        onSelectZone={onMarkerClick}
      />
    </div>
  );
};

export default MarineMap;
