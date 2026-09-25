/**
 * Unit tests for frontend/chat/streamFailure.ts — classification of
 * mid-stream SSE failures surfaced by useSSEChat's catch block.
 *
 * Bug context: Firefox aborts text/event-stream responses after ~10-12s of
 * silence with `TypeError: Error in input stream`, which previously leaked
 * as the raw red banner "⚠️ Error in input stream" even though the pipeline
 * trace / zone cards had already rendered.
 *
 * Owner: M-E (Frontend & Chat)
 * Module: frontend/tests/streamFailure.test.ts
 */

import { describe, expect, it } from 'bun:test';
import { describeStreamFailure } from '../chat/streamFailure';

describe('describeStreamFailure', () => {
  it('treats Firefox "Error in input stream" as a transport failure', () => {
    const result = describeStreamFailure({
      name: 'TypeError',
      message: 'Error in input stream',
      hasPartialResult: true,
    });
    expect(result.kind).toBe('transport');
    expect(result.severity).toBe('warning');
    expect(result.message).not.toContain('input stream');
  });

  it('degrades to a friendly fatal message when nothing was rendered yet', () => {
    const result = describeStreamFailure({
      name: 'TypeError',
      message: 'Error in input stream',
      hasPartialResult: false,
    });
    expect(result.kind).toBe('transport');
    expect(result.severity).toBe('fatal');
    expect(result.message).not.toContain('input stream');
    expect(result.message.toLowerCase()).toContain('interrupted');
  });

  it('keeps constructed HTTP/proxy errors verbatim (they are actionable)', () => {
    const result = describeStreamFailure({
      name: 'Error',
      message: 'Chat proxy error: 504 Gateway Timeout',
      hasPartialResult: false,
    });
    expect(result.kind).toBe('explicit');
    expect(result.severity).toBe('fatal');
    expect(result.message).toBe('Chat proxy error: 504 Gateway Timeout');
  });

  it('recognises other engines’ transport errors (Chrome/Firefox/Safari)', () => {
    for (const message of [
      'network error',
      'Failed to fetch',
      'Load failed',
      'terminated',
      'The operation was interrupted.',
    ]) {
      const result = describeStreamFailure({
        name: 'TypeError',
        message,
        hasPartialResult: true,
      });
      expect(result.kind).toBe('transport');
      expect(result.severity).toBe('warning');
    }
  });

  it('falls back to the default copy when the engine gives no message', () => {
    const result = describeStreamFailure({
      name: 'TypeError',
      message: '',
      hasPartialResult: false,
    });
    expect(result.severity).toBe('fatal');
    expect(result.message.length).toBeGreaterThan(0);
  });
});
