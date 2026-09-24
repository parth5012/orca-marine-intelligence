/**
 * Backend base URL + same-origin API rewrite contract.
 *
 * Production symptom (2026-09-23): `lib/pfz.ts::getBackendBaseUrl()` fell
 * back to `http://localhost:8000` in the browser whenever
 * NEXT_PUBLIC_API_URL was unset — dead on any deployed host. Combined with
 * `frontend/vercel.json` having no `/api` rewrite, relative API calls 404'd.
 *
 * Run: bun test tests/backendBaseUrl.test.ts
 */
import { describe, expect, it, beforeEach, afterEach } from 'bun:test';
import { readFileSync } from 'node:fs';
import { getBackendBaseUrl } from '../lib/pfz';

const ENV_KEY = 'NEXT_PUBLIC_API_URL';
const hadEnv = process.env[ENV_KEY];

type FakeWindow = { location: { protocol: string; hostname: string; origin: string } };

function setWindow(win: FakeWindow | undefined) {
  if (win === undefined) {
    delete (globalThis as { window?: unknown }).window;
  } else {
    (globalThis as { window?: unknown }).window = win;
  }
}

function setOrigin(protocol: string, hostname: string) {
  setWindow({
    location: { protocol, hostname, origin: `${protocol}//${hostname}` },
  } as FakeWindow);
}

beforeEach(() => {
  delete process.env[ENV_KEY];
});

afterEach(() => {
  delete (globalThis as { window?: unknown }).window;
  if (hadEnv === undefined) delete process.env[ENV_KEY];
  else process.env[ENV_KEY] = hadEnv;
});

describe('getBackendBaseUrl', () => {
  it('prefers NEXT_PUBLIC_API_URL and strips trailing slashes', () => {
    process.env[ENV_KEY] = 'https://orca-marine-intelligence-backend.vercel.app///';
    setOrigin('https:', 'orca-marine-intelligence-ten.vercel.app');
    expect(getBackendBaseUrl()).toBe('https://orca-marine-intelligence-backend.vercel.app');
  });

  it('falls back to the page origin on https (never localhost)', () => {
    setOrigin('https:', 'orca-marine-intelligence-ten.vercel.app');
    const base = getBackendBaseUrl();
    expect(base).toBe('https://orca-marine-intelligence-ten.vercel.app');
    expect(base).not.toContain('localhost');
    expect(base).not.toContain('onrender.com');
  });

  it('keeps localhost:8000 for local http dev', () => {
    // window.location.hostname carries no port — origin does.
    setOrigin('http:', 'localhost');
    expect(getBackendBaseUrl()).toBe('http://localhost:8000');
  });

  it('keeps localhost:8000 during SSR (no window)', () => {
    setWindow(undefined);
    expect(getBackendBaseUrl()).toBe('http://localhost:8000');
  });

  it('never returns the dead Render backend', () => {
    setOrigin('https:', 'orca-marine-intelligence-ten.vercel.app');
    expect(getBackendBaseUrl()).not.toContain('onrender.com');
    process.env[ENV_KEY] = '';
    expect(getBackendBaseUrl()).not.toContain('onrender.com');
  });
});

describe('frontend/vercel.json api rewrite', () => {
  it('forwards backend-only /api paths to the live backend', () => {
    const raw = readFileSync(new URL('../vercel.json', import.meta.url), 'utf8');
    const cfg = JSON.parse(raw) as { rewrites?: { source: string; destination: string }[] };
    const rewrites = cfg.rewrites ?? [];
    const sources = rewrites.map((r) => r.source);

    expect(sources.some((s) => s.includes('/api/weather'))).toBe(true);
    expect(sources.some((s) => s.includes('/api/geofence'))).toBe(true);
    expect(sources.some((s) => s.includes('/api/officer'))).toBe(true);
    // Next.js route handlers own these exact paths — never rewrite them.
    expect(sources.some((s) => s.startsWith('/api/chat'))).toBe(false);
    expect(sources).not.toContain('/api/status');
    expect(sources).not.toContain('/api/route');
    expect(sources).not.toContain('/api/pfz');
    for (const r of rewrites) {
      expect(r.destination).toContain('orca-marine-intelligence-backend.vercel.app');
    }
  });
});
