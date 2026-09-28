/**
 * Unit tests for frontend/public/sw-policy.js — pure logic for
 * service worker request classification, caching eligibility, and tile LRU.
 *
 * Owner: M-E (Frontend Chat & App Shell)
 * Module: frontend/tests/swPolicy.test.ts
 */

import { describe, expect, it } from 'bun:test';
import {
  classifyRequest,
  createLru,
  isCacheableResponse,
  isCacheableTileResponse,
  OFFLINE_SHELL_PATHS,
  CACHE_BUDGET_BYTES,
  TILE_ENTRY_LIMIT,
} from '../public/sw-policy';

describe('Service Worker Policy — Constants', () => {
  it('exports correct cache budget and entry limit constants', () => {
    expect(CACHE_BUDGET_BYTES).toBe(50 * 1024 * 1024);
    expect(TILE_ENTRY_LIMIT).toBe(2000);
  });

  it('exports offline shell paths array', () => {
    expect(OFFLINE_SHELL_PATHS).toEqual([
      '/',
      '/map',
      '/officer',
      '/manifest.webmanifest',
    ]);
  });
});

describe('Service Worker Policy — Request Classification', () => {
  it('classifies navigation requests regardless of URL', () => {
    expect(classifyRequest('/', 'navigate')).toBe('navigation');
    expect(classifyRequest('/map', 'navigate')).toBe('navigation');
    expect(classifyRequest('/officer', 'navigate')).toBe('navigation');
    expect(classifyRequest('/api/chat', 'navigate')).toBe('navigation');
    expect(classifyRequest('/api/pfz?sector=KC', 'navigate')).toBe('navigation');
  });

  it('classifies chat requests with priority over other api paths', () => {
    expect(classifyRequest('/api/chat', 'cors')).toBe('chat');
    expect(classifyRequest('/api/chat/voice', 'cors')).toBe('chat');
    expect(classifyRequest('http://localhost:3000/api/chat?sessionId=123', 'cors')).toBe('chat');
  });

  it('classifies advisory requests correctly', () => {
    expect(classifyRequest('/api/pfz', 'cors')).toBe('advisory');
    expect(classifyRequest('/api/pfz?sector=KC', 'cors')).toBe('advisory');
    expect(classifyRequest('/api/status', 'cors')).toBe('advisory');
    expect(classifyRequest('/api/geofence', 'cors')).toBe('advisory');
    expect(classifyRequest('/api/geofence/check', 'cors')).toBe('advisory');
  });

  it('classifies weather requests as advisory', () => {
    expect(classifyRequest('/api/weather/current?lat=9.9&lon=76.2', 'cors')).toBe('advisory');
    expect(classifyRequest('/api/weather/forecast', 'cors')).toBe('advisory');
  });

  it('preserves navigation and chat precedence with weather paths', () => {
    expect(classifyRequest('/api/weather/current?lat=9.9&lon=76.2', 'navigate')).toBe('navigation');
    expect(classifyRequest('/api/chat/weather', 'cors')).toBe('chat');
    expect(classifyRequest('/api/chat', 'cors')).toBe('chat');
  });

  it('classifies tile requests from OSM hosts and tile path patterns', () => {
    expect(classifyRequest('https://tile.openstreetmap.org/1/2/3.png', 'no-cors')).toBe('tile');
    expect(classifyRequest('https://a.tile.openstreetmap.org/1/2/3.png', 'no-cors')).toBe('tile');
    expect(classifyRequest('https://b.tile.openstreetmap.org/10/20/30.png', 'no-cors')).toBe('tile');
    expect(classifyRequest('/api/tiles/1/2/3.png', 'cors')).toBe('tile');
    expect(classifyRequest('/tiles/12/34/56.webp', 'cors')).toBe('tile');
    expect(classifyRequest('https://custom-tiles.org/osm/5/10/15.jpg', 'no-cors')).toBe('tile');
  });

  it('classifies static assets correctly', () => {
    expect(classifyRequest('/_next/static/chunk.js', 'cors')).toBe('static');
    expect(classifyRequest('/_next/static/css/app.css', 'cors')).toBe('static');
    expect(classifyRequest('/favicon.svg', 'no-cors')).toBe('static');
    expect(classifyRequest('/icons/orca-192.png', 'no-cors')).toBe('static');
    expect(classifyRequest('/fonts/font.woff2', 'cors')).toBe('static');
    expect(classifyRequest('/manifest.webmanifest', 'cors')).toBe('static');
  });

  it('classifies unhandled paths as other', () => {
    expect(classifyRequest('/api/officer/register', 'cors')).toBe('other');
    expect(classifyRequest('/external-api/data', 'cors')).toBe('other');
  });

  it('respects precedence rules', () => {
    // Navigation takes precedence over chat/api/static
    expect(classifyRequest('/api/chat', 'navigate')).toBe('navigation');
    expect(classifyRequest('/_next/static/chunk.js', 'navigate')).toBe('navigation');
    // Chat takes precedence over general advisory/static
    expect(classifyRequest('/api/chat', 'cors')).toBe('chat');
    // Tile takes precedence over static (even though tile has .png)
    expect(classifyRequest('https://tile.openstreetmap.org/1/2/3.png', 'no-cors')).toBe('tile');
    expect(classifyRequest('/api/tiles/1/2/3.png', 'cors')).toBe('tile');
  });
});

