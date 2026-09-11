/**
 * PayloadInspector (UI-MIG-T4)
 *
 * Owner: M-E (Frontend Chat & App Shell)
 * Module: frontend/components/agent/PayloadInspector.tsx
 *
 * Visual port of the source design payload inspector (READ-ONLY).
 * Live-only contract: callers pass the REAL SSE `POST /api/chat` request
 * JSON plus the aggregated live response frames for the selected turn.
 * No fixtures, no canned payloads — empty state says "no live payload".
 */

'use client';

import React, { useState } from 'react';
import { useApp } from '@/context/AppContext';
import { X, Copy, Check, Terminal } from 'lucide-react';

interface PayloadInspectorProps {
  isOpen: boolean;
  onClose: () => void;
  requestPayload?: string;
  responsePayload?: string;
}

export const PayloadInspectorModal: React.FC<PayloadInspectorProps> = ({
  isOpen,
  onClose,
  requestPayload,
  responsePayload,
}) => {
  const { themeMode } = useApp();
  const isLight = themeMode === 'light';
  const [activeTab, setActiveTab] = useState<'response' | 'request'>('response');
  const [copied, setCopied] = useState(false);

  if (!isOpen) return null;

  const currentPayload = activeTab === 'response' ? responsePayload : requestPayload;

  const handleCopy = () => {
    if (!currentPayload) return;
    // Chain the clipboard promise: `copied` flips only after the write
    // resolves (sync try/catch cannot catch the async rejection).
    Promise.resolve(navigator.clipboard?.writeText(currentPayload))
      .then(() => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 2000);
      })
      .catch(() => {
        /* clipboard unavailable — selection still visible */
      });
  };

  return (
    <div
      data-testid="payload-inspector-modal"
      role="dialog"
      aria-label="Live SSE payload inspector"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-xl animate-fade-in"
    >
      <div className={`relative w-full max-w-3xl rounded-3xl p-6 sm:p-8 border shadow-2xl transition-colors max-h-[85vh] flex flex-col ${
        isLight
          ? 'bg-white border-cyan-200 text-slate-900 shadow-sky-900/10'
          : 'glass-panel border-cyan-500/40 bg-slate-950/95 text-slate-100 shadow-cyan-950/80'
      }`}>
        {/* Close Button */}
        <button
          type="button"
          data-testid="payload-inspector-close"
          aria-label="Close payload inspector"
          onClick={onClose}
          className={`absolute top-4 right-4 w-9 h-9 rounded-full border flex items-center justify-center transition-colors ${
            isLight
              ? 'bg-slate-100 border-slate-200 text-slate-600 hover:bg-slate-200'
              : 'bg-slate-900 border-slate-800 text-slate-400 hover:text-white'
          }`}
        >
          <X className="w-5 h-5" />
        </button>

        {/* Modal Header */}
        <div className="flex items-center gap-2 mb-1">
          <Terminal className="w-5 h-5 text-cyan-600" />
          <h2 className="text-lg sm:text-xl font-extrabold tracking-tight">
            Live SSE Payload Inspector
          </h2>
        </div>
        <p className={`text-xs font-medium mb-4 ${isLight ? 'text-slate-600' : 'text-slate-400'}`}>
          Real POST /api/chat request plus streamed response frames for this turn.
        </p>

        {/* Tab switcher & Copy button */}
        <div className="flex items-center justify-between pb-3 border-b border-slate-200 dark:border-slate-800">
          <div className="flex items-center gap-2">
            <button
              type="button"
              data-testid="payload-inspector-response-tab"
              onClick={() => setActiveTab('response')}
              className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
                activeTab === 'response'
                  ? 'bg-cyan-700 text-white shadow-sm'
                  : isLight
                  ? 'bg-slate-100 text-slate-700 hover:bg-slate-200'
                  : 'bg-slate-900 text-slate-400 hover:text-white'
              }`}
            >
              Response Frames (JSON)
            </button>

            <button
              type="button"
              data-testid="payload-inspector-request-tab"
              onClick={() => setActiveTab('request')}
              className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
                activeTab === 'request'
                  ? 'bg-cyan-700 text-white shadow-sm'
                  : isLight
                  ? 'bg-slate-100 text-slate-700 hover:bg-slate-200'
                  : 'bg-slate-900 text-slate-400 hover:text-white'
              }`}
            >
              Request Payload (JSON)
            </button>
          </div>

          <button
            type="button"
            data-testid="payload-inspector-copy"
            aria-label="Copy live payload JSON"
            onClick={handleCopy}
            className={`px-3 py-1.5 rounded-lg border text-xs font-semibold flex items-center gap-1.5 transition-colors ${
              isLight
                ? 'bg-slate-50 border-slate-200 text-slate-700 hover:bg-slate-100'
                : 'bg-slate-900 border-slate-800 text-slate-300 hover:text-white'
            }`}
          >
            {copied ? (
              <>
                <Check className="w-3.5 h-3.5 text-emerald-600" />
                <span className="text-emerald-600 font-bold">Copied!</span>
              </>
            ) : (
              <>
                <Copy className="w-3.5 h-3.5 text-cyan-600" />
                <span>Copy JSON</span>
              </>
            )}
          </button>
        </div>

        {/* JSON Code Viewer Container */}
        <div
          data-testid="payload-inspector-content"
          className="flex-1 overflow-y-auto mt-4 p-4 rounded-2xl bg-slate-950 text-cyan-300 font-mono text-xs border border-cyan-900/60 shadow-inner"
        >
          <pre className="whitespace-pre-wrap break-all">
            {currentPayload || '// No live payload for this turn yet — send a query first'}
          </pre>
        </div>

        <div className="mt-4 pt-3 border-t border-slate-800 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-xl bg-cyan-700 text-white font-bold text-xs hover:bg-cyan-800 transition-colors"
          >
            Close Inspector
          </button>
        </div>
      </div>
    </div>
  );
};

/** Source-design alias kept for a familiar import name. */
export const ApiPayloadInspectorModal = PayloadInspectorModal;

export default PayloadInspectorModal;
