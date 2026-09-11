/**
 * VoiceModal (UI-MIG-T7)
 *
 * Owner: M-E (Frontend Chat & App Shell)
 * Module: frontend/components/voice/VoiceModal.tsx
 *
 * Ported UI + animation from source design `voice/VoiceModal` (READ-ONLY):
 * mic pulse rings, equalizer bars, STT transcript box, sample prompts,
 * language bar. NO simulated timers/transcripts.
 *
 * Live-only recording/upload — same flow as ChatPanel.sendVoiceAudio:
 * browser MediaRecorder (audio/webm;codecs=opus) -> POST direct
 * {backend}/api/chat/voice with Next.js /api/chat/voice proxy fallback ->
 * transcription auto-sent via AppContext.submitChatQuery (ChatPanel SSE
 * consumes it like any other query). No new STT vendor.
 * Keeps isTranscribing/voiceError + 25MB limit + 503 messages.
 */

'use client';

import React, { useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Mic, MicOff, X, Sparkles, Radio, RotateCcw, ArrowRight } from 'lucide-react';
import { useApp, KOCHI_FALLBACK } from '@/context/AppContext';
import { INDIAN_LANGUAGES } from '@/lib/translations';

const MAX_AUDIO_BYTES = 25 * 1024 * 1024;

function getBackendBase(): string {
  if (typeof window === 'undefined') return 'http://localhost:8000';
  const envUrl = process.env.NEXT_PUBLIC_API_URL;
  if (envUrl && envUrl.trim().length > 0) return envUrl.replace(/\/$/, '');
  return 'http://localhost:8000';
}

const SAMPLE_VOICE_PROMPTS = [
  'Kal subah fishing ke liye jaana safe hai?',
  'Sabse nearest high-yield PFZ zone kaunsa hai?',
  'Safest navigation route aur wave height batao',
  'Any cyclone or high wave alert in my port?',
];

