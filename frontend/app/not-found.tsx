/**
 * Custom 404 page.
 *
 * Owner: M-E (Frontend Chat & App Shell)
 * Module: frontend/app/not-found.tsx
 *
 * Branded fallback for unknown routes (E2E NAV-07).
 * Exposes data-testid="not-found-page" for browser tests.
 */

import Link from 'next/link';

export default function NotFound() {
  return (
    <main
      data-testid="not-found-page"
      className="min-h-screen flex flex-col items-center justify-center gap-4 bg-slate-950 text-slate-100 px-6 text-center"
    >
      <span className="text-5xl" role="img" aria-label="Ocean wave">
        🌊
      </span>
      <h1 className="text-2xl font-bold">Lost at sea?</h1>
      <p className="text-sm text-slate-400 max-w-md">
        This chart doesn&apos;t exist. Head back to the ORCA advisory or ocean
        map to continue.
      </p>
      <div className="flex items-center gap-3">
        <Link
          href="/"
          data-testid="not-found-home-link"
          className="px-4 py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-slate-950 text-sm font-semibold"
        >
          💬 Back to Chat
        </Link>
        <Link
          href="/map"
          data-testid="not-found-map-link"
          className="px-4 py-2 rounded-lg border border-cyan-700 text-cyan-300 hover:bg-cyan-950 text-sm font-semibold"
        >
          🗺️ Ocean Map
        </Link>
      </div>
    </main>
  );
}
