/**
 * Type declarations for frontend/public/sw-policy.js
 *
 * Owner: M-E (Frontend Chat & App Shell)
 * Module: frontend/public/sw-policy.d.ts
 */

export const CACHE_BUDGET_BYTES: number;
export const TILE_ENTRY_LIMIT: number;
export const OFFLINE_SHELL_PATHS: readonly string[];

export type RequestKind =
  | 'navigation'
  | 'advisory'
  | 'tile'
  | 'chat'
  | 'static'
  | 'other';

export function classifyRequest(url: string, mode?: string): RequestKind;

export function isCacheableResponse(status: number): boolean;

export interface LruOptions<T = any> {
  maxBytes?: number;
  maxEntries?: number;
  onEvict?: (key: string, value: T) => void;
}

export interface LruCache<T = any> {
  put(key: string, sizeOrValue: number | T, explicitSize?: number): string[];
  has(key: string): boolean;
  get(key: string): T | undefined;
  size(): number;
  keys(): string[];
  prune(): string[];
}

export function createLru<T = any>(options?: LruOptions<T>): LruCache<T>;

declare global {
  interface Window {
    __orcaChatStreamActive?: boolean;
  }
}