export const VoiceModal: React.FC = () => {
  const {
    voiceModalOpen,
    setVoiceModalOpen,
    selectedLanguage,
    setSelectedLanguage,
    submitChatQuery,
    userLocation,
    setActiveTab,
    themeMode,
  } = useApp();

  const isLight = themeMode === 'light';

  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const [transcriptText, setTranscriptText] = useState('');
  const [recordingSeconds, setRecordingSeconds] = useState(0);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Reset transient state each time the modal opens.
  useEffect(() => {
    if (voiceModalOpen) {
      setTranscriptText('');
      setVoiceError(null);
      setIsTranscribing(false);
      setRecordingSeconds(0);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [voiceModalOpen]);

  // Release the mic if the modal unmounts mid-recording.
  useEffect(() => {
    return () => {
      try {
        mediaRecorderRef.current?.stream?.getTracks().forEach((t) => t.stop());
      } catch {
        /* already released */
      }
      streamRef.current?.getTracks().forEach((t) => t.stop());
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  const stopTimer = () => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  };

  const uploadAndTranscribe = async (audioBlob: Blob, mimeType: string) => {
    if (audioBlob.size > MAX_AUDIO_BYTES) {
      setVoiceError(
        'Audio file exceeds 25MB. Please record a shorter message and try again.'
      );
      return;
    }
    setIsTranscribing(true);
    setVoiceError(null);
    try {
      const lat = userLocation?.lat ?? KOCHI_FALLBACK.lat;
      const lon = userLocation?.lon ?? KOCHI_FALLBACK.lon;
      const sessionId =
        (typeof window !== 'undefined' &&
          window.localStorage.getItem('orca_session_id')) ||
        `session-${Date.now()}`;
      const formData = new FormData();
      formData.append('file', audioBlob, 'voice.webm');
      formData.append('session_id', sessionId);
      formData.append('lat', String(lat));
      formData.append('lon', String(lon));
      formData.append('language', selectedLanguage || 'en');

      let res: Response;
      try {
        res = await fetch(`${getBackendBase()}/api/chat/voice`, {
          method: 'POST',
          body: formData,
        });
      } catch {
        // Direct backend unreachable — fall back to the Next.js proxy.
        res = await fetch('/api/chat/voice', { method: 'POST', body: formData });
      }

      if (res.status === 413) {
        setVoiceError(
          'Audio file exceeds 25MB. Please record a shorter message and try again.'
        );
        return;
      }
      if (res.status === 503) {
        setVoiceError(
          'Voice transcription unavailable right now (service 503). Please try text input or retry shortly.'
        );
        return;
      }
      if (res.status === 422) {
        setVoiceError(
          'No speech detected in audio. Please record again and speak clearly.'
        );
        return;
      }
      if (!res.ok) {
        throw new Error(`Voice transcription failed: ${res.status}`);
      }
      const data = await res.json();
      const transcription: string = String(data?.transcription ?? '').trim();
      if (data?.session_id && typeof window !== 'undefined') {
        try {
          window.localStorage.setItem('orca_session_id', String(data.session_id));
        } catch {
          /* storage unavailable */
        }
      }
      if (transcription) {
        setTranscriptText(transcription);
      } else {
        setVoiceError('No speech detected in audio.');
      }
    } catch (err: unknown) {
      setVoiceError(
        err instanceof Error ? err.message : 'Voice transcription failed.'
      );
    } finally {
      setIsTranscribing(false);
    }
  };

  const handleMicClick = async () => {
    if (isTranscribing) return;
    // Toggle off: stop recording -> onstop uploads.
    if (isRecording) {
      try {
        mediaRecorderRef.current?.stop();
      } catch {
        setIsRecording(false);
      }
      return;
    }
    setVoiceError(null);
    setTranscriptText('');
    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        setVoiceError('Voice recording is not supported on this browser.');
        return;
      }
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      audioChunksRef.current = [];
      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : 'audio/webm';
      const recorder = new MediaRecorder(stream, { mimeType });
      mediaRecorderRef.current = recorder;
      recorder.ondataavailable = (event: BlobEvent) => {
        if (event.data && event.data.size > 0) audioChunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        stopTimer();
        setIsRecording(false);
        setRecordingSeconds(0);
        const blob = new Blob(audioChunksRef.current, { type: mimeType });
        if (blob.size > 0) void uploadAndTranscribe(blob, mimeType);
      };
      recorder.start(250);
      setIsRecording(true);
      setRecordingSeconds(0);
      timerRef.current = setInterval(
        () => setRecordingSeconds((s) => s + 1),
        1000
      );
    } catch (err: unknown) {
      setIsRecording(false);
      const name = err instanceof Error ? err.name : '';
      if (name === 'NotAllowedError' || name === 'SecurityError') {
        setVoiceError(
          'Microphone permission denied. Please allow microphone access to use voice queries.'
        );
      } else {
        setVoiceError(
          `Failed to access microphone: ${err instanceof Error ? err.message : 'Unknown error'}`
        );
      }
    }
  };

  const handleSendVoiceQuery = (queryText: string) => {
    const trimmed = queryText.trim();
    if (!trimmed || isTranscribing) return;
    submitChatQuery(trimmed);
    setVoiceModalOpen(false);
    setActiveTab('chat');
  };

  if (!voiceModalOpen) return null;

  const formatTimer = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
  };

  return (
    <AnimatePresence>
      <div
        data-testid="voice-modal"
        role="dialog"
        aria-label="Voice input"
        className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-xl animate-fade-in"
      >
        <motion.div
          initial={{ opacity: 0, scale: 0.9, y: 20 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.9, y: 20 }}
          transition={{ duration: 0.25, ease: 'easeOut' }}
          className={`relative w-full max-w-lg rounded-3xl p-6 sm:p-8 border shadow-2xl overflow-hidden transition-colors ${
            isLight
              ? 'bg-white border-cyan-300 text-slate-900 shadow-sky-900/20'
              : 'glass-panel border-cyan-500/40 bg-slate-950/95 text-slate-100 shadow-cyan-950/80'
          }`}
        >
          <div className="absolute -top-20 -left-20 w-60 h-60 bg-cyan-500/20 rounded-full blur-3xl pointer-events-none" />
          <div className="absolute -bottom-20 -right-20 w-60 h-60 bg-teal-500/20 rounded-full blur-3xl pointer-events-none" />

          <button
            type="button"
            onClick={() => setVoiceModalOpen(false)}
            aria-label="Close voice input"
            className={`absolute top-4 right-4 w-9 h-9 rounded-full border flex items-center justify-center transition-colors z-10 ${
              isLight
                ? 'bg-slate-100 border-slate-200 text-slate-600 hover:bg-slate-200'
                : 'bg-slate-900 border-slate-800 text-slate-400 hover:text-white'
            }`}
          >
            <X className="w-5 h-5" />
          </button>

          <div className="relative z-10 space-y-4 text-center">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-cyan-950 text-cyan-300 border border-cyan-800 text-xs font-bold shadow-sm">
              <Sparkles className="w-3.5 h-3.5 text-cyan-300 animate-pulse" />
              <span>Bhashini Voice AI Engine Active</span>
            </div>

            <h3 className="text-2xl font-black tracking-tight">Ask ORCA by Voice</h3>

            <div className="flex items-center justify-center gap-2">
              <span
                className={`text-xs font-semibold ${isLight ? 'text-slate-500' : 'text-slate-400'}`}
              >
                Speaking in:
              </span>
              <div className="relative">
                <select
                  value={selectedLanguage}
                  onChange={(e) => setSelectedLanguage(e.target.value)}
                  data-testid="voice-language-select"
                  aria-label="Voice input language"
                  className={`px-3 py-1 rounded-xl text-xs font-bold border focus:outline-none cursor-pointer ${
                    isLight
                      ? 'bg-cyan-50 border-cyan-300 text-cyan-900'
                      : 'bg-slate-900 border-cyan-700 text-cyan-300'
                  }`}
                >
                  {INDIAN_LANGUAGES.map((lang) => (
                    <option key={lang.code} value={lang.code}>
                      {lang.flag} {lang.nativeName} ({lang.name})
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="py-6 flex flex-col items-center justify-center">
              <div className="relative flex items-center justify-center">
                {isRecording && (
                  <>
                    <span className="absolute w-32 h-32 rounded-full bg-cyan-500/20 animate-ping opacity-75" />
                    <span className="absolute w-40 h-40 rounded-full bg-teal-500/10 animate-pulse" />
                  </>
                )}

                <button
                  type="button"
                  onClick={() => void handleMicClick()}
                  disabled={isTranscribing}
                  data-testid="voice-record-button"
                  aria-label={isRecording ? 'Stop recording' : 'Start recording'}
                  className={`relative z-10 w-24 h-24 rounded-full flex items-center justify-center shadow-2xl transition-all border-4 ${
                    isRecording
                      ? 'bg-gradient-to-tr from-cyan-600 via-teal-500 to-cyan-400 text-white border-white scale-105 shadow-cyan-500/50'
                      : 'bg-slate-800 text-slate-400 border-slate-700 hover:scale-105'
                  } disabled:opacity-60`}
                >
                  {isRecording ? (
                    <Mic className="w-10 h-10 animate-pulse stroke-[2.5]" />
                  ) : (
                    <MicOff className="w-10 h-10 stroke-[2.5]" />
                  )}
                </button>
              </div>

              {isRecording && (
                <div className="flex items-center justify-center gap-1.5 mt-5 h-8" aria-hidden="true">
                  <span className="w-1.5 h-4 bg-cyan-400 rounded-full animate-bounce [animation-delay:-0.4s]" />
                  <span className="w-1.5 h-7 bg-teal-400 rounded-full animate-bounce [animation-delay:-0.2s]" />
                  <span className="w-1.5 h-5 bg-cyan-300 rounded-full animate-bounce [animation-delay:-0.3s]" />
                  <span className="w-1.5 h-8 bg-emerald-400 rounded-full animate-bounce" />
                  <span className="w-1.5 h-5 bg-cyan-400 rounded-full animate-bounce [animation-delay:-0.1s]" />
                </div>
              )}

              <div className="mt-3 text-xs font-bold tracking-wide flex items-center gap-1.5 text-cyan-400">
                <Radio className="w-3.5 h-3.5 animate-pulse" />
                <span data-testid="voice-status">
                  {isTranscribing
                    ? 'Transcribing via Whisper...'
                    : isRecording
                    ? `Recording ${formatTimer(recordingSeconds)} — tap mic to stop & transcribe`
                    : transcriptText
                    ? 'Transcription ready — review & send'
                    : 'Tap microphone and speak naturally'}
                </span>
              </div>
            </div>

            {voiceError && (
              <div
                data-testid="voice-error"
                role="alert"
                className="p-3 rounded-2xl border text-left text-xs font-semibold bg-rose-950/60 border-rose-500/40 text-rose-200"
              >
                {voiceError}
              </div>
            )}

            <div
              className={`p-4 rounded-2xl border text-left min-h-[70px] transition-colors ${
                isLight
                  ? 'bg-cyan-50/70 border-cyan-200 text-slate-800'
                  : 'bg-slate-900/90 border-cyan-900/60 text-slate-100'
              }`}
            >
              <div className="text-[10px] font-mono font-bold text-cyan-600 dark:text-cyan-400 uppercase tracking-wider mb-1 flex items-center justify-between">
                <span>STT Real-time Transcript:</span>
                {transcriptText && (
                  <button
                    type="button"
                    onClick={() => setTranscriptText('')}
                    className="text-slate-400 hover:text-cyan-400 text-[10px] flex items-center gap-0.5"
                  >
                    <RotateCcw className="w-3 h-3" /> Clear
                  </button>
                )}
              </div>
              <p data-testid="voice-transcript" className="text-xs sm:text-sm font-medium italic">
                {transcriptText
                  ? `"${transcriptText}"`
                  : isTranscribing
                  ? 'Transcribing your voice...'
                  : 'Tap the microphone and speak...'}
              </p>
            </div>

            {transcriptText && (
              <motion.button
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                onClick={() => handleSendVoiceQuery(transcriptText)}
                disabled={isTranscribing}
                data-testid="voice-send-button"
                className="w-full py-3.5 rounded-2xl bg-gradient-to-r from-cyan-500 via-teal-500 to-emerald-500 text-slate-950 font-black text-sm shadow-xl shadow-cyan-500/25 hover:scale-[1.01] active:scale-[0.99] transition-all flex items-center justify-center gap-2"
              >
                <span>{isTranscribing ? 'Processing...' : 'Ask ORCA Multi-Agent Engine'}</span>
                <ArrowRight className="w-4 h-4 stroke-[2.5]" />
              </motion.button>
            )}

            <div className="pt-2">
              <div className="text-[11px] font-bold uppercase tracking-wider mb-2 text-slate-400">
                Or tap a sample voice question:
              </div>
              <div className="flex flex-wrap justify-center gap-1.5 text-xs">
                {SAMPLE_VOICE_PROMPTS.map((prompt, idx) => (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => handleSendVoiceQuery(prompt)}
                    disabled={isTranscribing}
                    className={`px-3 py-1.5 rounded-xl border text-[11px] font-medium transition-all disabled:opacity-50 ${
                      isLight
                        ? 'bg-white border-slate-200 text-slate-700 hover:bg-cyan-50 hover:border-cyan-300'
                        : 'bg-slate-900 border-slate-800 text-slate-300 hover:text-white hover:border-cyan-500/50'
                    }`}
                  >
                    🗣️ {prompt}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
};

export default VoiceModal;
