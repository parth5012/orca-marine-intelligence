/**
 * RouteViewScreen (UI-MIG-T6)
 *
 * Owner: M-E (Frontend Chat & App Shell)
 * Module: frontend/components/screens/RouteViewScreen.tsx
 *
 * Ported layout from source design `screens/RouteViewScreen` (READ-ONLY):
 * back button, header route card (origin -> destination + safety index +
 * Start Navigation), specs bar, geofence callout, marine route chart,
 * waypoint sequence table.
 *
 * Live-only rewiring (no mock zone/route imports):
 * - Origin = live GPS snapshot (AppContext.userLocation, Kochi fallback).
 * - Dest = AppContext.selectedPFZ via shared `@/lib/pfz` toPFZItem (same
 *   T3 mapper — route values derive from the live /api/pfz feature).
 * - Distance/bearing/ETA = haversine `computeLiveRoute`; safety index =
 *   live `GET /api/weather/current` (zone) thresholds; hazards = live
 *   weather/current + geofence/status copy. Backend-down keeps the
 *   haversine route with a warning chip, never mock waypoints.
 * - Chart = ssr:false Leaflet MapView with the dest feature highlight —
 *   the guarded nav polyline (origin -> zone, SSE [lon,lat] convention)
 *   draws the route; waypoints table lists origin/mid/dest [lat,lon].
 * - View Boundary -> viewOnMap (guarded flyTo+highlight); back -> pfz-detail.
 */

'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useApp } from '@/context/AppContext';
import { MapView } from '@/map';
import { MPA_GEOJSON } from '@/map/boundaries';
import {
  buildSafeRoute,
  classifySea,
  computeLiveRoute,
  getBackendBaseUrl,
  num,
  pfzItemToFeature,
  toPFZItem,
  type LiveRouteInfo,
  type PFZItem,
} from '@/lib/pfz';
import {
  Navigation,
  Compass,
  MapPin,
  Clock,
  Fuel,
  AlertTriangle,
  Play,
  ArrowLeft,
  Route,
} from 'lucide-react';

