/**
 * AgentWorkflowModal (UI-MIG-T7)
 *
 * Owner: M-E (Frontend Chat & App Shell)
 * Module: frontend/components/agent/AgentWorkflowModal.tsx
 *
 * Ported pipeline visual from source design `agent/AgentWorkflowModal`
 * (READ-ONLY). Strictly READ-ONLY over live `reasoning_steps` owned by the
 * SSE stream (`frontend/chat/useSSEChat.ts`): renders agent state badges +
 * the static ASK→UNDERSTAND→COLLABORATE→REASON→VALIDATE→RECOMMEND→ACT
 * journey. Never mutates chat state, never synthesizes steps.
 */

'use client';

import React, { useEffect } from 'react';
import {
  X,
  Sparkles,
  Cpu,
  Waves,
  CloudSun,
  Compass,
  Brain,
  ShieldCheck,
  ArrowDown,
  Layers,
  Database,
} from 'lucide-react';
import { useApp } from '@/context/AppContext';
import type { ReasoningStep } from '@/chat';

interface AgentWorkflowModalProps {
  /** Live reasoning steps from the SSE stream (read-only). */
  steps: ReasoningStep[];
  isOpen: boolean;
  onClose: () => void;
}

const STATE_STYLE: Record<string, string> = {
  running: 'bg-cyan-950 text-cyan-300 border-cyan-800',
  done: 'bg-emerald-950 text-emerald-300 border-emerald-800',
  timeout: 'bg-amber-950 text-amber-300 border-amber-800',
  error: 'bg-rose-950 text-rose-300 border-rose-800',
  fallback: 'bg-amber-950 text-amber-300 border-amber-800',
};

