/**
 * Officer top bar: Navbar parity with sticky glass bar, brand block,
 * port selector grouped by state, active-pill role switcher, GPS pill,
 * theme toggle, and compact slots for SafetyBadge & LanguageSwitch.
 *
 * Owner: M-C shell (T3 #173, UI Parity #220)
 * Module: frontend/officer/OfficerTopBar.tsx
 */

'use client';

import React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { motion, useReducedMotion } from 'framer-motion';
import {
  Navigation,
  Radio,
  MapPin,
  Sun,
  Moon,
} from 'lucide-react';
import { useApp } from '@/context/AppContext';
import LanguageSwitch from '@/chat/LanguageSwitch';
import { SafetyBadge } from '@/map';
import { SystemStatusBadge } from '@/components/common/SystemStatusBadge';
import type { OfficerPort } from './ports';
import { groupPortsByState } from './ports';

export type OfficerRole = 'port' | 'watch';

export interface OfficerTopBarSafety {
  waves_m?: number | null;
  wind_kts?: number | null;
  danger?: string;
  badge?: string;
}

export interface OfficerTopBarProps {
  selectedPort: OfficerPort;
  role: OfficerRole;
  safety?: OfficerTopBarSafety;
}

export default function OfficerTopBar({ selectedPort, role, safety }: OfficerTopBarProps) {
  const router = useRouter();
  const {
    themeMode,
    toggleThemeMode,
    userLocation,
    gpsStatus,
    selectedLanguage,
    setSelectedLanguage,
    setActiveTab,
  } = useApp();

  const shouldReduceMotion = useReducedMotion();
  const isLight = themeMode === 'light';
  const groups = groupPortsByState();
  const watch = role === 'watch';

  const gpsText =
    gpsStatus === 'acquiring'
      ? 'Acquiring...'
      : `${userLocation.lat.toFixed(2)}°N, ${userLocation.lon.toFixed(2)}°E`;

  return (
    <header
      className={`sticky top-0 z-40 w-full backdrop-blur-md transition-colors ${
        isLight
          ? 'bg-white/90 border-b border-cyan-100 shadow-sm text-slate-800'
          : 'glass-panel border-b border-cyan-900/40 bg-slate-950/90 text-slate-100'
      }`}
    >
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex flex-wrap lg:flex-nowrap items-center justify-between min-h-16 py-2.5 lg:py-0 gap-3">
          {/* Brand Logo & Tag — persistent link back to fisherman home "/" */}
          <Link
            href="/"
            id="nav-brand-link"
            data-testid="nav-brand-link"
            aria-label="ORCA Home"
            className="flex items-center gap-3 hover:opacity-95 transition-opacity shrink-0 order-1 rounded-xl focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500 focus-visible:ring-offset-2"
            onClick={() => setActiveTab('home')}
          >
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-500 to-teal-600 flex items-center justify-center shadow-md shadow-cyan-500/20 shrink-0">
              <Navigation className="w-5 h-5 text-white rotate-45 stroke-[2.5]" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span
                  className={`font-extrabold text-xl tracking-wider ${
                    isLight
                      ? 'text-cyan-700'
                      : 'text-transparent bg-clip-text bg-gradient-to-r from-cyan-300 via-teal-200 to-emerald-400'
                  }`}
                >
                  ORCA
                </span>
                <span
                  className={`px-1.5 py-0.5 text-[10px] font-bold rounded ${
                    isLight
                      ? 'bg-cyan-100 text-cyan-800 border border-cyan-200'
                      : 'bg-cyan-950 text-cyan-400 border border-cyan-800'
                  }`}
                >
                  SIH26176
                </span>
                <span
                  className={`px-1.5 py-0.5 text-[10px] font-bold rounded tracking-wider ${
                    isLight
                      ? 'bg-amber-100 text-amber-900 border border-amber-300'
                      : 'bg-amber-950/80 text-amber-300 border border-amber-700/60'
                  }`}
                >
                  OFFICER
                </span>
              </div>
              <p
                className={`text-[10px] hidden sm:block font-medium tracking-tight ${
                  isLight ? 'text-slate-500' : 'text-slate-400'
                }`}
              >
                Agentic Marine Intelligence for Indian Fishermen
              </p>
            </div>
          </Link>

          {/* Port Selector + Role Switcher Controls */}
          <div className="flex items-center gap-2.5 order-3 lg:order-2 w-full lg:w-auto justify-between sm:justify-center shrink-0">
            <div className="relative">
              <label htmlFor="officer-port-select" className="sr-only">
                Port selector
              </label>
              <select
                id="officer-port-select"
                aria-label="Port selector"
                data-testid="officer-port-select"
                disabled={watch}
                value={watch ? '' : selectedPort.id}
                onChange={(e) => router.push(`/officer?role=port&port=${e.target.value}`)}
                className={`rounded-xl px-3 py-1.5 text-xs font-medium border transition-colors focus:outline-none focus:ring-2 focus:ring-cyan-500/40 focus-visible:ring-2 focus-visible:ring-cyan-500 disabled:opacity-50 disabled:cursor-not-allowed ${
                  isLight
                    ? 'bg-white border-slate-200 text-slate-800 hover:border-cyan-300 shadow-sm'
                    : 'bg-slate-900/90 border-slate-800 text-slate-100 hover:border-cyan-700/60'
                }`}
              >
                {watch && <option value="">All ports</option>}
                {groups.map((g) => (
                  <optgroup
                    key={g.state}
                    label={g.state}
                    className={isLight ? 'bg-white text-slate-900 font-semibold' : 'bg-slate-900 text-slate-100 font-semibold'}
                  >
                    {g.ports.map((p: OfficerPort) => (
                      <option
                        key={p.id}
                        value={p.id}
                        className={isLight ? 'bg-white text-slate-800' : 'bg-slate-900 text-slate-200'}
                      >
                        {p.name}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </div>

            <nav
              aria-label="Role switcher"
              className={`flex items-center p-1 rounded-xl border transition-colors ${
                isLight
                  ? 'bg-slate-100/90 border-slate-200'
                  : 'bg-slate-900/90 border-slate-800'
              }`}
            >
              <Link
                href={`/officer?role=port&port=${selectedPort.id}`}
                aria-current={watch ? undefined : 'page'}
                className={`relative px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500 focus-visible:ring-offset-1 ${
                  !watch
                    ? isLight
                      ? 'text-cyan-950 font-bold'
                      : 'text-cyan-200 font-bold'
                    : isLight
                      ? 'text-slate-600 hover:text-slate-900'
                      : 'text-slate-400 hover:text-white'
                }`}
              >
                {!watch && (
                  <motion.div
                    layoutId="officerRolePill"
                    className={`absolute inset-0 rounded-lg ${
                      isLight
                        ? 'bg-white border border-cyan-200 shadow-sm'
                        : 'bg-cyan-500/20 border border-cyan-500/40 shadow-inner'
                    }`}
                    transition={shouldReduceMotion ? { duration: 0 } : { type: 'spring', stiffness: 380, damping: 30 }}
                  />
                )}
                <span className="relative z-10">Port</span>
              </Link>
              <Link
                href="/officer?role=watch"
                aria-current={watch ? 'page' : undefined}
                className={`relative px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500 focus-visible:ring-offset-1 ${
                  watch
                    ? isLight
                      ? 'text-cyan-950 font-bold'
                      : 'text-cyan-200 font-bold'
                    : isLight
                      ? 'text-slate-600 hover:text-slate-900'
                      : 'text-slate-400 hover:text-white'
                }`}
              >
                {watch && (
                  <motion.div
                    layoutId="officerRolePill"
                    className={`absolute inset-0 rounded-lg ${
                      isLight
                        ? 'bg-white border border-cyan-200 shadow-sm'
                        : 'bg-cyan-500/20 border border-cyan-500/40 shadow-inner'
                    }`}
                    transition={shouldReduceMotion ? { duration: 0 } : { type: 'spring', stiffness: 380, damping: 30 }}
                  />
                )}
                <span className="relative z-10">Watch</span>
              </Link>
            </nav>
          </div>

          {/* Right Controls: GPS + Status + Theme Toggle + SafetyBadge + Language */}
          <div className="flex items-center gap-2 sm:gap-2.5 order-2 lg:order-3 ml-auto lg:ml-0 shrink-0">
            {/* GPS Live Indicator */}
            <div
              data-testid="gps-pill"
              role="status"
              aria-label={`GPS position: ${gpsText}`}
              title={userLocation.name}
              className={`hidden lg:flex items-center gap-2 px-3 py-1.5 rounded-full border text-xs ${
                isLight
                  ? 'bg-emerald-50 border-emerald-200 text-emerald-800'
                  : 'bg-emerald-950/40 border-emerald-500/30 text-emerald-300'
              }`}
            >
              <Radio className="w-3.5 h-3.5 text-emerald-500 animate-pulse" />
              <MapPin className="w-3.5 h-3.5 text-emerald-500" />
              <span className="font-mono font-semibold text-[11px]">{gpsText}</span>
            </div>

            {/* Live System Health Status Poller */}
            <div className="hidden sm:inline-flex">
              <SystemStatusBadge />
            </div>

            {/* Theme Toggle Button */}
            <motion.button
              type="button"
              whileTap={{ scale: 0.9 }}
              onClick={toggleThemeMode}
              data-testid="theme-toggle"
              className={`p-2 rounded-xl border transition-all flex items-center justify-center focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500 focus-visible:ring-offset-2 ${
                isLight
                  ? 'bg-slate-100 border-slate-200 text-slate-700 hover:bg-slate-200'
                  : 'bg-slate-900 border-slate-800 text-amber-300 hover:bg-slate-800'
              }`}
              title={`Switch to ${isLight ? 'Dark' : 'Light'} Mode`}
              aria-label={`Switch to ${isLight ? 'Dark' : 'Light'} Mode`}
            >
              {isLight ? (
                <Moon className="w-4 h-4 text-slate-700" />
              ) : (
                <Sun className="w-4 h-4 text-amber-400" />
              )}
            </motion.button>

            {/* Live SafetyBadge compact slot */}
            {safety && (
              <SafetyBadge
                waves={safety.waves_m ?? null}
                wind={safety.wind_kts ?? null}
                danger={safety.danger ?? 'unknown'}
                badge={safety.badge ?? 'amber'}
                language={selectedLanguage}
                compact
              />
            )}

            {/* Live Language slot */}
            <LanguageSwitch
              currentLanguage={selectedLanguage}
              onLanguageChange={setSelectedLanguage}
              compact
            />
          </div>
        </div>
      </div>
    </header>
  );
}
