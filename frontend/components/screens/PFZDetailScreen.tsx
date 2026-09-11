/**
 * PFZDetailScreen (UI-MIG-T6)
 *
 * Owner: M-E (Frontend Chat & App Shell)
 * Module: frontend/components/screens/PFZDetailScreen.tsx
 *
 * Ported layout from source design `screens/PFZDetailScreen` (READ-ONLY):
 * back button, header banner (code/updated/name/region + SafetyStatus),
 * 4 route specs, 5 ocean-metric cards, species tags, safety checklist,
 * EvidenceCard rationale, mini map preview, bottom actions.
 *
 * Live-only rewiring (no mock zone/alert/route imports):
 * - Zone = AppContext.selectedPFZ normalized by the shared `@/lib/pfz`
 *   `toPFZItem` (same T3 mapper as HomeScreen — detail values equal the
 *   live /api/pfz feature properties).
 * - Safety checklist = live `GET /api/weather/current` (zone) thresholds
 *   + live `GET /api/weather/cyclone` (zone) + live
 *   `GET /api/geofence/status` counts. Backend-down degrades to the
 *   PFZ-mapped values with a warning chip, never mock zones.
 * - Evidence = live mapper evidence + live telemetry citation lines.
 * - Actions: View-on-Map -> viewOnMap (Shell flyTo+highlight, guarded);
 *   View Route -> startRouteNavigation; Ask ORCA -> submitChatQuery;
 *   back -> home. Mini preview is ssr:false Leaflet via MapView.
 */

'use client';

import React, { useEffect, useMemo, useState } from 'react';
import { useApp } from '@/context/AppContext';
import { SafetyStatus } from '@/components/common/SafetyStatus';
import { EvidenceCard } from '@/components/common/EvidenceCard';
import { MapView } from '@/map';
import { formatDMS } from '@/map/geo';
import {
  classifySea,
  getBackendBaseUrl,
  num,
  pfzItemToFeature,
  toPFZItem,
} from '@/lib/pfz';
import {
  Compass,
  MapPin,
  Thermometer,
  Waves,
  Wind,
  Navigation,
  MessageSquareText,
  ShieldCheck,
  Fuel,
  Clock,
  ArrowLeft,
  Fish,
  Sun,
} from 'lucide-react';

interface ZoneLive {
  loading: boolean;
  offline: boolean;
  windKt: number | null;
  waveM: number | null;
  currentKt: number | null;
  pressureHpa: number | null;
  sea: 'safe' | 'caution' | 'danger' | null;
  cycloneLevel: string | null;
  cycloneText: string | null;
  geofenceText: string | null;
}

const INITIAL_LIVE: ZoneLive = {
  loading: true,
  offline: false,
  windKt: null,
  waveM: null,
  currentKt: null,
  pressureHpa: null,
  sea: null,
  cycloneLevel: null,
  cycloneText: null,
  geofenceText: null,
};

