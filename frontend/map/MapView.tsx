/**
 * MapView Component
 *
 * Owner: M-D (Frontend & Maps) — Leaflet map with PFZ circles & maritime boundaries
 * Module: frontend/map/MapView.tsx
 *
 * Client-side dynamic wrapper around MapInner to prevent SSR `window is not defined`
 * errors with Leaflet.
 */

'use client';

import React from 'react';
import dynamic from 'next/dynamic';
import type { MapInnerProps, MapLayerToggles } from './MapInner';

export type { MapLayerToggles };

export type MapViewProps = MapInnerProps & {
  className?: string;
  style?: React.CSSProperties;
};

const MapInner = dynamic(() => import('./MapInner'), {
  ssr: false,
  loading: () => (
    <div className="w-full h-full min-h-[400px] flex items-center justify-center bg-slate-950 text-cyan-400 border border-slate-800">
      <div className="flex flex-col items-center gap-3">
        <div className="w-9 h-9 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin" />
        <div className="text-xs font-mono tracking-wider uppercase text-slate-300">
          Loading ORCA Ocean Map...
        </div>
      </div>
    </div>
  ),
});

export default function MapView({ className, style, ...props }: MapViewProps) {
  return (
    <div
      className={`map-view relative w-full h-full overflow-hidden ${className || ''}`}
      style={style}
    >
      <MapInner {...props} />
    </div>
  );
}
