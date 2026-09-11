/**
 * PFZRecommendationCard (UI-MIG-T3, extended T6)
 *
 * Owner: M-E (Frontend Chat & App Shell)
 * Module: frontend/components/cards/PFZRecommendationCard.tsx
 *
 * Ported visuals from source design cards/PFZRecommendationCard (READ-ONLY).
 *
 * Live-only rewiring (no mocks):
 * - `pfz` is a PFZItem mapped by the shared `@/lib/pfz` mapper from live
 *   `GET /api/pfz` (GeoJSON -> PFZItem). No hardcoded zones.
 * - Buttons call live AppContext: viewOnMap (map flyTo+highlight),
 *   startRouteNavigation, openPFZDetail. No simulators.
 * - PFZItem type lives in `@/lib/pfz` (single source); re-exported here
 *   so existing T3 importers keep working.
 */

'use client';

import React from 'react';
import { useApp } from '@/context/AppContext';
import { SafetyStatus } from '@/components/common/SafetyStatus';
import { motion } from 'framer-motion';
import {
  Compass,
  MapPin,
  Thermometer,
  Waves,
  Navigation,
  Fish,
  Eye,
} from 'lucide-react';

import type { PFZItem } from '@/lib/pfz';
export type { PFZItem } from '@/lib/pfz';

interface PFZCardProps {
  pfz: PFZItem;
  isFeatured?: boolean;
}