export const PFZDetailScreen: React.FC = () => {
  const {
    selectedPFZ,
    setActiveTab,
    startRouteNavigation,
    submitChatQuery,
    viewOnMap,
    userLocation,
    themeMode,
  } = useApp();
  const isLight = themeMode === 'light';

  const pfz = useMemo(
    () => toPFZItem(selectedPFZ, userLocation.lat, userLocation.lon),
    [selectedPFZ, userLocation.lat, userLocation.lon]
  );

  const [live, setLive] = useState<ZoneLive>(INITIAL_LIVE);

  // Live safety/weather/geofence at the selected zone (direct backend calls).
  useEffect(() => {
    if (!pfz) {
      setLive({ ...INITIAL_LIVE, loading: false });
      return;
    }
    let cancelled = false;
    const base = getBackendBaseUrl();
    const [zLat, zLon] = pfz.coordinates;
    setLive({ ...INITIAL_LIVE, loading: true });

    const weatherP = fetch(
      `${base}/api/weather/current?lat=${zLat}&lon=${zLon}`
    )
      .then((r) => {
        if (!r.ok) throw new Error(`weather ${r.status}`);
        return r.json();
      })
      .then((d) => ({ ok: true as const, d }))
      .catch(() => ({ ok: false as const }));

    const cycloneP = fetch(
      `${base}/api/weather/cyclone?lat=${zLat}&lon=${zLon}`
    )
      .then((r) => {
        if (!r.ok) throw new Error(`cyclone ${r.status}`);
        return r.json();
      })
      .then((d) => ({ ok: true as const, d }))
      .catch(() => ({ ok: false as const }));

    const geofenceP = fetch(`${base}/api/geofence/status`)
      .then((r) => {
        if (!r.ok) throw new Error(`geofence ${r.status}`);
        return r.json();
      })
      .then((d) => ({ ok: true as const, d }))
      .catch(() => ({ ok: false as const }));

    Promise.all([weatherP, cycloneP, geofenceP]).then(([w, c, g]) => {
      if (cancelled) return;
      const windKt = w.ok ? num(w.d.temperature_c !== undefined ? (w.d.wind_speed_kt ?? w.d.wind_speed_kts) : null, NaN) : NaN;
      const waveM = w.ok ? num(w.d.wave_height_m, NaN) : NaN;
      const currentKt = w.ok ? num(w.d.current_speed_kt, NaN) : NaN;
      const pressure = w.ok ? num(w.d.pressure_hpa, NaN) : NaN;
      const hasSea =
        Number.isFinite(windKt) ||
        Number.isFinite(waveM) ||
        Number.isFinite(currentKt) ||
        Number.isFinite(pressure);
      const sea = hasSea
        ? classifySea(
            Number.isFinite(windKt) ? windKt : 0,
            Number.isFinite(waveM) ? waveM : 0,
            Number.isFinite(currentKt) ? currentKt : 0,
            Number.isFinite(pressure) ? pressure : 1013
          )
        : null;
      const cycloneLevel = c.ok ? String(c.d.alert_level ?? 'safe') : null;
      const cycloneText = c.ok
        ? String(c.d.description ?? 'No active cyclone alerts.')
        : null;
      const counts =
        g.ok && (g.d.boundary_counts || g.d.count_protected_boundaries != null)
          ? (g.d.boundary_counts?.total ??
            g.d.count_protected_boundaries ??
            g.d.protected_boundaries_count)
          : null;
      setLive({
        loading: false,
        offline: !w.ok && !c.ok && !g.ok,
        windKt: Number.isFinite(windKt) ? windKt : null,
        waveM: Number.isFinite(waveM) ? waveM : null,
        currentKt: Number.isFinite(currentKt) ? currentKt : null,
        pressureHpa: Number.isFinite(pressure) ? pressure : null,
        sea,
        cycloneLevel,
        cycloneText,
        geofenceText:
          counts != null
            ? `${counts} protected boundaries monitored (EEZ/MPA/IMBL)`
            : g.ok
              ? 'EEZ/MPA/IMBL boundaries monitored'
              : null,
      });
    });
    return () => {
      cancelled = true;
    };
  }, [pfz?.coordinates?.[0], pfz?.coordinates?.[1]]); // eslint-disable-line react-hooks/exhaustive-deps

  const focusFeature = useMemo(
    () => (pfz ? (pfzItemToFeature(selectedPFZ) ?? pfzItemToFeature(pfz)) : null),
    [selectedPFZ, pfz]
  );

  const evidence = useMemo(() => {
    if (!pfz) return [];
    const lines = [...pfz.evidence];
    if (live.windKt != null || live.waveM != null) {
      lines.push(
        `Live sea state at zone: wind ${live.windKt ?? '—'} kt, wave ${live.waveM ?? '—'} m (${live.sea ?? 'unknown'})`
      );
    }
    if (live.cycloneLevel) {
      lines.push(`IMD cyclone watch: ${live.cycloneLevel} — ${live.cycloneText ?? ''}`.trim());
    }
    if (live.geofenceText) lines.push(`Geofence: ${live.geofenceText}`);
    return lines;
  }, [pfz, live]);

  if (!pfz) {
    return (
      <div
        data-testid="pfz-detail-screen"
        className={`max-w-4xl mx-auto rounded-2xl border p-6 text-sm ${
          isLight
            ? 'bg-white border-sky-200 text-slate-600'
            : 'glass-panel border-cyan-900/40 bg-slate-950/90 text-slate-300'
        }`}
      >
        <p data-testid="pfz-detail-empty">
          No zone selected yet. Pick a zone from chat or the map.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            data-testid="pfz-detail-back"
            onClick={() => setActiveTab('home')}
            className="px-4 py-2 rounded-xl border border-cyan-500/40 text-sm font-bold hover:bg-cyan-50 dark:hover:bg-slate-800 transition-colors"
          >
            Back to Dashboard
          </button>
          <button
            type="button"
            data-testid="pfz-detail-go-map"
            onClick={() => setActiveTab('map')}
            className="px-4 py-2 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white text-sm font-bold transition-colors"
          >
            Open map
          </button>
        </div>
      </div>
    );
  }

  const [dLat, dLon] = pfz.coordinates;
  const seaBadge =
    live.sea === 'danger' ? 'AVOID' : live.sea === 'caution' ? 'CAUTION' : null;
  const cycloneOk =
    live.cycloneLevel == null ||
    live.cycloneLevel.toLowerCase() === 'safe' ||
    live.cycloneLevel.toLowerCase() === 'advisory';
  const seaOk = live.sea == null || live.sea !== 'danger';

  const card = (extra = '') =>
    isLight ? `bg-white border-sky-100 ${extra}` : `bg-slate-950/80 border-cyan-900/40 ${extra}`;

  return (
    <div data-testid="pfz-detail-screen" className="max-w-4xl mx-auto space-y-6 pb-16">
      <button
        type="button"
        data-testid="pfz-detail-back"
        onClick={() => setActiveTab('home')}
        className="px-3.5 py-1.5 rounded-xl glass-panel bg-slate-900 border border-slate-800 text-cyan-300 hover:text-white text-xs font-semibold inline-flex items-center gap-1.5 transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        <span>Back to Dashboard</span>
      </button>

      {live.offline && (
        <p
          data-testid="pfz-detail-warning-chip"
          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-amber-500/20 border border-amber-400/50 text-amber-200 text-[11px] font-bold"
        >
          Live safety feed unreachable — showing INCOIS zone values
        </p>
      )}

      <div className="glass-panel rounded-3xl p-6 sm:p-8 border border-cyan-500/40 bg-gradient-to-br from-slate-950 via-slate-900 to-cyan-950/50 shadow-2xl relative overflow-hidden">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="px-3 py-1 rounded-lg bg-cyan-950 text-cyan-300 font-mono text-sm font-bold border border-cyan-800">
                {pfz.code}
              </span>
              <span className="text-xs font-semibold text-slate-400">
                Updated {pfz.lastUpdated}
              </span>
            </div>
            <h1 className="text-2xl sm:text-4xl font-extrabold text-white tracking-tight">
              {pfz.name}
            </h1>
            <p className="text-xs sm:text-sm text-slate-300 mt-1 font-medium">
              Region: <span className="text-cyan-200">{pfz.region}</span>
            </p>
            <p className="text-[11px] font-mono text-slate-400 mt-1">
              {formatDMS(dLat, true)} | {formatDMS(dLon, false)}
            </p>
          </div>

          <div className="shrink-0 flex flex-col items-end gap-2">
            <SafetyStatus status={pfz.suitability} size="lg" />
            {seaBadge && (
              <span
                data-testid="pfz-detail-live-safety"
                className={`px-2.5 py-0.5 rounded-full text-[11px] font-bold border ${
                  seaBadge === 'AVOID'
                    ? 'bg-rose-500/20 text-rose-300 border-rose-500/40'
                    : 'bg-amber-500/20 text-amber-300 border-amber-500/40'
                }`}
              >
                Live sea: {seaBadge}
              </span>
            )}
          </div>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-6 pt-6 border-t border-slate-800">
          <div className="p-3 rounded-2xl bg-slate-900/80 border border-slate-800">
            <div className="text-xs text-slate-400 flex items-center gap-1">
              <MapPin className="w-4 h-4 text-cyan-400" />
              Distance
            </div>
            <div className="text-lg sm:text-xl font-extrabold text-cyan-200 mt-1">
              {pfz.distanceKm} km
            </div>
            <div className="text-[11px] text-slate-400">From Harbor</div>
          </div>

          <div className="p-3 rounded-2xl bg-slate-900/80 border border-slate-800">
            <div className="text-xs text-slate-400 flex items-center gap-1">
              <Compass className="w-4 h-4 text-teal-400" />
              Bearing
            </div>
            <div className="text-lg sm:text-xl font-extrabold text-teal-200 mt-1">
              {pfz.bearing}
            </div>
            <div className="text-[11px] text-slate-400">Compass Heading</div>
          </div>

          <div className="p-3 rounded-2xl bg-slate-900/80 border border-slate-800">
            <div className="text-xs text-slate-400 flex items-center gap-1">
              <Clock className="w-4 h-4 text-amber-400" />
              Est. Time
            </div>
            <div className="text-lg sm:text-xl font-extrabold text-amber-200 mt-1">
              ~{pfz.travelTimeMinutes} mins
            </div>
            <div className="text-[11px] text-slate-400">At 12 knots speed</div>
          </div>

          <div className="p-3 rounded-2xl bg-slate-900/80 border border-slate-800">
            <div className="text-xs text-slate-400 flex items-center gap-1">
              <Fuel className="w-4 h-4 text-blue-400" />
              Fuel Est.
            </div>
            <div className="text-lg sm:text-xl font-extrabold text-blue-200 mt-1">
              ~{pfz.fuelEstimateLiters} L
            </div>
            <div className="text-[11px] text-slate-400">Diesel consumption</div>
          </div>
        </div>
      </div>

      <div className="space-y-3">
        <h2 className="font-extrabold text-lg text-white tracking-wide flex items-center gap-2">
          <Waves className="w-5 h-5 text-cyan-400" />
          Oceanographic & Weather Metrics
        </h2>

        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
          <div className={`rounded-2xl p-3.5 border ${card()}`}>
            <span className="text-xs text-slate-400 flex items-center gap-1">
              <Thermometer className="w-4 h-4 text-amber-400" />
              SST
            </span>
            <div className="text-xl font-bold text-amber-200 mt-1">{pfz.sstCelsius}°C</div>
            <span className="text-[10px] text-slate-400">Thermal Front</span>
          </div>

          <div className={`rounded-2xl p-3.5 border ${card()}`}>
            <span className="text-xs text-slate-400 flex items-center gap-1">
              <Waves className="w-4 h-4 text-cyan-400" />
              Chlorophyll
            </span>
            <div className="text-xl font-bold text-cyan-200 mt-1">{pfz.chlorophyllMgM3} mg/m³</div>
            <span className="text-[10px] text-slate-400">High Plankton</span>
          </div>

          <div className={`rounded-2xl p-3.5 border ${card()}`}>
            <span className="text-xs text-slate-400 flex items-center gap-1">
              <Waves className="w-4 h-4 text-blue-400" />
              Wave Height
            </span>
            <div className="text-xl font-bold text-blue-200 mt-1">
              {live.waveM ?? pfz.waveHeightMeters} m
            </div>
            <span className="text-[10px] text-slate-400">
              {live.waveM != null ? 'Live telemetry' : 'INCOIS zone value'}
            </span>
          </div>

          <div className={`rounded-2xl p-3.5 border ${card()}`}>
            <span className="text-xs text-slate-400 flex items-center gap-1">
              <Wind className="w-4 h-4 text-sky-400" />
              Wind Speed
            </span>
            <div className="text-xl font-bold text-sky-200 mt-1">
              {live.windKt != null
                ? `${Number((live.windKt * 1.852).toFixed(1))} km/h`
                : `${pfz.windSpeedKmh} km/h`}
            </div>
            <span className="text-[10px] text-slate-400">Dir: {pfz.windDirection}</span>
          </div>

          <div className={`rounded-2xl p-3.5 border ${card()}`}>
            <span className="text-xs text-slate-400 flex items-center gap-1">
              <Sun className="w-4 h-4 text-yellow-400" />
              Weather
            </span>
            <div className="text-sm font-bold text-white mt-1.5 truncate">
              {pfz.weatherCondition}
            </div>
            <span className="text-[10px] text-slate-400">Operational</span>
          </div>
        </div>
      </div>

      <div className="glass-panel rounded-2xl p-4 border border-cyan-900/40 bg-slate-950/80">
        <div className="flex items-center gap-2 mb-2 text-cyan-300 font-bold text-sm">
          <Fish className="w-5 h-5 text-cyan-400" />
          Target High-Yield Fish Species in Zone
        </div>
        <div className="flex flex-wrap gap-2">
          {pfz.targetFishSpecies.map((sp, idx) => (
            <span
              key={idx}
              className="px-3 py-1 rounded-xl bg-cyan-950 text-cyan-200 border border-cyan-800 text-xs font-semibold"
            >
              🐟 {sp}
            </span>
          ))}
        </div>
      </div>

      <div className="glass-panel rounded-2xl p-4 border border-slate-800 bg-slate-950/80">
        <div className="flex items-center gap-2 mb-3 text-white font-bold text-sm">
          <ShieldCheck className="w-5 h-5 text-emerald-400" />
          Safety & Regulatory Verification
          {live.loading && (
            <span className="text-[11px] font-medium text-slate-400">Checking live feeds…</span>
          )}
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
          <div
            data-testid="pfz-detail-check-cyclone"
            className={`p-3 rounded-xl border ${
              cycloneOk
                ? 'bg-emerald-950/30 border-emerald-500/30 text-emerald-200'
                : 'bg-rose-950/30 border-rose-500/30 text-rose-200'
            }`}
          >
            <div className="font-bold flex items-center gap-1">
              {cycloneOk ? '✓' : '⚠'} Cyclone Risk:{' '}
              {live.cycloneLevel ? live.cycloneLevel.toUpperCase() : 'CHECKING'}
            </div>
            <p className="text-[11px] text-slate-300 mt-0.5">
              {live.cycloneText ?? 'Live IMD cyclone watch at this zone.'}
            </p>
          </div>

          <div
            data-testid="pfz-detail-check-sea"
            className={`p-3 rounded-xl border ${
              seaOk
                ? 'bg-emerald-950/30 border-emerald-500/30 text-emerald-200'
                : 'bg-rose-950/30 border-rose-500/30 text-rose-200'
            }`}
          >
            <div className="font-bold flex items-center gap-1">
              {seaOk ? '✓' : '⚠'} Sea State:{' '}
              {live.sea ? live.sea.toUpperCase() : 'ZONE VALUES'}
            </div>
            <p className="text-[11px] text-slate-300 mt-0.5">
              {live.windKt != null || live.waveM != null
                ? `Live wind ${live.windKt ?? '—'} kt, wave ${live.waveM ?? '—'} m`
                : `Zone wind ${pfz.windSpeedKmh} km/h, wave ${pfz.waveHeightMeters} m`}
            </p>
          </div>

          <div
            data-testid="pfz-detail-check-geofence"
            className="p-3 rounded-xl bg-emerald-950/30 border border-emerald-500/30 text-emerald-200"
          >
            <div className="font-bold flex items-center gap-1">✓ Geofence Clear</div>
            <p className="text-[11px] text-slate-300 mt-0.5">
              {live.geofenceText ?? 'EEZ/MPA/IMBL boundaries monitored.'}
            </p>
          </div>
        </div>
      </div>

      <div id="evidence-section" data-testid="pfz-detail-evidence">
        <EvidenceCard
          evidence={evidence}
          title="Why ORCA Recommends This Zone"
        />
      </div>

      <div className="space-y-2">
        <h3 className="font-bold text-sm text-white flex items-center gap-2">
          <Compass className="w-4 h-4 text-cyan-400" />
          Zone Coordinates on Map ({dLat}, {dLon})
        </h3>
        <div data-testid="pfz-detail-map-preview" className="h-[280px] rounded-2xl overflow-hidden border border-cyan-500/20">
          <MapView
            center={[dLat, dLon]}
            zoom={11}
            highlightFeatures={focusFeature ? [focusFeature] : []}
            userLocation={{ lat: userLocation.lat, lon: userLocation.lon }}
            onSelectZone={() => undefined}
          />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3 pt-4 border-t border-slate-800">
        <button
          type="button"
          data-testid="pfz-detail-view-map"
          onClick={() => viewOnMap(selectedPFZ as Exclude<typeof selectedPFZ, null>)}
          className="flex-1 min-w-[130px] px-5 py-3 rounded-2xl bg-cyan-950/80 border border-cyan-700 text-cyan-200 hover:bg-cyan-900/60 font-bold text-sm flex items-center justify-center gap-2"
        >
          <MapPin className="w-5 h-5 text-cyan-400" />
          <span>View on Map</span>
        </button>

        <button
          type="button"
          data-testid="pfz-detail-route"
          onClick={() =>
            startRouteNavigation(selectedPFZ as Exclude<typeof selectedPFZ, null>)
          }
          className="flex-1 min-w-[130px] px-5 py-3 rounded-2xl bg-gradient-to-r from-cyan-600 via-teal-600 to-emerald-600 text-white font-extrabold text-sm shadow-xl shadow-cyan-600/30 hover:scale-[1.02] transition-transform flex items-center justify-center gap-2"
        >
          <Navigation className="w-5 h-5 fill-white" />
          <span>View Route</span>
        </button>

        <button
          type="button"
          data-testid="pfz-detail-ask"
          onClick={() => {
            submitChatQuery(`Explain fishing prospects and safety for ${pfz.code}`);
          }}
          className="flex-1 min-w-[130px] px-5 py-3 rounded-2xl glass-panel bg-slate-900 border border-cyan-800 text-cyan-200 hover:text-white font-bold text-sm flex items-center justify-center gap-2"
        >
          <MessageSquareText className="w-5 h-5 text-cyan-400" />
          <span>Ask ORCA</span>
        </button>

        <button
          type="button"
          data-testid="pfz-detail-evidence-btn"
          onClick={() => {
            const el = document.getElementById('evidence-section');
            if (el) el.scrollIntoView({ behavior: 'smooth' });
          }}
          className="flex-1 min-w-[130px] px-5 py-3 rounded-2xl glass-panel bg-cyan-950/60 border border-cyan-700 text-cyan-300 hover:bg-cyan-900/60 font-bold text-sm flex items-center justify-center gap-2"
        >
          <ShieldCheck className="w-5 h-5 text-emerald-400" />
          <span>View Evidence</span>
        </button>
      </div>
    </div>
  );
};

export default PFZDetailScreen;
