/**
 * ORCA Marine Intelligence — Service Worker (ES Module).
 * Offline caching for navigation shells, advisory snapshots, and LRU raster tiles.
 *
 * Owner: M-E (Frontend Chat & App Shell)
 * Module: frontend/public/sw.js
 */

import {
  classifyRequest,
  createLru,
  isCacheableResponse,
  isCacheableTileResponse,
  OFFLINE_SHELL_PATHS,
  CACHE_BUDGET_BYTES,
  TILE_ENTRY_LIMIT,
} from './sw-policy.js';

const SHELL_CACHE = 'orca-shell-v1';
const ADVISORY_CACHE = 'orca-advisory-v1';
const TILES_CACHE = 'orca-tiles-v1';
const KNOWN_CACHES = new Set([SHELL_CACHE, ADVISORY_CACHE, TILES_CACHE]);

const FALLBACK_HTML = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ORCA Marine Intelligence — Offline</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #edf6ff; color: #0B3C5D; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 1rem; box-sizing: border-box; }
    .card { background: white; padding: 2rem; border-radius: 0.75rem; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); max-width: 28rem; text-align: center; }
    h1 { margin-top: 0; font-size: 1.5rem; }
    p { color: #475569; line-height: 1.5; }
  </style>
</head>
<body>
  <div class="card">
    <h1>ORCA Marine Intelligence</h1>
    <p>You are currently offline. Please reconnect to access live marine intelligence and satellite advisories.</p>
  </div>
</body>
</html>`;

const tileLru = createLru({
  maxBytes: CACHE_BUDGET_BYTES,
  maxEntries: TILE_ENTRY_LIMIT,
  onEvict: (evictedUrl) => {
    if ('caches' in self) {
      caches.open(TILES_CACHE).then((cache) => cache.delete(evictedUrl)).catch(() => {});
    }
  },
});

let lruRestored = false;
let lruRestorePromise = null;

async function ensureTileLru() {
  if (lruRestored) return;
  if (!lruRestorePromise) {
    lruRestorePromise = (async () => {
      try {
        if ('caches' in self) {
          const cache = await caches.open(TILES_CACHE);
          const requests = await cache.keys();
          for (const req of requests) {
            const res = await cache.match(req);
            const cl = res?.headers.get('content-length');
            const size = cl ? parseInt(cl, 10) : 25000;
            tileLru.put(req.url, isNaN(size) ? 25000 : size);
          }
        }
      } catch {}
      lruRestored = true;
    })();
  }
  return lruRestorePromise;
}

async function recordTilePut(cache, request, response) {
  try {
    const cl = response.headers.get('content-length');
    const size = cl ? parseInt(cl, 10) : 25000;
    const evicted = tileLru.put(request.url, isNaN(size) ? 25000 : size);
    for (const key of evicted) {
      await cache.delete(key);
    }
  } catch {}
}

self.addEventListener('install', (event) => {
  event.waitUntil(
    (async () => {
      try {
        if ('caches' in self) {
          const cache = await caches.open(SHELL_CACHE);
          try {
            await cache.addAll(OFFLINE_SHELL_PATHS);
          } catch {
            await Promise.allSettled(
              OFFLINE_SHELL_PATHS.map(async (path) => {
                const res = await fetch(path);
                if (res.ok) await cache.put(path, res);
              })
            );
          }
        }
      } catch {}
      await self.skipWaiting();
    })()
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      try {
        if ('caches' in self) {
          const keys = await caches.keys();
          await Promise.all(
            keys
              .filter((key) => !KNOWN_CACHES.has(key))
              .map((key) => caches.delete(key))
          );
        }
      } catch {}
      if (self.clients && self.clients.claim) {
        await self.clients.claim();
      }
    })()
  );
});

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  const kind = classifyRequest(request.url, request.mode);

  if (kind === 'chat' || kind === 'other') {
    return;
  }

  if (kind === 'navigation') {
    event.respondWith(
      (async () => {
        try {
          const netRes = await fetch(request);
          if (isCacheableResponse(netRes.status) && 'caches' in self) {
            const copy = netRes.clone();
            event.waitUntil(
              caches.open(SHELL_CACHE).then((cache) => cache.put(request, copy)).catch(() => {})
            );
          }
          return netRes;
        } catch {
          try {
            if ('caches' in self) {
              const cache = await caches.open(SHELL_CACHE);
              const pathMatch = await cache.match(request);
              if (pathMatch) return pathMatch;
              const rootMatch = await cache.match('/');
              if (rootMatch) return rootMatch;
            }
          } catch {}
          return new Response(FALLBACK_HTML, {
            status: 200,
            headers: { 'Content-Type': 'text/html; charset=utf-8' },
          });
        }
      })()
    );
    return;
  }

  if (kind === 'advisory') {
    event.respondWith(
      (async () => {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 6000);
        try {
          const netRes = await fetch(request, { signal: controller.signal });
          clearTimeout(timeoutId);
          if (isCacheableResponse(netRes.status)) {
            if ('caches' in self) {
              const copy = netRes.clone();
              event.waitUntil(
                caches.open(ADVISORY_CACHE).then((cache) => cache.put(request, copy)).catch(() => {})
              );
            }
            return netRes;
          }
          if ('caches' in self) {
            const cache = await caches.open(ADVISORY_CACHE);
            const cached = await cache.match(request);
            if (cached && isCacheableResponse(cached.status)) {
              return cached;
            }
          }
          return netRes;
        } catch {
          clearTimeout(timeoutId);
          try {
            if ('caches' in self) {
              const cache = await caches.open(ADVISORY_CACHE);
              const cached = await cache.match(request);
              if (cached && isCacheableResponse(cached.status)) {
                return cached;
              }
            }
          } catch {}
          return new Response(
            JSON.stringify({ error: 'Offline — advisory snapshot unavailable' }),
            {
              status: 504,
              headers: { 'Content-Type': 'application/json; charset=utf-8' },
            }
          );
        }
      })()
    );
    return;
  }

  if (kind === 'tile') {
    event.respondWith(
      (async () => {
        try {
          await ensureTileLru();
          let cache = null;
          if ('caches' in self) {
            cache = await caches.open(TILES_CACHE);
          }
          if (cache) {
            const cached = await cache.match(request);
            if (cached && isCacheableTileResponse(cached)) {
              tileLru.get(request.url);
              event.waitUntil(
                fetch(request)
                  .then(async (netRes) => {
                    if (isCacheableTileResponse(netRes)) {
                      await cache.put(request, netRes.clone());
                      await recordTilePut(cache, request, netRes);
                    }
                  })
                  .catch(() => {})
              );
              return cached;
            }
          }

          const netRes = await fetch(request);
          if (isCacheableTileResponse(netRes) && cache) {
            const copy = netRes.clone();
            event.waitUntil(
              (async () => {
                try {
                  await cache.put(request, copy);
                  await recordTilePut(cache, request, netRes);
                } catch {}
              })()
            );
          }
          return netRes;
        } catch {
          return new Response(null, {
            status: 504,
            statusText: 'Tile unavailable offline',
          });
        }
      })()
    );
    return;
  }

  if (kind === 'static') {
    event.respondWith(
      (async () => {
        try {
          let cache = null;
          if ('caches' in self) {
            cache = await caches.open(SHELL_CACHE);
          }
          if (cache) {
            const cached = await cache.match(request);
            if (cached) {
              event.waitUntil(
                fetch(request)
                  .then(async (netRes) => {
                    if (isCacheableResponse(netRes.status)) {
                      await cache.put(request, netRes);
                    }
                  })
                  .catch(() => {})
              );
              return cached;
            }
          }

          const netRes = await fetch(request);
          if (isCacheableResponse(netRes.status) && cache) {
            const copy = netRes.clone();
            event.waitUntil(cache.put(request, copy).catch(() => {}));
          }
          return netRes;
        } catch {
          try {
            if ('caches' in self) {
              const cache = await caches.open(SHELL_CACHE);
              const cached = await cache.match(request);
              if (cached) return cached;
            }
          } catch {}
          return new Response('Asset unavailable offline', { status: 504 });
        }
      })()
    );
    return;
  }
});
