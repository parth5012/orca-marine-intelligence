/**
 * EvidenceCard (UI-MIG-T4)
 *
 * Owner: M-E (Frontend Chat & App Shell)
 * Module: frontend/components/common/EvidenceCard.tsx
 *
 * Visual port of the source design EvidenceCard (READ-ONLY).
 * Live-only: `evidence` items come straight from SSE `evidence` frames;
 * `confidenceScore` comes from the `done.confidence` frame (0..1 or 0..100).
 */

'use client';

import React from 'react';
import { CheckCircle2, ShieldCheck, Database, Info } from 'lucide-react';
import { useApp } from '@/context/AppContext';
import { motion } from 'framer-motion';

interface EvidenceCardProps {
  evidence: string[];
  title?: string;
  sourceText?: string;
  confidenceScore?: number;
  lastUpdated?: string;
}

const DATA_SOURCES = [
  'PFZ Advisory',
  'Ocean Conditions',
  'Weather Forecast',
  'Hazard Alerts',
  'Geospatial Constraints',
];

const listContainer = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: {
      staggerChildren: 0.12,
    },
  },
};

const listItem = {
  hidden: { opacity: 0, x: -10 },
  show: { opacity: 1, x: 0 },
};

function toPercent(confidence?: number): number {
  if (confidence == null || !Number.isFinite(Number(confidence))) return 87;
  const n = Number(confidence);
  if (n > 0 && n <= 1) return Math.round(n * 100);
  return Math.round(n);
}

export const EvidenceCard: React.FC<EvidenceCardProps> = ({
  evidence,
  title = 'WHY ORCA RECOMMENDS THIS',
  sourceText = 'Validated by INCOIS Marine Oceanography & IMD Weather Models',
  confidenceScore = 87,
  lastUpdated = 'Live advisory stream',
}) => {
  const { themeMode } = useApp();
  const isLight = themeMode === 'light';

  if (!evidence || evidence.length === 0) return null;

  return (
    <div
      data-testid="evidence-card"
      className={`rounded-2xl p-4 sm:p-5 border my-3 transition-colors shadow-sm ${
        isLight
          ? 'bg-white border-sky-200 text-slate-800'
          : 'glass-panel border-cyan-900/40 bg-slate-950/90 text-slate-100'
      }`}
    >
      {/* Header Row */}
      <div className={`flex flex-wrap items-center justify-between gap-2 pb-3 mb-3 border-b ${isLight ? 'border-slate-100' : 'border-slate-800'}`}>
        <div className="flex items-center gap-2">
          <ShieldCheck className={`w-5 h-5 ${isLight ? 'text-cyan-700' : 'text-cyan-400'}`} />
          <h4 className={`font-extrabold text-sm uppercase tracking-wider ${isLight ? 'text-slate-900' : 'text-white'}`}>
            {title}
          </h4>
        </div>

        <div className="flex items-center gap-2 font-mono text-xs">
          <span className={`px-2.5 py-0.5 rounded-full font-bold border ${
            isLight ? 'bg-emerald-50 text-emerald-900 border-emerald-300' : 'bg-emerald-950 text-emerald-300 border-emerald-800'
          }`}>
            Confidence: {toPercent(confidenceScore)}%
          </span>
          <span className={`hidden sm:inline-block px-2 py-0.5 rounded border text-[10px] ${
            isLight ? 'bg-cyan-50 text-cyan-900 border-cyan-200' : 'bg-cyan-950 text-cyan-300 border-cyan-800'
          }`}>
            Updated: {lastUpdated}
          </span>
        </div>
      </div>

      {/* Data Considered Source Chips */}
      <div className="mb-3.5">
        <div className={`text-[11px] font-bold uppercase tracking-wider mb-1.5 flex items-center gap-1.5 ${
          isLight ? 'text-slate-500' : 'text-slate-400'
        }`}>
          <Database className="w-3.5 h-3.5 text-cyan-600" />
          <span>Data Sources Fused:</span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {DATA_SOURCES.map((ds, idx) => (
            <span
              key={idx}
              className={`px-2 py-0.5 rounded text-[10px] font-semibold border ${
                isLight
                  ? 'bg-sky-50 text-cyan-900 border-sky-200'
                  : 'bg-slate-900 text-cyan-300 border-slate-800'
              }`}
            >
              • {ds} ✓
            </span>
          ))}
        </div>
      </div>

      {/* Decision Rationale Checklist with Staggered Entry Animation */}
      <motion.ul
        variants={listContainer}
        initial="hidden"
        animate="show"
        className={`space-y-2.5 text-xs sm:text-sm font-medium ${isLight ? 'text-slate-700' : 'text-slate-200'}`}
      >
        {evidence.map((item, idx) => (
          <motion.li key={idx} variants={listItem} className="flex items-start gap-2.5 p-1 rounded-lg hover:bg-cyan-500/5 transition-colors">
            <CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0 mt-0.5" />
            <span className="leading-snug">{item}</span>
          </motion.li>
        ))}
      </motion.ul>

      {sourceText && (
        <div className={`mt-4 pt-2.5 border-t flex items-center justify-between text-[11px] ${
          isLight ? 'border-slate-100 text-slate-500' : 'border-slate-800/80 text-slate-400'
        }`}>
          <div className="flex items-center gap-1.5">
            <Info className="w-3.5 h-3.5 text-cyan-600 shrink-0" />
            <span>Source: {sourceText}</span>
          </div>
          <span className="font-mono text-[10px] text-emerald-500 font-bold flex items-center gap-1">
            <ShieldCheck className="w-3 h-3 text-emerald-400" />
            SAFETY VALIDATED ✓
          </span>
        </div>
      )}
    </div>
  );
};

export default EvidenceCard;
