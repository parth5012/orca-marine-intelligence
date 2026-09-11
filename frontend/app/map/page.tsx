/**
 * ORCA Standalone Map Page (UI-MIG-T5)
 *
 * Owner: M-D (Frontend & Maps) — full-screen map page
 * Module: frontend/app/map/page.tsx
 *
 * Thin wrapper around the shared `ExploreMap` component (same engine as the
 * `/` map tab): live PFZ GeoJSON, live weather, sector/search/GPS/drawer,
 * 5 legacy toggles + 8 visual-only pills, basemap styles. All legacy
 * id/data-testid/aria-label live inside ExploreMap so both surfaces carry
 * them. Search params `?basemap=`/`?style=`/`?sector=` seed the map.
 */

'use client';

import React, { Suspense, useMemo } from 'react';
import { useSearchParams } from 'next/navigation';
import { AppProvider } from '@/context/AppContext';
import { ExploreMap } from '@/map';
import { normalizeBasemapStyle, BasemapStyle } from '@/map';

function MapPageInner() {
  // Client Component: read query params via hook (server page props are
  // unavailable here), wrapped in Suspense for static rendering.
  const searchParams = useSearchParams();
  const resolvedBasemapStyle = useMemo<BasemapStyle | undefined>(() => {
    const candidate = searchParams.get('basemap') || searchParams.get('style');
    if (candidate) {
      return normalizeBasemapStyle(candidate);
    }
    return undefined;
  }, [searchParams]);

  const initialSector = useMemo(() => {
    const raw = searchParams.get('sector');
    if (raw && raw.trim().length > 0) return raw.trim().toUpperCase();
    return undefined;
  }, [searchParams]);

  return (
    <div className="flex flex-col h-screen w-screen overflow-hidden bg-slate-950 text-slate-100 font-sans">
      <div className="flex-1 relative overflow-hidden flex p-3 sm:p-4">
        <ExploreMap
          initialBasemapStyle={resolvedBasemapStyle}
          sector={initialSector}
          showNavLinks
        />
      </div>
    </div>
  );
}

export default function MapPage() {
  return (
    <AppProvider>
      <Suspense fallback={<div className="flex-1 bg-slate-950" />}>
        <MapPageInner />
      </Suspense>
    </AppProvider>
  );
}
