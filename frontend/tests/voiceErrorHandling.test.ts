/**
 * Unit & Integration tests for US-VOICE-503:
 * Vernacular voice error handling, actionable messages, and retry contracts.
 *
 * Run: bun test tests/voiceErrorHandling.test.ts
 */
import { describe, expect, it } from 'bun:test';
import {
  VOICE_ERROR_MESSAGES,
  getVoiceErrorMessage,
  parseVoiceError,
  type VoiceErrorPayload,
} from '../chat/useSSEChat';

describe('US-VOICE-503: Voice Error Code Actionable Messages', () => {
  it('defines exact blueprint messages for all 6 voice error codes', () => {
    expect(VOICE_ERROR_MESSAGES.ASR_CONFIG_MISSING).toBe(
      'Voice input is currently unavailable on the server. Please type your message.'
    );
    expect(VOICE_ERROR_MESSAGES.NO_SPEECH_DETECTED).toBe(
      'No speech was detected. Please hold the microphone and speak clearly.'
    );
    expect(VOICE_ERROR_MESSAGES.BHASHINI_UPSTREAM_ERROR).toBe(
      'Voice recognition service is temporarily unavailable. Please retry or type your message.'
    );
    expect(VOICE_ERROR_MESSAGES.ASR_TIMEOUT).toBe(
      'Voice transcription request timed out. Please try again.'
    );
    expect(VOICE_ERROR_MESSAGES.AUDIO_PROCESSING_ERROR).toBe(
      'Audio could not be processed. Please try recording again.'
    );
    expect(VOICE_ERROR_MESSAGES.AUDIO_TOO_LARGE).toBe(
      'Audio file exceeds 25MB limit. Please record a shorter message.'
    );
  });

  it('getVoiceErrorMessage extracts actionable message based on error_code', () => {
    const payload1: VoiceErrorPayload = {
      detail: 'Credentials not configured',
      error_code: 'ASR_CONFIG_MISSING',
      retryable: false,
    };
    expect(getVoiceErrorMessage(payload1, 503)).toBe(
      'Voice input is currently unavailable on the server. Please type your message.'
    );

    const payload2: VoiceErrorPayload = {
      detail: 'No speech in file',
      error_code: 'NO_SPEECH_DETECTED',
      retryable: true,
    };
    expect(getVoiceErrorMessage(payload2, 422)).toBe(
      'No speech was detected. Please hold the microphone and speak clearly.'
    );

    const payload3: VoiceErrorPayload = {
      detail: 'Gateway timed out',
      error_code: 'ASR_TIMEOUT',
      retryable: true,
    };
    expect(getVoiceErrorMessage(payload3, 504)).toBe(
      'Voice transcription request timed out. Please try again.'
    );

    const payload4: VoiceErrorPayload = {
      detail: 'Upstream connection error',
      error_code: 'BHASHINI_UPSTREAM_ERROR',
      retryable: true,
    };
    expect(getVoiceErrorMessage(payload4, 502)).toBe(
      'Voice recognition service is temporarily unavailable. Please retry or type your message.'
    );
  });

  it('getVoiceErrorMessage falls back gracefully when error_code is absent', () => {
    expect(getVoiceErrorMessage({ detail: 'Too large' }, 413)).toBe(
      'Audio file exceeds 25MB limit. Please record a shorter message.'
    );
    expect(getVoiceErrorMessage({ detail: 'Unprocessable' }, 422)).toBe(
      'No speech was detected. Please hold the microphone and speak clearly.'
    );
    expect(getVoiceErrorMessage({ detail: 'Timed out' }, 504)).toBe(
      'Voice transcription request timed out. Please try again.'
    );
    expect(getVoiceErrorMessage({ detail: 'Bad gateway' }, 502)).toBe(
      'Voice recognition service is temporarily unavailable. Please retry or type your message.'
    );
    expect(getVoiceErrorMessage({ detail: 'ASR config missing' }, 503)).toBe(
      'Voice input is currently unavailable on the server. Please type your message.'
    );
  });

  it('parseVoiceError parses Response JSON and extracts message', async () => {
    const mockRes = new Response(
      JSON.stringify({
        detail: 'Timeout after 30s',
        error_code: 'ASR_TIMEOUT',
        retryable: true,
      }),
      {
        status: 504,
        headers: { 'Content-Type': 'application/json' },
      }
    );

    const result = await parseVoiceError(mockRes);
    expect(result.payload?.error_code).toBe('ASR_TIMEOUT');
    expect(result.payload?.retryable).toBe(true);
    expect(result.message).toBe('Voice transcription request timed out. Please try again.');
  });

  it('parseVoiceError handles FastAPI nested detail dictionary', async () => {
    const mockRes = new Response(
      JSON.stringify({
        detail: {
          detail: 'Voice transcription service is unconfigured.',
          error_code: 'ASR_CONFIG_MISSING',
          retryable: false,
        },
      }),
      {
        status: 503,
        headers: { 'Content-Type': 'application/json' },
      }
    );

    const result = await parseVoiceError(mockRes);
    expect(result.payload?.error_code).toBe('ASR_CONFIG_MISSING');
    expect(result.payload?.retryable).toBe(false);
    expect(result.message).toBe(
      'Voice input is currently unavailable on the server. Please type your message.'
    );
  });

  it('parseVoiceError handles non-JSON response body', async () => {
    const mockRes = new Response('<html>502 Bad Gateway</html>', {
      status: 502,
      headers: { 'Content-Type': 'text/html' },
    });

    const result = await parseVoiceError(mockRes);
    expect(result.payload).toBeNull();
    expect(result.message).toBe(
      'Voice recognition service is temporarily unavailable. Please retry or type your message.'
    );
  });
});

