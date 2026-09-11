/**
 * LanguageSelector (UI-MIG-T7)
 *
 * Owner: M-E (Frontend Chat & App Shell)
 * Module: frontend/components/common/LanguageSelector.tsx
 *
 * Ported dropdown from source design `common/LanguageSelector` (READ-ONLY).
 * Live-only: reads/writes the SAME selectedLanguage + localStorage
 * `orca_language` owned by AppContext (reuses INDIAN_LANGUAGES from
 * `frontend/lib/translations.ts` — no duplicate list). Bhashini ULCA flow
 * (`frontend/chat/bhashini.ts`) is untouched; this only switches UI locale.
 */

'use client';

import React, { useState } from 'react';
import { useApp } from '@/context/AppContext';
import { INDIAN_LANGUAGES } from '@/lib/translations';
import { Globe, ChevronDown, Check } from 'lucide-react';

export const LanguageSelector: React.FC = () => {
  const { selectedLanguage, setSelectedLanguage, themeMode } = useApp();
  const [isOpen, setIsOpen] = useState(false);
  const isLight = themeMode === 'light';

  const currentLang =
    INDIAN_LANGUAGES.find((l) => l.code === selectedLanguage) ||
    INDIAN_LANGUAGES[0];

  return (
    <div className="relative" data-testid="language-selector">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        data-testid="language-selector-toggle"
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border transition-all text-xs sm:text-sm font-medium focus:outline-none ${
          isLight
            ? 'bg-slate-100/90 border-slate-200 text-slate-800 hover:bg-slate-200/80'
            : 'bg-slate-900/80 border-cyan-500/30 text-cyan-200 hover:bg-slate-800'
        }`}
        title="Select Language (Bhashini AI Support)"
      >
        <Globe
          className={`w-4 h-4 shrink-0 ${isLight ? 'text-cyan-700' : 'text-cyan-400'}`}
        />
        <span className="hidden sm:inline font-semibold">{currentLang.nativeName}</span>
        <span className="sm:hidden font-semibold uppercase">{currentLang.code}</span>
        <span className={`text-xs ${isLight ? 'text-slate-500' : 'text-slate-400'}`}>
          ({currentLang.code.toUpperCase()})
        </span>
        <ChevronDown
          className={`w-3.5 h-3.5 transition-transform ${
            isLight ? 'text-cyan-700' : 'text-cyan-400'
          } ${isOpen ? 'rotate-180' : ''}`}
        />
      </button>

      {isOpen && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setIsOpen(false)} />
          <div
            role="listbox"
            aria-label="Select language"
            className={`absolute right-0 mt-2 w-56 rounded-xl border shadow-xl z-50 py-2 max-h-80 overflow-y-auto ${
              isLight
                ? 'bg-white border-slate-200 text-slate-800 shadow-slate-900/10'
                : 'glass-panel bg-slate-950/95 border-cyan-500/30 text-slate-100 shadow-cyan-950/40'
            }`}
          >
            <div
              className={`px-3 py-1.5 text-[11px] font-bold tracking-wider uppercase border-b mb-1 flex justify-between items-center ${
                isLight ? 'text-cyan-800 border-slate-100' : 'text-cyan-400/80 border-slate-800'
              }`}
            >
              <span>Bhashini Voice AI</span>
              <span
                className={`text-[10px] px-1.5 py-0.5 rounded border ${
                  isLight
                    ? 'bg-cyan-50 text-cyan-800 border-cyan-200'
                    : 'bg-cyan-950 text-cyan-300 border-cyan-800'
                }`}
              >
                10 Languages
              </span>
            </div>

            {INDIAN_LANGUAGES.map((lang) => {
              const isSelected = lang.code === selectedLanguage;
              return (
                <button
                  key={lang.code}
                  type="button"
                  role="option"
                  aria-selected={isSelected}
                  onClick={() => {
                    setSelectedLanguage(lang.code);
                    setIsOpen(false);
                  }}
                  data-testid={`language-option-${lang.code}`}
                  className={`w-full text-left px-3.5 py-2 flex items-center justify-between text-sm transition-colors ${
                    isSelected
                      ? isLight
                        ? 'bg-cyan-50 text-cyan-900 font-semibold'
                        : 'bg-cyan-500/20 text-cyan-300 font-semibold'
                      : isLight
                      ? 'text-slate-700 hover:bg-slate-100 hover:text-slate-900'
                      : 'text-slate-300 hover:bg-slate-800/80 hover:text-white'
                  }`}
                >
                  <div className="flex items-center gap-2.5">
                    <span className="text-base">{lang.flag}</span>
                    <div>
                      <div className="font-medium leading-tight">{lang.nativeName}</div>
                      <div
                        className={`text-[11px] leading-tight ${
                          isLight ? 'text-slate-500' : 'text-slate-400'
                        }`}
                      >
                        {lang.name}
                      </div>
                    </div>
                  </div>
                  {isSelected && (
                    <Check className={`w-4 h-4 ${isLight ? 'text-cyan-700' : 'text-cyan-400'}`} />
                  )}
                </button>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
};

export default LanguageSelector;