describe('Service Worker Policy — isCacheableResponse', () => {
  it('returns true strictly for status 200', () => {
    expect(isCacheableResponse(200)).toBe(true);
    expect(isCacheableResponse(204)).toBe(false);
    expect(isCacheableResponse(301)).toBe(false);
    expect(isCacheableResponse(302)).toBe(false);
    expect(isCacheableResponse(400)).toBe(false);
    expect(isCacheableResponse(404)).toBe(false);
    expect(isCacheableResponse(500)).toBe(false);
    expect(isCacheableResponse(503)).toBe(false);
  });
});

describe('Service Worker Policy — createLru', () => {
  it('tracks size and keys correctly', () => {
    const lru = createLru({ maxBytes: 1000, maxEntries: 10 });
    expect(lru.size()).toBe(0);
    expect(lru.keys()).toEqual([]);

    lru.put('tile-1', 200);
    expect(lru.size()).toBe(200);
    expect(lru.has('tile-1')).toBe(true);
    expect(lru.get('tile-1')).toBe(200);

    lru.put('tile-2', 300);
    expect(lru.size()).toBe(500);
    expect(lru.keys()).toEqual(['tile-1', 'tile-2']);
  });

  it('updating existing key refreshes recency and updates size', () => {
    const lru = createLru({ maxBytes: 1000, maxEntries: 10 });
    lru.put('tile-1', 200);
    lru.put('tile-2', 300);
    lru.put('tile-1', 250);

    expect(lru.size()).toBe(550);
    expect(lru.keys()).toEqual(['tile-2', 'tile-1']);
  });

  it('evicts least-recently-used when exceeding byte budget', () => {
    const lru = createLru({ maxBytes: 500, maxEntries: 10 });
    lru.put('tile-1', 200);
    lru.put('tile-2', 200);
    expect(lru.size()).toBe(400);

    // Adding tile-3 (200B) pushes total to 600B > 500B budget. tile-1 should be evicted.
    lru.put('tile-3', 200);
    expect(lru.has('tile-1')).toBe(false);
    expect(lru.has('tile-2')).toBe(true);
    expect(lru.has('tile-3')).toBe(true);
    expect(lru.size()).toBe(400);
  });

  it('get refreshes recency so eviction removes a different key', () => {
    const lru = createLru({ maxBytes: 500, maxEntries: 10 });
    lru.put('tile-1', 200);
    lru.put('tile-2', 200);

    // Reading tile-1 refreshes it to most recently used
    expect(lru.get('tile-1')).toBe(200);

    // Now inserting tile-3 (200B) should evict tile-2, not tile-1
    lru.put('tile-3', 200);
    expect(lru.has('tile-2')).toBe(false);
    expect(lru.has('tile-1')).toBe(true);
    expect(lru.has('tile-3')).toBe(true);
    expect(lru.size()).toBe(400);
  });

  it('has refreshes recency as well', () => {
    const lru = createLru({ maxBytes: 500, maxEntries: 10 });
    lru.put('tile-1', 200);
    lru.put('tile-2', 200);

    // Checking has('tile-1') refreshes it to most recently used
    expect(lru.has('tile-1')).toBe(true);

    // Inserting tile-3 (200B) should evict tile-2
    lru.put('tile-3', 200);
    expect(lru.has('tile-2')).toBe(false);
    expect(lru.has('tile-1')).toBe(true);
    expect(lru.has('tile-3')).toBe(true);
  });

  it('evicts when exceeding entry count limit', () => {
    const lru = createLru({ maxBytes: 10000, maxEntries: 2 });
    lru.put('tile-1', 100);
    lru.put('tile-2', 100);
    expect(lru.keys()).toEqual(['tile-1', 'tile-2']);

    lru.put('tile-3', 100);
    expect(lru.has('tile-1')).toBe(false);
    expect(lru.keys()).toEqual(['tile-2', 'tile-3']);
  });

  it('single oversized entry survives alone without evicting itself', () => {
    const lru = createLru({ maxBytes: 500, maxEntries: 10 });
    lru.put('tile-1', 200);
    lru.put('tile-2', 200);

    // Insert single entry larger than maxBytes (600B > 500B)
    lru.put('giant-tile', 600);

    // All previous entries evicted, but giant-tile itself is preserved
    expect(lru.has('tile-1')).toBe(false);
    expect(lru.has('tile-2')).toBe(false);
    expect(lru.has('giant-tile')).toBe(true);
    expect(lru.size()).toBe(600);
  });

  it('prune manually enforces limits', () => {
    const lru = createLru({ maxBytes: 400, maxEntries: 5 });
    lru.put('tile-1', 200);
    lru.put('tile-2', 200);
    expect(lru.size()).toBe(400);

    // Lowering or calling prune() returns evicted keys
    const evicted = lru.prune();
    expect(evicted).toEqual([]);
  });

  it('uses default CACHE_BUDGET_BYTES and TILE_ENTRY_LIMIT when options omitted', () => {
    const lru = createLru();
    lru.put('tile-1', 1024);
    expect(lru.get('tile-1')).toBe(1024);
    expect(lru.size()).toBe(1024);
  });
});

describe('Service Worker Policy — tile classification & opaque caching', () => {
  it('classifies extensionless ESRI MapServer tile URLs as tile', () => {
    expect(
      classifyRequest(
        'https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Base/MapServer/tile/6/23/36',
        'no-cors'
      )
    ).toBe('tile');
    expect(
      classifyRequest('https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Base/MapServer/info.json', 'cors')
    ).toBe('other');
  });

  it('isCacheableTileResponse accepts 200 and opaque responses, rejects others', () => {
    expect(isCacheableTileResponse({ status: 200, type: 'basic' })).toBe(true);
    expect(isCacheableTileResponse({ status: 0, type: 'opaque' })).toBe(true);
    expect(isCacheableTileResponse({ status: 500, type: 'basic' })).toBe(false);
    expect(isCacheableTileResponse({ status: 404, type: 'basic' })).toBe(false);
  });

  it('isCacheableResponse stays strict status 200 for non-tile traffic', () => {
    expect(isCacheableResponse(0)).toBe(false);
    expect(isCacheableResponse(503)).toBe(false);
  });
});
