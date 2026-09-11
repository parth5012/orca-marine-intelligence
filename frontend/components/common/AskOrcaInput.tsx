/**
 * AskOrcaInput (UI-MIG-T3)
 *
 * Owner: M-E (Frontend Chat & App Shell)
 * Module: frontend/components/common/AskOrcaInput.tsx
 *
 * Ported visuals from source design common/AskOrcaInput (READ-ONLY) —
 * hero banner + search form + suggested-question pills, both themes.
 *
 * Live-only rewiring (no mock data, no fake workflows):
 * - Submit (form or pill) calls `submitChatQuery(text)` from AppContext,
 *   which queues a pending query and switches to the chat tab.
 * - ChatPanel consumes the pending query and calls the real
 *   `sendMessage` (SSE `POST /api/chat`). Nothing is faked here.
 */

'use client';

import React, { useState } from 'react';
import { useApp } from '@/context/AppContext';
import { MapPin, ArrowRight, Sparkles, Search, Send } from 'lucide-react';

export const AskOrcaInput: React.FC = () => {
  const { submitChatQuery, userLocation, setActiveTab, themeMode, t } =
    useApp();
  const [inputText, setInputText] = useState('');
  const isLight = themeMode === 'light';

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputText.trim()) return;
    submitChatQuery(inputText);
    setInputText('');
  };

  const featuredQuery =
    'Kal subah fishing ke liye mere paas sabse safe aur suitable PFZ kaunsa hai?';

  const suggestedQuestions = [
    featuredQuery,
    t('suggestedQ1'),
    t('suggestedQ2'),
    t('suggestedQ3'),
  ];

  return (
    <div className="w-full max-w-4xl mx-auto my-4 space-y-3">
      {/* Prominent Text Query Banner */}
      <div
        onClick={() => setActiveTab('chat')}
        data-testid="ask-orca-banner"
        className={`p-3.5 rounded-2xl border flex items-center justify-between cursor-pointer transition-all hover:scale-[1.01] ${
          isLight
            ? 'bg-gradient-to-r from-sky-50 via-cyan-50 to-teal-50 border-cyan-300 text-slate-800 shadow-sm'
            : 'glass-panel bg-gradient-to-r from-cyan-950/80 via-slate-900 to-teal-950/60 border-cyan-500/40 text-white'
        }`}
      >
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-2xl bg-gradient-to-tr from-cyan-600 to-teal-600 text-white flex items-center justify-center shadow-md shadow-cyan-600/30 shrink-0">
            <Sparkles className="w-5 h-5 fill-white stroke-white animate-pulse" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span
                className={`font-extrabold text-xs sm:text-sm ${isLight ? 'text-slate-900' : 'text-white'}`}
              >
                Ask ORCA Anything About the Sea
              </span>
              <span
                className={`px-2 py-0.5 rounded text-[10px] font-bold border ${
                  isLight
                    ? 'bg-cyan-100 text-cyan-900 border-cyan-300'
                    : 'bg-cyan-950 text-cyan-300 border-cyan-800'
                }`}
              >
                Multi-Agent Reasoning Engine
              </span>
            </div>
            <p
              className={`text-xs font-medium mt-0.5 flex items-center gap-1 ${isLight ? 'text-slate-600' : 'text-slate-300'}`}
            >
              <span>Try asking:</span>
              <strong className="text-cyan-700 dark:text-cyan-300 italic">
                &quot;{featuredQuery}&quot;
              </strong>
            </p>
          </div>
        </div>

        <div className="hidden sm:flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-cyan-700 text-white font-bold text-xs shrink-0 shadow-sm">
          <span>Start Reasoning</span>
          <ArrowRight className="w-3.5 h-3.5" />
        </div>
      </div>

      {/* Main Search Input Form */}
      <form
        onSubmit={handleSubmit}
        className="relative"
        data-testid="ask-orca-form"
      >
        <div
          className={`relative flex items-center rounded-2xl p-2.5 shadow-xl transition-colors border ${
            isLight
              ? 'bg-white border-cyan-300 shadow-sky-900/10 hover:border-cyan-500'
              : 'glass-panel bg-slate-950/90 border-cyan-500/40 hover:border-cyan-400'
          }`}
        >
          {/* Left Search Icon */}
          <div className="pl-3 pr-2 shrink-0">
            <Search
              className={`w-5 h-5 ${isLight ? 'text-cyan-600' : 'text-cyan-400'}`}
            />
          </div>

          {/* Main Input Text */}
          <input
            type="text"
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            placeholder={t('searchPlaceholder')}
            aria-label="Ask ORCA"
            data-testid="ask-orca-input"
            className={`w-full bg-transparent text-sm sm:text-base focus:outline-none px-2 py-2 font-medium ${
              isLight
                ? 'text-slate-900 placeholder-slate-400'
                : 'text-slate-100 placeholder-slate-400'
            }`}
          />

          {/* Right Action Buttons */}
          <div className="flex items-center gap-2 pr-1 shrink-0">
            {/* Locate Me Button */}
            <button
              type="button"
              onClick={() => setActiveTab('map')}
              aria-label="Show my location on map"
              className={`p-2.5 rounded-xl border transition-colors ${
                isLight
                  ? 'bg-emerald-50 border-emerald-200 text-emerald-700 hover:bg-emerald-100'
                  : 'bg-slate-900 border-slate-800 text-slate-300 hover:text-cyan-300 hover:bg-slate-800'
              }`}
              title={`Current Location: ${userLocation.name}`}
            >
              <MapPin className="w-4 h-4 text-emerald-600" />
            </button>

            {/* Submit Button */}
            <button
              type="submit"
              disabled={!inputText.trim()}
              data-testid="ask-orca-submit"
              aria-label="Send query to ORCA chat"
              className="p-2.5 px-4 rounded-xl bg-gradient-to-r from-cyan-600 to-teal-600 text-white font-bold text-xs disabled:opacity-40 disabled:hover:scale-100 hover:scale-105 transition-transform flex items-center gap-1.5 shadow-md shadow-cyan-600/30"
            >
              <span>Ask</span>
              <Send className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </form>

      {/* Suggested Questions Pills */}
      <div className="flex items-center gap-2 overflow-x-auto pb-1 no-scrollbar text-xs">
        <span
          className={`text-[11px] font-semibold shrink-0 uppercase tracking-wider ${isLight ? 'text-slate-500' : 'text-slate-400'}`}
        >
          {t('suggestedHeader')}
        </span>
        {suggestedQuestions.map((q, idx) => (
          <button
            key={idx}
            type="button"
            onClick={() => submitChatQuery(q)}
            data-testid={`ask-orca-suggestion-${idx}`}
            className={`px-3 py-1.5 rounded-xl border transition-all shrink-0 font-medium whitespace-nowrap ${
              idx === 0
                ? isLight
                  ? 'bg-cyan-100 text-cyan-900 border-cyan-300 font-bold shadow-sm'
                  : 'bg-cyan-950 text-cyan-200 border-cyan-700 font-bold shadow-sm'
                : isLight
                  ? 'bg-white border-slate-200 text-slate-700 hover:bg-slate-100 hover:border-cyan-300'
                  : 'bg-slate-900/80 border-slate-800 text-slate-300 hover:text-white hover:border-cyan-500/40'
            }`}
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
};
