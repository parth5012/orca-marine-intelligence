/**
 * PFZ fetch cache (perf hardening #198).
 *
 * 60s TTL in-memory cache per request URL + in-flight dedup, so sector
 * switches and repeated Find-Nearest clicks reuse one
 * `/api/pfz?limit=200` payload per sector instead of refetching every
 * click. Stale-while-revalidate: a failed refresh still serves the last
 * good payload (live-only — never synthetic zones).
 */

const TTL_MS = 60_000;

export const PFZ_CACHE_TTL_MS = TTL_MS;

type Entry = { at: number; data: any };

const cache = new Map<string, Entry>();
const inflight = new Map<string, Promise<any>>();

export function clearPfzCache(): void {
  cache.clear();
  inflight.clear();
}

/**
 * Fetch a PFZ JSON payload with 60s caching + in-flight dedup.
 * Resolves to the parsed JSON body (throws on HTTP error with no stale copy).
 */
export async function fetchPfzCached(url: string, init?: RequestInit): Promise<any> {
  const now = Date.now();
  const hit = cache.get(url);
  if (hit && now - hit.at < TTL_MS) return hit.data;

  const ongoing = inflight.get(url);
  if (ongoing) return ongoing;

  const req = fetch(url, init)
    .then(async (res) => {
      if (!res.ok) throw new Error(`pfz ${res.status}`);
      const data = await res.json();
      cache.set(url, { at: Date.now(), data });
      return data;
    })
    .finally(() => {
      inflight.delete(url);
    });
  inflight.set(url, req);

  try {
    return await req;
  } catch (err) {
    // SWR: serve stale payload when the refresh fails.
    const stale = cache.get(url);
    if (stale) return stale.data;
    throw err;
  }
}
