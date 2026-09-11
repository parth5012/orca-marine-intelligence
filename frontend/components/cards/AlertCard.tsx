/**
 * AlertCard (UI-MIG-T7)
 *
 * Owner: M-E (Frontend Chat & App Shell)
 * Module: frontend/components/cards/AlertCard.tsx
 *
 * Ported visual from source design `cards/AlertCard` (READ-ONLY).
 * Live-only: renders a live `AlertItem` from AlertsScreen (cyclone/weather
 * hazards + geofence copy). Skeleton shape mirrors the same fields; no mock
 * imports, no mock data. "View on Map" routes via AppContext tab
 * router (map tab stable, Leaflet untouched).
 */

'use client';

import React from 'react';
import { motion } from 'framer-motion';
import {
  AlertTriangle,
  ShieldCheck,
  MapPin,
  Clock,
  ArrowRight,
  XCircle,
} from 'lucide-react';
import { useApp } from '@/context/AppContext';

export type AlertSeverity = 'RED' | 'ORANGE' | 'GREEN';

export interface AlertItem {
  id: string;
  title: string;
  location: string;
  category: string;
  severity: AlertSeverity | string;
  validity: string;
  description: string;
  coordinates?: [number, number];
  radiusKm?: number;
  /** True when this card is an offline skeleton (stale, not live). */
  stale?: boolean;
}

interface AlertCardProps {
  alert: AlertItem;
}

export const AlertCard: React.FC<AlertCardProps> = ({ alert }) => {
  const { setActiveTab, themeMode } = useApp();
  const isLight = themeMode === 'light';

  const isRed = String(alert.severity).toUpperCase() === 'RED';
  const isOrange = String(alert.severity).toUpperCase() === 'ORANGE';

  let borderBg = isLight
    ? 'border-slate-200 bg-white shadow-sm'
    : 'border-slate-800 bg-slate-950/80';
  let badgeStyle = isLight
    ? 'bg-emerald-50 text-emerald-800 border-emerald-300'
    : 'bg-emerald-950 text-emerald-300 border-emerald-800';
  let Icon = ShieldCheck;
  let iconColor = isLight ? 'text-emerald-600' : 'text-emerald-400';

  if (isRed) {
    borderBg = isLight
      ? 'border-rose-300 bg-rose-50/60 shadow-md'
      : 'border-rose-500/50 bg-gradient-to-r from-slate-950 via-slate-900 to-rose-950/40';
    badgeStyle = isLight
      ? 'bg-rose-100 text-rose-900 border-rose-400 font-extrabold shadow-sm'
      : 'bg-rose-950 text-rose-300 border-rose-700 shadow-rose-950/80 font-extrabold';
    Icon = XCircle;
    iconColor = isLight ? 'text-rose-600' : 'text-rose-400';
  } else if (isOrange) {
    borderBg = isLight
      ? 'border-amber-200 bg-amber-50/50 shadow-sm'
      : 'border-amber-500/40 bg-gradient-to-r from-slate-950 via-slate-900 to-amber-950/30';
    badgeStyle = isLight
      ? 'bg-amber-100 text-amber-900 border-amber-300'
      : 'bg-amber-950 text-amber-300 border-amber-800';
    Icon = AlertTriangle;
    iconColor = isLight ? 'text-amber-600' : 'text-amber-400';
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      whileHover={{ y: -2 }}
      data-testid={`alert-card-${alert.id}`}
      className={`rounded-2xl p-5 border ${borderBg} transition-all relative overflow-hidden`}
    >
      {isRed && (
        <div className="absolute top-0 right-0 w-24 h-24 bg-rose-500/10 rounded-full blur-xl pointer-events-none" />
      )}

      <div
        className={`flex flex-wrap items-center justify-between gap-2 pb-3 border-b ${
          isLight ? 'border-slate-100' : 'border-slate-800/80'
        }`}
      >
        <div className="flex items-center gap-2.5">
          <div
            className={`w-9 h-9 rounded-xl border flex items-center justify-center shadow-sm ${
              isLight
                ? 'bg-slate-100 border-slate-200'
                : 'bg-slate-900 border-slate-800'
            }`}
          >
            <Icon className={`w-5 h-5 ${iconColor} ${isRed ? 'animate-bounce' : ''}`} />
          </div>
          <div>
            <h3
              className={`font-extrabold text-base ${
                isLight ? 'text-slate-900' : 'text-white'
              }`}
            >
              {alert.title}
            </h3>
            <div
              className={`flex items-center gap-1.5 text-xs mt-0.5 ${
                isLight ? 'text-slate-500' : 'text-slate-400'
              }`}
            >
              <MapPin className="w-3.5 h-3.5 text-cyan-600" />
              <span className="font-semibold">{alert.location}</span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {alert.stale && (
            <span className="px-2 py-1 rounded-lg text-[10px] font-bold border border-slate-400/40 text-slate-400">
              OFFLINE SKELETON
            </span>
          )}
          <span
            data-testid={`alert-severity-${alert.id}`}
            className={`px-2.5 py-1 rounded-lg text-xs font-extrabold border flex items-center gap-1.5 ${badgeStyle}`}
          >
            {isRed && (
              <span className="w-2 h-2 rounded-full bg-rose-500 animate-ping" />
            )}
            {String(alert.severity).toUpperCase()} ALERT
          </span>
        </div>
      </div>

      <div className="my-3">
        <p
          className={`text-xs sm:text-sm leading-relaxed ${
            isLight ? 'text-slate-700 font-medium' : 'text-slate-300'
          }`}
        >
          {alert.description}
        </p>
      </div>

      <div
        className={`flex items-center justify-between pt-3 border-t text-xs ${
          isLight ? 'border-slate-100' : 'border-slate-800/80'
        }`}
      >
        <div
          className={`flex items-center gap-1.5 ${
            isLight ? 'text-slate-500' : 'text-slate-400'
          }`}
        >
          <Clock className="w-3.5 h-3.5 text-cyan-600" />
          <span className="font-mono text-[11px] font-bold">{alert.validity}</span>
        </div>

        {alert.coordinates && (
          <button
            type="button"
            onClick={() => setActiveTab('map')}
            data-testid={`alert-view-map-${alert.id}`}
            className={`px-3 py-1.5 rounded-lg border transition-all font-bold text-xs flex items-center gap-1 hover:scale-105 ${
              isLight
                ? 'bg-cyan-50 border-cyan-200 text-cyan-800 hover:bg-cyan-100'
                : 'bg-cyan-950 border-cyan-800 text-cyan-300 hover:bg-cyan-900'
            }`}
          >
            <span>View on Map</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
    </motion.div>
  );
};

export default AlertCard;
