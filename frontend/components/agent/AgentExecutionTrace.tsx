/**
 * AgentExecutionTrace (UI-MIG-T4)
 *
 * Owner: M-E (Frontend Chat & App Shell)
 * Module: frontend/components/agent/AgentExecutionTrace.tsx
 *
 * Visual port of the source design trace (READ-ONLY) rewired to live SSE:
 * - Props accept live `ReasoningStep[]` from `useSSEChat` (status/token/
 *   map/safety/evidence/done/error frames), never design-time fixtures.
 * - Header shows live sub-agent count + confidence (from `done.confidence`)
 *   + summed elapsed_ms. Accordion lists each live step with icon, state
 *   pill, elapsed, and description.
 * - "API Payload" opens the live PayloadInspector (real request + frames).
 */

'use client';

import React, { useState } from 'react';
import { useApp } from '@/context/AppContext';
import type { ReasoningStep } from '@/chat/useSSEChat';
import {
  Cpu,
  ChevronDown,
  CheckCircle2,
  Clock,
  AlertTriangle,
  XCircle,
  Sparkles,
  Waves,
  CloudSun,
  ShieldCheck,
  Brain,
  Compass,
  FileCode2,
} from 'lucide-react';

interface AgentExecutionTraceProps {
  traces: ReasoningStep[];
  confidenceScore?: number;
  onInspectPayload?: () => void;
  /** Effective reply language — Hindi header only when 'hi' (dual-gate). */
  responseLang?: string;
}

function stateStyle(state: string) {
  const s = String(state ?? '').toLowerCase();
  if (s === 'running') return { dot: 'bg-cyan-400 animate-pulse', pillLight: 'bg-cyan-50 text-cyan-800 border-cyan-200', pillDark: 'bg-cyan-950 text-cyan-300 border-cyan-800', Icon: Clock };
  if (s === 'timeout') return { dot: 'bg-amber-500', pillLight: 'bg-amber-50 text-amber-800 border-amber-200', pillDark: 'bg-amber-950 text-amber-300 border-amber-800', Icon: Clock };
  if (s === 'error') return { dot: 'bg-rose-500', pillLight: 'bg-rose-50 text-rose-800 border-rose-200', pillDark: 'bg-rose-950 text-rose-300 border-rose-800', Icon: XCircle };
  if (s === 'fallback') return { dot: 'bg-amber-400', pillLight: 'bg-amber-50 text-amber-800 border-amber-200', pillDark: 'bg-amber-950 text-amber-300 border-amber-800', Icon: AlertTriangle };
  return { dot: 'bg-emerald-500', pillLight: 'bg-emerald-50 text-emerald-800 border-emerald-200', pillDark: 'bg-emerald-950 text-emerald-300 border-emerald-800', Icon: CheckCircle2 };
}
function iconForAgent(agent: string) {
  const key = agent.toLowerCase();
  if (key.includes('fish') || key.includes('pfz') || key.includes('ocean') || key.includes('marine')) return Waves;
  if (key.includes('weather')) return CloudSun;
  if (key.includes('danger') || key.includes('risk') || key.includes('hazard') || key.includes('decision')) return ShieldCheck;
  if (key.includes('planner') || key.includes('orchestrator') || key.includes('parallel')) return Cpu;
  if (key.includes('gis') || key.includes('map') || key.includes('geo')) return Compass;
  if (key.includes('router') || key.includes('intent') || key.includes('language') || key.includes('chitchat')) return Sparkles;
  if (key.includes('synth') || key.includes('reason')) return Brain;
  return Cpu;
}

