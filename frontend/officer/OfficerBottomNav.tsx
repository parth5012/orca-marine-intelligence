/**
 * Officer Mobile Navigation Dock (UI Parity #222, B4 Mobile Nav Decision).
 *
 * Owner: M-C shell
 * Module: frontend/officer/OfficerBottomNav.tsx
 *
 * DECISION: Reuse BottomNavigation pattern as a dedicated Officer navigation dock
 * on mobile (< md screens). Rather than overloading the sticky top bar with collapsed
 * menus, this dock anchors thumb-reach actions at the bottom of the screen:
 * - Jump to #gonogo (Decision)
 * - Jump to #register (Map & Register)
 * - Jump to #alerts (Alerts & Broadcasts)
 * - Jump to / (Fisherman Home)
 *
 * Guards scroll navigation with matchMedia('(prefers-reduced-motion: reduce)').
 */

'use client';

import React from 'react';
import Link from 'next/link';
import { Compass, ClipboardList, Bell, Home } from 'lucide-react';
import { useApp } from '@/context/AppContext';

interface OfficerBottomNavProps {
  gonogoEnabled?: boolean;
}

export const OfficerBottomNav: React.FC<OfficerBottomNavProps> = ({ gonogoEnabled = true }) => {
  const { themeMode } = useApp();
  const isLight = themeMode === 'light';

  const scrollToSection = (id: string) => {
    const el = document.getElementById(id);
    if (!el) return;
    const prefersReduced =
      typeof window !== 'undefined' &&
      window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;

    el.scrollIntoView({
      behavior: prefersReduced ? 'auto' : 'smooth',
      block: 'start',
    });
  };

  const itemClass =
    'flex flex-col items-center gap-1 px-2.5 py-1.5 rounded-xl transition-all text-xs font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500';

  return (
    <nav
      data-testid="officer-mobile-nav"
      aria-label="Officer Mobile Navigation"
      className="md:hidden fixed bottom-0 left-0 right-0 z-40 px-3 pb-3 pt-1 pointer-events-none"
    >
      <div
        className={`max-w-md mx-auto pointer-events-auto rounded-2xl p-2 flex items-center justify-around shadow-2xl backdrop-blur-xl border transition-colors ${
          isLight
            ? 'bg-white/95 border-cyan-200 text-slate-800 shadow-sky-900/10'
            : 'glass-panel bg-slate-950/95 border-cyan-500/30 text-slate-100 shadow-slate-950/90'
        }`}
      >
        {/* Decision / GoNoGo */}
        {gonogoEnabled && (
          <button
            type="button"
            data-testid="officer-nav-gonogo"
            aria-label="Jump to Go-No-Go decision"
            onClick={() => scrollToSection('gonogo')}
            className={`${itemClass} ${
              isLight
                ? 'text-slate-600 hover:text-cyan-800 hover:bg-cyan-50 active:bg-cyan-100'
                : 'text-slate-300 hover:text-cyan-300 hover:bg-cyan-950/40 active:bg-cyan-900/50'
            }`}
          >
            <Compass className="w-5 h-5 text-cyan-500" />
            <span className="text-[10px] font-semibold">Decision</span>
          </button>
        )}

        {/* Map & Register */}
        <button
          type="button"
          data-testid="officer-nav-register"
          aria-label="Jump to departure register"
          onClick={() => scrollToSection('register')}
          className={`${itemClass} ${
            isLight
              ? 'text-slate-600 hover:text-cyan-800 hover:bg-cyan-50 active:bg-cyan-100'
              : 'text-slate-300 hover:text-cyan-300 hover:bg-cyan-950/40 active:bg-cyan-900/50'
          }`}
        >
          <ClipboardList className="w-5 h-5 text-teal-500" />
          <span className="text-[10px] font-semibold">Register</span>
        </button>

        {/* Alerts & Broadcast */}
        <button
          type="button"
          data-testid="officer-nav-alerts"
          aria-label="Jump to alerts and broadcasts"
          onClick={() => scrollToSection('alerts')}
          className={`${itemClass} ${
            isLight
              ? 'text-slate-600 hover:text-cyan-800 hover:bg-cyan-50 active:bg-cyan-100'
              : 'text-slate-300 hover:text-cyan-300 hover:bg-cyan-950/40 active:bg-cyan-900/50'
          }`}
        >
          <Bell className="w-5 h-5 text-amber-500" />
          <span className="text-[10px] font-semibold">Alerts</span>
        </button>

        {/* Return to Fisherman Home */}
        <Link
          href="/"
          data-testid="officer-nav-home"
          aria-label="Return to fisherman home"
          className={`${itemClass} ${
            isLight
              ? 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
              : 'text-slate-300 hover:text-white hover:bg-slate-800'
          }`}
        >
          <Home className="w-5 h-5 text-slate-400" />
          <span className="text-[10px] font-semibold">Home</span>
        </Link>
      </div>
    </nav>
  );
};

export default OfficerBottomNav;
