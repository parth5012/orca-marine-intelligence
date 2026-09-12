/**
 * ProfileScreen (UI-MIG-T7)
 *
 * Owner: M-E (Frontend Chat & App Shell)
 * Module: frontend/components/screens/ProfileScreen.tsx
 *
 * Ported layout from source design `screens/ProfileScreen` (READ-ONLY).
 * Live-only: identity stays static via AppContext passthrough (never blocks);
 * preferences persist locally (`orca_profile` in localStorage). Language
 * reuses INDIAN_LANGUAGES from `frontend/lib/translations.ts` (same
 * selectedLanguage + orca_language as the rest of the shell). Role switch is
 * the AppContext passthrough (no reload, no login wall).
 */

'use client';

import React, { useEffect, useState } from 'react';
import { useApp } from '@/context/AppContext';
import { INDIAN_LANGUAGES } from '@/lib/translations';
import { LanguageSelector } from '@/components/common/LanguageSelector';
import {
  Anchor,
  Globe,
  Bell,
  Sliders,
  ShieldAlert,
  Save,
  CheckCircle2,
  ShieldCheck,
  RefreshCw,
} from 'lucide-react';

const PROFILE_STORAGE_KEY = 'orca_profile';

interface StoredProfile {
  landingPort: string;
  vesselName: string;
  regNo: string;
  speedUnit: 'knots' | 'kmh';
  distUnit: 'nm' | 'km';
  smsAlerts: boolean;
  audioAlarms: boolean;
  offlineCache: boolean;
  ttsVoice: 'male' | 'female';
}

const DEFAULT_PROFILE: StoredProfile = {
  landingPort: 'Kochi Harbor, Kerala',
  vesselName: 'MFV Sea Star',
  regNo: 'IND-KL-04-MM-1234',
  speedUnit: 'kmh',
  distUnit: 'km',
  smsAlerts: true,
  audioAlarms: true,
  offlineCache: true,
  ttsVoice: 'male',
};

function readStoredProfile(): StoredProfile {
  if (typeof window === 'undefined') return DEFAULT_PROFILE;
  try {
    const raw = localStorage.getItem(PROFILE_STORAGE_KEY);
    if (!raw) return DEFAULT_PROFILE;
    const parsed = JSON.parse(raw) as Partial<StoredProfile>;
    return {
      landingPort:
        typeof parsed.landingPort === 'string'
          ? parsed.landingPort
          : DEFAULT_PROFILE.landingPort,
      vesselName:
        typeof parsed.vesselName === 'string'
          ? parsed.vesselName
          : DEFAULT_PROFILE.vesselName,
      regNo:
        typeof parsed.regNo === 'string' ? parsed.regNo : DEFAULT_PROFILE.regNo,
      speedUnit: parsed.speedUnit === 'knots' ? 'knots' : 'kmh',
      distUnit: parsed.distUnit === 'nm' ? 'nm' : 'km',
      smsAlerts: parsed.smsAlerts ?? true,
      audioAlarms: parsed.audioAlarms ?? true,
      offlineCache: parsed.offlineCache ?? true,
      ttsVoice: parsed.ttsVoice === 'female' ? 'female' : 'male',
    };
  } catch {
    return DEFAULT_PROFILE;
  }
}