export const AgentExecutionTrace: React.FC<AgentExecutionTraceProps> = ({
  traces,
  confidenceScore,
  onInspectPayload,
  responseLang = 'en',
}) => {
  const isHi = responseLang === 'hi';
  const { themeMode } = useApp();
  const isLight = themeMode === 'light';
  const [isOpen, setIsOpen] = useState(false);

  if (!traces || traces.length === 0) return null;

  const totalTimeMs = traces.reduce((acc, curr) => acc + (curr.elapsed_ms ?? 0), 0);
  // Confidence passthrough: undefined when the backend omits it (no invented 87%).
  const pct =
    confidenceScore == null || !Number.isFinite(Number(confidenceScore))
      ? null
      : Math.round(Number(confidenceScore) <= 1 && Number(confidenceScore) > 0
        ? Number(confidenceScore) * 100
        : Number(confidenceScore));

  return (
    <div
      data-testid="agent-execution-trace"
      className={`rounded-2xl border my-3 overflow-hidden transition-all ${
        isLight
          ? 'bg-sky-50/60 border-sky-200 text-slate-800'
          : 'glass-panel border-cyan-900/50 bg-slate-950/80 text-slate-100'
      }`}
    >
      {/* Header Bar */}
      <div
        onClick={() => setIsOpen(!isOpen)}
        role="button"
        tabIndex={0}
        aria-expanded={isOpen}
        aria-label="Toggle agent execution trace"
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') setIsOpen(!isOpen);
        }}
        className={`p-3.5 flex items-center justify-between cursor-pointer select-none transition-colors ${
          isLight ? 'hover:bg-sky-100/50' : 'hover:bg-cyan-950/40'
        }`}
      >
        <div className="flex items-center gap-2.5">
          <div
            className={`w-8 h-8 rounded-xl flex items-center justify-center border ${
              isLight ? 'bg-white border-sky-200 text-cyan-700' : 'bg-cyan-950 border-cyan-800 text-cyan-300'
            }`}
          >
            <Cpu className="w-4 h-4 animate-pulse" />
          </div>

          <div>
            <div className="flex items-center gap-2">
              <span className={`font-extrabold text-xs sm:text-sm ${isLight ? 'text-slate-900' : 'text-white'}`}>
                {isHi ? `एजेंटिक पाइपलाइन ट्रेस (${traces.length} उप-एजेंट)` : `Agentic Pipeline Trace (${traces.length} Sub-Agents)`}
              </span>
              {pct != null && (
                <span
                  className={`px-2 py-0.5 rounded text-[10px] font-bold border ${
                    isLight ? 'bg-cyan-100 text-cyan-900 border-cyan-300' : 'bg-cyan-950 text-cyan-300 border-cyan-800'
                  }`}
                >
                  {isHi ? `${pct}% विश्वास` : `${pct}% Confidence`}
                </span>
              )}
            </div>
            <p className={`text-[11px] font-medium flex items-center gap-2 ${isLight ? 'text-slate-500' : 'text-slate-400'}`}>
              <Clock className="w-3 h-3 text-cyan-600 inline" />
              {isHi ? 'कुल निष्पादन समय:' : 'Total Execution Time:'} <span className="font-mono font-bold text-cyan-700">{totalTimeMs}ms</span>
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {onInspectPayload && (
            <button
              type="button"
              data-testid="trace-inspect-payload-button"
              aria-label="Inspect live SSE payload"
              onClick={(e) => {
                e.stopPropagation();
                onInspectPayload();
              }}
              className={`hidden sm:flex items-center gap-1 px-2.5 py-1 rounded-lg border text-[11px] font-semibold transition-colors ${
                isLight
                  ? 'bg-white border-slate-200 text-slate-700 hover:bg-slate-50'
                  : 'bg-slate-900 border-slate-800 text-cyan-300 hover:bg-slate-800'
              }`}
              title="Inspect live SSE request + frames"
            >
              <FileCode2 className="w-3.5 h-3.5 text-cyan-600" />
              <span>{isHi ? 'API पेलोड' : 'API Payload'}</span>
            </button>
          )}

          <ChevronDown className={`w-4 h-4 transition-transform ${isLight ? 'text-cyan-700' : 'text-cyan-400'} ${isOpen ? 'rotate-180' : ''}`} />
        </div>
      </div>

      {/* Accordion Content */}
      {isOpen && (
        <div className={`p-3.5 pt-1 border-t space-y-2 text-xs ${isLight ? 'border-sky-200/80 bg-white/70' : 'border-slate-800 bg-slate-950/90'}`}>
          <div className={`text-[11px] font-semibold mb-2 ${isLight ? 'text-slate-500' : 'text-slate-400'}`}>
            {isHi ? 'लाइव मल्टी-एजेंट वर्कफ़्लो चरण (SSE स्थिति फ्रेम):' : 'Live multi-agent workflow steps (SSE status frames):'}
          </div>

          <div className="space-y-2 relative before:absolute before:left-4 before:top-3 before:bottom-3 before:w-0.5 before:bg-cyan-500/30">
            {traces.map((step, idx) => {
              const IconComp = iconForAgent(step.agent);
              const stateLabel = step.state;
              const st = stateStyle(stateLabel);
              const StateIcon = st.Icon;
              return (
                <div
                  key={`${step.agent}-${idx}`}
                  className={`relative pl-8 p-3 rounded-xl border transition-all ${
                    isLight
                      ? 'bg-white border-slate-200 shadow-sm'
                      : 'bg-slate-900/90 border-slate-800'
                  }`}
                >
                  <div className={`absolute left-2.5 top-3.5 w-3 h-3 rounded-full border-2 ${st.dot} ${
                    isLight ? 'border-white' : 'border-slate-950'
                  }`} />

                  <div className="flex flex-wrap items-center justify-between gap-1 mb-1">
                    <div className="flex items-center gap-1.5 font-extrabold text-xs">
                      <IconComp className={`w-4 h-4 ${isLight ? 'text-cyan-700' : 'text-cyan-400'}`} />
                      <span className={isLight ? 'text-slate-900' : 'text-white'}>{step.title}</span>
                    </div>

                    <div className="flex items-center gap-1.5 font-mono text-[10px]">
                      <span className={`px-1.5 py-0.5 rounded border ${
                        isLight ? st.pillLight : st.pillDark
                      }`}>
                        <StateIcon className="w-2.5 h-2.5 inline mr-1" />
                        {stateLabel}
                      </span>
                      {step.elapsed_ms != null && (
                        <span className={`px-1.5 py-0.5 rounded border ${
                          isLight ? 'bg-slate-100 text-slate-600 border-slate-200' : 'bg-slate-950 text-slate-400 border-slate-800'
                        }`}>
                          {step.elapsed_ms}ms
                        </span>
                      )}
                    </div>
                  </div>

                  {(step.description || step.agent) && (
                    <p className={`text-[11px] font-medium ${isLight ? 'text-slate-600' : 'text-slate-300'}`}>
                      {step.description || `Live agent: ${step.agent}`}
                    </p>
                  )}
                </div>
              );
            })}
          </div>

          {onInspectPayload && (
            <div className="pt-2 text-center sm:hidden">
              <button
                type="button"
                data-testid="trace-inspect-payload-button-mobile"
                aria-label="Inspect live SSE payload"
                onClick={onInspectPayload}
                className="w-full py-2 rounded-xl bg-cyan-700 text-white font-bold text-xs flex items-center justify-center gap-1.5"
              >
                <FileCode2 className="w-4 h-4 text-white" />
                <span>Inspect live SSE payload</span>
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default AgentExecutionTrace;
