/**
 * Unit tests for frontend/chat/bhashini.ts client-side translate() credential
 * resolution: BHASHINI_INFERENCE_KEY preferred, BHASHINI_API_KEY fallback.
 *
 * Owner: M-E (Frontend Chat & App Shell)
 * Module: frontend/tests/bhashiniEnv.test.ts
 */

import { afterEach, beforeEach, describe, expect, it } from 'bun:test';
import { translate } from '../chat/bhashini';

const ENV_KEYS = [
  'BHASHINI_INFERENCE_KEY',
  'BHASHINI_API_KEY',
  'NEXT_PUBLIC_BHASHINI_INFERENCE_KEY',
  'NEXT_PUBLIC_BHASHINI_API_KEY',
] as const;

function okResponse(target: string): Response {
  return new Response(
    JSON.stringify({ pipelineResponse: [{ output: [{ target }] }] }),
    { status: 200, headers: { 'Content-Type': 'application/json' } }
  );
}

describe('bhashini.ts translate env credentials', () => {
  const saved: Record<string, string | undefined> = {};
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    for (const k of ENV_KEYS) {
      saved[k] = process.env[k];
      delete process.env[k];
    }
  });

  afterEach(() => {
    for (const k of ENV_KEYS) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k]!;
    }
    globalThis.fetch = originalFetch;
  });

  it('uses BHASHINI_INFERENCE_KEY as Authorization when set (overrides API key)', async () => {
    process.env.BHASHINI_INFERENCE_KEY = 'infer-env-key';
    process.env.BHASHINI_API_KEY = 'ulca-api-key';

    let auth: string | undefined;
    globalThis.fetch = (async (_url: unknown, init?: RequestInit) => {
      const headers = init?.headers as Record<string, string> | undefined;
      auth = headers?.Authorization;
      return okResponse('Kochi');
    }) as typeof fetch;

    const res = await translate('കൊച്ചി', 'ml', 'en');
    expect(res.translated).toBe(true);
    expect(res.text).toBe('Kochi');
    expect(auth).toBe('infer-env-key');
  });

  it('falls back to BHASHINI_API_KEY when no inference key is set', async () => {
    process.env.BHASHINI_API_KEY = 'ulca-api-key';

    let auth: string | undefined;
    globalThis.fetch = (async (_url: unknown, init?: RequestInit) => {
      const headers = init?.headers as Record<string, string> | undefined;
      auth = headers?.Authorization;
      return okResponse('Kochi');
    }) as typeof fetch;

    const res = await translate('കൊച്ചി', 'ml', 'en');
    expect(res.translated).toBe(true);
    expect(auth).toBe('ulca-api-key');
  });

  it('returns untranslated text when no credentials are configured', async () => {
    globalThis.fetch = (async () => {
      throw new Error('fetch must not be called without credentials');
    }) as typeof fetch;

    const res = await translate('hello', 'en', 'ml');
    expect(res.translated).toBe(false);
    expect(res.text).toBe('hello');
  });
});