export const ProfileScreen: React.FC = () => {
  const {
    selectedLanguage,
    setSelectedLanguage,
    userLocation,
    gpsStatus,
    themeMode,
    toggleThemeMode,
    t,
    userRole,
    userProfile,
    logoutOrSwitchRole,
  } = useApp();
  const isLight = themeMode === 'light';

  const [stored, setStored] = useState<StoredProfile>(DEFAULT_PROFILE);
  const [hydrated, setHydrated] = useState(false);
  const [savedMsg, setSavedMsg] = useState(false);
  const [sosTriggered, setSosTriggered] = useState(false);

  useEffect(() => {
    setStored(readStoredProfile());
    setHydrated(true);
  }, []);

  const update = (patch: Partial<StoredProfile>) =>
    setStored((prev) => ({ ...prev, ...patch }));

  const handleSave = () => {
    try {
      localStorage.setItem(PROFILE_STORAGE_KEY, JSON.stringify(stored));
      setSavedMsg(true);
      setTimeout(() => setSavedMsg(false), 3000);
    } catch {
      /* storage unavailable — no success confirmation */
    }
  };

  const handleSOS = () => {
    setSosTriggered(true);
    setTimeout(() => setSosTriggered(false), 5000);
  };

  return (
    <div data-testid="tab-panel-profile" className="max-w-4xl mx-auto space-y-6 pb-16">
      {/* Header Banner */}
      <div
        className={`rounded-3xl p-6 sm:p-8 border flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 transition-all ${
          isLight
            ? 'bg-white border-slate-200 shadow-sm text-slate-900'
            : 'glass-panel border-cyan-500/30 bg-gradient-to-r from-slate-950 via-slate-900 to-cyan-950/40 text-white shadow-2xl'
        }`}
      >
        <div className="flex items-center gap-4">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-cyan-400 to-teal-600 flex items-center justify-center text-slate-950 font-black text-2xl shadow-xl shadow-cyan-950/60 shrink-0">
            {userRole === 'official' ? 'CO' : 'FE'}
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h1
                className={`text-xl sm:text-2xl font-extrabold ${
                  isLight ? 'text-slate-900' : 'text-white'
                }`}
              >
                {userProfile.name}
              </h1>
              <span
                className={`px-2 py-0.5 rounded text-[10px] font-extrabold flex items-center gap-1 ${
                  userRole === 'official'
                    ? 'bg-cyan-950 text-cyan-300 border border-cyan-800'
                    : 'bg-emerald-950 text-emerald-300 border border-emerald-800'
                }`}
              >
                {userRole === 'official' ? (
                  <ShieldCheck className="w-3 h-3 text-cyan-400" />
                ) : (
                  <Anchor className="w-3 h-3 text-emerald-400" />
                )}
                {userProfile.roleTitle}
              </span>
            </div>
            {userRole === 'official' ? (
              <p className={`text-xs mt-1 font-medium flex items-center gap-2 ${isLight ? 'text-slate-700' : 'text-slate-300'}`}>
                <span>Org: {userProfile.org || 'INCOIS Coastal Command'}</span>
                <span>•</span>
                <span>ID: {userProfile.email}</span>
              </p>
            ) : (
              <p className={`text-xs mt-0.5 flex items-center gap-2 font-medium ${isLight ? 'text-slate-700' : 'text-slate-300'}`}>
                <span>Vessel: {hydrated ? stored.vesselName : DEFAULT_PROFILE.vesselName}</span>
                <span>•</span>
                <span>Reg: {hydrated ? stored.regNo : DEFAULT_PROFILE.regNo}</span>
              </p>
            )}
            <p className={`text-xs mt-1 flex items-center gap-1 font-semibold ${isLight ? 'text-cyan-700' : 'text-cyan-300'}`}>
              <Anchor className="w-3.5 h-3.5" />
              {hydrated ? stored.landingPort : DEFAULT_PROFILE.landingPort}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <button
            type="button"
            onClick={logoutOrSwitchRole}
            data-testid="profile-switch-role"
            className={`px-3.5 py-2.5 rounded-2xl font-extrabold text-xs border transition-all flex items-center gap-1.5 ${
              isLight
                ? 'bg-slate-50 border-slate-300 text-cyan-700 hover:bg-slate-100 shadow-sm'
                : 'bg-slate-900 border-slate-700 text-cyan-300 hover:bg-slate-800'
            }`}
            title="Switch Access Role"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>Switch Role</span>
          </button>

          <button
            type="button"
            onClick={handleSOS}
            data-testid="profile-sos"
            className={`px-4 py-2.5 rounded-2xl font-extrabold text-xs shadow-xl flex items-center gap-2 transition-all ${
              sosTriggered
                ? 'bg-rose-600 text-white animate-pulse'
                : isLight
                ? 'bg-rose-50 border border-rose-300 text-rose-700 hover:bg-rose-100'
                : 'bg-rose-500/20 border border-rose-500/50 text-rose-300 hover:bg-rose-500/30'
            }`}
          >
            <ShieldAlert className="w-4 h-4 text-rose-400" />
            <span>{sosTriggered ? 'SOS DISTRESS SIGNAL SENT!' : t('emergencySos')}</span>
          </button>
        </div>
      </div>

      {savedMsg && (
        <div
          data-testid="profile-saved"
          className={`p-3 rounded-xl border text-xs font-bold flex items-center gap-2 animate-fade-in ${
            isLight
              ? 'bg-emerald-50 border-emerald-300 text-emerald-900 shadow-sm'
              : 'bg-emerald-950/80 border-emerald-500/40 text-emerald-200'
          }`}
        >
          <CheckCircle2 className="w-4 h-4 text-emerald-400" />
          <span>Settings saved successfully!</span>
        </div>
      )}

      {/* Language & Voice AI Settings (Bhashini) */}
      <div
        className={`rounded-2xl p-5 border space-y-4 transition-colors ${
          isLight
            ? 'bg-white border-slate-200 shadow-sm text-slate-900'
            : 'glass-panel border-slate-800 bg-slate-950/80 text-white'
        }`}
      >
        <div
          className={`flex items-center gap-2 font-bold text-base pb-3 border-b ${
            isLight ? 'text-slate-900 border-slate-100' : 'text-white border-slate-800'
          }`}
        >
          <Globe className="w-5 h-5 text-cyan-600" />
          <span>Bhashini Multi-Language & Voice Assistant Settings</span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
          <div>
            <label
              className={`block font-semibold mb-1.5 ${
                isLight ? 'text-slate-700' : 'text-slate-300'
              }`}
            >
              Primary Language (10 Indian Languages Supported):
            </label>
            <select
              value={selectedLanguage}
              onChange={(e) => setSelectedLanguage(e.target.value)}
              data-testid="profile-language-select"
              className={`w-full rounded-xl p-2.5 font-medium border focus:outline-none ${
                isLight
                  ? 'bg-slate-50 border-cyan-300 text-cyan-900'
                  : 'bg-slate-900 border-cyan-800 text-cyan-200'
              }`}
            >
              {INDIAN_LANGUAGES.map((l) => (
                <option key={l.code} value={l.code}>
                  {l.flag} {l.nativeName} - {l.name}
                </option>
              ))}
            </select>
            <div className="mt-2">
              <LanguageSelector />
            </div>
          </div>

          <div>
            <label
              className={`block font-semibold mb-1.5 ${
                isLight ? 'text-slate-700' : 'text-slate-300'
              }`}
            >
              Bhashini Speech Synthesis (TTS Voice Gender):
            </label>
            <select
              value={hydrated ? stored.ttsVoice : DEFAULT_PROFILE.ttsVoice}
              onChange={(e) =>
                update({ ttsVoice: e.target.value === 'female' ? 'female' : 'male' })
              }
              data-testid="profile-tts-voice"
              className={`w-full rounded-xl p-2.5 font-medium border focus:outline-none ${
                isLight
                  ? 'bg-slate-50 border-slate-200 text-slate-800'
                  : 'bg-slate-900 border-slate-800 text-slate-200'
              }`}
            >
              <option value="male">Male Voice (Natural Indian Accent)</option>
              <option value="female">Female Voice (Clear Audio Output)</option>
            </select>
          </div>
        </div>
      </div>

      {/* Landing Centre & Location Configuration */}
      <div
        className={`rounded-2xl p-5 border space-y-4 transition-colors ${
          isLight
            ? 'bg-white border-slate-200 shadow-sm text-slate-900'
            : 'glass-panel border-slate-800 bg-slate-950/80 text-white'
        }`}
      >
        <div
          className={`flex items-center gap-2 font-bold text-base pb-3 border-b ${
            isLight ? 'text-slate-900 border-slate-100' : 'text-white border-slate-800'
          }`}
        >
          <Anchor className="w-5 h-5 text-teal-400" />
          <span>Home Landing Centre & Base Port</span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
          <div>
            <label
              className={`block font-semibold mb-1.5 ${
                isLight ? 'text-slate-700' : 'text-slate-300'
              }`}
            >
              Saved Home Fishing Harbor:
            </label>
            <select
              value={stored.landingPort}
              onChange={(e) => update({ landingPort: e.target.value })}
              data-testid="profile-landing-port"
              className={`w-full rounded-xl p-2.5 font-medium focus:outline-none border ${
                isLight
                  ? 'bg-slate-50 border-slate-200 text-slate-800'
                  : 'bg-slate-900 border-slate-800 text-slate-200'
              }`}
            >
              <option value="Veraval Fishing Harbor, Gujarat">
                Veraval Fishing Harbor, Gujarat
              </option>
              <option value="Kochi Harbor, Kerala">Kochi Harbor, Kerala</option>
              <option value="Visakhapatnam Fishing Port, Andhra Pradesh">
                Visakhapatnam Fishing Port, Andhra Pradesh
              </option>
              <option value="Paradeep Harbor, Odisha">Paradeep Harbor, Odisha</option>
              <option value="Chennai Kasimedu Fishing Harbor, Tamil Nadu">
                Chennai Kasimedu Fishing Harbor, Tamil Nadu
              </option>
            </select>
          </div>

          <div>
            <label
              className={`block font-semibold mb-1.5 ${
                isLight ? 'text-slate-700' : 'text-slate-300'
              }`}
            >
              GPS Position Precision:
            </label>
            <div
              className={`p-2.5 rounded-xl border flex items-center justify-between font-mono text-xs ${
                isLight
                  ? 'bg-slate-50 border-slate-200 text-cyan-800'
                  : 'bg-slate-900 border-slate-800 text-cyan-300'
              }`}
            >
              <span data-testid="profile-gps-coords">
                {userLocation.lat.toFixed(2)}, {userLocation.lon.toFixed(2)}
              </span>
              <span
                data-testid="profile-gps-status"
                className={
                  gpsStatus === 'locked'
                    ? 'text-emerald-400 font-bold'
                    : gpsStatus === 'acquiring'
                      ? 'text-amber-400 font-bold'
                      : 'text-slate-400 font-bold'
                }
              >
                {gpsStatus === 'locked'
                  ? 'LOCKED'
                  : gpsStatus === 'acquiring'
                    ? 'ACQUIRING…'
                    : 'ESTIMATE'}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Measurement Units & Preferences */}
      <div
        className={`rounded-2xl p-5 border space-y-4 transition-colors ${
          isLight
            ? 'bg-white border-slate-200 shadow-sm text-slate-900'
            : 'glass-panel border-slate-800 bg-slate-950/80 text-white'
        }`}
      >
        <div
          className={`flex items-center gap-2 font-bold text-base pb-3 border-b ${
            isLight ? 'text-slate-900 border-slate-100' : 'text-white border-slate-800'
          }`}
        >
          <Sliders className="w-5 h-5 text-amber-400" />
          <span>Navigation Unit Preferences</span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
          <div
            className={`flex items-center justify-between p-3 rounded-xl border ${
              isLight ? 'bg-slate-50 border-slate-200' : 'bg-slate-900 border-slate-800'
            }`}
          >
            <span
              className={`font-semibold ${
                isLight ? 'text-slate-700' : 'text-slate-300'
              }`}
            >
              Speed Unit:
            </span>
            <div
              className={`flex items-center gap-1 p-1 rounded-lg border ${
                isLight
                  ? 'bg-slate-200/70 border-slate-300'
                  : 'bg-slate-950 border-slate-800'
              }`}
            >
              <button
                type="button"
                onClick={() => update({ speedUnit: 'kmh' })}
                data-testid="profile-speed-kmh"
                className={`px-3 py-1 rounded text-[11px] font-bold ${
                  stored.speedUnit === 'kmh'
                    ? 'bg-cyan-500 text-slate-950'
                    : isLight
                    ? 'text-slate-600'
                    : 'text-slate-400'
                }`}
              >
                km/h
              </button>
              <button
                type="button"
                onClick={() => update({ speedUnit: 'knots' })}
                data-testid="profile-speed-knots"
                className={`px-3 py-1 rounded text-[11px] font-bold ${
                  stored.speedUnit === 'knots'
                    ? 'bg-cyan-500 text-slate-950'
                    : isLight
                    ? 'text-slate-600'
                    : 'text-slate-400'
                }`}
              >
                Knots
              </button>
            </div>
          </div>

          <div
            className={`flex items-center justify-between p-3 rounded-xl border ${
              isLight ? 'bg-slate-50 border-slate-200' : 'bg-slate-900 border-slate-800'
            }`}
          >
            <span
              className={`font-semibold ${
                isLight ? 'text-slate-700' : 'text-slate-300'
              }`}
            >
              Distance Unit:
            </span>
            <div
              className={`flex items-center gap-1 p-1 rounded-lg border ${
                isLight
                  ? 'bg-slate-200/70 border-slate-300'
                  : 'bg-slate-950 border-slate-800'
              }`}
            >
              <button
                type="button"
                onClick={() => update({ distUnit: 'km' })}
                data-testid="profile-dist-km"
                className={`px-3 py-1 rounded text-[11px] font-bold ${
                  stored.distUnit === 'km'
                    ? 'bg-cyan-500 text-slate-950'
                    : isLight
                    ? 'text-slate-600'
                    : 'text-slate-400'
                }`}
              >
                Kilometers
              </button>
              <button
                type="button"
                onClick={() => update({ distUnit: 'nm' })}
                data-testid="profile-dist-nm"
                className={`px-3 py-1 rounded text-[11px] font-bold ${
                  stored.distUnit === 'nm'
                    ? 'bg-cyan-500 text-slate-950'
                    : isLight
                    ? 'text-slate-600'
                    : 'text-slate-400'
                }`}
              >
                Nautical Miles
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Safety & Notifications Toggles */}
      <div
        className={`rounded-2xl p-5 border space-y-4 transition-colors ${
          isLight
            ? 'bg-white border-slate-200 shadow-sm text-slate-900'
            : 'glass-panel border-slate-800 bg-slate-950/80 text-white'
        }`}
      >
        <div
          className={`flex items-center gap-2 font-bold text-base pb-3 border-b ${
            isLight ? 'text-slate-900 border-slate-100' : 'text-white border-slate-800'
          }`}
        >
          <Bell className="w-5 h-5 text-rose-400" />
          <span>Safety Broadcast & Audio Alerts</span>
        </div>

        <div className="space-y-3 text-xs">
          <div
            className={`flex items-center justify-between p-3 rounded-xl border ${
              isLight ? 'bg-slate-50 border-slate-200' : 'bg-slate-900 border-slate-800'
            }`}
          >
            <div>
              <div
                className={`font-semibold ${
                  isLight ? 'text-slate-800' : 'text-white'
                }`}
              >
                Emergency SMS Safety Broadcasts
              </div>
              <div
                className={`text-[11px] ${
                  isLight ? 'text-slate-600' : 'text-slate-400'
                }`}
              >
                Receive instant SMS cyclone & high wave warnings without internet
              </div>
            </div>
            <input
              type="checkbox"
              checked={stored.smsAlerts}
              onChange={(e) => update({ smsAlerts: e.target.checked })}
              data-testid="profile-sms-alerts"
              className="w-5 h-5 accent-cyan-500"
            />
          </div>

          <div
            className={`flex items-center justify-between p-3 rounded-xl border ${
              isLight ? 'bg-slate-50 border-slate-200' : 'bg-slate-900 border-slate-800'
            }`}
          >
            <div>
              <div
                className={`font-semibold ${
                  isLight ? 'text-slate-800' : 'text-white'
                }`}
              >
                Loud Audio Horn Alarm Red Alerts
              </div>
              <div
                className={`text-[11px] ${
                  isLight ? 'text-slate-600' : 'text-slate-400'
                }`}
              >
                Play siren alarm sound when vessel enters danger restricted zone
              </div>
            </div>
            <input
              type="checkbox"
              checked={stored.audioAlarms}
              onChange={(e) => update({ audioAlarms: e.target.checked })}
              data-testid="profile-audio-alarms"
              className="w-5 h-5 accent-cyan-500"
            />
          </div>

          <div
            className={`flex items-center justify-between p-3 rounded-xl border ${
              isLight ? 'bg-slate-50 border-slate-200' : 'bg-slate-900 border-slate-800'
            }`}
          >
            <div>
              <div
                className={`font-semibold ${
                  isLight ? 'text-slate-800' : 'text-white'
                }`}
              >
                Offline Marine Tile Caching
              </div>
              <div
                className={`text-[11px] ${
                  isLight ? 'text-slate-600' : 'text-slate-400'
                }`}
              >
                Keep offline marine maps & PFZ data saved locally deep sea voyages
              </div>
            </div>
            <input
              type="checkbox"
              checked={stored.offlineCache}
              onChange={(e) => update({ offlineCache: e.target.checked })}
              data-testid="profile-offline-cache"
              className="w-5 h-5 accent-cyan-500"
            />
          </div>
        </div>
      </div>

      {/* Save Settings Button */}
      <div className="pt-2 flex flex-col gap-2">
        <button
          type="button"
          onClick={handleSave}
          data-testid="profile-save"
          className="w-full py-3.5 rounded-2xl bg-gradient-to-r from-cyan-400 via-teal-400 to-emerald-400 text-slate-950 font-extrabold text-sm shadow-xl shadow-cyan-500/20 hover:scale-[1.01] transition-transform flex items-center justify-center gap-2"
        >
          <Save className="w-5 h-5 stroke-[2.5]" />
          <span>{t('savePreferences')}</span>
        </button>
        <button
          type="button"
          onClick={toggleThemeMode}
          data-testid="theme-toggle-profile"
          className="w-full py-2.5 rounded-2xl border border-cyan-500/40 text-sm font-bold hover:bg-cyan-50 dark:hover:bg-slate-800 transition-colors"
        >
          Toggle theme
        </button>
      </div>
    </div>
  );
};

export default ProfileScreen;
