/**
 * AlertsScreen (UI-MIG-T7)
 *
 * Owner: M-E (Frontend Chat & App Shell)
 * Module: frontend/components/screens/AlertsScreen.tsx
 *
 * Ported layout from source design `screens/AlertsScreen` (READ-ONLY):
 * header banner + category filter tabs + AlertCard list.
 *
 * Live-only contract (no mock imports):
 * - Live source = GET {backend}/api/weather/cyclone (+lat/lon) and
 *   GET {backend}/api/weather/current?lat=&lon= at the context GPS snapshot,
 *   plus one geofence monitoring card (copy from GET /api/geofence/status
 *   counts when reachable; static "monitored boundary" copy otherwise).
 * - RED/ORANGE/GREEN derived from backend thresholds (cyclone alert_level;
 *   wave>2.5m / wind>25kt danger, wave>1.5m / wind>15kt caution — mirrors
 *   docs/API.md weather/current classification).
 * - Offline (backend unreachable): same-shape skeleton cards + warning
 *   banner ("live feed unavailable"). Cards are flagged stale.
 * - Filter tabs: All / Critical (severity RED) / category match.
 * - "View on Map" per card (AlertCard) + header "View on map" shortcut.
 * - Syncs live list into AppContext alertsList (Navbar/badge consumers).
 */

'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { useApp, KOCHI_FALLBACK } from '@/context/AppContext';
import { AlertCard, AlertItem } from '@/components/cards/AlertCard';
import { ShieldAlert, ShieldCheck, Filter } from 'lucide-react';

const FILTER_CATEGORIES = [
  'All',
  'Critical',
  'Marine Warnings',
  'Weather',
  'Cyclone',
  'Lightning',
  'High Waves',
  'Wind',
];

/**
 * Offline skeleton — same AlertItem shape, clearly flagged stale.
 * Shown only when the live cyclone/weather feed is unreachable.
 */
const OFFLINE_SKELETON_ALERTS: AlertItem[] = [
  {
    id: 'skeleton-cyclone',
    title: 'Cyclone watch — feed unavailable',
    location: 'Indian coastal waters',
    category: 'Cyclone',
    severity: 'ORANGE',
    validity: 'Last known: unavailable offline',
    description:
      'Live cyclone feed unreachable. Last known state unavailable — treat offshore sectors with caution until the feed reconnects.',
    stale: true,
  },
  {
    id: 'skeleton-waves',
    title: 'Wave & wind advisory — feed unavailable',
    location: 'Home waters',
    category: 'High Waves',
    severity: 'ORANGE',
    validity: 'Last known: unavailable offline',
    description:
      'Live weather feed unreachable. Nearshore conditions unknown — avoid deep water until live telemetry resumes.',
    stale: true,
  },
];

function getBackendBase(): string {
  if (typeof window === 'undefined') return 'http://localhost:8000';
  const envUrl = process.env.NEXT_PUBLIC_API_URL;
  if (envUrl && envUrl.trim().length > 0) return envUrl.replace(/\/$/, '');
  return 'http://localhost:8000';
}

function waveWindSeverity(
  waveM: number | null,
  windKt: number | null
): 'RED' | 'ORANGE' | 'GREEN' {
  if (
    (waveM != null && waveM > 2.5) ||
    (windKt != null && windKt > 25)
  ) {
    return 'RED';
  }
  if (
    (waveM != null && waveM > 1.5) ||
    (windKt != null && windKt > 15)
  ) {
    return 'ORANGE';
  }
  return 'GREEN';
}

