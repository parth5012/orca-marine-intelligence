/**
 * Navbar (UI-MIG-T2)
 *
 * Owner: M-E (Frontend Chat & App Shell)
 * Module: frontend/components/layout/Navbar.tsx
 *
 * Adapted from source layout/Navbar (read-only). Differences from source:
 * - Language slot wired to LIVE LanguageSwitch (frontend/chat) via
 *   AppContext.selectedLanguage — no INDIAN_LANGUAGES mock list.
 * - GPS pill reads LIVE coords from AppContext.userLocation/gpsStatus
 *   (page-shell geolocation; Kochi fallback) — no fixture location.
 * - Alerts badge count reads LIVE AppContext.alertsList (empty until the
 *   alerts screen wires the feed) — no fixture alerts.
 * - SafetyBadge slot (LIVE, from page-shell safetyState) rendered beside
 *   the language switcher.
 * - Brand keeps id/data-testid "nav-brand-link" (href="/" alias → home tab).
 * - SIH26176 badge text preserved from the previous shell.
 */

'use client';

import React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import {
  Compass,
  MessageSquareText,
  Bell,
  User,
  Navigation,
  Waves,
  Radio,
  MapPin,
  Sun,
  Moon,
  ShieldCheck,
  Anchor,
} from 'lucide-react';
import { useApp, TabType } from '@/context/AppContext';
import LanguageSwitch from '@/chat/LanguageSwitch';
import { SafetyBadge } from '@/map';
import { SystemStatusBadge } from '@/components/common/SystemStatusBadge';

export interface NavbarSafety {
  waves_m?: number | null;
  wind_kts?: number | null;
  danger?: string;
  badge?: string;
}

interface NavbarProps {
  /** Live safety snapshot from the page shell (SSE-driven). */
  safety?: NavbarSafety;
}

export const Navbar: React.FC<NavbarProps> = ({ safety }) => {
  const {
    activeTab,
    setActiveTab,
    alertsList,
    userLocation,
    gpsStatus,
    themeMode,
    toggleThemeMode,
    t,
    userRole,
    loginAsOfficial,
    selectedLanguage,
    setSelectedLanguage,
  } = useApp();
  const router = useRouter();

  const isLight = themeMode === 'light';

  const navItems: {
    id: TabType;
    label: string;
    icon: React.ComponentType<{ className?: string }>;
  }[] = [
    { id: 'home', label: t('home'), icon: Waves },
    { id: 'map', label: t('exploreMap'), icon: Compass },
    { id: 'chat', label: t('askOrca'), icon: MessageSquareText },
    { id: 'alerts', label: t('alerts'), icon: Bell },
    { id: 'profile', label: t('profile'), icon: User },
  ];

  const redAlertsCount = alertsList.filter(
    (a) => String(a.severity).toUpperCase() === 'RED'
  ).length;

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
        <div className="flex items-center justify-between h-16">
          {/* Brand Logo & Tag — "/" route alias driving the home tab */}
          <Link
            href="/"
            id="nav-brand-link"
            data-testid="nav-brand-link"
            aria-label="ORCA Home"
            className="flex items-center gap-3 hover:opacity-95 transition-opacity"
            onClick={() => setActiveTab('home')}
          >
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-500 to-teal-600 flex items-center justify-center shadow-md shadow-cyan-500/20">
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

          {/* Desktop Navigation Links */}
          <nav
            className="hidden md:flex items-center space-x-1 lg:space-x-2 relative"
            aria-label="Primary"
          >
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = activeTab === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setActiveTab(item.id)}
                  aria-current={isActive ? 'page' : undefined}
                  className={`relative flex items-center gap-2 px-3.5 py-2 rounded-xl text-sm font-medium transition-colors ${
                    isActive
                      ? isLight
                        ? 'text-cyan-900 font-bold'
                        : 'text-cyan-300 font-bold'
                      : isLight
                        ? 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
                        : 'text-slate-300 hover:text-white hover:bg-slate-800/60'
                  }`}
                >
                  {isActive && (
                    <motion.div
                      layoutId="activeTabPill"
                      className={`absolute inset-0 rounded-xl ${
                        isLight
                          ? 'bg-cyan-100/90 border border-cyan-300 shadow-sm'
                          : 'bg-cyan-500/20 border border-cyan-500/40 shadow-inner'
                      }`}
                      transition={{ type: 'spring', stiffness: 380, damping: 30 }}
                    />
                  )}
                  <span className="relative z-10 flex items-center gap-2">
                    <Icon
                      className={`w-4 h-4 ${
                        isActive
                          ? isLight
                            ? 'text-cyan-700'
                            : 'text-cyan-400'
                          : isLight
                            ? 'text-slate-500'
                            : 'text-slate-400'
                      }`}
                    />
                    <span>{item.label}</span>
                    {item.id === 'alerts' && redAlertsCount > 0 && (
                      <span className="w-4 h-4 rounded-full bg-rose-500 text-white text-[10px] font-bold flex items-center justify-center animate-pulse">
                        {redAlertsCount}
                      </span>
                    )}
                  </span>
                </button>
              );
            })}
          </nav>

          {/* Right Section: GPS + Role Badge + Theme Toggle + Safety + Language */}
          <div className="flex items-center gap-2.5">
            {/* Official Access entry → /officer (additive, never blocks shell) */}
            <button
              type="button"
              data-testid="nav-official-access"
              onClick={() => {
                loginAsOfficial();
                router.push('/officer');
              }}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-[11px] font-extrabold transition-transform hover:scale-105 ${
                userRole === 'official'
                  ? isLight
                    ? 'bg-cyan-100 border-cyan-300 text-cyan-900'
                    : 'bg-cyan-950/80 border-cyan-700 text-cyan-300'
                  : isLight
                    ? 'bg-emerald-100 border-emerald-300 text-emerald-900'
                    : 'bg-emerald-950/80 border-emerald-700 text-emerald-300'
              }`}
              title="Open officer dashboard"
            >
              {userRole === 'official' ? (
                <>
                  <ShieldCheck className="w-3.5 h-3.5 text-cyan-400" />
                  <span>Official Access</span>
                </>
              ) : (
                <>
                  <Anchor className="w-3.5 h-3.5 text-emerald-400" />
                  <span>Public Access</span>
                </>
              )}
            </button>

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
          <SystemStatusBadge />

          {/* Theme Toggle Button */}
            <motion.button
              type="button"
              whileTap={{ scale: 0.9 }}
              onClick={toggleThemeMode}
              data-testid="theme-toggle"
              className={`p-2 rounded-xl border transition-all flex items-center justify-center ${
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

            {/* Live SafetyBadge slot (SSE-driven via page shell).
                Ticket #195: missing telemetry passes through as null so the
                badge reads UNKNOWN (amber), never a hardcoded SAFE. */}
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
};

export default Navbar;