export const PFZRecommendationCard: React.FC<PFZCardProps> = ({
  pfz,
  isFeatured = false,
}) => {
  const { openPFZDetail, startRouteNavigation, viewOnMap, themeMode } =
    useApp();
  const isLight = themeMode === 'light';

  return (
    <motion.div
      whileHover={{ y: -3 }}
      transition={{ type: 'spring', stiffness: 400, damping: 25 }}
      data-testid="pfz-featured-card"
      className={`rounded-2xl p-5 border transition-all ${
        isLight
          ? isFeatured
            ? 'border-sky-300 bg-white shadow-lg shadow-sky-900/5'
            : 'border-slate-200 bg-white shadow-sm'
          : isFeatured
            ? 'glass-panel glass-card-interactive border-cyan-500/50 bg-gradient-to-br from-slate-950 via-slate-900 to-cyan-950/40 shadow-xl shadow-cyan-950/60'
            : 'glass-panel glass-card-interactive border-slate-800 bg-slate-950/80'
      }`}
    >
      {/* Top Header Row */}
      <div
        className={`flex flex-wrap items-center justify-between gap-2 pb-3 border-b ${isLight ? 'border-slate-100' : 'border-slate-800'}`}
      >
        <div>
          <div className="flex items-center gap-2">
            <span
              className={`px-2.5 py-0.5 rounded-md font-mono text-xs font-bold border ${
                isLight
                  ? 'bg-sky-100 text-sky-800 border-sky-200'
                  : 'bg-cyan-950 text-cyan-300 border-cyan-800'
              }`}
            >
              {pfz.code}
            </span>
            <h3
              className={`font-extrabold text-base sm:text-lg ${isLight ? 'text-slate-900' : 'text-white'}`}
            >
              {pfz.name}
            </h3>
          </div>
          <p
            className={`text-xs mt-0.5 font-medium ${isLight ? 'text-slate-500' : 'text-slate-400'}`}
          >
            {pfz.region}
          </p>
        </div>

        <SafetyStatus status={pfz.suitability} size="sm" />
      </div>

      {/* Primary Specs Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 my-4">
        <div
          className={`p-2.5 rounded-xl border ${isLight ? 'bg-sky-50/70 border-sky-100' : 'bg-slate-900/60 border-slate-800/80'}`}
        >
          <div
            className={`text-[11px] flex items-center gap-1 ${isLight ? 'text-slate-500' : 'text-slate-400'}`}
          >
            <MapPin className="w-3.5 h-3.5 text-cyan-600" />
            Distance
          </div>
          <div
            className={`text-base font-bold mt-0.5 ${isLight ? 'text-cyan-900' : 'text-cyan-200'}`}
          >
            {pfz.distanceKm} km
          </div>
          <div
            className={`text-[10px] ${isLight ? 'text-slate-500' : 'text-slate-400'}`}
          >
            ~{pfz.travelTimeMinutes} mins travel
          </div>
        </div>

        <div
          className={`p-2.5 rounded-xl border ${isLight ? 'bg-teal-50/70 border-teal-100' : 'bg-slate-900/60 border-slate-800/80'}`}
        >
          <div
            className={`text-[11px] flex items-center gap-1 ${isLight ? 'text-slate-500' : 'text-slate-400'}`}
          >
            <Compass className="w-3.5 h-3.5 text-teal-600" />
            Bearing
          </div>
          <div
            className={`text-base font-bold mt-0.5 ${isLight ? 'text-teal-900' : 'text-teal-200'}`}
          >
            {pfz.bearing}
          </div>
          <div
            className={`text-[10px] ${isLight ? 'text-slate-500' : 'text-slate-400'}`}
          >
            Depth: {pfz.depthMeters}m
          </div>
        </div>

        <div
          className={`p-2.5 rounded-xl border ${isLight ? 'bg-amber-50/70 border-amber-100' : 'bg-slate-900/60 border-slate-800/80'}`}
        >
          <div
            className={`text-[11px] flex items-center gap-1 ${isLight ? 'text-slate-500' : 'text-slate-400'}`}
          >
            <Thermometer className="w-3.5 h-3.5 text-amber-500" />
            SST Temp
          </div>
          <div
            className={`text-base font-bold mt-0.5 ${isLight ? 'text-amber-900' : 'text-amber-200'}`}
          >
            {pfz.sstCelsius}°C
          </div>
          <div
            className={`text-[10px] ${isLight ? 'text-slate-500' : 'text-slate-400'}`}
          >
            Chl: {pfz.chlorophyllMgM3} mg/m³
          </div>
        </div>

        <div
          className={`p-2.5 rounded-xl border ${isLight ? 'bg-blue-50/70 border-blue-100' : 'bg-slate-900/60 border-slate-800/80'}`}
        >
          <div
            className={`text-[11px] flex items-center gap-1 ${isLight ? 'text-slate-500' : 'text-slate-400'}`}
          >
            <Waves className="w-3.5 h-3.5 text-blue-600" />
            Wave Height
          </div>
          <div
            className={`text-base font-bold mt-0.5 ${isLight ? 'text-blue-900' : 'text-blue-200'}`}
          >
            {pfz.waveHeightMeters} m
          </div>
          <div
            className={`text-[10px] ${isLight ? 'text-slate-500' : 'text-slate-400'}`}
          >
            Wind: {pfz.windSpeedKmh} km/h
          </div>
        </div>
      </div>

      {/* Fish species tags */}
      {pfz.targetFishSpecies.length > 0 && (
        <div className="flex items-center gap-1.5 flex-wrap my-3 text-xs">
          <Fish className="w-4 h-4 text-cyan-600 shrink-0" />
          <span
            className={`text-[11px] ${isLight ? 'text-slate-500' : 'text-slate-400'}`}
          >
            Species:
          </span>
          {pfz.targetFishSpecies.map((sp, idx) => (
            <span
              key={idx}
              className={`px-2 py-0.5 rounded-full border text-[11px] font-semibold ${
                isLight
                  ? 'bg-sky-50 text-cyan-800 border-sky-200'
                  : 'bg-slate-900 text-cyan-300 border-slate-800'
              }`}
            >
              {sp}
            </span>
          ))}
        </div>
      )}

      {/* CTA Action Buttons */}
      <div
        className={`flex flex-wrap items-center justify-between gap-2 pt-3 border-t ${isLight ? 'border-slate-100' : 'border-slate-800'}`}
      >
        <button
          type="button"
          onClick={() => viewOnMap(pfz)}
          data-testid="pfz-card-view-map"
          className={`flex-1 min-w-[110px] px-3 py-2 rounded-xl border transition-colors text-xs font-bold flex items-center justify-center gap-1.5 ${
            isLight
              ? 'bg-cyan-50 border-cyan-200 text-cyan-900 hover:bg-cyan-100'
              : 'bg-cyan-950/80 border-cyan-800 text-cyan-300 hover:bg-cyan-900/60'
          }`}
        >
          <MapPin className="w-4 h-4 text-cyan-600 shrink-0" />
          <span>View on Map</span>
        </button>

        <button
          type="button"
          onClick={() => startRouteNavigation(pfz)}
          data-testid="pfz-card-safe-route"
          className="flex-1 min-w-[110px] px-3.5 py-2 rounded-xl bg-gradient-to-r from-cyan-600 to-teal-600 text-white text-xs font-extrabold shadow-md hover:scale-[1.02] transition-transform flex items-center justify-center gap-1.5"
        >
          <Navigation className="w-4 h-4 fill-white shrink-0" />
          <span>Safe Route</span>
        </button>

        <button
          type="button"
          onClick={() => openPFZDetail(pfz)}
          data-testid="pfz-card-why"
          className={`flex-1 min-w-[150px] px-3 py-2 rounded-xl border transition-colors text-xs font-bold flex items-center justify-center gap-1.5 ${
            isLight
              ? 'bg-white border-slate-300 text-slate-800 hover:bg-slate-50'
              : 'bg-slate-900 border-slate-800 text-cyan-200 hover:text-white'
          }`}
        >
          <Eye className="w-4 h-4 text-cyan-600 shrink-0" />
          <span>Why this recommendation?</span>
        </button>
      </div>
    </motion.div>
  );
};
