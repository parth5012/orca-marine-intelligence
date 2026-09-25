/**
 * /demo redirect contract.
 *
 * Requirement (2026-09-25): opening `/demo` on the site must redirect to the
 * public demo video at https://youtu.be/pew44mcyDdc.
 *
 * Run: bun test tests/demoRedirect.test.ts
 */
import { describe, expect, it } from 'bun:test';
import { NextRequest } from 'next/server';
import { GET } from '../app/demo/route';

const DEMO_URL = 'https://youtu.be/pew44mcyDdc';

function makeRequest(path = '/demo'): NextRequest {
  return new NextRequest(`https://orca-marine-intelligence.vercel.app${path}`);
}

describe('GET /demo', () => {
  it('redirects to the demo video', async () => {
    const res = await GET(makeRequest());

    expect([301, 302, 303, 307, 308]).toContain(res.status);
    expect(res.headers.get('location')).toBe(DEMO_URL);
  });

  it('keeps the redirect permanent-ish and stable across calls', async () => {
    const first = await GET(makeRequest());
    const second = await GET(makeRequest());

    expect(first.status).toBe(second.status);
    expect(second.headers.get('location')).toBe(DEMO_URL);
  });
});
