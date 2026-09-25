/**
 * Classification of mid-stream SSE failures for the chat UI.
 *
 * Owner: M-E (Frontend & Chat)
 * Module: frontend/chat/streamFailure.ts
 *
 * Firefox aborts text/event-stream responses after ~10-12s without bytes
 * (github.com/enisdenjo/graphql-sse/issues/99 — `TypeError: Error in input
 * stream`). The backend now sends keepalive comments so this should no
 * longer happen, but any transport failure must still not leak raw engine
 * text into the red banner when the reply / trace / zone cards already
 * rendered.
 */

export type StreamFailureKind = 'transport' | 'explicit';

export interface StreamFailure {
  kind: StreamFailureKind;
  /** `warning` keeps the partial reply and renders a non-fatal banner. */
  severity: 'warning' | 'fatal';
  message: string;
}

/** Known cross-engine messages produced by a broken response body stream. */
const TRANSPORT_PATTERNS: readonly string[] = [
  'error in input stream', // Firefox: silent SSE response aborted
  'network error', // Firefox fetch() failure
  'failed to fetch', // Chrome fetch() failure
  'load failed', // Safari fetch() failure
  'terminated', // undici/Node body terminated
  'the operation was interrupted',
];

const INTERRUPTED_MESSAGE =
  'Connection to ORCA was interrupted before the reply finished. Please try again.';

const INTERRUPTED_PARTIAL_MESSAGE =
  'Connection to ORCA was interrupted — showing what was received so far.';

const DEFAULT_MESSAGE = 'Failed to connect to ORCA advisory stream.';

export function describeStreamFailure(input: {
  name?: string;
  message?: string;
  hasPartialResult: boolean;
}): StreamFailure {
  const name = input.name || '';
  const raw = (input.message || '').trim();
  const lowered = raw.toLowerCase();

  const isTransport =
    name === 'TypeError' ||
    TRANSPORT_PATTERNS.some((pattern) => lowered.includes(pattern));

  if (!isTransport) {
    // Constructed errors (`Chat proxy error: 504 ...`) are actionable —
    // surface them verbatim.
    return {
      kind: 'explicit',
      severity: 'fatal',
      message: raw || DEFAULT_MESSAGE,
    };
  }

  if (input.hasPartialResult) {
    return {
      kind: 'transport',
      severity: 'warning',
      message: INTERRUPTED_PARTIAL_MESSAGE,
    };
  }
  return {
    kind: 'transport',
    severity: 'fatal',
    message: INTERRUPTED_MESSAGE,
  };
}
