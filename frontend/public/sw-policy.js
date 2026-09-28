/**
 * Service Worker Policy & Cache Rules.
 * Pure logic for request classification, caching eligibility, and bounded tile LRU.
 *
 * Owner: M-E (Frontend Chat & App Shell)
 * Module: frontend/public/sw-policy.js
 */

export const CACHE_BUDGET_BYTES = 50 * 1024 * 1024;
export const TILE_ENTRY_LIMIT = 2000;
export const OFFLINE_SHELL_PATHS = [
  '/',
  '/map',
  '/officer',
  '/manifest.webmanifest',
];

export function isCacheableResponse(status) {
  return status === 200;
}

export function classifyRequest(url, mode) {
  if (mode === 'navigate') {
    return 'navigation';
  }

  let pathname = '';
  let hostname = '';

  try {
    const parsed = new URL(url, 'http://localhost');
    pathname = parsed.pathname;
    hostname = parsed.hostname;
  } catch {
    pathname = typeof url === 'string' ? url : '';
  }

  // 1. Chat requests (never cached)
  if (pathname.startsWith('/api/chat')) {
    return 'chat';
  }

  // 2. Advisory requests
  if (
    pathname.startsWith('/api/pfz') ||
    pathname === '/api/status' ||
    pathname.startsWith('/api/geofence') ||
    pathname.startsWith('/api/weather')
  ) {
    return 'advisory';
  }

  // 3. Tile requests
  const isOsmHost =
    hostname === 'tile.openstreetmap.org' ||
    hostname.endsWith('.tile.openstreetmap.org');
  const isTileApi = pathname.startsWith('/api/tiles');
  const isRasterTilePattern =
    /\/\d+\/\d+\/\d+\.(?:png|webp|jpg)(?:$|[?#])/i.test(pathname) ||
    /\/\d+\/\d+\/\d+\.(?:png|webp|jpg)\b/i.test(pathname);

  if (isOsmHost || isTileApi || isRasterTilePattern) {
    return 'tile';
  }

  // 4. Static assets
  if (
    pathname.startsWith('/_next/static/') ||
    /\.(?:js|css|woff2|png|svg|webmanifest)$/i.test(pathname)
  ) {
    return 'static';
  }

  return 'other';
}

export function createLru(options = {}) {
  const maxBytes =
    typeof options.maxBytes === 'number' ? options.maxBytes : CACHE_BUDGET_BYTES;
  const maxEntries =
    typeof options.maxEntries === 'number' ? options.maxEntries : TILE_ENTRY_LIMIT;
  const onEvict =
    typeof options.onEvict === 'function' ? options.onEvict : null;

  const map = new Map();
  let totalBytes = 0;

  function pruneInternal(protectKey = null) {
    const evicted = [];
    while (
      (totalBytes > maxBytes || map.size > maxEntries) &&
      map.size > (protectKey ? 1 : 0)
    ) {
      const oldestKey = map.keys().next().value;
      if (protectKey && oldestKey === protectKey) {
        break;
      }
      const entry = map.get(oldestKey);
      totalBytes -= entry.size;
      map.delete(oldestKey);
      evicted.push(oldestKey);
      if (onEvict) {
        onEvict(oldestKey, entry.value);
      }
    }
    return evicted;
  }

  return {
    put(key, sizeOrValue, explicitSize) {
      const size =
        typeof explicitSize === 'number'
          ? explicitSize
          : typeof sizeOrValue === 'number'
            ? sizeOrValue
            : 0;
      const value =
        explicitSize !== undefined
          ? sizeOrValue
          : typeof sizeOrValue === 'number'
            ? sizeOrValue
            : sizeOrValue;

      if (map.has(key)) {
        const old = map.get(key);
        totalBytes -= old.size;
        map.delete(key);
      }

      totalBytes += size;
      map.set(key, { value, size });

      return pruneInternal(key);
    },

    has(key) {
      if (!map.has(key)) return false;
      const entry = map.get(key);
      map.delete(key);
      map.set(key, entry);
      return true;
    },

    get(key) {
      if (!map.has(key)) return undefined;
      const entry = map.get(key);
      map.delete(key);
      map.set(key, entry);
      return entry.value;
    },

    size() {
      return totalBytes;
    },

    keys() {
      return Array.from(map.keys());
    },

    prune() {
      return pruneInternal(null);
    },
  };
}
