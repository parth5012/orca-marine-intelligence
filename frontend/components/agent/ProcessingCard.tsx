/**
 * ProcessingCard (UI-MIG-T4)
 *
 * Owner: M-E (Frontend Chat & App Shell)
 * Module: frontend/components/agent/ProcessingCard.tsx
 *
 * Visual port of the source design processing card (READ-ONLY).
 * Live-only: purely presentational "pipeline active" indicator rendered
 * while `useSSEChat.isStreaming` is true. No timers drive conversation
 * state; the SSE stream owns progress via reasoning_steps.
 */

'use client';

import React from 'react';
import { useApp } from '@/context/AppContext';
import { motion } from 'framer-motion';
import {
  Sparkles,
  CheckCircle2,
  Waves,
  CloudSun,
  Compass,
  ShieldCheck,
  Cpu,
  Brain,
  Route,
} from 'lucide-react';

interface ProcessingCardProps {
  label?: string;
}

const PIPELINE_STAGES = [
  { label: 'ASK', icon: Sparkles },
  { label: 'UNDERSTAND', icon: Brain },
  { label: 'COLLABORATE', icon: Cpu },
  { label: 'REASON', icon: Waves },
  { label: 'VALIDATE', icon: ShieldCheck },
  { label: 'RECOMMEND', icon: CheckCircle2 },
  { label: 'ACT', icon: Route },
];

export const ProcessingCard: React.FC<ProcessingCardProps> = ({
  label = 'ORCA Multi-Agent Intelligence Pipeline Active',
}) => {
  const { themeMode } = useApp();
  const isLight = themeMode === 'light';

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      data-testid="agent-processing-card"
      role="status"
      aria-label="ORCA multi-agent pipeline active"
      className={`p-4 sm:p-5 rounded-2xl border transition-all my-3 shadow-xl ${
        isLight
          ? 'bg-sky-50/95 border-sky-300 text-slate-800 shadow-sky-900/10'
          : 'glass-panel border-cyan-500/40 bg-slate-950/90 text-slate-100 shadow-cyan-950/60'
      }`}
    >
      {/* Header with Intelligence Badge */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2.5">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-cyan-500 to-teal-600 flex items-center justify-center text-white shadow-md shadow-cyan-500/30">
            <Cpu className="w-5 h-5 animate-spin" />
          </div>
          <div>
            <h3 className={`font-extrabold text-sm ${isLight ? 'text-slate-900' : 'text-white'}`}>
              {label}
            </h3>
            <p className={`text-[11px] font-medium ${isLight ? 'text-slate-500' : 'text-slate-400'}`}>
              Live SSE stream — oceanography, weather &amp; GIS agents reporting
            </p>
          </div>
        </div>

        <span className="px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 animate-pulse hidden sm:inline-block">
          Streaming live
        </span>
      </div>

      {/* High-Level System Journey Banner */}
      <div className="flex items-center justify-between gap-1 p-2 rounded-xl bg-slate-900/80 border border-cyan-900/40 my-3 text-[10px] font-mono font-bold text-cyan-300 overflow-x-auto no-scrollbar">
        {PIPELINE_STAGES.map((st, i) => {
          const IconComp = st.icon;
          return (
            <div key={st.label} className="flex items-center gap-1 shrink-0">
              <span className="px-1.5 py-0.5 rounded flex items-center gap-1 transition-colors bg-cyan-500/30 text-cyan-200 border border-cyan-400/50">
                <IconComp className="w-3 h-3" />
                {st.label}
              </span>
              {i < PIPELINE_STAGES.length - 1 && <span className="text-slate-600">→</span>}
            </div>
          );
        })}
      </div>

      <div className="space-y-2.5 text-xs font-medium">
        <div className={`p-2.5 rounded-xl border flex items-center justify-between transition-all ${
          isLight
            ? 'bg-white border-cyan-300 text-slate-800 shadow-sm'
            : 'bg-cyan-950/40 border-cyan-800 text-slate-200'
        }`}>
          <div className="flex items-center gap-2">
            <Sparkles className="w-3.5 h-3.5 text-cyan-500" />
            <span>Live advisory streaming — watch the trace above for agent steps</span>
          </div>
          <span className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse" />
        </div>

        <div className={`p-3 rounded-xl border transition-all ${
          isLight
            ? 'bg-white border-cyan-300 text-slate-800 shadow-sm'
            : 'bg-cyan-950/40 border-cyan-800 text-slate-200'
        }`}>
          <div className="flex items-center justify-between mb-2 font-semibold text-[11px] text-cyan-700 dark:text-cyan-400">
            <span>Live sub-agent grid (PFZ • Ocean • Weather • Hazard • GIS):</span>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-5 gap-1.5 text-[10px]">
            <span className="px-2 py-1 rounded-lg bg-blue-500/20 text-blue-300 border border-blue-400/40 flex items-center justify-center gap-1 font-bold shadow-sm">
              <Waves className="w-3 h-3 text-blue-400" /> PFZ Agent
            </span>
            <span className="px-2 py-1 rounded-lg bg-cyan-500/20 text-cyan-300 border border-cyan-400/40 flex items-center justify-center gap-1 font-bold shadow-sm">
              <Waves className="w-3 h-3 text-cyan-400" /> Ocean Agent
            </span>
            <span className="px-2 py-1 rounded-lg bg-amber-500/20 text-amber-300 border border-amber-400/40 flex items-center justify-center gap-1 font-bold shadow-sm">
              <CloudSun className="w-3 h-3 text-amber-400" /> Weather Agent
            </span>
            <span className="px-2 py-1 rounded-lg bg-rose-500/20 text-rose-300 border border-rose-400/40 flex items-center justify-center gap-1 font-bold shadow-sm">
              <ShieldCheck className="w-3 h-3 text-rose-400" /> Hazard Agent
            </span>
            <span className="col-span-2 sm:col-span-1 px-2 py-1 rounded-lg bg-emerald-500/20 text-emerald-300 border border-emerald-400/40 flex items-center justify-center gap-1 font-bold shadow-sm">
              <Compass className="w-3 h-3 text-emerald-400" /> GIS Agent
            </span>
          </div>
        </div>
      </div>
    </motion.div>
  );
};

/** Source-design alias kept for a familiar import name. */
export const AgentProcessingCard = ProcessingCard;

export default ProcessingCard;
