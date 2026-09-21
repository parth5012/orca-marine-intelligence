/**
 * Officer mini map: shared MapView engine, no new map stack.
 *
 * Owner: M-C shell (T3 #173)
 * Module: frontend/officer/OfficerMiniMap.tsx
 *
 * Reuses fisherman MapView (dynamic ssr:false MapInner): live PFZ
 * CircleMarkers via GET /api/pfz proxy (revalidate 3600, local
 * fallback) come free with the engine. Port role: port center,
 * zoom 9, sector filter. Watch role: all-India, no sector filter.
 */

'use client';

import { useEffect, useRef } from 'react';
import MapView from '@/map/MapView';
import { useApp } from '@/context/AppContext';

interface Props {
  center: [number, number];
  zoom: number;
  sector?: string;
}

export default function OfficerMiniMap({ center, zoom, sector }: Props) {
  const { themeMode } = useApp();
  const isLight = themeMode === 'light';
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current || typeof ResizeObserver === 'undefined') return;

    const triggerInvalidate = () => {
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new Event('resize'));
      }
      const leafletEl = containerRef.current?.querySelector('.leaflet-container') as any;
      if (leafletEl && leafletEl._leaflet_map) {
        try {
          leafletEl._leaflet_map.invalidateSize();
        } catch {}
      }
    };

    const observer = new ResizeObserver(() => {
      requestAnimationFrame(triggerInvalidate);
    });

    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  // Ensure invalidateSize after role/port motion transitions (0.22s easeOut)
  useEffect(() => {
    const timer = setTimeout(() => {
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new Event('resize'));
      }
      const leafletEl = containerRef.current?.querySelector('.leaflet-container') as any;
      if (leafletEl && leafletEl._leaflet_map) {
        try {
          leafletEl._leaflet_map.invalidateSize();
        } catch {}
      }
    }, 260);
    return () => clearTimeout(timer);
  }, [center, zoom, sector]);

  return (
    <div
      ref={containerRef}
      data-testid="officer-mini-map"
      className={`h-80 w-full overflow-hidden rounded-2xl border transition-colors shadow-sm ${
        isLight
          ? 'glass-panel border-cyan-100'
          : 'glass-panel-dark border-cyan-900/40'
      }`}
    >
      <MapView center={center} zoom={zoom} sector={sector} />
    </div>
  );
}
