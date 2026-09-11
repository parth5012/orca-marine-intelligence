/**
 * BottomNavigation (UI-MIG-T2)
 *
 * Owner: M-E (Frontend Chat & App Shell)
 * Module: frontend/components/layout/BottomNavigation.tsx
 *
 * Adapted from source layout/BottomNavigation (read-only):
 * - Alerts badge count reads LIVE AppContext.alertsList (no fixture data).
 * - Labels via AppContext.t() (no TRANSLATIONS mock import).
 * - Preserves previous-shell testids as aliases driving activeTab:
 *   mobile-tab-chat → chat, mobile-tab-map → map (with role="tab",
 *   aria-selected, aria-controls, aria-label carried over).
 */

'use client';

import React from 'react';
import { useApp } from '@/context/AppContext';
import { Waves, Compass, Mic, MessageSquareText, Bell } from 'lucide-react';

export const BottomNavigation: React.FC = () => {
  const {
    activeTab,
    setActiveTab,
    setVoiceModalOpen,
    alertsList,
    themeMode,
    t,
  } = useApp();
  const isLight = themeMode === 'light';

  const redAlertsCount = alertsList.filter(
    (a) => String(a.severity).toUpperCase() === 'RED'
  ).length;

  const itemClass = (id: string) =>
    `flex flex-col items-center gap-1 px-3 py-1.5 rounded-xl transition-all ${
      activeTab === id
        ? isLight
          ? 'text-cyan-800 font-bold bg-cyan-100'
          : 'text-cyan-300 font-bold bg-cyan-500/20'
        : isLight
          ? 'text-slate-500 hover:text-slate-900'
          : 'text-slate-400 hover:text-slate-200'
    }`;

  return (
    <div
      className="md:hidden fixed bottom-0 left-0 right-0 z-40 px-3 pb-3 pt-1 pointer-events-none"
      role="tablist"
      aria-label="Mobile Navigation"
    >
      <div
        className={`max-w-md mx-auto pointer-events-auto rounded-2xl p-2 flex items-center justify-around shadow-2xl backdrop-blur-xl border transition-colors ${
          isLight
            ? 'bg-white/95 border-cyan-200 text-slate-800 shadow-sky-900/10'
            : 'glass-panel bg-slate-950/95 border-cyan-500/30 text-slate-100 shadow-slate-950/90'
        }`}
      >
        {/* Home */}
        <button
          type="button"
          id="mobile-tab-home"
          data-testid="mobile-tab-home"
          role="tab"
          aria-selected={activeTab === 'home'}
          aria-label="Switch to Home Tab"
          onClick={() => setActiveTab('home')}
          className={itemClass('home')}
        >
          <Waves className="w-5 h-5" />
          <span className="text-[10px]">{t('home')}</span>
        </button>

        {/* Map — preserves previous-shell mobile-tab-map alias */}
        <button
          type="button"
          id="mobile-tab-map"
          data-testid="mobile-tab-map"
          role="tab"
          aria-selected={activeTab === 'map'}
          aria-controls="map-view-container"
          aria-label="Switch to Ocean Map Tab"
          onClick={() => setActiveTab('map')}
          className={itemClass('map')}
        >
          <Compass className="w-5 h-5" />
          <span className="text-[10px]">{t('exploreMap')}</span>
        </button>

        {/* Center Prominent Voice Button */}
        <div className="-mt-7 relative">
          <button
            type="button"
            onClick={() => setVoiceModalOpen(true)}
            data-testid="voice-mic-button"
            className="w-14 h-14 rounded-full bg-gradient-to-tr from-cyan-600 via-teal-500 to-cyan-400 text-white flex items-center justify-center shadow-lg shadow-cyan-600/40 hover:scale-105 active:scale-95 transition-transform border-4 border-white glow-mic"
            title="Ask ORCA by Voice"
            aria-label="Ask ORCA by Voice"
          >
            <Mic className="w-6 h-6 fill-white stroke-white" />
          </button>
        </div>

        {/* Chat — preserves previous-shell mobile-tab-chat alias */}
        <button
          type="button"
          id="mobile-tab-chat"
          data-testid="mobile-tab-chat"
          role="tab"
          aria-selected={activeTab === 'chat'}
          aria-controls="chat-panel-container"
          aria-label="Switch to Chat Advisory Tab"
          onClick={() => setActiveTab('chat')}
          className={itemClass('chat')}
        >
          <MessageSquareText className="w-5 h-5" />
          <span className="text-[10px]">{t('askOrca')}</span>
        </button>

        {/* Alerts */}
        <button
          type="button"
          id="mobile-tab-alerts"
          data-testid="mobile-tab-alerts"
          role="tab"
          aria-selected={activeTab === 'alerts'}
          aria-label="Switch to Alerts Tab"
          onClick={() => setActiveTab('alerts')}
          className={`relative ${itemClass('alerts')}`}
        >
          <Bell className="w-5 h-5" />
          <span className="text-[10px]">{t('alerts')}</span>
          {redAlertsCount > 0 && (
            <span className="absolute top-1 right-3 w-2.5 h-2.5 rounded-full bg-rose-500 animate-ping" />
          )}
        </button>
      </div>
    </div>
  );
};

export default BottomNavigation;
