/**
 * HomeScreen (UI-MIG-T3)
 *
 * Owner: M-E (Frontend Chat & App Shell)
 * Module: frontend/components/screens/HomeScreen.tsx
 *
 * Ported layout from source design screens/HomeScreen.tsx (READ-ONLY):
 * hero + waves + INCOIS pill + t(greeting) + base port + Explore-Map button,
 * AskOrcaInput, BaseKPIGrid, MarineMap preview h-[380px], KPITrends,
 * 5 ConditionCards, featured / ghost PFZRecommendationCard.
 * Both themes (#edf6ff light / #070d18 dark).
 *
 * Live-only rewiring (no mock data, no stub services, no fake workflows):
 * - AskOrcaInput submit -> AppContext.submitChatQuery -> chat tab + real
 *   sendMessage (SSE POST /api/chat via ChatPanel). Nothing faked here.
 * - 5 ConditionCards from direct `GET /api/weather/current` (T5 rule: live
 *   telemetry calls backend directly). Thresholds mirror
 *   backend/routers/weather.py (danger: wind>25kt|wave>2.5m|current>2.5kt|
 *   pressure<995hPa; caution: wind>15kt|wave>1.5m|current>1.5kt|
 *   pressure<1005hPa; else safe).
 * - Featured card & BaseKPIGrid from `GET /api/pfz?limit=100` via the
 *   shared GeoJSON->PFZItem mapper (`@/lib/pfz`).
 * - Ghost demo fallback (`KOCHI_GHOST_PFZ`) when no live PFZ features returned.
 * - SystemStatusBadge with live health status polling.
 * - Backend-down -> synthetic coordinate-based estimate + warning chip
 *   (data-testid="home-warning-chip"), never a crash.
 */

'use client';

import React, { useEffect, useMemo, useState } from 'react';
import { useApp } from '@/context/AppContext';
import { AskOrcaInput } from '@/components/common/AskOrcaInput';
import { ConditionCard } from '@/components/common/ConditionCard';
import {
  PFZRecommendationCard,
} from '@/components/cards/PFZRecommendationCard';
import { BaseKPIGrid } from '@/components/analytics/BaseKPIGrid';
import { OfficerKPIGrid } from '@/components/analytics/OfficerKPIGrid';
import { KPITrends } from '@/components/analytics/KPITrends';
import { SkeletonLoader } from '@/components/common/SkeletonLoader';
import { SystemStatusBadge } from '@/components/common/SystemStatusBadge';
import { KOCHI_GHOST_PFZ } from '@/lib/ghostPFZ';
import type { PFZItem } from '@/lib/pfz';
import {
  KT_TO_KMH,
  classifySea,
  getBackendBaseUrl,
  mapFeatureToPFZItem,
  num,
} from '@/lib/pfz';
import { MapView } from '@/map';
import { motion } from 'framer-motion';
import {
  Waves,
  Sun,
  Wind,
  ShieldAlert,
  Compass,
  ArrowRight,
  Sparkles,
  MapPin,
} from 'lucide-react';

interface LiveConditions {
  tempC: number;
  windKt: number;
  windDir: string;
  waveM: number;
  wavePeriodS: number;
  currentKt: number;
  pressureHpa: number;
  safety: 'safe' | 'caution' | 'danger' | 'unknown';
  offline: boolean;
}

