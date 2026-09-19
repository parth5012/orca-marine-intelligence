/**
 * MapInner Component (Client-only Leaflet instance)
 *
 * Owner: M-D (Frontend & Maps)
 * Module: frontend/map/MapInner.tsx
 *
 * Interactive React-Leaflet map integrating:
 * 1. OpenStreetMap / CartoDB tile layer
 * 2. PFZ CircleMarkers colored by suitability (green/high, amber/medium, yellow/low)
 * 3. EEZ Blue boundary polygons (India EEZ)
 * 4. MPA Red danger polygons with warning popups
 * 5. IMBL Dashed orange/red international border line
 * 6. Highlighted zone marker with pulse ring & navigation polyline from user GPS
 * 7. Live marine weather tooltip / inspector at center or clicked location
 * 8. Smooth flyTo camera animations on coordinate updates
 */

'use client';

import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  MapContainer,
  TileLayer,
  CircleMarker,
  Polyline,
  Polygon,
  Popup,
  Tooltip,
  Marker,
  useMap,
  useMapEvents,
} from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

import { EEZ_GEOJSON, MPA_GEOJSON, IMBL_COORDINATES } from './boundaries';
import { haversineDistance, bearing, formatDMS, getCompassDirection } from './geo';
import SafetyBadge from './SafetyBadge';
import { toFiniteNumber, MISSING, distanceLabel, suitabilityLabel } from './drawerHonesty';
import {
  BasemapStyle,
  BASEMAP_OPTIONS,
  getBasemapTileUrl,
  getDefaultBasemapStyle,
  getThemeBasemapStyle,
  getBasemapAttribution,
  getBasemapMaxNativeZoom,
  getBasemapMaxZoom,
  CARTO_ATTRIBUTION,
  OSM_ATTRIBUTION,
  ESRI_OCEAN_ATTRIBUTION,
  ESRI_DARK_ATTRIBUTION,
} from './carto';
import { useThemeModeOptional } from '@/context/AppContext';
import { haversineKm, segmentCrossesPolygon } from '@/lib/pfz';

export interface MapLayerToggles {
  pfz?: boolean;
  eez?: boolean;
  mpa?: boolean;
  imbl?: boolean;
  weather?: boolean;
  /**
   * Visual-only design pills (UI-MIG-T5, see frontend/map/layers.ts).
   * All optional; missing keys default to true (legacy 5-key callers keep
   * full visuals). cyclone/lightning are reserved no-ops until a live
   * source exists — accepted, never mocked.
   */
  sst?: boolean;
  chlorophyll?: boolean;
  waves?: boolean;
  wind?: boolean;
  currents?: boolean;
  cyclone?: boolean;
  lightning?: boolean;
  restricted?: boolean;
}

export interface MapInnerProps {
  center?: [number, number];
  zoom?: number;
  highlightFeatures?: any[];
  userLocation?: { lat: number; lon: number } | null;
  onSelectZone?: (feature: any) => void;
  activeLayers?: MapLayerToggles;
  sector?: string;
  onCenterChange?: (center: [number, number]) => void;
  initialBasemapStyle?: BasemapStyle;
  route?: [number, number][] | number[][] | null;
  routeMeta?: {
    detourOccurred?: boolean;
    safetyLabel?: 'SAFE' | 'CAUTION' | 'AVOID';
  } | null;
  themeMode?: 'light' | 'dark';
}

interface LiveWeatherState {
  lat: number;
  lon: number;
  temperature_c?: number;
  wind_speed_kt?: number;
  wave_height_m?: number;
  status?: string;
  danger?: string;
  badge?: string;
  source?: string;
  loading?: boolean;
}

/**
 * Controller hook for fly-to transitions and center synchronization.
 */
function MapController({
  center,
  zoom,
  highlightFeatures,
}: {
  center: [number, number];
  zoom: number;
  highlightFeatures?: any[];
}) {
  const map = useMap();

  useEffect(() => {
    if (highlightFeatures && highlightFeatures.length > 0) {
      const first = highlightFeatures[0];
      const coords = first.geometry?.coordinates || first.coordinates;
      if (Array.isArray(coords) && coords.length >= 2) {
        // Handle GeoJSON [lon, lat] vs standard [lat, lon]
        const lat = coords[0] > 50 && coords[1] < 40 ? coords[1] : coords[0];
        const lon = coords[0] > 50 && coords[1] < 40 ? coords[0] : coords[1];
        if (typeof lat === 'number' && typeof lon === 'number' && Number.isFinite(lat) && Number.isFinite(lon)) {
          try { map.flyTo([lat, lon], Math.max(map.getZoom() || 8, 9), { duration: 1.2 }); } catch (err) { console.warn('Safe flyTo prevented crash:', err); }
          return;
        }
      }
    }
    if (center && center.length === 2 && typeof center[0] === 'number' && typeof center[1] === 'number' && Number.isFinite(center[0]) && Number.isFinite(center[1])) {
      try { map.flyTo(center, (typeof zoom === 'number' && Number.isFinite(zoom)) ? zoom : (map.getZoom() || 8), { duration: 1.0 }); } catch (err) { console.warn('Safe flyTo prevented crash:', err); }
    }
  }, [center, zoom, highlightFeatures, map]);

  return null;
}

/**
 * Map click handler to inspect weather and coordinates at any ocean location.
 */
function MapClickHandler({
  onMapClick,
}: {
  onMapClick: (lat: number, lon: number) => void;
}) {
  useMapEvents({
    click(e) {
      onMapClick(e.latlng.lat, e.latlng.lng);
    },
  });
  return null;
}

