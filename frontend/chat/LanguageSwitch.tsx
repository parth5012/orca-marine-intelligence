/**
 * LanguageSwitch Component
 *
 * Owner: M-E (Frontend Chat & App Shell) - Vernacular language selector
 * Module: frontend/chat/LanguageSwitch.tsx
 *
 * Supports Indian coastal languages with native scripts:
 * Malayalam (മലയാളം), Tamil (தமிழ்), Hindi (हिन्दी),
 * Telugu (తెలుగు), Gujarati (ગુજરાતી), Bengali (বাংলা),
 * Kannada (ಕನ್ನಡ), Marathi (मराठी), Odia (ଓଡ଼ିଆ), and English.
 * Persists user preference in localStorage.
 */

'use client';

import React, { useState, useEffect, useRef } from 'react';

export interface LanguageOption {
  code: string;
  name: string;
  native: string;
  region: string;
}

export const SUPPORTED_LANGUAGES: LanguageOption[] = [
  { code: 'en', name: 'English', native: 'English', region: 'Pan-India' },
  { code: 'ml', name: 'Malayalam', native: 'മലയാളം', region: 'Kerala & Lakshadweep' },
  { code: 'ta', name: 'Tamil', native: 'தமிழ்', region: 'Tamil Nadu & Puducherry' },
  { code: 'hi', name: 'Hindi', native: 'हिन्दी', region: 'Northern / Central' },
  { code: 'te', name: 'Telugu', native: 'తెలుగు', region: 'Andhra Pradesh & Telangana' },
  { code: 'gu', name: 'Gujarati', native: 'ગુજરાતી', region: 'Gujarat (Veraval / Porbandar)' },
  { code: 'bn', name: 'Bengali', native: 'বাংলা', region: 'West Bengal & Andaman' },
  { code: 'kn', name: 'Kannada', native: 'ಕನ್ನಡ', region: 'Karnataka (Mangalore)' },
  { code: 'mr', name: 'Marathi', native: 'मराठी', region: 'Maharashtra (Mumbai / Ratnagiri)' },
  { code: 'or', name: 'Odia', native: 'ଓଡ଼ିଆ', region: 'Odisha (Paradip / Puri)' },
];

export interface LanguageSwitchProps {
  currentLanguage?: string;
  onLanguageChange?: (lang: string) => void;
  compact?: boolean;
}

export default function LanguageSwitch({
  currentLanguage = 'en',
  onLanguageChange,
  compact = false,
}: LanguageSwitchProps) {
  const [selectedLang, setSelectedLang] = useState<string>(currentLanguage);
  const [isOpen, setIsOpen] = useState<boolean>(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Load from localStorage on mount
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('orca_language');
      if (saved && saved !== selectedLang) {
        setSelectedLang(saved);
        onLanguageChange?.(saved);
      }
    }
  }, []);

  // Sync if prop changes externally
  useEffect(() => {
    if (currentLanguage && currentLanguage !== selectedLang) {
      setSelectedLang(currentLanguage);
    }
  }, [currentLanguage]);

  // Click outside to close dropdown
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleSelect = (code: string) => {
    setSelectedLang(code);
    if (typeof window !== 'undefined') {
      localStorage.setItem('orca_language', code);
    }
    onLanguageChange?.(code);
    setIsOpen(false);
  };

  const currentOption =
    SUPPORTED_LANGUAGES.find((l) => l.code === selectedLang) || SUPPORTED_LANGUAGES[0];

  return (
    <div className="relative inline-block text-left" ref={dropdownRef}>
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-900/90 hover:bg-slate-800 border border-cyan-500/30 text-xs sm:text-sm font-medium text-cyan-200 transition-colors shadow-sm focus:outline-none focus:ring-1 focus:ring-cyan-400"
        title="Change Language"
        aria-label="Change Language"
      >
        <span className="text-base" role="img" aria-label="Globe">
          🌐
        </span>
        <span className="font-semibold text-white">{currentOption.native}</span>
        {!compact && (
          <span className="text-slate-400 hidden sm:inline">
            ({currentOption.name})
          </span>
        )}
        <svg
          className={`w-3.5 h-3.5 text-cyan-400 transition-transform ${
            isOpen ? 'rotate-180' : ''
          }`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth="2"
            d="M19 9l-7 7-7-7"
          />
        </svg>
      </button>

      {isOpen && (
        <div className="absolute right-0 mt-1.5 w-64 sm:w-72 rounded-xl bg-slate-900 border border-cyan-500/30 shadow-2xl z-50 overflow-hidden backdrop-blur-md">
          <div className="px-3 py-2 border-b border-slate-800 bg-slate-950/60">
            <p className="text-xs font-medium text-cyan-400 uppercase tracking-wider">
              Select Language / ഭാഷ / மொழி
            </p>
            <p className="text-[11px] text-slate-400">
              Bhashini Vernacular AI Voice & Text
            </p>
          </div>

          <div className="max-h-72 overflow-y-auto p-1.5 space-y-0.5">
            {SUPPORTED_LANGUAGES.map((lang) => {
              const isSelected = lang.code === selectedLang;
              return (
                <button
                  key={lang.code}
                  onClick={() => handleSelect(lang.code)}
                  className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-left text-xs sm:text-sm transition-colors ${
                    isSelected
                      ? 'bg-cyan-950/70 text-cyan-300 border border-cyan-500/40 font-semibold'
                      : 'text-slate-200 hover:bg-slate-800/80 hover:text-white'
                  }`}
                >
                  <div className="flex flex-col">
                    <span className="text-sm font-medium text-white">
                      {lang.native}
                    </span>
                    <span className="text-[11px] text-slate-400">
                      {lang.name} • <span className="text-slate-500">{lang.region}</span>
                    </span>
                  </div>
                  {isSelected && (
                    <span className="text-cyan-400 text-sm font-bold">✓</span>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