export const HomeScreen: React.FC = () => {
  const {
    userLocation,
    gpsStatus,
    setActiveTab,
    openPFZDetail,
    themeMode,
    t,
    activeRoute,
    activeRouteInfo,
    mapFocusFeature,
    mapFocusNonce,
  } = useApp();
  const isLight = themeMode === 'light';

  const highlightFeatures = useMemo(() => {
    if (mapFocusFeature && mapFocusNonce > 0) return [mapFocusFeature];
    return undefined;
  }, [mapFocusFeature, mapFocusNonce]);

  const [conditions, setConditions] = useState<LiveConditions | null>(null);
  const [featuredPFZ, setFeaturedPFZ] = useState<PFZItem | null>(null);
  const [pfzFallback, setPfzFallback] = useState<boolean>(false);
  const [pfzLoading, setPfzLoading] = useState<boolean>(true);
  const [activeZonesCount, setActiveZonesCount] = useState<number | null>(null);
  const [nearestPfzDist, setNearestPfzDist] = useState<number | null>(null);
  const [nearestPfzBearing, setNearestPfzBearing] = useState<string | undefined>(undefined);
  const [nearestPfzName, setNearestPfzName] = useState<string | undefined>(undefined);
  const [avgSst, setAvgSst] = useState<number | null>(null);
  const [avgChl, setAvgChl] = useState<number | null>(null);

  // Live weather telemetry (direct backend call per docs/API.md T5 rule).
  useEffect(() => {
    let cancelled = false;
    const lat = userLocation.lat;
    const lon = userLocation.lon;
    const base = getBackendBaseUrl();
    fetch(
      `${base}/api/weather/current?lat=${lat}&lon=${lon}`
    )
      .then((res) => {
        if (!res.ok) throw new Error(`weather ${res.status}`);
        return res.json();
      })
      .then((data) => {
        if (cancelled) return;
        const windKt = num(data.wind_speed_kt ?? data.wind_speed_kts, 12);
        const waveM = num(data.wave_height_m, 0.9);
        const currentKt = num(data.current_speed_kt, 1.0);
        const pressure = num(data.pressure_hpa, 1012);
        setConditions({
          tempC: num(data.temperature_c, 28.4),
          windKt,
          windDir: String(data.wind_direction ?? 'NE'),
          waveM,
          wavePeriodS: num(data.wave_period_s, 7.0),
          currentKt,
          pressureHpa: pressure,
          safety: classifySea(windKt, waveM, currentKt, pressure),
          offline: false,
        });
      })
      .catch(() => {
        if (cancelled) return;
        // Backend-down: no feed, so no safety verdict. Keep coordinate-based
        // estimates out of the verdict — cards render placeholders (see below).
        const distToCoast = Math.abs(lon - 76.0) * 111;
        const estWave = Math.min(
          2.2,
          Math.max(0.6, 0.7 + distToCoast * 0.015)
        );
        const estWind = Math.min(
          24,
          Math.max(8, 10 + distToCoast * 0.12)
        );
        const waveM = Math.round(estWave * 10) / 10;
        const windKt = Math.round(estWind * 10) / 10;
        setConditions({
          tempC: 28.4,
          windKt,
          windDir: 'NE',
          waveM,
          wavePeriodS: 7.0,
          currentKt: 1.0,
          pressureHpa: 1010,
          safety: 'unknown',
          offline: true,
        });
      });
    return () => {
      cancelled = true;
    };
  }, [userLocation.lat, userLocation.lon]);

  // Featured zone & Base KPI derivation: live PFZ features via Next.js proxy.
  useEffect(() => {
    let cancelled = false;
    setPfzLoading(true);
    fetch('/api/pfz?limit=100')
      .then((res) => {
        if (!res.ok) throw new Error(`pfz ${res.status}`);
        return res.json();
      })
      .then((data) => {
        if (cancelled) return;
        const features = Array.isArray(data?.features) ? data.features : [];
        if (features.length === 0) {
          setFeaturedPFZ(null);
          setPfzFallback(true);
          setActiveZonesCount(0);
          setNearestPfzDist(null);
          setNearestPfzBearing(undefined);
          setNearestPfzName(undefined);
          setAvgSst(null);
          setAvgChl(null);
          setPfzLoading(false);
          return;
        }

        const items: PFZItem[] = [];
        let sstSum = 0;
        let sstCount = 0;
        let chlSum = 0;
        let chlCount = 0;

        for (const feat of features) {
          const item = mapFeatureToPFZItem(
            feat,
            userLocation.lat,
            userLocation.lon
          );
          if (item) {
            items.push(item);
            if (typeof item.sstCelsius === 'number' && Number.isFinite(item.sstCelsius) && item.sstCelsius > 0) {
              sstSum += item.sstCelsius;
              sstCount += 1;
            }
            if (typeof item.chlorophyllMgM3 === 'number' && Number.isFinite(item.chlorophyllMgM3) && item.chlorophyllMgM3 > 0) {
              chlSum += item.chlorophyllMgM3;
              chlCount += 1;
            }
          }
        }

        if (items.length === 0) {
          setFeaturedPFZ(null);
          setPfzFallback(true);
          setActiveZonesCount(0);
          setNearestPfzDist(null);
          setNearestPfzBearing(undefined);
          setNearestPfzName(undefined);
          setAvgSst(null);
          setAvgChl(null);
          setPfzLoading(false);
          return;
        }

        items.sort((a, b) => a.distanceKm - b.distanceKm);
        const nearest = items[0];

        setActiveZonesCount(items.length);
        setNearestPfzDist(nearest.distanceKm);
        setNearestPfzBearing(nearest.bearing);
        setNearestPfzName(nearest.name);
        setAvgSst(sstCount > 0 ? Number((sstSum / sstCount).toFixed(1)) : null);
        setAvgChl(chlCount > 0 ? Number((chlSum / chlCount).toFixed(2)) : null);
        setFeaturedPFZ(nearest);
        setPfzFallback(false);
        setPfzLoading(false);
      })
      .catch(() => {
        if (cancelled) return;
        setFeaturedPFZ(null);
        setPfzFallback(true);
        setActiveZonesCount(0);
        setNearestPfzDist(null);
        setNearestPfzBearing(undefined);
        setNearestPfzName(undefined);
        setAvgSst(null);
        setAvgChl(null);
        setPfzLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [userLocation.lat, userLocation.lon]);

  const showWarning = conditions?.offline === true || pfzFallback;

  const cards = useMemo(() => {
    if (!conditions) return null;
    const offline = conditions.offline === true;
    const windKmh = Number((conditions.windKt * KT_TO_KMH).toFixed(1));
    const seaLabel = offline
      ? 'Unknown — offline'
      : conditions.safety === 'danger'
        ? 'Rough Seas'
        : conditions.safety === 'caution'
          ? 'Moderate Swell'
          : 'Calm & Favorable';
    const seaState = offline
      ? '—'
      : conditions.safety === 'danger'
        ? 'Rough'
        : conditions.safety === 'caution'
          ? 'Moderate'
          : 'Calm';
    const weatherLabel = offline
      ? 'Feed unavailable'
      : conditions.safety === 'danger'
        ? 'Stormy • Avoid'
        : conditions.safety === 'caution'
          ? 'Partly Cloudy'
          : 'Clear & Favorable';
    const seaBadge = offline
      ? 'UNKNOWN'
      : conditions.safety === 'danger'
        ? 'AVOID'
        : conditions.safety === 'caution'
          ? 'CAUTION'
          : 'SAFE';
    const warnCount = offline
      ? 0
      : (conditions.waveM > 1.5 ? 1 : 0) +
        (conditions.windKt > 15 ? 1 : 0) +
        (conditions.pressureHpa < 1005 ? 1 : 0);
    const warnParts: string[] = [];
    if (conditions.waveM > 1.5) warnParts.push('High Wave');
    if (conditions.windKt > 15) warnParts.push('Wind');
    if (conditions.pressureHpa < 1005) warnParts.push('Pressure');
    return {
      windKmh,
      seaLabel,
      seaState,
      weatherLabel,
      seaBadge,
      warnCount,
      warnSub: offline
        ? 'Live feed unreachable'
        : warnParts.length > 0 ? warnParts.join(' • ') : 'No active warnings',
    };
  }, [conditions]);

  const containerVariants = {
    hidden: { opacity: 0 },
    show: { opacity: 1, transition: { staggerChildren: 0.08 } },
  };

  const itemVariants = {
    hidden: { opacity: 0, y: 15 },
    show: { opacity: 1, y: 0 },
  };

  return (
    <div className="space-y-6 pb-12" data-testid="home-screen">
      {/* Hero Greeting & Port Banner with Animated Ocean Wave Elements */}
      <div
        className={`rounded-3xl p-6 sm:p-8 border relative overflow-hidden shadow-xl transition-all ${
          isLight
            ? 'bg-gradient-to-r from-sky-900 via-cyan-900 to-teal-950 text-white border-cyan-700/40 shadow-cyan-900/10'
            : 'glass-panel border-cyan-500/30 bg-gradient-to-r from-slate-950 via-slate-900 to-cyan-950/40 text-white shadow-2xl'
        }`}
      >
        {/* Prominent Flowing Ocean Wave SVG Vector Layer */}
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <svg
            className="absolute bottom-0 left-0 w-[200%] h-32 opacity-40 animate-[waveDrift_16s_linear_infinite]"
            viewBox="0 0 1200 120"
            preserveAspectRatio="none"
          >
            <path
              d="M0,0 C150,90 350,-40 500,50 C650,140 900,10 1200,60 L1200,120 L0,120 Z"
              fill="url(#waveGradient1)"
            />
            <defs>
              <linearGradient
                id="waveGradient1"
                x1="0%"
                y1="0%"
                x2="100%"
                y2="0%"
              >
                <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.6" />
                <stop offset="50%" stopColor="#06b6d4" stopOpacity="0.4" />
                <stop offset="100%" stopColor="#14b8a6" stopOpacity="0.6" />
              </linearGradient>
            </defs>
          </svg>
          <svg
            className="absolute bottom-0 left-0 w-[200%] h-24 opacity-30 animate-[waveDrift_10s_linear_infinite_reverse]"
            viewBox="0 0 1200 120"
            preserveAspectRatio="none"
          >
            <path
              d="M0,30 C200,-20 400,80 600,20 C800,-40 1000,70 1200,30 L1200,120 L0,120 Z"
              fill="#0284c7"
            />
          </svg>
        </div>
        <div className="absolute right-0 top-0 bottom-0 w-1/3 opacity-25 bg-[radial-gradient(circle_at_center,_var(--tw-gradient-stops))] from-cyan-300 via-transparent to-transparent pointer-events-none" />

        <div className="relative z-10 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-2 flex-wrap">
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-cyan-950/80 text-cyan-300 border border-cyan-700/60 text-xs font-bold shadow-sm">
                <Sparkles className="w-3.5 h-3.5 text-cyan-300 animate-pulse" />
                <span>INCOIS Live Marine Feeds Active</span>
              </div>
              <SystemStatusBadge />
            </div>
            <h1 className="text-2xl sm:text-4xl font-extrabold tracking-tight">
              {t('greeting')}
            </h1>
            <p className="text-sm text-cyan-100/90 mt-1 font-medium flex items-center gap-1.5">
              <MapPin className="w-4 h-4 text-cyan-300 inline shrink-0" />
              {t('basePort')}:{' '}
              <span className="text-white font-bold">{userLocation.name}</span>
            </p>
            <p
              className="text-xs mt-2 font-mono opacity-70"
              data-testid="gps-pill-home"
            >
              GPS:{' '}
              {gpsStatus === 'acquiring'
                ? 'Acquiring…'
                : `${userLocation.lat.toFixed(2)}°N, ${userLocation.lon.toFixed(2)}°E (${userLocation.name})`}
            </p>
            {showWarning && (
              <p
                data-testid="home-warning-chip"
                className="mt-2 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-amber-500/20 border border-amber-400/50 text-amber-200 text-[11px] font-bold"
              >
                <ShieldAlert className="w-3.5 h-3.5" />
                Offline estimate — live backend unreachable, data may be stale
              </p>
            )}
          </div>

          <button
            type="button"
            onClick={() => setActiveTab('map')}
            data-testid="home-explore-map"
            aria-label="Explore map"
            className="px-5 py-2.5 rounded-2xl bg-white/10 hover:bg-white/20 border border-white/20 text-white transition-all font-bold text-sm flex items-center gap-2 shadow-md shrink-0 backdrop-blur-md hover:scale-105 active:scale-95"
          >
            <Compass className="w-4 h-4 text-cyan-300 animate-spin-slow" />
            <span>{t('exploreMap')}</span>
            <ArrowRight className="w-4 h-4" />
          </button>
        </div>

        {/* Large Conversational / Voice Search Bar */}
        <div className="relative z-10 mt-6">
          <AskOrcaInput />
        </div>
      </div>

      {/* 4 Base KPIs Grid */}
      <BaseKPIGrid
        activeZonesCount={activeZonesCount}
        nearestPfzDistanceKm={nearestPfzDist}
        nearestPfzBearing={nearestPfzBearing}
        nearestPfzName={nearestPfzName}
        seaSafety={conditions?.safety ?? null}
        seaSafetyLabel={
          conditions?.safety === 'safe'
            ? 'Safe to sail'
            : conditions?.safety === 'caution'
              ? 'Exercise caution'
              : conditions?.safety === 'danger'
                ? 'Rough seas - avoid'
                : 'Unknown'
        }
        avgSstC={avgSst ?? conditions?.tempC ?? null}
        avgChlorophyllMgM3={avgChl}
        isLoading={pfzLoading || conditions === null}
        isGhostDemo={pfzFallback}
      />

      {/* Officer-Gated 2nd KPI Row (T3 #147) */}
      <OfficerKPIGrid />

      {/* Main Interactive Marine Map */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Compass
              className={`w-5 h-5 ${isLight ? 'text-cyan-700' : 'text-cyan-400'}`}
            />
            <h2
              className={`font-extrabold text-lg tracking-wide ${isLight ? 'text-slate-900' : 'text-white'}`}
            >
              {t('liveMap')}
            </h2>
          </div>
          <button
            type="button"
            onClick={() => setActiveTab('map')}
            className={`text-xs font-semibold flex items-center gap-1 transition-colors ${isLight ? 'text-cyan-700 hover:text-cyan-900' : 'text-cyan-400 hover:text-cyan-300'}`}
          >
            <span>{t('exploreMap')}</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>

        <div
          data-testid="home-map-preview"
          className="h-[380px] sm:h-[440px] rounded-2xl overflow-hidden border border-cyan-500/20"
        >
          <MapView
            center={[userLocation.lat, userLocation.lon]}
            zoom={8}
            highlightFeatures={highlightFeatures}
            userLocation={{ lat: userLocation.lat, lon: userLocation.lon }}
            route={activeRoute}
            routeMeta={
              activeRouteInfo
                ? {
                    detourOccurred: activeRouteInfo.detourOccurred,
                    safetyLabel: activeRouteInfo.safetyLabel,
                  }
                : null
            }
            onSelectZone={(feature) => openPFZDetail(feature)}
          />
        </div>
      </div>

      {/* KPI Trends Section */}
      <KPITrends
        liveStats={{
          sstC: avgSst ?? conditions?.tempC ?? null,
          waveM: conditions?.waveM ?? null,
          windKt: conditions?.windKt ?? null,
          activeZones: activeZonesCount,
        }}
      />

      {/* Quick Condition Cards Row */}
      <div className="space-y-3">
        <h2
          className={`font-extrabold text-lg tracking-wide flex items-center gap-2 ${isLight ? 'text-slate-900' : 'text-white'}`}
        >
          <Waves
            className={`w-5 h-5 ${isLight ? 'text-cyan-700' : 'text-cyan-400'}`}
          />
          {t('currentConditions')}
        </h2>

        {cards ? (
          <motion.div
            variants={containerVariants}
            initial="hidden"
            animate="show"
            className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3.5"
          >
            <motion.div variants={itemVariants} whileHover={{ y: -3 }}>
              <ConditionCard
                title={t('seaState')}
                value={cards.seaLabel}
                subtext={`State: ${cards.seaState}`}
                icon={Waves}
                color="text-cyan-600"
                statusBadge={cards.seaBadge}
                testid="condition-card-sea-state"
              />
            </motion.div>

            <motion.div variants={itemVariants} whileHover={{ y: -3 }}>
              <ConditionCard
                title={t('weather')}
                value={conditions!.offline ? '—' : `${conditions!.tempC}°C`}
                subtext={cards.weatherLabel}
                icon={Sun}
                color="text-amber-500"
                testid="condition-card-weather"
              />
            </motion.div>

            <motion.div variants={itemVariants} whileHover={{ y: -3 }}>
              <ConditionCard
                title={t('windSpeed')}
                value={conditions!.offline ? '—' : `${cards.windKmh} km/h`}
                subtext={conditions!.offline ? '—' : `Dir: ${conditions!.windDir}`}
                icon={Wind}
                color="text-sky-600"
                testid="condition-card-wind"
              />
            </motion.div>

            <motion.div variants={itemVariants} whileHover={{ y: -3 }}>
              <ConditionCard
                title={t('waveHeight')}
                value={conditions!.offline ? '—' : `${conditions!.waveM} m`}
                subtext={conditions!.offline ? '—' : `Period: ${conditions!.wavePeriodS}s`}
                icon={Waves}
                color="text-blue-600"
                testid="condition-card-wave"
              />
            </motion.div>

            <motion.div variants={itemVariants} whileHover={{ y: -3 }}>
              <ConditionCard
                title={t('activeWarnings')}
                value={conditions!.offline ? '—' : cards.warnCount}
                subtext={cards.warnSub}
                icon={ShieldAlert}
                color="text-rose-500"
                statusBadge={conditions!.offline ? 'UNKNOWN' : cards.warnCount > 0 ? 'CAUTION' : 'SAFE'}
                testid="condition-card-warnings"
              />
            </motion.div>
          </motion.div>
        ) : (
          <div
            data-testid="condition-cards-loading"
            className={`rounded-2xl border p-5 text-sm font-medium ${isLight ? 'bg-white border-sky-100 text-slate-500' : 'bg-slate-950/80 border-cyan-900/40 text-slate-400'}`}
          >
            Loading live sea conditions…
          </div>
        )}
      </div>

      {/* Spotlight Recommended Fishing Zone */}
      <div className="space-y-3 pt-2">
        <div className="flex items-center justify-between">
          <h2
            className={`font-extrabold text-lg tracking-wide flex items-center gap-2 ${isLight ? 'text-slate-900' : 'text-white'}`}
          >
            <Sparkles
              className={`w-5 h-5 ${isLight ? 'text-cyan-700' : 'text-cyan-400'}`}
            />
            {t('topRecommendedZone')}
          </h2>
          <span
            className={`text-xs font-semibold ${isLight ? 'text-slate-500' : 'text-slate-400'}`}
          >
            {showWarning ? 'Demo Estimate' : 'Live from INCOIS feed'}
          </span>
        </div>

        <motion.div
          initial={{ opacity: 0, y: 15 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
        >
          {pfzLoading ? (
            <SkeletonLoader variant="card" />
          ) : featuredPFZ ? (
            <PFZRecommendationCard pfz={featuredPFZ} isFeatured={true} />
          ) : (
            <PFZRecommendationCard pfz={KOCHI_GHOST_PFZ} isGhostDemo={true} isFeatured={true} />
          )}
        </motion.div>
      </div>
    </div>
  );
};