export const RouteViewScreen: React.FC = () => {
  const {
    selectedPFZ,
    userLocation,
    setActiveTab,
    viewOnMap,
    themeMode,
  } = useApp();
  const isLight = themeMode === 'light';

  const dest = useMemo(
    () => toPFZItem(selectedPFZ, userLocation.lat, userLocation.lon),
    [selectedPFZ, userLocation.lat, userLocation.lon]
  );

  const [isNavigating, setIsNavigating] = useState(false);
  const [navProgress, setNavProgress] = useState(0);
  const [seaLevel, setSeaLevel] = useState<'safe' | 'caution' | 'danger'>('safe');
  const [hazards, setHazards] = useState<string[]>([]);
  const [feedOffline, setFeedOffline] = useState(false);
  const [recalcNote, setRecalcNote] = useState<string | null>(null);

  // Navigation interval id (cleared on stop + unmount so restarts never stack).
  const navTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  // Guards async safety loads against post-unmount setState.
  const mountedRef = useRef(true);
  // Monotonic request sequence: only the latest loadSafety invocation may
  // commit results, so a slow earlier request can never overwrite the
  // current destination's seaLevel/hazards/feedOffline.
  const safetySeqRef = useRef(0);
  useEffect(() => () => {
    mountedRef.current = false;
    if (navTimer.current) {
      clearInterval(navTimer.current);
      navTimer.current = null;
    }
  }, []);

  // Live safety + hazards at the destination (direct backend calls).
  // Shared by the mount effect and the Recalculate handler so both paths
  // update seaLevel, hazards, and feedOffline identically.
  const loadSafety = useCallback(async (
    bailOnCancel = true
  ): Promise<'safe' | 'caution' | 'danger' | null> => {
    if (!dest) return null;
    const seq = (safetySeqRef.current += 1);
    const isCurrent = (): boolean => seq === safetySeqRef.current;
    const base = getBackendBaseUrl();
    const [dLat, dLon] = dest.coordinates;
    try {
      const [wRes, gRes] = await Promise.all([
        fetch(`${base}/api/weather/current?lat=${dLat}&lon=${dLon}`),
        fetch(`${base}/api/geofence/status`),
      ]);
      if ((!mountedRef.current || !isCurrent()) && bailOnCancel) return null;
        let level: 'safe' | 'caution' | 'danger' = 'safe';
        const hz: string[] = [];
        let weatherOk = false;
        if (wRes.ok) {
          const w = await wRes.json();
          const windKt = num(w.wind_speed_kt ?? w.wind_speed_kts, 10);
          const waveM = num(w.wave_height_m, 1.0);
          const currentKt = num(w.current_speed_kt, 1.0);
          const pressure = num(w.pressure_hpa, 1012);
          level = classifySea(windKt, waveM, currentKt, pressure);
          weatherOk = true;
          if (waveM > 2.5) hz.push(`High waves ${waveM} m at destination (avoid >2.5 m)`);
          else if (waveM > 1.5) hz.push(`Moderate swell ${waveM} m at destination`);
          if (windKt > 25) hz.push(`Strong wind ${windKt} kt at destination (avoid >25 kt)`);
          else if (windKt > 15) hz.push(`Breezy ${windKt} kt at destination`);
          if (pressure < 995) hz.push(`Low pressure ${pressure} hPa — storm risk`);
        }
        let geoOk = false;
        if (gRes.ok) {
          const g = await gRes.json();
          geoOk = true;
          const total =
            g.boundary_counts?.total ??
            g.count_protected_boundaries ??
            g.protected_boundaries_count;
          hz.push(
            total != null
              ? `Route checked against ${total} monitored EEZ/MPA/IMBL boundaries`
              : 'Route checked against monitored EEZ/MPA/IMBL boundaries'
          );
        }
        if ((!mountedRef.current || !isCurrent()) && bailOnCancel) return null;
        setSeaLevel(level);
        setHazards(hz);
        setFeedOffline(!weatherOk && !geoOk);
        return level;
      } catch {
        if ((!mountedRef.current || !isCurrent()) && bailOnCancel) return null;
        setSeaLevel('safe');
        setHazards([]);
        setFeedOffline(true);
        return null;
      }
  }, [dest?.coordinates?.[0], dest?.coordinates?.[1]]); // eslint-disable-line react-hooks/exhaustive-deps

  // Initial load at the destination.
  useEffect(() => {
    void loadSafety(true);
  }, [loadSafety]);

  const [backendRoute, setBackendRoute] = useState<LiveRouteInfo | null>(null);
  const [isBackendLive, setIsBackendLive] = useState<boolean>(false);

  useEffect(() => {
    const currentDest = dest;
    if (!currentDest) return;
    let cancelled = false;
    setBackendRoute(null);
    setIsBackendLive(false);
    async function fetchBackendRoute(target: PFZItem) {
      try {
        const params = new URLSearchParams({
          olat: String(userLocation.lat),
          olon: String(userLocation.lon),
          dlat: String(target.coordinates[0]),
          dlon: String(target.coordinates[1]),
        });
        const res = await fetch(`/api/route?${params.toString()}`);
        if (!res.ok) throw new Error('route failed');
        const data = await res.json();
        if (cancelled) return;
        if (data.waypoints && data.distance_km != null) {
          setBackendRoute({
            originName: userLocation.name || 'Current GPS Location',
            destinationName: `${target.code} (${target.name})`,
            totalDistanceKm: data.distance_km,
            totalDistanceNm: data.distance_nm,
            bearing: data.bearing,
            bearingDegrees: data.bearing_deg ?? 0,
            estimatedTimeMinutes: data.eta_min,
            safetyIndexPercent: data.safety_index,
            safetyLabel: data.safety_label,
            waypoints: data.waypoints,
            hazardWarnings: data.hazards || [],
            detourOccurred:
              data.detour_occurred ??
              (Array.isArray(data.hazards) &&
                data.hazards.some((h: string) => h.includes('Marine Protected Area'))),
            offlineCalculated: data.source !== 'backend_live',
          });
          setIsBackendLive(data.source === 'backend_live');
        }
      } catch {
        if (cancelled) return;
        setIsBackendLive(false);
      }
    }
    void fetchBackendRoute(currentDest);
    return () => {
      cancelled = true;
    };
  }, [dest?.coordinates?.[0], dest?.coordinates?.[1], userLocation.lat, userLocation.lon, userLocation.name]);

  const clientSafeRoute: LiveRouteInfo | null = useMemo(() => {
    if (!dest) return null;
    return buildSafeRoute(
      { lat: userLocation.lat, lon: userLocation.lon, name: userLocation.name },
      dest,
      { mpa: MPA_GEOJSON, imblBufferKm: 2.0, seaLevel }
    );
  }, [dest, userLocation.lat, userLocation.lon, userLocation.name, seaLevel]);

  const route: LiveRouteInfo | null = backendRoute ?? clientSafeRoute;

  const destFeature = useMemo(
    () => (dest ? (pfzItemToFeature(selectedPFZ) ?? pfzItemToFeature(dest)) : null),
    [selectedPFZ, dest]
  );

  const chartCenter: [number, number] = useMemo(() => {
    if (!route) return [userLocation.lat, userLocation.lon];
    const [oLat, oLon] = route.waypoints[0];
    const [dLat, dLon] = route.waypoints[route.waypoints.length - 1];
    return [Number(((oLat + dLat) / 2).toFixed(4)), Number(((oLon + dLon) / 2).toFixed(4))];
  }, [route, userLocation.lat, userLocation.lon]);

  const toggleNavigation = () => {
    if (!isNavigating) {
      setIsNavigating(true);
      setNavProgress(15);
      if (navTimer.current) clearInterval(navTimer.current);
      navTimer.current = setInterval(() => {
        setNavProgress((prev) => {
          if (prev >= 100) {
            if (navTimer.current) clearInterval(navTimer.current);
            navTimer.current = null;
            setIsNavigating(false);
            return 100;
          }
          return prev + 25;
        });
      }, 1500);
    } else {
      if (navTimer.current) clearInterval(navTimer.current);
      navTimer.current = null;
      setIsNavigating(false);
      setNavProgress(0);
    }
  };

  if (!dest || !route) {
    return (
      <div
        data-testid="route-screen"
        className={`max-w-5xl mx-auto rounded-2xl border p-6 text-sm ${
          isLight
            ? 'bg-white border-sky-200 text-slate-600'
            : 'glass-panel border-cyan-900/40 bg-slate-950/90 text-slate-300'
        }`}
      >
        <p data-testid="route-empty">
          No destination set. Select a PFZ first, then start navigation.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            data-testid="route-back"
            onClick={() => setActiveTab('pfz-detail')}
            className="px-4 py-2 rounded-xl border border-cyan-500/40 text-sm font-bold hover:bg-cyan-50 dark:hover:bg-slate-800 transition-colors"
          >
            Back to PFZ Details
          </button>
          <button
            type="button"
            data-testid="route-go-map"
            onClick={() => setActiveTab('map')}
            className="px-4 py-2 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white text-sm font-bold transition-colors"
          >
            Open map
          </button>
        </div>
      </div>
    );
  }

  // Route-level safety participates in the alert state: an AVOID route (or
  // one carrying MPA/IMBL warnings) must never render a "safe" callout.
  const routeBlocking =
    route.safetyLabel === 'AVOID' ||
    route.hazardWarnings.some((h) => /marine protected area|international maritime boundary/i.test(h));

  const geofenceActive =
    seaLevel === 'danger' ||
    hazards.some((h) => /strong|high waves|low pressure/i.test(h)) ||
    routeBlocking;

  const calloutWarnings =
    routeBlocking && route.hazardWarnings.length > 0
      ? [...route.hazardWarnings, ...hazards.filter((h) => !route.hazardWarnings.includes(h))]
      : hazards;

  return (
    <div data-testid="route-screen" className="max-w-5xl mx-auto space-y-6 pb-16">
      <button
        type="button"
        data-testid="route-back"
        onClick={() => setActiveTab('pfz-detail')}
        className="px-3.5 py-1.5 rounded-xl glass-panel bg-slate-900 border border-slate-800 text-cyan-300 hover:text-white text-xs font-semibold inline-flex items-center gap-1.5 transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        <span>Back to PFZ Details</span>
      </button>

      {feedOffline && (
        <p
          data-testid="route-warning-chip"
          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-amber-500/20 border border-amber-400/50 text-amber-200 text-[11px] font-bold"
        >
          Live safety feed unreachable — route uses INCOIS zone values
        </p>
      )}

      <div className="glass-panel rounded-3xl p-6 border border-cyan-500/40 bg-gradient-to-br from-slate-950 via-slate-900 to-cyan-950/40 shadow-2xl">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-cyan-950 text-cyan-300 border border-cyan-800 text-xs font-bold mb-2">
              <Route className="w-3.5 h-3.5 text-cyan-400" />
              <span>Marine Route Guidance System</span>
            </div>

            <div className="flex items-center gap-2 text-white flex-wrap">
              <h1 className="text-xl sm:text-3xl font-extrabold tracking-tight">
                {route.originName}
              </h1>
              <span className="text-cyan-400 font-bold">→</span>
              <h1 className="text-xl sm:text-3xl font-extrabold text-cyan-300 tracking-tight">
                {route.destinationName}
              </h1>
            </div>
            <p className="text-xs text-slate-400 mt-1 font-medium">
              Live GPS waypoints from {userLocation.lat.toFixed(2)}°N,{' '}
              {userLocation.lon.toFixed(2)}°E — haversine route over live INCOIS zone
            </p>
          </div>

          <div className="shrink-0 flex items-center gap-3">
            <div className="text-right hidden sm:block">
              <div className="text-xs text-slate-400">Route Safety Index</div>
              <div
                data-testid="route-safety-index"
                className={`text-xl font-extrabold ${
                  route.safetyLabel === 'AVOID'
                    ? 'text-rose-400'
                    : route.safetyLabel === 'CAUTION'
                      ? 'text-amber-400'
                      : 'text-emerald-400'
                }`}
              >
                {route.safetyIndexPercent}% {route.safetyLabel}
              </div>
            </div>

            <button
              type="button"
              data-testid="route-start"
              onClick={toggleNavigation}
              className={`px-5 py-3 rounded-2xl font-extrabold text-sm shadow-xl flex items-center gap-2 transition-all ${
                isNavigating
                  ? 'bg-rose-500 text-white animate-pulse'
                  : 'bg-gradient-to-r from-cyan-400 to-teal-500 text-slate-950 hover:scale-105'
              }`}
            >
              {isNavigating ? (
                <>
                  <span className="w-3 h-3 rounded-full bg-white animate-ping" />
                  <span>Stop Navigation</span>
                </>
              ) : (
                <>
                  <Play className="w-5 h-5 fill-slate-950 stroke-slate-950" />
                  <span>Start Navigation</span>
                </>
              )}
            </button>
          </div>
        </div>

        {isNavigating && (
          <div className="mt-4 pt-3 border-t border-slate-800">
            <div className="flex justify-between text-xs text-cyan-300 font-semibold mb-1">
              <span>Voyage Progress</span>
              <span>{navProgress}% Completed</span>
            </div>
            <div className="w-full bg-slate-900 rounded-full h-2.5 overflow-hidden border border-cyan-800">
              <div
                className="bg-gradient-to-r from-cyan-400 to-emerald-400 h-2.5 transition-all duration-700"
                style={{ width: `${navProgress}%` }}
              />
            </div>
          </div>
        )}

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-5 pt-4 border-t border-slate-800">
          <div className="p-2.5 rounded-xl bg-slate-900/80 border border-slate-800">
            <div className="text-xs text-slate-400 flex items-center gap-1">
              <MapPin className="w-3.5 h-3.5 text-cyan-400" />
              Distance
            </div>
            <div className="text-base font-bold text-cyan-200 mt-0.5">
              {route.totalDistanceKm} km ({route.totalDistanceNm} Nm)
            </div>
          </div>

          <div className="p-2.5 rounded-xl bg-slate-900/80 border border-slate-800">
            <div className="text-xs text-slate-400 flex items-center gap-1">
              <Compass className="w-3.5 h-3.5 text-teal-400" />
              Bearing
            </div>
            <div className="text-base font-bold text-teal-200 mt-0.5">
              {route.bearing}
            </div>
          </div>

          <div className="p-2.5 rounded-xl bg-slate-900/80 border border-slate-800">
            <div className="text-xs text-slate-400 flex items-center gap-1">
              <Clock className="w-3.5 h-3.5 text-amber-400" />
              Est. Travel Time
            </div>
            <div className="text-base font-bold text-amber-200 mt-0.5">
              {route.estimatedTimeMinutes} Minutes
            </div>
          </div>

          <div className="p-2.5 rounded-xl bg-slate-900/80 border border-slate-800">
            <div className="text-xs text-slate-400 flex items-center gap-1">
              <Fuel className="w-3.5 h-3.5 text-blue-400" />
              Est. Fuel
            </div>
            <div className="text-base font-bold text-blue-200 mt-0.5">
              ~{dest.fuelEstimateLiters} Liters
            </div>
          </div>
        </div>
      </div>

      <div
        data-testid="route-geofence-callout"
        className={`p-4 sm:p-5 rounded-2xl border transition-all shadow-xl relative overflow-hidden ${
          isLight
            ? 'bg-amber-50 border-amber-300 text-slate-900 shadow-amber-900/10'
            : 'glass-panel bg-amber-950/40 border-amber-500/50 text-amber-100 shadow-amber-950/50'
        }`}
      >
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 relative z-10">
          <div className="flex items-start gap-3">
            <div className="relative">
              <span className="absolute w-12 h-12 rounded-2xl bg-amber-500/30 animate-ping -top-1 -left-1 pointer-events-none" />
              <div className="w-10 h-10 rounded-2xl bg-gradient-to-tr from-amber-500 to-yellow-400 text-slate-950 flex items-center justify-center font-extrabold shrink-0 shadow-lg shadow-amber-500/40 relative z-10">
                <AlertTriangle className="w-5 h-5 fill-slate-950 stroke-slate-950 animate-bounce" />
              </div>
            </div>
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-extrabold text-sm text-amber-700 dark:text-amber-300 uppercase tracking-wider">
                  {geofenceActive ? '⚠️ LIVE HAZARD WATCH' : '✓ ROUTE SAFETY CHECK'}
                </span>
                <span className="px-2.5 py-0.5 rounded-full text-[10px] font-extrabold bg-amber-200 dark:bg-amber-950 text-amber-900 dark:text-amber-300 border border-amber-400">
                  {route.safetyLabel} · {route.safetyIndexPercent}%
                </span>
              </div>
              <p className="text-xs font-bold mt-0.5 text-slate-800 dark:text-slate-100">
                {calloutWarnings.length > 0 ? calloutWarnings[0] : 'Live feeds show no blocking hazard on this route.'}
              </p>
              <div className="text-[11px] text-slate-600 dark:text-slate-400 mt-1 font-medium">
                {calloutWarnings.length > 1
                  ? calloutWarnings.slice(1).join(' • ')
                  : 'Hazards from live /api/weather/current + /api/geofence/status.'}
              </div>
              {recalcNote && (
                <p data-testid="route-recalc-note" className="text-[11px] mt-1 text-cyan-700 dark:text-cyan-300">
                  {recalcNote}
                </p>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <button
              type="button"
              data-testid="route-view-boundary"
              onClick={() =>
                viewOnMap(selectedPFZ as Exclude<typeof selectedPFZ, null>)
              }
              className="px-3.5 py-1.5 rounded-xl bg-amber-100 dark:bg-amber-950 border border-amber-300 dark:border-amber-700 text-amber-900 dark:text-amber-200 text-xs font-bold hover:scale-105 transition-transform"
            >
              View Boundary
            </button>
            <button
              type="button"
              data-testid="route-recalc"
              onClick={() => {
                setRecalcNote('Re-checking live weather + geofence…');
                void loadSafety(false).then((level) => {
                  if (!mountedRef.current) return;
                  if (level == null) {
                    setRecalcNote('Live feed unreachable — holding last known route.');
                  } else if (level === 'danger') {
                    setRecalcNote('Re-checked just now — sea DANGER, avoid sailing.');
                  } else {
                    setRecalcNote(`Re-checked just now — sea ${level.toUpperCase()}, route holds.`);
                  }
                });
              }}
              className="px-3.5 py-1.5 rounded-xl bg-gradient-to-r from-amber-500 to-amber-600 text-slate-950 font-extrabold text-xs shadow-md hover:scale-105 transition-transform"
            >
              Recalculate Route
            </button>
          </div>
        </div>
      </div>

      <div className="space-y-2">
        <h3 className="font-extrabold text-base text-white flex items-center gap-2">
          <Navigation className="w-4 h-4 text-cyan-400" />
          Interactive Marine Route Chart
        </h3>
        <div data-testid="route-map" className="h-[420px] rounded-2xl overflow-hidden border border-cyan-500/20">
          <MapView
            center={chartCenter}
            zoom={9}
            highlightFeatures={destFeature ? [destFeature] : []}
            userLocation={{ lat: userLocation.lat, lon: userLocation.lon }}
            route={route.waypoints}
            routeMeta={{ detourOccurred: route.detourOccurred, safetyLabel: route.safetyLabel }}
            onSelectZone={() => undefined}
          />
        </div>
      </div>

      <div className="glass-panel rounded-2xl p-5 border border-slate-800 bg-slate-950/80 space-y-3">
        <h3 className="font-bold text-sm text-cyan-200 uppercase tracking-wider">
          GPS Waypoint Navigation Sequence
        </h3>
        <div className="space-y-2 text-xs">
          {route.waypoints.map((wp, idx) => (
            <div
              key={idx}
              data-testid={`route-waypoint-${idx}`}
              className="p-3 rounded-xl bg-slate-900/80 border border-slate-800 flex items-center justify-between"
            >
              <div className="flex items-center gap-3">
                <span className="w-6 h-6 rounded-full bg-cyan-950 border border-cyan-800 text-cyan-400 font-mono font-bold flex items-center justify-center text-[11px]">
                  0{idx + 1}
                </span>
                <div>
                  <div className="font-semibold text-white">
                    {idx === 0
                      ? `Origin: ${route.originName}`
                      : idx === route.waypoints.length - 1
                        ? `Destination: ${dest.code}`
                        : route.detourOccurred
                          ? `Detour Waypoint ${idx} (Avoidance)`
                          : `Safe Channel Waypoint ${idx}`}
                  </div>
                  <div className="text-[11px] font-mono text-slate-400">
                    Lat: {wp[0].toFixed(3)}° N, Lng: {wp[1].toFixed(3)}° E
                  </div>
                </div>
              </div>

              <span
                className={`px-2.5 py-1 rounded text-[10px] font-bold border ${
                  route.safetyLabel === 'AVOID'
                    ? 'bg-rose-950 text-rose-300 border-rose-800'
                    : route.safetyLabel === 'CAUTION'
                      ? 'bg-amber-950 text-amber-300 border-amber-800'
                      : 'bg-emerald-950 text-emerald-300 border-emerald-800'
                }`}
              >
                {route.safetyLabel === 'AVOID'
                  ? 'AVOID'
                  : route.safetyLabel === 'CAUTION'
                    ? 'CAUTION'
                    : 'CLEAR'}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default RouteViewScreen;