export const AgentWorkflowModal: React.FC<AgentWorkflowModalProps> = ({
  steps,
  isOpen,
  onClose,
}) => {
  const { themeMode } = useApp();
  const isLight = themeMode === 'light';

  // Escape dismisses the modal (declared before the isOpen guard).
  useEffect(() => {
    if (!isOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const liveSteps = Array.isArray(steps) ? steps : [];

  return (
    <div
      data-testid="workflow-modal"
      role="dialog"
      aria-modal="true"
      aria-label="ORCA multi-agent workflow"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-xl animate-fade-in overflow-y-auto"
    >
      <div
        className={`relative w-full max-w-3xl rounded-3xl p-6 sm:p-8 border shadow-2xl transition-colors max-h-[90vh] overflow-y-auto ${
          isLight
            ? 'bg-white border-cyan-200 text-slate-900 shadow-sky-900/10'
            : 'glass-panel border-cyan-500/40 bg-slate-950/95 text-slate-100 shadow-cyan-950/80'
        }`}
      >
        <button
          type="button"
          onClick={onClose}
          aria-label="Close workflow diagram"
          className={`absolute top-4 right-4 w-9 h-9 rounded-full border flex items-center justify-center transition-colors ${
            isLight
              ? 'bg-slate-100 border-slate-200 text-slate-600 hover:bg-slate-200'
              : 'bg-slate-900 border-slate-800 text-slate-400 hover:text-white'
          }`}
        >
          <X className="w-5 h-5" />
        </button>

        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-cyan-950/80 border border-cyan-500/40 text-cyan-300 text-xs font-bold mb-3">
          <Sparkles className="w-3.5 h-3.5 text-cyan-300 animate-pulse" />
          <span>SIH 2026 Agentic Architecture Specification</span>
        </div>

        <h2 className="text-xl sm:text-2xl font-extrabold tracking-tight">
          ORCA Multi-Agent Workflow Pipeline
        </h2>
        <p
          className={`text-xs sm:text-sm font-medium mt-1 mb-4 ${
            isLight ? 'text-slate-600' : 'text-slate-400'
          }`}
        >
          High-performance distributed AI architecture combining Bhashini NLU, INCOIS
          oceanography, IMD weather models, & GIS boundary geofencing.
        </p>

        {/* Live reasoning trace (read-only) */}
        <div
          data-testid="workflow-live-steps"
          className={`mb-6 rounded-2xl border p-4 ${
            isLight ? 'bg-slate-50 border-slate-200' : 'bg-slate-900/80 border-slate-800'
          }`}
        >
          <div
            className={`text-[11px] font-bold uppercase tracking-wider mb-2 ${
              isLight ? 'text-slate-500' : 'text-slate-400'
            }`}
          >
            Live execution trace ({liveSteps.length} step{liveSteps.length === 1 ? '' : 's'})
          </div>
          {liveSteps.length === 0 ? (
            <p className={`text-xs ${isLight ? 'text-slate-500' : 'text-slate-400'}`}>
              No agent steps yet — ask ORCA a marine question and the live trace appears
              here.
            </p>
          ) : (
            <ul className="space-y-1.5">
              {liveSteps.map((step, idx) => (
                <li
                  key={`${step.agent}-${idx}`}
                  data-testid={`workflow-step-${step.agent}`}
                  className="flex items-center justify-between gap-2 text-xs"
                >
                  <span className="font-semibold truncate">
                    {step.title || step.agent}
                    {step.elapsed_ms != null && (
                      <span className="font-mono font-normal opacity-60">
                        {' '}
                        · {step.elapsed_ms}ms
                      </span>
                    )}
                  </span>
                  <span
                    className={`px-2 py-0.5 rounded text-[10px] font-extrabold border shrink-0 ${
                      STATE_STYLE[String(step.state)] ?? STATE_STYLE.running
                    }`}
                  >
                    {String(step.state).toUpperCase()}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="flex items-center justify-between gap-1 p-2.5 rounded-2xl bg-cyan-950/60 border border-cyan-500/30 mb-6 text-[10px] font-mono font-bold text-cyan-300 overflow-x-auto no-scrollbar shadow-inner">
          <span className="px-2 py-0.5 rounded bg-cyan-500/20 text-cyan-200">1. ASK</span>
          <span className="text-slate-600">→</span>
          <span className="px-2 py-0.5 rounded bg-cyan-500/20 text-cyan-200">2. UNDERSTAND</span>
          <span className="text-slate-600">→</span>
          <span className="px-2 py-0.5 rounded bg-cyan-500/20 text-cyan-200">3. COLLABORATE</span>
          <span className="text-slate-600">→</span>
          <span className="px-2 py-0.5 rounded bg-cyan-500/20 text-cyan-200">4. REASON</span>
          <span className="text-slate-600">→</span>
          <span className="px-2 py-0.5 rounded bg-cyan-500/20 text-cyan-200">5. VALIDATE</span>
          <span className="text-slate-600">→</span>
          <span className="px-2 py-0.5 rounded bg-cyan-500/20 text-cyan-200">6. RECOMMEND</span>
          <span className="text-slate-600">→</span>
          <span className="px-2 py-0.5 rounded bg-emerald-500/30 text-emerald-300 border border-emerald-500/40">
            7. ACT
          </span>
        </div>

        <div className="space-y-4 text-xs font-medium">
          <div
            className={`p-4 rounded-2xl border text-center relative ${
              isLight ? 'bg-sky-50 border-sky-200' : 'bg-slate-900/90 border-slate-800'
            }`}
          >
            <div className="inline-flex items-center gap-2 font-extrabold text-sm text-cyan-700">
              <Sparkles className="w-4 h-4" />
              <span>1. User Input (Text / Bhashini Voice)</span>
            </div>
            <p className={`text-[11px] mt-1 ${isLight ? 'text-slate-600' : 'text-slate-400'}`}>
              Multi-Lingual STT/TTS across 10 Indian Languages (Hindi, Malayalam, Tamil,
              Telugu, etc.)
            </p>
          </div>

          <div className="flex justify-center">
            <ArrowDown className="w-5 h-5 text-cyan-600 animate-bounce" />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div
              className={`p-3.5 rounded-2xl border ${
                isLight ? 'bg-cyan-50 border-cyan-200' : 'bg-cyan-950/40 border-cyan-900'
              }`}
            >
              <div className="font-bold text-cyan-800 flex items-center gap-1.5 mb-1">
                <Brain className="w-4 h-4 text-cyan-600" />
                <span>Language & Intent NLU</span>
              </div>
              <p className={`text-[11px] ${isLight ? 'text-slate-600' : 'text-slate-400'}`}>
                Classifies query intent (PFZ Search, Weather Safety, Safe Route, Hazard
                Warnings).
              </p>
            </div>

            <div
              className={`p-3.5 rounded-2xl border ${
                isLight ? 'bg-teal-50 border-teal-200' : 'bg-teal-950/40 border-teal-900'
              }`}
            >
              <div className="font-bold text-teal-800 flex items-center gap-1.5 mb-1">
                <Cpu className="w-4 h-4 text-teal-600" />
                <span>Orchestrator / Planner Agent</span>
              </div>
              <p className={`text-[11px] ${isLight ? 'text-slate-600' : 'text-slate-400'}`}>
                Decomposes tasks and dispatches requests in parallel to domain agents.
              </p>
            </div>
          </div>

          <div className="flex justify-center">
            <ArrowDown className="w-5 h-5 text-cyan-600" />
          </div>

          <div>
            <div
              className={`text-[11px] font-bold uppercase tracking-wider mb-2 text-center ${
                isLight ? 'text-slate-500' : 'text-slate-400'
              }`}
            >
              Parallel Sub-Agent Execution Layer:
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div
                className={`p-3.5 rounded-2xl border ${
                  isLight
                    ? 'bg-white border-blue-200 shadow-sm'
                    : 'bg-slate-900 border-slate-800'
                }`}
              >
                <div className="font-extrabold text-blue-700 flex items-center gap-1.5 mb-1 text-xs">
                  <Waves className="w-4 h-4 text-blue-600" />
                  <span>Marine Agent</span>
                </div>
                <div className="text-[11px] text-slate-500 font-mono">INCOIS Telemetry</div>
                <p className={`text-[11px] mt-1 ${isLight ? 'text-slate-600' : 'text-slate-400'}`}>
                  PFZ zone coordinates, SST (°C), Chlorophyll-a density, & target fish
                  species.
                </p>
              </div>

              <div
                className={`p-3.5 rounded-2xl border ${
                  isLight
                    ? 'bg-white border-amber-200 shadow-sm'
                    : 'bg-slate-900 border-slate-800'
                }`}
              >
                <div className="font-extrabold text-amber-700 flex items-center gap-1.5 mb-1 text-xs">
                  <CloudSun className="w-4 h-4 text-amber-600" />
                  <span>Weather Agent</span>
                </div>
                <div className="text-[11px] text-slate-500 font-mono">IMD Forecast Grid</div>
                <p className={`text-[11px] mt-1 ${isLight ? 'text-slate-600' : 'text-slate-400'}`}>
                  Wind vector speed/direction, ocean wave height, swell period, & cyclone
                  alerts.
                </p>
              </div>

              <div
                className={`p-3.5 rounded-2xl border ${
                  isLight
                    ? 'bg-white border-emerald-200 shadow-sm'
                    : 'bg-slate-900 border-slate-800'
                }`}
              >
                <div className="font-extrabold text-emerald-700 flex items-center gap-1.5 mb-1 text-xs">
                  <Compass className="w-4 h-4 text-emerald-600" />
                  <span>GIS Agent</span>
                </div>
                <div className="text-[11px] text-slate-500 font-mono">Boundary Geofence</div>
                <p className={`text-[11px] mt-1 ${isLight ? 'text-slate-600' : 'text-slate-400'}`}>
                  Indian EEZ boundary, IMBL proximity, Naval defense restricted zones.
                </p>
              </div>
            </div>
          </div>

          <div className="flex justify-center">
            <ArrowDown className="w-5 h-5 text-cyan-600" />
          </div>

          <div
            className={`p-4 rounded-2xl border text-center ${
              isLight ? 'bg-indigo-50 border-indigo-200' : 'bg-slate-900/90 border-slate-800'
            }`}
          >
            <div className="inline-flex items-center gap-2 font-extrabold text-sm text-indigo-800">
              <Layers className="w-4 h-4 text-indigo-600" />
              <span>4. Risk & Reasoning Engine</span>
            </div>
            <p className={`text-[11px] mt-1 ${isLight ? 'text-slate-600' : 'text-slate-400'}`}>
              Evaluates multi-agent telemetry using multi-criteria risk scoring (0-100
              Safety Index).
            </p>
          </div>

          <div className="flex justify-center">
            <ArrowDown className="w-5 h-5 text-cyan-600" />
          </div>

          <div
            className={`p-4 rounded-2xl border text-center ${
              isLight
                ? 'bg-emerald-50 border-emerald-200'
                : 'bg-slate-950 border-emerald-800'
            }`}
          >
            <div className="inline-flex items-center gap-2 font-extrabold text-sm text-emerald-800">
              <ShieldCheck className="w-4 h-4 text-emerald-600" />
              <span>5. Decision Engine Output (AI Answer + Safe Route + Alerts)</span>
            </div>
            <p className={`text-[11px] mt-1 ${isLight ? 'text-slate-600' : 'text-slate-400'}`}>
              Outputs easy-to-understand multi-lingual audio/text recommendation,
              interactive map polyline, and safety notifications.
            </p>
          </div>
        </div>

        <div
          className={`mt-6 pt-4 border-t flex items-center justify-between text-xs ${
            isLight ? 'border-slate-100 text-slate-500' : 'border-slate-800 text-slate-400'
          }`}
        >
          <span className="flex items-center gap-1">
            <Database className="w-3.5 h-3.5 text-cyan-600" />
            Backend REST Endpoint:{' '}
            <code className="font-mono text-cyan-700">/v1/agent/workflow/execute</code>
          </span>

          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-xl bg-cyan-700 text-white font-bold text-xs hover:bg-cyan-800 transition-colors"
          >
            Close Diagram
          </button>
        </div>
      </div>
    </div>
  );
};

export default AgentWorkflowModal;