describe('US-VOICE-503: Voice Proxy Route Tests', () => {
  it('proxy route returns 504 on abort with exact payload', async () => {
    const { POST } = await import('../app/api/chat/voice/route');
    const originalFetch = globalThis.fetch;
    try {
      globalThis.fetch = () => {
        const abortErr = new Error('The operation was aborted.');
        abortErr.name = 'AbortError';
        return Promise.reject(abortErr);
      };

      const formData = new FormData();
      formData.append('file', new Blob(['test'], { type: 'audio/wav' }), 'test.wav');
      const req = new Request('http://localhost:3000/api/chat/voice', {
        method: 'POST',
        body: formData,
      });

      const res = await POST(req as any);
      expect(res.status).toBe(504);
      const json = await res.json();
      expect(json).toEqual({
        detail: 'Voice transcription timed out.',
        error_code: 'ASR_TIMEOUT',
        retryable: true,
      });
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it('proxy route returns 502 on network/connection error with exact payload', async () => {
    const { POST } = await import('../app/api/chat/voice/route');
    const originalFetch = globalThis.fetch;
    try {
      globalThis.fetch = () => {
        return Promise.reject(new Error('ECONNREFUSED'));
      };

      const formData = new FormData();
      formData.append('file', new Blob(['test'], { type: 'audio/wav' }), 'test.wav');
      const req = new Request('http://localhost:3000/api/chat/voice', {
        method: 'POST',
        body: formData,
      });

      const res = await POST(req as any);
      expect(res.status).toBe(502);
      expect(res.headers.get('x-orca-proxy-error')).toBe('connection-failed');
      const json = await res.json();
      expect(json).toEqual({
        detail: 'Failed to connect to backend voice service.',
        error_code: 'PROXY_CONNECTION_FAILED',
        retryable: true,
      });
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it('proxy route forwards non-200 JSON error body intact', async () => {
    const { POST } = await import('../app/api/chat/voice/route');
    const originalFetch = globalThis.fetch;
    try {
      globalThis.fetch = () => {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              detail: {
                detail: 'Bhashini credentials not found in environment.',
                error_code: 'ASR_CONFIG_MISSING',
                retryable: false,
              },
            }),
            {
              status: 503,
              headers: { 'Content-Type': 'application/json' },
            }
          )
        );
      };

      const formData = new FormData();
      formData.append('file', new Blob(['test'], { type: 'audio/wav' }), 'test.wav');
      const req = new Request('http://localhost:3000/api/chat/voice', {
        method: 'POST',
        body: formData,
      });

      const res = await POST(req as any);
      expect(res.status).toBe(503);
      const json = await res.json();
      expect(json).toEqual({
        detail: 'Bhashini credentials not found in environment.',
        error_code: 'ASR_CONFIG_MISSING',
        retryable: false,
      });
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it('proxy route forwards 422 with NO_SPEECH_DETECTED and retryable=false', async () => {
    const { POST } = await import('../app/api/chat/voice/route');
    const originalFetch = globalThis.fetch;
    try {
      globalThis.fetch = () => {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              detail: {
                detail: 'Audio file is empty',
                error_code: 'NO_SPEECH_DETECTED',
                retryable: false,
              },
            }),
            {
              status: 422,
              headers: { 'Content-Type': 'application/json' },
            }
          )
        );
      };

      const formData = new FormData();
      formData.append('file', new Blob([], { type: 'audio/wav' }), 'empty.wav');
      const req = new Request('http://localhost:3000/api/chat/voice', {
        method: 'POST',
        body: formData,
      });

      const res = await POST(req as any);
      expect(res.status).toBe(422);
      const json = await res.json();
      expect(json).toEqual({
        detail: 'Audio file is empty',
        error_code: 'NO_SPEECH_DETECTED',
        retryable: false,
      });
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it('fail-closed: proxy route never produces mock or hallucinated transcription on error', async () => {
    const { POST } = await import('../app/api/chat/voice/route');
    const originalFetch = globalThis.fetch;
    try {
      globalThis.fetch = () => {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              detail: {
                detail: 'Upstream ASR failure',
                error_code: 'BHASHINI_UPSTREAM_ERROR',
                retryable: true,
              },
            }),
            {
              status: 502,
              headers: { 'Content-Type': 'application/json' },
            }
          )
        );
      };

      const formData = new FormData();
      formData.append('file', new Blob(['test'], { type: 'audio/wav' }), 'test.wav');
      const req = new Request('http://localhost:3000/api/chat/voice', {
        method: 'POST',
        body: formData,
      });

      const res = await POST(req as any);
      expect(res.status).toBe(502);
      const json = await res.json();
      expect(json.transcription).toBeUndefined();
      expect(json.mock).toBeUndefined();
      expect(json.error_code).toBe('BHASHINI_UPSTREAM_ERROR');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });
});
