'use client';

/**
 * PWA Update Toast Notification.
 * Informs the user when a service worker update is ready and provides a safe refresh trigger.
 *
 * Owner: M-E (Frontend Chat & App Shell)
 * Module: frontend/components/pwa/UpdateToast.tsx
 */

import React from 'react';

export interface UpdateToastProps {
  show: boolean;
  onRefresh: () => void;
  onDismiss: () => void;
  isWaitingForIdle?: boolean;
}

export function UpdateToast({
  show,
  onRefresh,
  onDismiss,
  isWaitingForIdle = false,
}: UpdateToastProps) {
  if (!show) {
    return null;
  }

  return (
    <aside
      role="status"
      aria-live="polite"
      className="fixed bottom-4 right-4 z-50 flex max-w-sm flex-col gap-2 rounded-lg border border-slate-700 bg-slate-900/95 p-4 text-white shadow-xl backdrop-blur-sm sm:bottom-6 sm:right-6"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-white">Update ready</p>
          <p className="mt-0.5 text-xs text-slate-300">
            {isWaitingForIdle
              ? 'Waiting for active advisory stream to complete before refreshing...'
              : 'A new version of ORCA is available. Refresh to load recent updates.'}
          </p>
        </div>
      </div>
      <div className="mt-1 flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={onDismiss}
          className="rounded px-2.5 py-1 text-xs font-medium text-slate-400 hover:text-white transition-colors focus:outline-none focus:ring-1 focus:ring-slate-400"
        >
          Dismiss
        </button>
        <button
          type="button"
          onClick={onRefresh}
          disabled={isWaitingForIdle}
          className="rounded bg-[#0B3C5D] px-3 py-1 text-xs font-medium text-white hover:bg-[#0e4e78] transition-colors disabled:opacity-50 focus:outline-none focus:ring-1 focus:ring-sky-400"
        >
          {isWaitingForIdle ? 'Waiting...' : 'Refresh'}
        </button>
      </div>
    </aside>
  );
}

export default UpdateToast;