export const AlertsScreen: React.FC = () => {
  const {
    alertsList,
    setAlertsList,
    selectedAlertFilter,
    setSelectedAlertFilter,
    setActiveTab,
    userLocation,
    submitChatQuery,
  } = useApp();

  const [loading, setLoading] = useState<boolean>(true);
  const [offline, setOffline] = useState<boolean>(false);

  const loadLiveAlerts = useCallback(async () => {
    const base = getBackendBase();
    const lat = userLocation?.lat ?? KOCHI_FALLBACK.lat;
    const lon = userLocation?.lon ?? KOCHI_FALLBACK.lon;
    setLoading(true);
    setOffline(false);

    const live: AlertItem[] = [];
    let anyLive = false;

    // 1. Cyclone feed (live).
    try {
      const res = await fetch(
        `${base}/api/weather/cyclone?lat=${lat}&lon=${lon}`
      );
      if (res.ok) {
        const data = await res.json();
        anyLive = true;
        const level = String(data?.alert_level ?? 'safe').toLowerCase();
        const active = Boolean(data?.active) || level === 'warning' || level === 'severe';
        const distKm =
          data?.nearest_cyclone_distance_km ?? data?.nearest_cyclone_km ?? null;
        if (active || level === 'advisory') {
          live.push({
            id: 'live-cyclone',
            title:
              level === 'severe'
                ? 'Severe Cyclone Warning'
                : level === 'warning'
                ? 'Cyclone Warning'
                : 'Cyclone Advisory',
            location:
              Array.isArray(data?.regions_affected) && data.regions_affected.length > 0
                ? String(data.regions_affected.join(', '))
                : 'Indian coastal waters',
            category: 'Cyclone',
            severity: active ? 'RED' : 'ORANGE',
            validity: `Updated ${String(data?.last_updated ?? 'recently')}`,
            description:
              String(data?.description ?? 'Cyclone bulletin active for coastal waters.') +
              (distKm != null ? ` Nearest system ~${distKm} km away.` : ''),
            radiusKm: 45,
          });
        } else {
          live.push({
            id: 'live-cyclone-clear',
            title: 'No active cyclone warning',
            location: 'Indian coastal waters',
            category: 'Cyclone',
            severity: 'GREEN',
            validity: `Updated ${String(data?.last_updated ?? 'recently')}`,
            description: String(
              data?.description ??
                'No active cyclone alerts or pressure anomalies detected in Indian coastal waters.'
            ),
          });
        }
      }
    } catch {
      // Backend unreachable — handled by offline fallback below.
    }

    // 2. Current weather hazards (live): wave/wind → High Waves / Wind cards.
    try {
      const res = await fetch(
        `${base}/api/weather/current?lat=${lat}&lon=${lon}`
      );
      if (res.ok) {
        const data = await res.json();
        anyLive = true;
        const waveM =
          data?.wave_height_m != null ? Number(data.wave_height_m) : null;
        const windKt =
          data?.wind_speed_kt ?? data?.wind_speed_kts ?? null;
        const windNum = windKt != null ? Number(windKt) : null;
        const severity = waveWindSeverity(
          Number.isFinite(waveM as number) ? (waveM as number) : null,
          Number.isFinite(windNum as number) ? (windNum as number) : null
        );
        const status = String(data?.status ?? '').toLowerCase();
        const danger = severity === 'RED' || status.includes('danger');
        live.push({
          id: 'live-waves',
          title:
            severity === 'RED'
              ? `High Wave Warning (${waveM ?? '?'}m)`
              : severity === 'ORANGE'
              ? 'Moderate Sea Advisory'
              : 'Coastal Weather Advisory — calm seas',
          location: userLocation?.name ?? 'Home waters',
          category: severity === 'GREEN' ? 'Weather' : 'High Waves',
          severity,
          validity: 'Live · weather/current',
          description:
            severity === 'GREEN'
              ? `Sea conditions calm (${waveM ?? '?'}m swell, wind ${windNum ?? '?'} kt). Good visibility for small motorized crafts.`
              : `Waves ${waveM ?? '?'}m, wind ${windNum ?? '?'} kt. ${
                  danger
                    ? 'Avoid venturing into deep waters.'
                    : 'Small boat operators should exercise caution.'
                }`,
          coordinates: [lat, lon],
          radiusKm: 25,
        });
        if (windNum != null && windNum > 15) {
          live.push({
            id: 'live-wind',
            title: `Wind Advisory (${windNum} kt)`,
            location: userLocation?.name ?? 'Home waters',
            category: 'Wind',
            severity: windNum > 25 ? 'RED' : 'ORANGE',
            validity: 'Live · weather/current',
            description: `Sustained winds ${windNum} kt${
              data?.wind_direction ? ` from ${data.wind_direction}` : ''
            }. ${windNum > 25 ? 'Gale conditions — do not sail.' : 'Gusty conditions — exercise caution.'}`,
            coordinates: [lat, lon],
            radiusKm: 20,
          });
        }
      }
    } catch {
      // Backend unreachable — handled below.
    }

    // 3. Geofence monitoring copy (live counts when reachable).
    try {
      const res = await fetch(`${base}/api/geofence/status`);
      if (res.ok) {
        const data = await res.json();
        anyLive = true;
        const mpas: string[] = Array.isArray(data?.active_mpas)
          ? data.active_mpas
          : [];
        live.push({
          id: 'live-geofence',
          title: 'Geofence Restricted Zones Monitored',
          location: 'EEZ / MPA boundaries',
          category: 'Critical',
          severity: 'GREEN',
          validity: 'Active 24/7 monitored boundary',
          description:
            `Protected boundaries monitored (${mpas.length > 0 ? mpas.join(', ') : 'EEZ + MPA layers'}). ` +
            'Crossing naval restricted perimeters triggers automated coast guard alerts — check the map before sailing.',
          radiusKm: 12,
        });
      }
    } catch {
      // Optional — geofence copy degrades silently.
    }

    if (!anyLive) {
      setOffline(true);
      setAlertsList(
        OFFLINE_SKELETON_ALERTS.map((a) => ({
          id: a.id,
          severity: String(a.severity),
          title: a.title,
        }))
      );
    } else {
      setAlertsList(
        live.map((a) => ({
          id: a.id,
          severity: String(a.severity),
          title: a.title,
          location: a.location,
          category: a.category,
          validity: a.validity,
          description: a.description,
          coordinates: a.coordinates,
          radiusKm: a.radiusKm,
        }))
      );
    }
    setLoading(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userLocation?.lat, userLocation?.lon]);

  useEffect(() => {
    void loadLiveAlerts();
  }, [loadLiveAlerts]);

  const displayAlerts: AlertItem[] = offline
    ? OFFLINE_SKELETON_ALERTS
    : (alertsList as AlertItem[]);

  const filteredAlerts = displayAlerts.filter((a) => {
    if (selectedAlertFilter === 'All') return true;
    if (selectedAlertFilter === 'Critical')
      return String(a.severity).toUpperCase() === 'RED';
    return a.category === selectedAlertFilter;
  });

  const redAlertsCount = displayAlerts.filter(
    (a) => String(a.severity).toUpperCase() === 'RED'
  ).length;

  return (
    <div data-testid="tab-panel-alerts" className="max-w-4xl mx-auto space-y-6 pb-16">
      {/* Header Banner */}
      <div className="glass-panel rounded-3xl p-6 sm:p-8 border border-rose-500/30 bg-gradient-to-r from-slate-950 via-slate-900 to-rose-950/20 shadow-2xl">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-rose-950 text-rose-300 border border-rose-800 text-xs font-bold mb-2">
              <ShieldAlert className="w-3.5 h-3.5 text-rose-400 animate-pulse" />
              <span>INCOIS & IMD Safety Advisory Broadcast</span>
            </div>
            <h1 className="text-2xl sm:text-3xl font-extrabold text-white tracking-tight">
              Marine Safety & Alert Center
            </h1>
            <p className="text-xs sm:text-sm text-slate-300 mt-1">
              Real-time hazard warnings, wave surges, lightning & weather advisories
            </p>
          </div>

          <div className="flex items-center gap-2">
            <div className="px-4 py-2 rounded-2xl bg-rose-500/20 border border-rose-500/40 text-rose-200 text-xs font-extrabold flex items-center gap-2 shadow-inner">
              <span className="w-2.5 h-2.5 rounded-full bg-rose-500 animate-ping" />
              <span data-testid="alerts-red-count">
                {redAlertsCount} CRITICAL ALERT{redAlertsCount === 1 ? '' : 'S'}
              </span>
            </div>
          </div>
        </div>
        <div className="flex flex-wrap gap-2 mt-4">
          <button
            type="button"
            onClick={() => setActiveTab('map')}
            data-testid="alerts-view-map"
            className="px-4 py-2 rounded-xl border border-cyan-500/40 text-cyan-200 text-xs font-bold hover:bg-cyan-950 transition-colors"
          >
            View on map
          </button>
          <button
            type="button"
            onClick={() => submitChatQuery('Any cyclone or high wave alert for my coast?')}
            data-testid="alerts-ask-orca"
            className="px-4 py-2 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-bold transition-colors"
          >
            Ask ORCA about alerts
          </button>
          <button
            type="button"
            onClick={() => void loadLiveAlerts()}
            data-testid="alerts-refresh"
            className="px-4 py-2 rounded-xl border border-slate-600 text-slate-300 text-xs font-bold hover:bg-slate-800 transition-colors"
          >
            Refresh live feed
          </button>
        </div>
      </div>

      {offline && (
        <div
          data-testid="alerts-warning"
          role="alert"
          className="p-3 rounded-xl bg-amber-950/80 border border-amber-500/40 text-amber-200 text-xs font-bold"
        >
          Live alert feed unavailable (backend offline) — showing offline
          skeleton. Treat offshore sectors with caution until the feed reconnects.
        </div>
      )}

      {/* Category Filter Tabs */}
      <div className="flex items-center gap-2 overflow-x-auto pb-2 no-scrollbar text-xs">
        <Filter className="w-4 h-4 text-cyan-400 shrink-0 ml-1" />
        {FILTER_CATEGORIES.map((cat) => {
          const isSelected = selectedAlertFilter === cat;
          return (
            <button
              key={cat}
              type="button"
              onClick={() => setSelectedAlertFilter(cat)}
              data-testid={`alerts-filter-${cat}`}
              className={`px-3.5 py-2 rounded-xl transition-all shrink-0 font-semibold ${
                isSelected
                  ? 'bg-gradient-to-r from-cyan-400 to-teal-500 text-slate-950 shadow-md shadow-cyan-500/20'
                  : 'glass-panel bg-slate-900/70 border border-slate-800 text-slate-300 hover:text-white hover:border-cyan-500/40'
              }`}
            >
              {cat}
            </button>
          );
        })}
      </div>

      {/* Alert Cards List */}
      <div className="space-y-4">
        {loading ? (
          <div data-testid="alerts-loading" className="space-y-4" aria-busy="true">
            {[0, 1].map((i) => (
              <div
                key={i}
                className="rounded-2xl p-5 border border-slate-800 bg-slate-950/60 animate-pulse"
              >
                <div className="h-4 w-2/3 rounded bg-slate-800" />
                <div className="h-3 w-full rounded bg-slate-800/70 mt-3" />
                <div className="h-3 w-5/6 rounded bg-slate-800/70 mt-2" />
              </div>
            ))}
          </div>
        ) : filteredAlerts.length > 0 ? (
          filteredAlerts.map((alert) => <AlertCard key={alert.id} alert={alert} />)
        ) : (
          <div className="glass-panel rounded-2xl p-8 text-center text-slate-400 border border-slate-800">
            <ShieldCheck className="w-12 h-12 text-emerald-400 mx-auto mb-3" />
            <p className="font-semibold text-white">No active warnings in this category.</p>
            <p className="text-xs mt-1">Operational waters are safe for fishing activities.</p>
          </div>
        )}
      </div>
    </div>
  );
};

export default AlertsScreen;