export default function MapInner({
  center = [9.93, 76.27],
  zoom = 8,
  highlightFeatures = [],
  userLocation,
  onSelectZone,
  activeLayers: initialLayers,
  sector,
  onCenterChange,
  initialBasemapStyle,
  route,
  routeMeta,
  themeMode,
}: MapInnerProps) {
  const autoTheme = useThemeModeOptional();
  const effTheme = themeMode ?? autoTheme ?? 'dark';
  const isLight = effTheme === 'light';

  const [hasManualOverride, setHasManualOverride] = useState<boolean>(
    Boolean(initialBasemapStyle)
  );

  // Basemap style state & fallback handling
  const [basemapStyle, setBasemapStyle] = useState<BasemapStyle>(
    getThemeBasemapStyle(effTheme, initialBasemapStyle)
  );

  useEffect(() => {
    if (!hasManualOverride) {
      tileErrorsRef.current = 0;
      setTileError(false);
      setBasemapStyle(getThemeBasemapStyle(effTheme));
    }
  }, [effTheme, hasManualOverride]);

  const [tileError, setTileError] = useState<boolean>(false);
  const tileErrorsRef = useRef<number>(0);

  // Layer toggles
  const [layers, setLayers] = useState<MapLayerToggles>({
    pfz: true,
    eez: true,
    mpa: true,
    imbl: true,
    weather: true,
    ...initialLayers,
  });

  // Keep internal layer state in sync if parent passes activeLayers
  useEffect(() => {
    if (initialLayers) {
      setLayers((prev) => ({ ...prev, ...initialLayers }));
    }
  }, [initialLayers]);

  // Green route polyline from user GPS to recommended zone (T4 #119)
  const routePositions = useMemo<[number, number][] | null>(() => {
    if (!route || !Array.isArray(route) || route.length < 2) return null;
    const validPoints: [number, number][] = [];
    for (const pt of route) {
      if (!Array.isArray(pt) || pt.length < 2) continue;
      const num0 = Number(pt[0]);
      const num1 = Number(pt[1]);
      if (!Number.isFinite(num0) || !Number.isFinite(num1)) continue;
      // Convert GeoJSON [lon, lat] to Leaflet [lat, lon]
      // In Indian waters (lat 5-30, lon 65-95), if num0 > 40 and num1 < 40, pt is [lon, lat]
      const lat = num0 > 40 && num1 < 40 ? num1 : num0;
      const lon = num0 > 40 && num1 < 40 ? num0 : num1;
      if (lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180) {
        validPoints.push([lat, lon]);
      }
    }
    return validPoints.length >= 2 ? validPoints : null;
  }, [route]);

  const routeStats = useMemo(() => {
    if (!routePositions || routePositions.length < 2) return null;
    let distKm = 0;
    for (let i = 0; i < routePositions.length - 1; i++) {
      distKm += haversineKm(
        routePositions[i][0],
        routePositions[i][1],
        routePositions[i + 1][0],
        routePositions[i + 1][1]
      );
    }
    const distNm = distKm / 1.852;
    const start = routePositions[0];
    const end = routePositions[routePositions.length - 1];
    const b = bearing(start[0], start[1], end[0], end[1]);
    const compass = getCompassDirection(b);
    const etaMin = Math.max(5, Math.round((distKm / 25) * 60));

    // Check if any segment crosses an MPA polygon
    let crossesMPA = false;
    let crossedMpaName = '';
    for (const feat of MPA_GEOJSON.features) {
      if (feat.geometry.type !== 'Polygon') continue;
      const ring = feat.geometry.coordinates[0];
      const polyLatLon: [number, number][] = ring.map((pt: [number, number]) => [pt[1], pt[0]]);
      for (let i = 0; i < routePositions.length - 1; i++) {
        if (segmentCrossesPolygon(routePositions[i], routePositions[i + 1], polyLatLon)) {
          crossesMPA = true;
          crossedMpaName = feat.properties.mpa_name || 'Protected Marine Reserve';
          break;
        }
      }
      if (crossesMPA) break;
    }

    // Prefer authoritative route metadata when the caller passes it:
    // buildSafeRoute adds a plain midpoint to every direct route, so
    // waypoint count alone mislabels normal SAFE routes as detours.
    const hasDetour = routeMeta?.detourOccurred ?? routePositions.length > 2;
    const safety: 'SAFE' | 'CAUTION' | 'AVOID' =
      routeMeta?.safetyLabel ?? (crossesMPA ? 'AVOID' : hasDetour ? 'CAUTION' : 'SAFE');
    const safeColor = isLight ? '#059669' : '#10b981';
    const detourColor = isLight ? '#d97706' : '#f59e0b';
    const dangerColor = isLight ? '#dc2626' : '#ef4444';

    return {
      distKm: Number(distKm.toFixed(1)),
      distNm: Number(distNm.toFixed(1)),
      bearingDeg: Math.round(b),
      bearingLabel: `${compass} ${Math.round(b)}°`,
      etaMin,
      crossesMPA,
      crossedMpaName,
      hasDetour,
      safety,
      color: safety === 'AVOID' ? dangerColor : safety === 'CAUTION' ? detourColor : safeColor,
    };
  }, [routePositions, isLight, routeMeta]);

  // UI-MIG-T5 visual-only flags (missing => true so legacy 5-key bags are unchanged).
  const ext = layers as Record<string, boolean | undefined>;
  const sstOn = ext.sst !== false;
  const chlorophyllOn = ext.chlorophyll !== false;
  const wavesOn = ext.waves !== false;
  const windOn = ext.wind !== false;
  const currentsOn = ext.currents !== false;
  // cyclone/lightning are reserved no-ops (accepted, never mocked) — no overlay yet.
  const restrictedOn = ext.restricted !== false;
  const mpaEmphasis = layers.mpa ? (restrictedOn ? 1 : 0.45) : 0;

  // PFZ GeoJSON points fetched from proxy
  const [pfzFeatures, setPfzFeatures] = useState<any[]>([]);
  const [pfzLoading, setPfzLoading] = useState<boolean>(true);
  const [selectedFeature, setSelectedFeature] = useState<any | null>(null);

  // Weather inspection state. Ticket #195: pre-fetch state is UNKNOWN
  // (amber) with no measurements — never SAFE-looking numbers.
  const [weatherState, setWeatherState] = useState<LiveWeatherState>({
    lat: center[0],
    lon: center[1],
    status: 'Sea state unavailable',
    danger: 'unknown',
    badge: 'amber',
    source: 'live_api',
    loading: false,
  });

  const [showLayerPanel, setShowLayerPanel] = useState<boolean>(false);

  // Live GPS tracking when userLocation is not provided or to track live updates (T6 #121)
  const [geoLoc, setGeoLoc] = useState<{ lat: number; lon: number } | null>(null);

  useEffect(() => {
    if (typeof window === 'undefined' || !navigator.geolocation) return;
    let watchId: number | null = null;
    try {
      watchId = navigator.geolocation.watchPosition(
        (pos) => {
          if (pos && pos.coords) {
            setGeoLoc({ lat: pos.coords.latitude, lon: pos.coords.longitude });
          }
        },
        (_err) => {
          // GPS permission denied or unavailable - graceful fallback (no crash)
        },
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 }
      );
    } catch (_e) {
      // Ignore geolocation watch errors
    }
    return () => {
      if (watchId !== null && typeof window !== 'undefined' && navigator.geolocation) {
        navigator.geolocation.clearWatch(watchId);
      }
    };
  }, []);

  const activeLocation = (userLocation && typeof userLocation.lat === 'number' && typeof userLocation.lon === 'number')
    ? userLocation
    : geoLoc;

  // Fetch PFZ points from /api/pfz proxy
  useEffect(() => {
    let isCancelled = false;
    setPfzLoading(true);

    const queryParams = new URLSearchParams();
    if (sector && sector !== 'ALL') {
      queryParams.set('sector', sector);
    }
    queryParams.set('limit', '1200');

    const url = `/api/pfz?${queryParams.toString()}`;

    fetch(url)
      .then((res) => res.json())
      .then((data) => {
        if (!isCancelled && data && Array.isArray(data.features)) {
          setPfzFeatures(data.features);
          setPfzLoading(false);
        }
      })
      .catch((err) => {
        console.warn('Could not fetch PFZ features from /api/pfz proxy:', err);
        if (!isCancelled) setPfzLoading(false);
      });

    return () => {
      isCancelled = true;
    };
  }, [sector]);

  // Fetch weather at given coordinate
  const fetchWeather = useCallback(async (lat: number, lon: number) => {
    setWeatherState((prev) => ({ ...prev, lat, lon, loading: true }));
    const backendBase =
      process.env.NEXT_PUBLIC_API_URL ||
      (typeof window !== 'undefined' && window.location.protocol === 'https:' ? '' : 'http://localhost:8000');
    try {
      const res = await fetch(`${backendBase}/api/weather/current?lat=${lat}&lon=${lon}`);
      if (res.ok) {
        const data = await res.json();
        // Ticket #195: missing fields propagate as unknown — only finite
        // live measurements can clear UNKNOWN, never default to SAFE.
        // #196: backend status is authoritative (verbatim); the numeric
        // check below is fallback only (canonical 2.5m / 25kt bands).
        const waveM = toFiniteNumber(data.wave_height_m);
        const windKt = toFiniteNumber(data.wind_speed_kt);
        const tempC = toFiniteNumber(data.temperature_c);
        const known = waveM != null && windKt != null;
        const backendStatus = String(data.status || '').toLowerCase();
        const dangerHit =
          backendStatus === 'danger' ||
          (backendStatus !== 'safe' &&
            backendStatus !== 'caution' &&
            known &&
            (waveM > 2.5 || windKt > 25));
        const cautionHit =
          backendStatus === 'caution' ||
          (backendStatus !== 'safe' &&
            backendStatus !== 'danger' &&
            known &&
            (waveM >= 1.5 || windKt >= 15));
        setWeatherState({
          lat,
          lon,
          temperature_c: tempC ?? undefined,
          wind_speed_kt: windKt ?? undefined,
          wave_height_m: waveM ?? undefined,
          status: data.status || (known ? 'Normal conditions' : 'Sea state unavailable'),
          danger: dangerHit ? 'danger' : cautionHit ? 'caution' : known ? 'none' : 'unknown',
          badge: dangerHit ? 'red' : cautionHit || !known ? 'amber' : 'green',
          source: data.source || 'live_api',
          loading: false,
        });
        return;
      }
    } catch {
      // Backend offline -> UNKNOWN amber, never synthetic SAFE numbers.
    }

    // Ticket #195: backend offline/unreachable -> UNKNOWN amber with no
    // measurements. Never invent estWave/estWind green SAFE values.
    setWeatherState({
      lat,
      lon,
      temperature_c: undefined,
      wind_speed_kt: undefined,
      wave_height_m: undefined,
      status: 'Sea state unavailable (backend offline)',
      danger: 'unknown',
      badge: 'amber',
      source: 'offline_fallback',
      loading: false,
    });
  }, []);

  // Update weather when center changes
  useEffect(() => {
    fetchWeather(center[0], center[1]);
  }, [center, fetchWeather]);

  // Handle map click
  const handleMapClick = useCallback(
    (lat: number, lon: number) => {
      fetchWeather(lat, lon);
      onCenterChange?.([lat, lon]);
    },
    [fetchWeather, onCenterChange]
  );

  // Determine highlighted coordinates
  const highlightedPoint = useMemo<[number, number] | null>(() => {
    if (selectedFeature) {
      const coords = selectedFeature.geometry?.coordinates || selectedFeature.coordinates;
      if (Array.isArray(coords) && coords.length >= 2) {
        const lat = coords[0] > 50 && coords[1] < 40 ? coords[1] : coords[0];
        const lon = coords[0] > 50 && coords[1] < 40 ? coords[0] : coords[1];
        return [lat, lon];
      }
    }
    if (highlightFeatures && highlightFeatures.length > 0) {
      const feat = highlightFeatures[0];
      const coords = feat.geometry?.coordinates || feat.coordinates;
      if (Array.isArray(coords) && coords.length >= 2) {
        const lat = coords[0] > 50 && coords[1] < 40 ? coords[1] : coords[0];
        const lon = coords[0] > 50 && coords[1] < 40 ? coords[0] : coords[1];
        return [lat, lon];
      }
    }
    return null;
  }, [selectedFeature, highlightFeatures]);

  // Highlighted feature object and properties (T9 #125)
  const highlightedFeature = useMemo(() => {
    if (selectedFeature) return selectedFeature;
    if (highlightFeatures && highlightFeatures.length > 0) return highlightFeatures[0];
    return null;
  }, [selectedFeature, highlightFeatures]);

  const hlProps = useMemo(() => {
    return highlightedFeature?.properties || {};
  }, [highlightedFeature]);
  const navOrigin = useMemo<[number, number]>(() => {
    if (activeLocation && typeof activeLocation.lat === 'number' && typeof activeLocation.lon === 'number') {
      return [activeLocation.lat, activeLocation.lon];
    }
    return center;
  }, [activeLocation, center]);

  // Calculate distance & bearing for navigation line
  const navMetrics = useMemo(() => {
    if (!highlightedPoint) return null;
    const distKm = haversineDistance(
      navOrigin[0],
      navOrigin[1],
      highlightedPoint[0],
      highlightedPoint[1]
    );
    const bearingDeg = bearing(
      navOrigin[0],
      navOrigin[1],
      highlightedPoint[0],
      highlightedPoint[1]
    );
    const compass = getCompassDirection(bearingDeg);
    return { distKm, bearingDeg, compass };
  }, [navOrigin, highlightedPoint]);

  // Color helper for PFZ points (UI-MIG-T5: sst OFF renders neutral so the
  // pill is a non-destructive visual filter over the same live PFZ source).
  const getSuitabilityColor = (suitability?: string) => {
    if (!sstOn) return '#38bdf8'; // neutral marine blue when SST tint off
    const s = String(suitability || '').toLowerCase();
    if (s === 'high' || s === 'excellent') return '#22c55e'; // green
    if (s === 'medium' || s === 'moderate') return '#f59e0b'; // amber
    if (s === 'low') return '#eab308'; // yellow
    return '#38bdf8'; // sky blue fallback
  };

  // Glow ring class for the new pill look (suppressed when chlorophyll OFF).
  const getGlowClass = (suitability?: string) => {
    if (!chlorophyllOn) return undefined;
    const s = String(suitability || '').toLowerCase();
    if (s === 'high' || s === 'excellent') return 'pfz-glow-suitable';
    if (s === 'medium' || s === 'moderate') return 'pfz-glow-moderate';
    return 'pfz-glow-caution';
  };

  // Custom User Location Icon
  const userIcon = useMemo(
    () =>
      L.divIcon({
        className: 'orca-user-marker',
        html: `
          <div style="position: relative; width: 22px; height: 22px; display: flex; align-items: center; justify-content: center;">
            <div style="position: absolute; width: 22px; height: 22px; border-radius: 50%; background: rgba(56, 189, 248, 0.4); animation: ping 1.5s cubic-bezier(0, 0, 0.2, 1) infinite;"></div>
            <div style="width: 12px; height: 12px; border-radius: 50%; background: #0284c7; border: 2.5px solid #ffffff; box-shadow: 0 0 6px rgba(0,0,0,0.5);"></div>
          </div>
        `,
        iconSize: [22, 22],
        iconAnchor: [11, 11],
      }),
    []
  );

  return (
    <div
      className={`relative w-full h-full min-h-[400px] overflow-hidden ${
        isLight ? 'bg-slate-100' : 'bg-slate-950'
      }`}
    >
      {/* React-Leaflet Map Instance */}
      <MapContainer
        center={center}
        zoom={zoom}
        scrollWheelZoom={true}
        className="w-full h-full z-0"
        style={{
          height: '100%',
          width: '100%',
          background: isLight ? '#cad2d3' : '#0b132b',
        }}
      >
        <MapController center={center} zoom={zoom} highlightFeatures={highlightFeatures} />
        <MapClickHandler onMapClick={handleMapClick} />

      {/* Base Tile Layer: CartoDB Dark Matter / Voyager marine styling */}
      <TileLayer
        key={tileError ? `osm-fallback-${effTheme}` : `${basemapStyle}-${effTheme}`}
        attribution={getBasemapAttribution(tileError ? 'osm' : basemapStyle)}
          url={getBasemapTileUrl(tileError ? 'osm' : basemapStyle)}
          maxZoom={getBasemapMaxZoom(tileError ? 'osm' : basemapStyle)}
          maxNativeZoom={getBasemapMaxNativeZoom(tileError ? 'osm' : basemapStyle)}
          eventHandlers={{
            tileerror: () => {
              tileErrorsRef.current += 1;
              if (tileErrorsRef.current >= 3 && !tileError && basemapStyle !== 'osm') {
                console.warn(
                  `Basemap tiles reported persistent failures (${tileErrorsRef.current}) on style "${basemapStyle}". Falling back to OpenStreetMap.`
                );
                setTileError(true);
              }
            },
          }}
        />

        {/* 1. EEZ Polygons Layer (Blue boundary) */}
        {layers.eez &&
          EEZ_GEOJSON.features.map((feat, idx) => {
            const polygonCoords = feat.geometry.coordinates[0].map(
              ([lon, lat]: [number, number]) => [lat, lon] as [number, number]
            );
            return (
              <Polygon
                key={`eez-${idx}`}
                positions={polygonCoords}
                pathOptions={{
                  color: '#0284c7',
                  weight: 2,
                  dashArray: '5 5',
                  fillColor: '#0ea5e9',
                  fillOpacity: 0.08,
                }}
              >
                <Popup>
                  <div className="text-xs p-1">
                    <div className="font-bold text-sky-400">
                      {feat.properties.boundary_name || 'India EEZ Boundary'}
                    </div>
                    <p className="text-slate-300 mt-1">
                      Sovereign Exclusive Economic Zone (200 nautical miles). Fishing permitted with authorized licenses.
                    </p>
                  </div>
                </Popup>
              </Polygon>
            );
          })}

        {/* 2. MPA Danger Polygons Layer (Red warning boundary) */}
        {layers.mpa &&
          MPA_GEOJSON.features.map((feat, idx) => {
            const polygonCoords = feat.geometry.coordinates[0].map(
              ([lon, lat]: [number, number]) => [lat, lon] as [number, number]
            );
            return (
              <Polygon
                key={`mpa-${idx}`}
                positions={polygonCoords}
                pathOptions={{
                  color: '#ef4444',
                  weight: 2.5,
                  fillColor: '#dc2626',
                  // UI-MIG-T5: `restricted` is emphasis-only — dim, never hide,
                  // while the legacy mpa toggle stays on.
                  fillOpacity: 0.35 * mpaEmphasis,
                  opacity: 0.4 + 0.6 * mpaEmphasis,
                }}
              >
                <Popup>
                  <div className="text-xs p-1">
                    <div className="font-bold text-red-400 flex items-center gap-1">
                      <span>⚠️</span> {feat.properties.mpa_name || 'Marine Protected Area'}
                    </div>
                    <p className="text-red-200 mt-1 font-semibold">
                      Restricted Sanctuary ({feat.properties.restriction_level || 'No-Take'}).
                    </p>
                    <p className="text-slate-300 text-[11px] mt-0.5">
                      Commercial fishing inside this perimeter is strictly prohibited by law.
                    </p>
                  </div>
                </Popup>
              </Polygon>
            );
          })}

        {/* 3. IMBL International Maritime Boundary Line (Dashed Orange/Red) */}
        {layers.imbl && (
          <Polyline
            positions={IMBL_COORDINATES}
            pathOptions={{
              color: '#ea580c',
              weight: 3.5,
              dashArray: '8 6',
              // UI-MIG-T5: restricted emphasis-only, never hides the legacy imbl line.
              opacity: restrictedOn ? 1 : 0.45,
            }}
          >
            <Tooltip permanent={false} direction="top">
              <span className="text-xs font-semibold text-orange-400">
                IMBL (India - Sri Lanka Boundary)
              </span>
            </Tooltip>
            <Popup>
              <div className="text-xs p-1">
                <div className="font-bold text-orange-400 flex items-center gap-1">
                  <span>⚓</span> International Maritime Boundary Line (IMBL)
                </div>
                <p className="text-slate-300 mt-1 text-[11px]">
                  Bilateral boundary accord between India and Sri Lanka. Do not cross into Sri Lankan territorial waters. Maintain minimum 2 km buffer zone.
                </p>
              </div>
            </Popup>
          </Polyline>
        )}

        {/* 4. PFZ Circle Markers (live /api/pfz, new glow-pill look) */}
        {layers.pfz &&
          pfzFeatures.map((feat, idx) => {
            const coords = feat.geometry?.coordinates;
            if (!coords || coords.length < 2) return null;
            const [lon, lat] = coords;
            const props = feat.properties || {};
            const color = getSuitabilityColor(props.suitability);
            const glowClass = getGlowClass(props.suitability);

            return (
              <CircleMarker
                key={`pfz-${idx}-${lat}-${lon}-${glowClass ?? 'plain'}`}
                center={[lat, lon]}
                radius={7}
                pathOptions={{
                  color: '#ffffff',
                  weight: 1.5,
                  fillColor: color,
                  fillOpacity: 0.85,
                  className: glowClass,
                }}
              >
                <Tooltip direction="top" offset={[0, -10]} opacity={0.95}>
                  <div className="text-xs font-bold px-1.5 py-0.5">
                    {props.place || 'Fishing Zone'}
                    {props.distance || props.distance_km
                      ? ` (${props.distance || props.distance_km} km away)`
                      : ''}
                  </div>
                </Tooltip>
                <Popup>
                  <div className="text-xs text-slate-100 min-w-[200px] p-1 font-sans">
                    <div className="flex items-center justify-between border-b border-slate-700 pb-1 mb-2">
                      <span className="font-bold text-sm text-cyan-300">
                        {props.place || 'Fishing Zone'}
                      </span>
                      <span
                        className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase"
                        style={{
                          backgroundColor: `${color}25`,
                          color: color,
                          border: `1px solid ${color}80`,
                        }}
                      >
                        {suitabilityLabel(props)}
                      </span>
                    </div>

                    <div className="grid grid-cols-2 gap-x-2 gap-y-1 text-[11px] text-slate-300">
                      <div>
                        <span className="text-slate-400">Sector:</span>{' '}
                        <span className="text-white font-medium">
                          {props.sector_name || props.sector || 'N/A'}
                        </span>
                      </div>
                      <div>
                        <span className="text-slate-400">Bearing:</span>{' '}
                        <span className="text-white font-medium">
                          {props.bearing ? `${props.bearing}°` : props.dir || 'N/A'}
                        </span>
                      </div>
                      <div>
                        <span className="text-slate-400">Distance:</span>{' '}
                        <span className="text-white font-medium">
                          {distanceLabel(props)}
                        </span>
                      </div>
                      <div>
                        <span className="text-slate-400">Depth:</span>{' '}
                        <span className="text-white font-medium">
                          {(() => {
                            const d = props.depth ?? props.depth_m;
                            if (d == null || String(d).trim() === '') return MISSING;
                            const s = String(d).trim();
                            return s.includes('m') ? s : `${s} m`;
                          })()}
                        </span>
                      </div>
                      <div className="col-span-2 text-[10px] font-mono text-cyan-200 mt-1">
                        {props.lat_dms || formatDMS(lat, true)} | {props.lon_dms || formatDMS(lon, false)}
                      </div>
                    </div>

                    <button
                      type="button"
                      onClick={() => {
                        setSelectedFeature(feat);
                        onSelectZone?.(feat);
                      }}
                      className="mt-3 w-full py-1.5 px-3 rounded bg-cyan-600 hover:bg-cyan-500 text-white font-bold text-xs transition-colors shadow flex items-center justify-center gap-1.5"
                    >
                      <span>🎯</span> Select Zone
                    </button>
                  </div>
                </Popup>
              </CircleMarker>
            );
          })}

        {/* 5. Highlighted Zone Pulse Ring & Pin */}
        {highlightedPoint && (
          <>
            {/* Outer Pulse Ring */}
            <CircleMarker
              center={highlightedPoint}
              radius={22}
              pathOptions={{
                color: '#22d3ee',
                weight: 2,
                fillColor: '#06b6d4',
                fillOpacity: 0.25,
                className: 'pulse-animation',
              }}
            />

            {/* Inner Core Marker */}
            <CircleMarker
              center={highlightedPoint}
              radius={9}
              pathOptions={{
                color: '#ffffff',
                weight: 2.5,
                fillColor: '#06b6d4',
                fillOpacity: 0.95,
              }}
              ref={(markerRef) => {
                if (markerRef && highlightFeatures && highlightFeatures.length > 0) {
                  setTimeout(() => {
                    try {
                      markerRef.openPopup();
                    } catch (_e) {
                      // ignore if component unmounted
                    }
                  }, 300);
                }
              }}
            >
              <Tooltip permanent direction="top" offset={[0, -10]}>
                <span className="text-xs font-bold text-cyan-300">
                  Target Fishing Zone
                </span>
              </Tooltip>
              <Popup>
                <div className="text-xs text-slate-100 min-w-[210px] p-1 font-sans">
                  <div className="flex items-center justify-between border-b border-slate-700 pb-1 mb-2">
                    <span className="font-bold text-sm text-cyan-300">
                      {hlProps.place || hlProps.name || hlProps.zone_id || 'Target Fishing Zone'}
                    </span>
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">
                      {suitabilityLabel(hlProps)}
                    </span>
                  </div>

                  <div className="grid grid-cols-2 gap-x-2 gap-y-1 text-[11px] text-slate-300">
                    <div>
                      <span className="text-slate-400">Sector:</span>{' '}
                      <span className="text-white font-medium">
                        {hlProps.sector_name || hlProps.sector || 'N/A'}
                      </span>
                    </div>
                    <div>
                      <span className="text-slate-400">Bearing:</span>{' '}
                      <span className="text-white font-medium">
                        {hlProps.bearing ? `${hlProps.bearing}°` : (navMetrics ? `${navMetrics.bearingDeg}° (${navMetrics.compass})` : 'N/A')}
                      </span>
                    </div>
                    <div>
                      <span className="text-slate-400">Distance:</span>{' '}
                      <span className="text-white font-medium">
                        {(() => {
                          const lbl = distanceLabel(hlProps);
                          if (lbl !== MISSING) return lbl;
                          if (navMetrics) return `${navMetrics.distKm} km`;
                          return MISSING;
                        })()}
                      </span>
                    </div>
                    <div>
                      <span className="text-slate-400">Depth:</span>{' '}
                      <span className="text-white font-medium">
                        {(() => {
                          const d = hlProps.depth ?? hlProps.depth_m;
                          if (d == null || String(d).trim() === '') return MISSING;
                          const s = String(d).trim();
                          return s.includes('m') ? s : `${s} m`;
                        })()}
                      </span>
                    </div>
                  </div>

                  <div className="mt-2 pt-1.5 border-t border-slate-800 text-[10px] text-slate-400 flex items-center justify-between">
                    <span>Citation:</span>
                    <span className="text-cyan-200 font-mono">
                      {hlProps.citation || hlProps.source || 'INCOIS TextData'}
                    </span>
                  </div>

                  <button
                    type="button"
                    onClick={() => {
                      if (highlightedFeature) {
                        setSelectedFeature(highlightedFeature);
                        onSelectZone?.(highlightedFeature);
                      }
                    }}
                    className="mt-2.5 w-full py-1 px-2.5 rounded bg-cyan-600 hover:bg-cyan-500 text-white font-bold text-xs transition-colors shadow flex items-center justify-center gap-1.5"
                  >
                    <span>🎯</span> Select Zone
                  </button>
                </div>
              </Popup>
            </CircleMarker>

            {/* Navigation Line connecting origin (userLocation/center) to target.
                UI-MIG-T5: `currents` OFF hides the line only (pulse stays). */}
            {currentsOn && (
            <Polyline
              positions={[navOrigin, highlightedPoint]}
              pathOptions={{
                color: '#38bdf8',
                weight: 3,
                dashArray: '6 8',
              }}
            >
              {navMetrics && (
                <Tooltip permanent direction="center" className="nav-line-tooltip">
                  <div className="text-[11px] font-mono bg-slate-900/90 text-cyan-200 px-2 py-0.5 rounded border border-cyan-500/50 shadow">
                    🧭 {navMetrics.bearingDeg}° ({navMetrics.compass}) · 📏 {navMetrics.distKm} km
                  </div>
                </Tooltip>
              )}
            </Polyline>
            )}
          </>
        )}

        {/* 5b. Safe route polyline & detour waypoints from user GPS to recommended zone (T6 #165) */}
        {routePositions && routePositions.length >= 2 && (userLocation || activeLocation) && routeStats && (
          <>
            <Polyline
              key={`route-${routePositions[0][0]}-${routePositions[0][1]}`}
              positions={routePositions}
              pathOptions={{
                color: routeStats.color,
                weight: 3.5,
                dashArray: routeStats.crossesMPA ? '4, 4' : '8, 6',
                opacity: 0.9,
              }}
            >
              <Tooltip sticky direction="top" opacity={0.95}>
                <div className={`p-1.5 font-sans ${isLight ? 'text-slate-900' : 'text-slate-100'}`}>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-bold text-xs">
                      {routeStats.hasDetour ? 'Safe Detour Route' : 'Direct Marine Route'}
                    </span>
                    <span
                      className={`text-[10px] px-1.5 py-0.5 rounded font-bold uppercase ${
                        routeStats.safety === 'AVOID'
                          ? 'bg-red-500/20 text-red-500 border border-red-500'
                          : routeStats.safety === 'CAUTION'
                          ? 'bg-amber-500/20 text-amber-500 border border-amber-500'
                          : 'bg-emerald-500/20 text-emerald-500 border border-emerald-500'
                      }`}
                    >
                      {routeStats.safety}
                    </span>
                  </div>
                  <div className="text-[11px] grid grid-cols-3 gap-2">
                    <div>
                      <div className="text-[9px] uppercase tracking-wider text-slate-400">Dist</div>
                      <div className="font-semibold">{routeStats.distKm} km ({routeStats.distNm} nm)</div>
                    </div>
                    <div>
                      <div className="text-[9px] uppercase tracking-wider text-slate-400">Bearing</div>
                      <div className="font-semibold">{routeStats.bearingLabel}</div>
                    </div>
                    <div>
                      <div className="text-[9px] uppercase tracking-wider text-slate-400">ETA</div>
                      <div className="font-semibold">{routeStats.etaMin} min</div>
                    </div>
                  </div>
                  {routeStats.crossesMPA && (
                    <div className="mt-1 text-[10px] text-red-400 font-medium">
                      ⚠️ Passes through {routeStats.crossedMpaName}
                    </div>
                  )}
                  {routeStats.hasDetour && !routeStats.crossesMPA && (
                    <div className="mt-1 text-[10px] text-amber-400 font-medium">
                      ⚡ Avoidance detour active around hazard
                    </div>
                  )}
                </div>
              </Tooltip>
            </Polyline>

            {/* Intermediate detour waypoint markers (T6 #165) */}
            {routeStats.hasDetour &&
              routePositions.slice(1, -1).map((wp, idx) => (
                <CircleMarker
                  key={`wp-${idx}-${wp[0]}-${wp[1]}`}
                  center={wp}
                  radius={5}
                  pathOptions={{
                    color: '#ffffff',
                    weight: 2,
                    fillColor: isLight ? '#0891b2' : '#06b6d4',
                    fillOpacity: 0.95,
                  }}
                >
                  <Tooltip direction="top" offset={[0, -6]}>
                    <div className="text-[11px] font-semibold text-cyan-500">
                      Waypoint {idx + 1} (Detour)
                    </div>
                  </Tooltip>
                </CircleMarker>
              ))}
          </>
        )}

        {/* 6. User GPS Blue Dot Marker (T6 #121) */}
        {activeLocation && typeof activeLocation.lat === 'number' && typeof activeLocation.lon === 'number' && (
          <>
            {/* Outer Accuracy / Aura Circle */}
            <CircleMarker
              center={[activeLocation.lat, activeLocation.lon]}
              radius={20}
              pathOptions={{
                color: '#3b82f6',
                weight: 1.5,
                fillColor: '#3b82f6',
                fillOpacity: 0.15,
                className: 'pulse-animation',
              }}
            />
            {/* Inner Pulsing Blue Dot */}
            <CircleMarker
              center={[activeLocation.lat, activeLocation.lon]}
              radius={8}
              pathOptions={{
                color: '#ffffff',
                weight: 2,
                fillColor: '#3b82f6',
                fillOpacity: 0.9,
              }}
            >
              <Tooltip permanent={false} direction="top">
                <span className="text-xs font-semibold text-blue-300">here</span>
              </Tooltip>
            </CircleMarker>
          </>
        )}
      </MapContainer>

      {/* Floating Layer Controls (Top Right) */}
      <div className="absolute top-3 right-3 z-10 flex flex-col items-end gap-2">
        <button
          type="button"
          id="floating-layers-toggle"
          data-testid="floating-layers-toggle"
          aria-label="Toggle Maritime Layers Panel"
          aria-expanded={showLayerPanel}
          onClick={() => setShowLayerPanel((p) => !p)}
          className="px-3 py-1.5 rounded-lg bg-slate-900/90 hover:bg-slate-800 text-cyan-300 border border-slate-700 backdrop-blur shadow-lg text-xs font-bold flex items-center gap-1.5 transition-all"
        >
          <span>🥞</span> Layers {showLayerPanel ? '▲' : '▼'}
        </button>

        {showLayerPanel && (
          <div
            id="floating-layers-panel"
            data-testid="floating-layers-panel"
            className="p-3 rounded-xl bg-slate-900/95 border border-slate-700/80 backdrop-blur shadow-2xl text-xs space-y-2 min-w-[170px] animate-fadeIn"
          >
            <div className="font-bold text-slate-300 text-[11px] uppercase tracking-wider mb-1 border-b border-slate-800 pb-1">
              Maritime Layers
            </div>
            <label className="flex items-center gap-2 cursor-pointer text-slate-200 hover:text-white">
              <input
                type="checkbox"
                id="layer-checkbox-pfz"
                data-testid="layer-checkbox-pfz"
                aria-label="PFZ Points layer toggle"
                checked={layers.pfz}
                onChange={(e) => setLayers((l) => ({ ...l, pfz: e.target.checked }))}
                className="rounded accent-cyan-500"
              />
              <span>🐟 PFZ Points</span>
              {pfzLoading && <span className="text-[10px] text-cyan-400 animate-pulse">...</span>}
            </label>
            <label className="flex items-center gap-2 cursor-pointer text-slate-200 hover:text-white">
              <input
                type="checkbox"
                id="layer-checkbox-eez"
                data-testid="layer-checkbox-eez"
                aria-label="EEZ Boundary layer toggle"
                checked={layers.eez}
                onChange={(e) => setLayers((l) => ({ ...l, eez: e.target.checked }))}
                className="rounded accent-sky-500"
              />
              <span>🌐 EEZ Boundary</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer text-slate-200 hover:text-white">
              <input
                type="checkbox"
                id="layer-checkbox-mpa"
                data-testid="layer-checkbox-mpa"
                aria-label="MPA Sanctuaries layer toggle"
                checked={layers.mpa}
                onChange={(e) => setLayers((l) => ({ ...l, mpa: e.target.checked }))}
                className="rounded accent-red-500"
              />
              <span>🛡️ MPA Sanctuaries</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer text-slate-200 hover:text-white">
              <input
                type="checkbox"
                id="layer-checkbox-imbl"
                data-testid="layer-checkbox-imbl"
                aria-label="IMBL Border layer toggle"
                checked={layers.imbl}
                onChange={(e) => setLayers((l) => ({ ...l, imbl: e.target.checked }))}
                className="rounded accent-orange-500"
              />
              <span>⚠️ IMBL Border</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer text-slate-200 hover:text-white">
              <input
                type="checkbox"
                id="layer-checkbox-weather"
                data-testid="layer-checkbox-weather"
                aria-label="Live Weather layer toggle"
                checked={layers.weather}
                onChange={(e) => setLayers((l) => ({ ...l, weather: e.target.checked }))}
                className="rounded accent-cyan-500"
              />
              <span>⛅ Live Weather</span>
            </label>

            {/* Basemap Style Switcher */}
            <div className="font-bold text-slate-300 text-[11px] uppercase tracking-wider mt-3 pt-2 mb-1.5 border-t border-slate-800">
              Base Cartography
            </div>
            <div className="space-y-1">
              {BASEMAP_OPTIONS.map((opt) => (
                <button
                  key={opt.id}
                  type="button"
                  data-testid={`basemap-option-${opt.id}`}
                  onClick={() => {
                    setHasManualOverride(true);
                    tileErrorsRef.current = 0;
                    setBasemapStyle(opt.id);
                    setTileError(false);
                  }}
                  className={`w-full text-left px-2 py-1 rounded flex items-center justify-between text-[11px] transition-colors ${
                    basemapStyle === opt.id && !tileError
                      ? 'bg-cyan-950/70 text-cyan-300 border border-cyan-800/60 font-semibold'
                      : 'text-slate-300 hover:bg-slate-800 hover:text-white'
                  }`}
                  title={opt.description}
                >
                  <span className="flex items-center gap-1.5">
                    <span>{opt.icon}</span>
                    <span>{opt.label}</span>
                  </span>
                  {basemapStyle === opt.id && !tileError && (
                    <span className="text-[10px] text-cyan-400">✓</span>
                  )}
                </button>
              ))}
            </div>

            {tileError && (
              <div className="mt-2 p-1.5 rounded bg-amber-950/60 border border-amber-800/50 text-[10px] text-amber-300 flex items-center gap-1">
                <span>⚠️</span>
                <span>OSM Fallback Active</span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Floating Weather & Sea Inspection Tooltip (Bottom Left) */}
      {layers.weather && (
        <div className="absolute bottom-4 left-4 z-10 max-w-sm rounded-xl bg-slate-900/90 border border-slate-700/80 backdrop-blur shadow-2xl p-3 text-xs text-slate-200">
          <div className="flex items-center justify-between gap-2 mb-2 border-b border-slate-800 pb-1.5">
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-cyan-400 animate-ping" />
              <span className="font-bold text-white text-xs">Ocean Telemetry</span>
            </div>
            <SafetyBadge
              waves={weatherState.wave_height_m}
              wind={weatherState.wind_speed_kt}
              danger={weatherState.danger}
              badge={weatherState.badge}
              compact
            />
          </div>

          <div className="grid grid-cols-2 gap-2 text-[11px]">
            {wavesOn && (
            <div className="bg-slate-950/60 p-1.5 rounded border border-slate-800">
              <span className="text-slate-400 block text-[10px]">Wave Height</span>
              <span className="text-cyan-300 font-bold text-sm">
                {weatherState.wave_height_m != null ? `${weatherState.wave_height_m} m` : '—'}
              </span>
            </div>
            )}
            {windOn && (
            <div className="bg-slate-950/60 p-1.5 rounded border border-slate-800">
              <span className="text-slate-400 block text-[10px]">Wind Speed</span>
              <span className="text-cyan-300 font-bold text-sm">
                {weatherState.wind_speed_kt != null ? `${weatherState.wind_speed_kt} kts` : '—'}
              </span>
            </div>
            )}
          </div>

          <div className="mt-2 text-[10px] text-slate-400 flex items-center justify-between font-mono">
            <span>
              Pos: [{weatherState.lat.toFixed(2)}, {weatherState.lon.toFixed(2)}]
            </span>
            <span>Click map to inspect</span>
          </div>
        </div>
      )}
    </div>
  );
}
