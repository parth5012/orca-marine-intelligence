/**
 * ChatScreen (UI-MIG-T4)
 *
 * Owner: M-E (Frontend Chat & App Shell)
 * Module: frontend/components/screens/ChatScreen.tsx
 *
 * New visual design (Bot header, execution trace, safety strip, evidence,
 * hazards, zone preview, Show-on-Map / Navigate, payload inspector)
 * rewired to the LIVE SSE engine:
 * - `useSSEChat` owns streaming: POST /api/chat direct + proxy fallback,
 *   token/status/map/safety/evidence/done/error frames.
 * - reasoning_steps -> AgentExecutionTrace; safety -> SafetyStatus + banner;
 *   zone_cards -> preview + flyTo via onLocationUpdate/onMapHighlight;
 *   evidence -> EvidenceCard; map events flow through the hook callbacks.
 * - PayloadInspector shows the real request JSON + aggregated live frames.
 * - Home -> chat handoff via AppContext.pendingChatQuery (same as ChatPanel).
 * - Voice via MediaRecorder -> sendVoiceAudio (Whisper) -> auto-send.
 *
 * Live-only: no canned initial thread, no local query engine, no fake
 * payloads. ChatPanel.tsx stays untouched until E2E passes.
 */

'use client';

import React, { useState, useRef, useEffect } from 'react';
import { useApp } from '@/context/AppContext';
import {
  useSSEChat,
  type ChatMessage,
  type MarineZoneCard,
  type SafetyData,
} from '@/chat/useSSEChat';
import LanguageSwitch from '@/chat/LanguageSwitch';
import { SafetyStatus } from '@/components/common/SafetyStatus';
import { EvidenceCard } from '@/components/common/EvidenceCard';
import { AgentExecutionTrace } from '@/components/agent/AgentExecutionTrace';
import { getEffectiveResponseLang } from '@/lib/languageGate';
import { ProcessingCard } from '@/components/agent/ProcessingCard';
import { PayloadInspectorModal } from '@/components/agent/PayloadInspector';
import {
  Send,
  MapPin,
  Navigation,
  Bot,
  User,
  ShieldCheck,
  Thermometer,
  Waves,
  Wind,
} from 'lucide-react';

export interface ChatScreenProps {
  onLocationUpdate?: (lat: number, lon: number) => void;
  onMapHighlight?: (features: any[]) => void;
  currentLanguage?: string;
  onLanguageChange?: (lang: string) => void;
  userLocation?: { lat: number; lon: number } | null;
  onSafetyUpdate?: (safety: SafetyData) => void;
  onRouteChange?: (route: [number, number][] | number[][] | null) => void;
}

const QUICK_ACTIONS = [
  { label: '🐟 Fish near Kochi', query: 'Where are the nearest fishing zones near Kochi today?' },
  { label: '🌊 Weather report', query: 'What is the current wind and wave weather advisory?' },
  { label: '⚓ Is it safe to sail today?', query: 'Is it safe for a small motorized boat to sail right now?' },
  { label: '🌪️ Cyclone alert', query: 'Are there any cyclone or high-wave alerts for Kerala coast?' },
  { label: '📍 Munambam PFZ', query: 'Check PFZ fishing coordinates near Munambam.' },
];

function toSafetyStatus(safety?: SafetyData): 'SAFE' | 'CAUTION' | 'AVOID' {
  const danger = String(safety?.danger ?? '').toLowerCase();
  const badge = String(safety?.badge ?? '').toLowerCase();
  const text = String(safety?.warning_text ?? '').toUpperCase();
  if (
    danger === 'danger' ||
    danger === 'cyclone' ||
    danger === 'eez' ||
    danger === 'mpa' ||
    badge === 'red' ||
    text.includes('DO NOT SAIL') ||
    text.includes('CYCLONE')
  ) {
    return 'AVOID';
  }
  if (danger === 'caution' || badge === 'amber' || text.includes('CAUTION')) {
    return 'CAUTION';
  }
  return 'SAFE';
}

function isDangerSafety(safety?: SafetyData): boolean {
  return toSafetyStatus(safety) === 'AVOID';
}

function isCautionSafety(safety?: SafetyData): boolean {
  return toSafetyStatus(safety) === 'CAUTION';
}

export const ChatScreen: React.FC<ChatScreenProps> = ({
  onLocationUpdate,
  onMapHighlight,
  currentLanguage = 'en',
  onLanguageChange,
  userLocation,
  onSafetyUpdate,
  onRouteChange,
}) => {
  const {
    themeMode,
    t,
    openPFZDetail,
    startRouteNavigation,
    setActiveTab,
    pendingChatQuery,
    consumeChatQuery,
    setActiveRoute,
  } = useApp();
  const isLight = themeMode === 'light';

  const [inputVal, setInputVal] = useState('');
  const [isRecording, setIsRecording] = useState<boolean>(false);
  const [recordingSeconds, setRecordingSeconds] = useState<number>(0);
  const [selectedZoneId, setSelectedZoneId] = useState<string | null>(null);
  const [inspectorData, setInspectorData] = useState<{
    isOpen: boolean;
    req?: string;
    res?: string;
  }>({ isOpen: false });

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const recordingTimerRef = useRef<NodeJS.Timeout | null>(null);

  const {
    messages,
    isStreaming,
    sessionId,
    language,
    location,
    isTranscribing,
    voiceError,
    sendMessage,
    stopStream,
    sendVoiceAudio,
    updateLanguage,
    clearSession,
  } = useSSEChat({
    initialLocation: userLocation,
    initialLanguage: currentLanguage,
    onLocationUpdate,
    onMapHighlight,
    onSafetyUpdate,
    onRouteChange: (route) => {
      setActiveRoute?.(route);
      onRouteChange?.(route);
    },
  });

  // Sync external language prop (shell owns selectedLanguage).
  useEffect(() => {
    if (currentLanguage && currentLanguage !== language) {
      updateLanguage(currentLanguage);
    }
  }, [currentLanguage, language, updateLanguage]);

  // Home -> chat handoff: AskOrcaInput queues pendingChatQuery; send it
  // through the real SSE sendMessage. Wait out any active stream so the
  // query is never dropped.
  useEffect(() => {
    if (!pendingChatQuery || isStreaming) return;
    const text = pendingChatQuery.text;
    consumeChatQuery();
    void sendMessage(text);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingChatQuery, isStreaming]);

  // Auto-scroll on new messages or token stream.
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isStreaming]);

  // Unmount cleanup: clear recording timer + stop active mic tracks.
  useEffect(() => {
    return () => {
      if (recordingTimerRef.current) {
        clearInterval(recordingTimerRef.current);
        recordingTimerRef.current = null;
      }
      try {
        mediaRecorderRef.current?.stream?.getTracks().forEach((t) => t.stop());
      } catch {
        /* already released */
      }
    };
  }, []);

  const effectiveLat = userLocation?.lat ?? location?.lat ?? null;
  const effectiveLon = userLocation?.lon ?? location?.lon ?? null;

  const buildRequestPayload = (text: string): string =>
    JSON.stringify(
      {
        message: text,
        session_id: sessionId || '(assigned on first stream)',
        lat: effectiveLat,
        lon: effectiveLon,
        language: language || currentLanguage || 'en',
      },
      null,
      2
    );

  const buildResponsePayload = (msg: ChatMessage): string =>
    JSON.stringify(
      {
        id: msg.id,
        content: msg.content,
        reasoning_steps: msg.reasoning_steps,
        zone_cards: msg.zone_cards,
        map_data: msg.map_data,
        safety: msg.safety,
        evidence: msg.evidence,
        latency_ms: msg.latency_ms,
        confidence: msg.confidence,
        warning: msg.warning,
        fallback: msg.fallback,
        fallback_message: msg.fallback_message,
        error: msg.error,
      },
      null,
      2
    );

  const openInspectorFor = (msg: ChatMessage) => {
    const idx = messages.findIndex((m) => m.id === msg.id);
    let queryText = '';
    for (let i = idx - 1; i >= 0; i -= 1) {
      if (messages[i]?.role === 'user') {
        queryText = messages[i].content;
        break;
      }
    }
    if (!queryText) {
      const lastUser = [...messages].reverse().find((m) => m.role === 'user');
      queryText = lastUser?.content ?? '';
    }
    setInspectorData({
      isOpen: true,
      req: buildRequestPayload(queryText),
      res: buildResponsePayload(msg),
    });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputVal.trim() || isStreaming) return;
    const query = inputVal.trim();
    setInputVal('');
    await sendMessage(query);
    inputRef.current?.focus();
  };

  const handleQuickAction = async (query: string) => {
    if (isStreaming) return;
    setInputVal('');
    await sendMessage(query);
  };

  const handleFlyToZone = (card: MarineZoneCard) => {
    setSelectedZoneId(card.id);
    if (card.coordinates && card.coordinates.length === 2) {
      onLocationUpdate?.(card.coordinates[0], card.coordinates[1]);
    }
    if (card.feature) {
      onMapHighlight?.([card.feature]);
    } else if (card.coordinates) {
      const pointFeature = {
        type: 'Feature',
        geometry: {
          type: 'Point',
          coordinates: [card.coordinates[1], card.coordinates[0]],
        },
        properties: {
          place: card.name,
          bearing: card.bearing,
          distance_km: card.distance_km,
          depth_m: card.depth_m,
          sst: card.sst_c,
          chlorophyll: card.chlorophyll,
          safety: card.safety ?? card.safety_status,
          wave_m: card.wave_m,
          wind_kph: card.wind_kph,
          confidence: card.confidence,
        },
      };
      onMapHighlight?.([pointFeature]);
    }
  };

  const showZoneOnMap = (card: MarineZoneCard) => {
    handleFlyToZone(card);
    setActiveTab('map');
  };

  // Vernacular voice recording (browser MediaRecorder -> Whisper -> auto-send).
  const startRecording = async () => {
    try {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        alert('Voice recording is not supported on this browser.');
        return;
      }

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioChunksRef.current = [];

      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : 'audio/webm';

      const mediaRecorder = new MediaRecorder(stream, { mimeType });
      mediaRecorderRef.current = mediaRecorder;

      mediaRecorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());

        if (recordingTimerRef.current) {
          clearInterval(recordingTimerRef.current);
          recordingTimerRef.current = null;
        }
        setIsRecording(false);
        setRecordingSeconds(0);

        const audioBlob = new Blob(audioChunksRef.current, { type: mimeType });
        if (audioBlob.size > 0) {
          await sendVoiceAudio(audioBlob);
        }
      };

      mediaRecorder.start(250);
      setIsRecording(true);
      setRecordingSeconds(0);

      recordingTimerRef.current = setInterval(() => {
        setRecordingSeconds((sec) => sec + 1);
      }, 1000);
    } catch (err: any) {
      setIsRecording(false);
      if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
        alert('Microphone permission denied. Please allow microphone access to use voice queries.');
      } else {
        alert('Failed to access microphone: ' + (err.message || 'Unknown error'));
      }
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }
  };

  const formatTimer = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <div
      data-testid="chat-screen"
      className="flex flex-col h-[calc(100vh-120px)] min-h-[550px] max-w-4xl mx-auto space-y-4 pb-16"
    >
      {/* Top Chat Header */}
      <div className={`rounded-2xl p-4 border flex items-center justify-between shadow-xl transition-colors ${
        isLight
          ? 'bg-white border-cyan-100 shadow-sky-900/5 text-slate-900'
          : 'glass-panel border-cyan-900/40 bg-slate-950/90 text-white'
      }`}>
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-600 to-teal-600 flex items-center justify-center shadow-lg text-white">
            <Bot className="w-6 h-6" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className={`font-extrabold text-base sm:text-lg ${isLight ? 'text-slate-900' : 'text-white'}`}>
                {t('askOrca')} AI Assistant
              </h2>
              <span className={`px-2 py-0.5 text-[10px] font-bold rounded border ${
                isLight ? 'bg-emerald-50 text-emerald-800 border-emerald-300' : 'bg-emerald-950 text-emerald-300 border-emerald-800'
              }`}>
                Multi-Agent Reasoning Active
              </span>
              <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-cyan-950 text-cyan-400 border border-cyan-800">
                SSE Live
              </span>
            </div>
            <p className={`text-xs font-medium ${isLight ? 'text-slate-500' : 'text-slate-400'}`}>
              Text-based multi-agent marine intelligence &amp; spatial decision platform
              {sessionId ? (
                <span className="font-mono text-cyan-600 dark:text-cyan-300"> • Session: {sessionId.slice(0, 8)}</span>
              ) : null}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            id="chat-clear-session-button"
            data-testid="chat-clear-session-button"
            aria-label="Clear chat session"
            onClick={clearSession}
            disabled={isStreaming}
            title="Start new conversation"
            className="px-2.5 py-1 text-xs font-medium rounded-md bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors border border-slate-700 disabled:opacity-50"
          >
            New Chat
          </button>
          <LanguageSwitch
            currentLanguage={language || currentLanguage}
            onLanguageChange={(lang) => {
              updateLanguage(lang);
              onLanguageChange?.(lang);
            }}
            compact
          />
        </div>
      </div>

      {/* Messages Scroll Area */}
      <div className="flex-1 overflow-y-auto space-y-4 pr-1">
        {messages.length === 0 && (
          <div className="py-8 text-center space-y-3">
            <div className="w-14 h-14 mx-auto rounded-2xl bg-cyan-950/60 border border-cyan-800 flex items-center justify-center text-2xl shadow-inner">
              🌊
            </div>
            <h3 className={`text-base font-semibold ${isLight ? 'text-slate-900' : 'text-white'}`}>
              Welcome to ORCA Marine Intelligence
            </h3>
            <p className={`text-xs max-w-sm mx-auto leading-relaxed ${isLight ? 'text-slate-500' : 'text-slate-400'}`}>
              Chat normally — say hello or ask for help. Ask about potential fishing zones (PFZ), wave height, wind speeds, geofence safety, or weather and ORCA runs its full multi-agent marine analysis over live SSE.
            </p>
          </div>
        )}

        {messages.map((msg, msgIdx) => {
          const isUser = msg.role === 'user';
          // Dual-gate: prefer backend decision, fallback to local gate from
          // the preceding user query + current UI language.
          let queryForGate = '';
          for (let i = msgIdx - 1; i >= 0; i -= 1) {
            if (messages[i]?.role === 'user') {
              queryForGate = messages[i].content ?? '';
              break;
            }
          }
          const effectiveLang =
            (!isUser && msg.response_language) ||
            getEffectiveResponseLang(language || currentLanguage, queryForGate);
          const isHi = !isUser && effectiveLang === 'hi';
          return (
            <div
              key={msg.id}
              className={`flex gap-3 ${isUser ? 'justify-end' : 'justify-start'}`}
            >
              {!isUser && (
                <div className={`w-8 h-8 rounded-full border flex items-center justify-center shrink-0 mt-1 ${
                  isLight ? 'bg-sky-100 border-sky-300 text-cyan-800' : 'bg-cyan-950 border-cyan-700 text-cyan-300'
                }`}>
                  <Bot className="w-4 h-4" />
                </div>
              )}

              <div
                className={`max-w-2xl rounded-2xl p-4 text-sm shadow-xl ${
                  isUser
                    ? 'bg-gradient-to-r from-cyan-600 to-teal-600 text-white font-medium rounded-tr-none'
                    : isLight
                    ? 'bg-white border border-slate-200 text-slate-900 rounded-tl-none'
                    : 'glass-panel bg-slate-950/95 border border-cyan-900/40 text-slate-100 rounded-tl-none'
                }`}
              >
                {/* Message Header */}
                <div className="flex items-center justify-between gap-4 mb-1 text-xs opacity-75">
                  <span className="font-bold">{isUser ? 'You' : 'ORCA Intelligence'}</span>
                  <span>{new Date(msg.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                </div>

                {/* Message Body */}
                {isUser ? (
                  <p className="leading-relaxed font-sans whitespace-pre-wrap">{msg.content}</p>
                ) : (
                  <>
                    {msg.content ? (
                      <div className="prose prose-invert max-w-none text-sm leading-relaxed whitespace-pre-wrap">
                        {msg.content}
                      </div>
                    ) : msg.isStreaming ? (
                      <div className="flex items-center gap-2 text-xs text-cyan-600 dark:text-cyan-300">
                        <span className="w-2 h-2 rounded-full bg-cyan-400 animate-ping" />
                        <span>ORCA Brain reasoning &amp; translating advisory...</span>
                      </div>
                    ) : null}

                    {/* Live multi-agent trace */}
                    {msg.reasoning_steps && msg.reasoning_steps.length > 0 && (
                      <AgentExecutionTrace
                        traces={msg.reasoning_steps}
                        confidenceScore={msg.confidence}
                        onInspectPayload={() => openInspectorFor(msg)}
                        responseLang={effectiveLang}
                      />
                    )}

                    {/* Rich live response details */}
                    <div className={`mt-3 space-y-3 pt-3 border-t ${isLight ? 'border-slate-100' : 'border-slate-800'}`}>
                      {/* Safety banner (same testids as the live panel) */}
                      {msg.safety && (
                        <div>
                          {isDangerSafety(msg.safety) ? (
                            <div data-testid="safety-banner-danger" role="alert" className="rounded-xl bg-red-950/80 border-2 border-red-600/90 p-3 shadow-lg shadow-red-950/40 animate-pulse">
                              <div className="flex items-center gap-2.5">
                                <span className="text-xl" role="img" aria-label="Danger">🚨</span>
                                <div className="flex-1">
                                  <div className="flex items-center justify-between">
                                    <h4 className="text-xs font-black uppercase tracking-wider text-red-200">
                                      {isHi ? `उच्च जोखिम सलाह: ${msg.safety.warning_text || 'समुद्र में न जाएँ'}` : `HIGH RISK ADVISORY: ${msg.safety.warning_text || 'DO NOT SAIL'}`}
                                    </h4>
                                    <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-red-800 text-white">
                                      {isHi ? 'खतरा' : 'DANGER'}
                                    </span>
                                  </div>
                                  <p className="text-xs text-red-100 font-medium mt-0.5">
                                    {isHi
                                      ? `खतरनाक समुद्री स्थिति। लहर ऊँचाई ${msg.safety.waves_m ?? '--'} मी, हवा गति ${msg.safety.wind_kts ?? '--'} नॉट।`
                                      : `Hazardous sea conditions. Wave height ${msg.safety.waves_m ?? '--'}m, wind speed ${msg.safety.wind_kts ?? '--'} kts.`}
                                  </p>
                                </div>
                              </div>
                            </div>
                          ) : isCautionSafety(msg.safety) ? (
                            <div data-testid="safety-banner-caution" role="alert" className="rounded-xl bg-amber-950/70 border border-amber-500/80 p-3 shadow-md">
                              <div className="flex items-center gap-2.5">
                                <span className="text-xl">⚠️</span>
                                <div className="flex-1">
                                  <div className="flex items-center justify-between">
                                    <h4 className="text-xs font-bold uppercase tracking-wider text-amber-300">
                                      {isHi ? 'समुद्री सलाह: सावधानी' : 'SEA ADVISORY: CAUTION'}
                                    </h4>
                                    <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-700 text-white">
                                      {isHi ? 'सावधानी' : 'CAUTION'}
                                    </span>
                                  </div>
                                  <p className="text-xs text-amber-200/90 mt-0.5">
                                    {isHi
                                      ? `मध्यम समुद्री स्थिति। लहरें ${msg.safety.waves_m ?? '--'} मी, हवाएँ ${msg.safety.wind_kts ?? '--'} नॉट। सतर्कता से आगे बढ़ें।`
                                      : `Moderate sea conditions. Waves ${msg.safety.waves_m ?? '--'}m, winds ${msg.safety.wind_kts ?? '--'} kts. Proceed with vigilance.`}
                                  </p>
                                </div>
                              </div>
                            </div>
                          ) : (
                            <div data-testid="safety-banner-safe" className="rounded-xl bg-emerald-950/50 border border-emerald-500/50 px-3 py-2 flex items-center justify-between">
                              <div className="flex items-center gap-2 text-xs text-emerald-300">
                                <span>✅</span>
                                <span className="font-semibold">{isHi ? 'सुरक्षित स्थिति' : 'SAFE CONDITIONS'}</span>
                                <span className="text-slate-400">
                                  {isHi
                                    ? `• लहरें: ${msg.safety.waves_m ?? '--'} मी | हवा: ${msg.safety.wind_kts ?? '--'} नॉट`
                                    : `• Waves: ${msg.safety.waves_m ?? '--'}m | Wind: ${msg.safety.wind_kts ?? '--'} kts`}
                                </span>
                              </div>
                              <span className="text-[10px] font-bold bg-emerald-800 px-1.5 py-0.5 rounded text-white">
                                {isHi ? 'सुरक्षित' : 'SAFE'}
                              </span>
                            </div>
                          )}
                          <div className="flex items-center justify-between mt-2">
                            <span className={`text-xs font-medium ${isLight ? 'text-slate-500' : 'text-slate-400'}`}>{isHi ? 'सुरक्षा स्थिति:' : 'Safety Status:'}</span>
                            <SafetyStatus status={toSafetyStatus(msg.safety)} size="sm" responseLang={effectiveLang} />
                          </div>
                        </div>
                      )}

                      {/* Live summary grid from SSE safety + first zone */}
                      {msg.safety && (msg.safety.waves_m != null || msg.safety.wind_kts != null || msg.zone_cards?.[0]?.sst_c != null) && (
                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-xs">
                          {msg.zone_cards?.[0]?.sst_c != null && (
                            <div className={`p-2 rounded-xl border flex items-center gap-2 ${
                              isLight ? 'bg-amber-50/60 border-amber-100 text-slate-800' : 'bg-slate-900/80 border-slate-800 text-slate-300'
                            }`}>
                              <Thermometer className="w-4 h-4 text-amber-500 shrink-0" />
                              <span className="truncate">SST {msg.zone_cards[0].sst_c}°C</span>
                            </div>
                          )}
                          {msg.safety.waves_m != null && (
                            <div className={`p-2 rounded-xl border flex items-center gap-2 ${
                              isLight ? 'bg-blue-50/60 border-blue-100 text-slate-800' : 'bg-slate-900/80 border-slate-800 text-slate-300'
                            }`}>
                              <Waves className="w-4 h-4 text-blue-600 shrink-0" />
                              <span className="truncate">{isHi ? `लहरें ${msg.safety.waves_m} मी` : `Waves ${msg.safety.waves_m}m`}</span>
                            </div>
                          )}
                          {msg.safety.wind_kts != null && (
                            <div className={`p-2 rounded-xl border flex items-center gap-2 ${
                              isLight ? 'bg-sky-50/60 border-sky-100 text-slate-800' : 'bg-slate-900/80 border-slate-800 text-slate-300'
                            }`}>
                              <Wind className="w-4 h-4 text-sky-600 shrink-0" />
                              <span className="truncate">{isHi ? `हवा ${msg.safety.wind_kts} नॉट` : `Wind ${msg.safety.wind_kts} kts`}</span>
                            </div>
                          )}
                        </div>
                      )}

                      {/* Evidence from live frames */}
                      {msg.evidence && msg.evidence.length > 0 && (
                        <EvidenceCard evidence={msg.evidence} confidenceScore={msg.confidence} responseLang={effectiveLang} />
                      )}

                      {/* Active hazards from live safety frame */}
                      {msg.safety && toSafetyStatus(msg.safety) !== 'SAFE' && (msg.safety.message || msg.safety.warning_text) && (
                        <div className={`p-3 rounded-xl border text-xs space-y-1 ${
                          isLight ? 'bg-rose-50 border-rose-200 text-rose-900' : 'bg-rose-950/30 border-rose-500/30 text-rose-200'
                        }`}>
                          <div className="font-bold flex items-center gap-1.5 text-rose-600">
                            <ShieldCheck className="w-4 h-4" />
                            <span>{isHi ? 'सक्रिय खतरे व सलाह' : 'Active Hazards & Advisories'}</span>
                          </div>
                          <div className={`text-[12px] ${isLight ? 'text-rose-800' : 'text-slate-300'}`}>
                            • {msg.safety.message || msg.safety.warning_text}
                          </div>
                        </div>
                      )}

                      {/* Fallback notice (live `fallback` state, never canned) */}
                      {(msg.fallback || msg.reasoning_steps?.some((s) => s.state === 'fallback')) && (
                        <div
                          data-testid="fallback-banner"
                          className="mt-2 text-xs text-amber-300 bg-amber-950/60 p-2 rounded-lg border border-amber-700/60 flex items-center gap-1.5"
                        >
                          <span className="text-amber-400 font-bold">⚠</span>
                          <span>{msg.fallback_message || 'using fallback (LLM unavailable)'}</span>
                        </div>
                      )}

                      {/* Fatal error only when no reply content exists */}
                      {msg.error && !msg.content?.trim() && (
                        <div className="mt-2 text-xs text-red-400 bg-red-950/40 p-2 rounded-lg border border-red-800/50">
                          ⚠️ {msg.error}
                        </div>
                      )}

                      {/* Synth warning — reply exists, polish degraded */}
                      {msg.warning && (
                        <div
                          data-testid="synth-warning"
                          className="mt-2 text-xs text-slate-400 bg-slate-800/60 p-2 rounded-lg border border-slate-700"
                        >
                          LLM polish unavailable — showing verified advisory.
                        </div>
                      )}

                      {/* Evidence & latency footer */}
                      <div data-testid="evidence-footer" className="mt-3 pt-2 border-t border-slate-800/80 flex flex-wrap items-center justify-between gap-2 text-[10px] text-slate-400">
                        {msg.evidence && msg.evidence.length > 0 && (
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className="text-slate-500 font-semibold">{isHi ? 'प्रमाण:' : 'Evidence:'}</span>
                            {msg.evidence.map((ev, eIdx) => (
                              <span
                                key={eIdx}
                                className="bg-slate-800 text-slate-300 px-1.5 py-0.5 rounded border border-slate-700"
                              >
                                {ev}
                              </span>
                            ))}
                          </div>
                        )}
                        {msg.latency_ms != null && (
                          <span className="font-mono text-slate-500 ml-auto">
                            ⚡ {msg.latency_ms}ms
                          </span>
                        )}
                      </div>

                      {/* Recommended zone quick preview (first live zone card) */}
                      {msg.zone_cards && msg.zone_cards.length > 0 && (
                        <div className={`p-3 rounded-xl border flex items-center justify-between text-xs ${
                          isLight ? 'bg-cyan-50/70 border-cyan-200' : 'bg-cyan-950/30 border-cyan-500/30'
                        }`}>
                          <div>
                            <span className={`text-[10px] font-mono font-bold ${isLight ? 'text-cyan-800' : 'text-cyan-400'}`}>
                              {isHi ? 'अनुशंसित क्षेत्र' : 'RECOMMENDED ZONE'}
                            </span>
                            <div className={`font-extrabold text-sm ${isLight ? 'text-slate-900' : 'text-cyan-100'}`}>
                              {msg.zone_cards[0].name}
                            </div>
                            <p className={`text-[11px] ${isLight ? 'text-slate-600' : 'text-slate-400'}`}>
                              {msg.zone_cards[0].distance_km != null ? (isHi ? `${msg.zone_cards[0].distance_km} किमी दूर` : `${msg.zone_cards[0].distance_km} km away`) : (isHi ? 'लाइव PFZ स्थिति' : 'Live PFZ fix')}
                              {msg.zone_cards[0].bearing ? ` • ${msg.zone_cards[0].bearing}` : ''}
                            </p>
                          </div>
                          <button
                            type="button"
                            data-testid="recommended-zone-view"
                            aria-label={`View ${msg.zone_cards[0].name} details`}
                            onClick={() => openPFZDetail({
                              ...msg.zone_cards[0],
                            })}
                            className="px-3 py-1.5 rounded-lg bg-cyan-700 text-white font-extrabold text-xs shadow hover:scale-105 transition-transform"
                          >
                            {isHi ? 'क्षेत्र देखें' : 'View Zone'}
                          </button>
                        </div>
                      )}

                      {/* Structured live zone cards */}
                      {msg.zone_cards && msg.zone_cards.length > 0 && (
                        <div className="space-y-2 pt-1">
                          <div className="flex items-center justify-between px-1">
                            <h4 className="text-xs font-semibold text-cyan-600 dark:text-cyan-400 uppercase tracking-wider flex items-center gap-1.5">
                              <span>🎯</span> {isHi ? `अनुशंसित मत्स्य क्षेत्र (${msg.zone_cards.length})` : `Recommended Fishing Zones (${msg.zone_cards.length})`}
                            </h4>
                            <span className="text-[10px] text-slate-400">{isHi ? 'मैप पर देखने के लिए क्लिक करें' : 'Click to fly on map'}</span>
                          </div>

                          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                            {msg.zone_cards.map((zone) => {
                              const isSelected = selectedZoneId === zone.id;
                              const canonicalSafety = zone.safety ?? zone.safety_status ?? null;
                              const displaySafety = canonicalSafety ?? (msg.fallback ? 'unknown' : null);
                              return (
                                <div
                                  key={zone.id}
                                  data-testid={`zone-card-${zone.id}`}
                                  className={`rounded-xl p-3 text-xs transition-all border ${
                                    isSelected
                                      ? 'bg-cyan-950/80 border-cyan-400 shadow-md shadow-cyan-950/40'
                                      : isLight
                                      ? 'bg-white hover:bg-slate-50 border-slate-200'
                                      : 'bg-slate-900 hover:bg-slate-850 border-slate-800'
                                  }`}
                                >
                                  <div className="flex items-start justify-between gap-2">
                                    <h5 className={`font-bold text-sm truncate ${isLight ? 'text-slate-900' : 'text-white'}`}>
                                      {zone.name}
                                    </h5>
                                    <div className="flex items-center gap-1.5">
                                      {zone.confidence != null && (
                                        <span
                                          title={`Confidence ${zone.confidence}`}
                                          className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-slate-800 text-cyan-300 border border-slate-700"
                                        >
                                          {(Number(zone.confidence) * 100).toFixed(0)}%
                                        </span>
                                      )}
                                      {displaySafety && (
                                        <span
                                          className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${
                                            displaySafety === 'safe'
                                              ? 'bg-emerald-950 text-emerald-300 border border-emerald-700'
                                              : displaySafety === 'caution'
                                              ? 'bg-amber-950 text-amber-300 border border-amber-700'
                                              : displaySafety === 'danger'
                                              ? 'bg-red-950 text-red-300 border border-red-700'
                                              : 'bg-slate-800 text-slate-400 border border-slate-700'
                                          }`}
                                        >
                                          {displaySafety}
                                        </span>
                                      )}
                                    </div>
                                  </div>

                                  <div className={`grid grid-cols-2 gap-x-2 gap-y-1 mt-2 text-[11px] ${isLight ? 'text-slate-600' : 'text-slate-300'}`}>
                                    {zone.distance_km != null && (
                                      <div>
                                        <span className="text-slate-500">Distance: </span>
                                        <span className={`font-semibold ${isLight ? 'text-slate-900' : 'text-white'}`}>
                                          {zone.distance_km} km
                                        </span>
                                      </div>
                                    )}
                                    {zone.bearing != null && (
                                      <div>
                                        <span className="text-slate-500">Bearing: </span>
                                        <span className="font-semibold text-cyan-600 dark:text-cyan-300">
                                          {typeof zone.bearing === 'number' ? `${zone.bearing}°` : zone.bearing}
                                        </span>
                                      </div>
                                    )}
                                    {zone.depth_m != null && (
                                      <div>
                                        <span className="text-slate-500">Depth: </span>
                                        <span className={`font-semibold ${isLight ? 'text-slate-900' : 'text-white'}`}>
                                          {zone.depth_m}m
                                        </span>
                                      </div>
                                    )}
                                    {zone.sst_c != null && (
                                      <div>
                                        <span className="text-slate-500">SST: </span>
                                        <span className="font-semibold text-amber-600 dark:text-amber-300">
                                          {zone.sst_c}°C
                                        </span>
                                      </div>
                                    )}
                                    {zone.wave_m != null && (
                                      <div>
                                        <span className="text-slate-500">Wave: </span>
                                        <span className={`font-semibold ${isLight ? 'text-slate-900' : 'text-white'}`}>
                                          {zone.wave_m}m
                                        </span>
                                      </div>
                                    )}
                                    {zone.wind_kph != null && (
                                      <div>
                                        <span className="text-slate-500">Wind: </span>
                                        <span className={`font-semibold ${isLight ? 'text-slate-900' : 'text-white'}`}>
                                          {zone.wind_kph} kph
                                        </span>
                                      </div>
                                    )}
                                    {zone.chlorophyll != null && (
                                      <div className="col-span-2">
                                        <span className="text-slate-500">Chlorophyll: </span>
                                        <span className="font-semibold text-emerald-600 dark:text-emerald-300">
                                          {zone.chlorophyll} mg/m³
                                        </span>
                                      </div>
                                    )}
                                  </div>

                                  <div className="mt-2.5 pt-2 border-t border-slate-800 flex items-center justify-end">
                                    <button
                                      type="button"
                                      data-testid={`zone-show-on-map-${zone.id}`}
                                      aria-label={`Show ${zone.name} on map`}
                                      onClick={() => handleFlyToZone(zone)}
                                      className={`px-2.5 py-1 rounded text-xs font-semibold flex items-center gap-1.5 transition-colors ${
                                        isSelected
                                          ? 'bg-cyan-500 text-slate-950 shadow-sm'
                                          : 'bg-slate-800 hover:bg-cyan-900/60 text-cyan-300 border border-cyan-800/40'
                                      }`}
                                    >
                                      <span>🗺️</span> Show on Map
                                    </button>
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      )}

                      {/* Map actions toolbar for the recommended zone */}
                      {msg.zone_cards && msg.zone_cards.length > 0 && (
                        <div className={`flex flex-wrap items-center justify-end gap-2 pt-2 border-t ${isLight ? 'border-slate-100' : 'border-slate-800'}`}>
                          <button
                            type="button"
                            data-testid="zone-show-on-map-toolbar"
                            aria-label="Show recommended zone on map"
                            onClick={() => showZoneOnMap(msg.zone_cards[0])}
                            className={`px-3 py-1.5 rounded-lg border text-xs font-semibold flex items-center gap-1 ${
                              isLight
                                ? 'bg-white border-slate-200 text-slate-700 hover:bg-slate-50'
                                : 'bg-slate-900 border border-slate-800 text-cyan-200 hover:text-white'
                            }`}
                          >
                            <MapPin className="w-3.5 h-3.5 text-cyan-600" />
                            <span>Show on Map</span>
                          </button>
                          <button
                            type="button"
                            data-testid="zone-navigate-toolbar"
                            aria-label="Navigate to recommended zone"
                            onClick={() => startRouteNavigation({
                              ...msg.zone_cards[0],
                            })}
                            className="px-3 py-1.5 rounded-lg bg-gradient-to-r from-cyan-600 to-teal-600 text-white font-bold text-xs flex items-center gap-1 hover:scale-105 transition-transform"
                          >
                            <Navigation className="w-3.5 h-3.5 fill-white" />
                            <span>Navigate</span>
                          </button>
                        </div>
                      )}
                    </div>
                  </>
                )}
              </div>

              {isUser && (
                <div className="w-8 h-8 rounded-full bg-cyan-700 text-white flex items-center justify-center shrink-0 mt-1">
                  <User className="w-4 h-4" />
                </div>
              )}
            </div>
          );
        })}

        {isStreaming && <ProcessingCard />}
        <div ref={messagesEndRef} />
      </div>

      {/* Quick Action Chips */}
      <div className="px-1 py-1">
        <div className="flex items-center gap-1.5 overflow-x-auto pb-1 text-xs no-scrollbar">
          {QUICK_ACTIONS.map((chip, idx) => (
            <button
              key={idx}
              type="button"
              id={`quick-action-chip-${idx}`}
              data-testid={`quick-action-chip-${idx}`}
              aria-label={`Quick query: ${chip.label}`}
              disabled={isStreaming}
              onClick={() => handleQuickAction(chip.query)}
              className="flex-shrink-0 px-2.5 py-1 rounded-full bg-slate-900 hover:bg-slate-800 text-slate-300 hover:text-white border border-slate-800 hover:border-cyan-500/40 text-[11px] transition-colors disabled:opacity-50"
            >
              {chip.label}
            </button>
          ))}
        </div>
      </div>

      {/* Voice Status or Transcribing Notice */}
      {(isRecording || isTranscribing || voiceError) && (
        <div className="px-4 py-1.5 bg-slate-900 border border-slate-800 rounded-xl text-xs flex items-center justify-between">
          {isRecording && (
            <div className="flex items-center gap-2 text-red-400">
              <span className="w-2.5 h-2.5 rounded-full bg-red-500 animate-ping" />
              <span className="font-semibold">Listening vernacular query... {formatTimer(recordingSeconds)}</span>
              <button
                type="button"
                onClick={stopRecording}
                className="ml-2 px-2 py-0.5 rounded bg-red-900 text-red-100 hover:bg-red-800 text-[10px] font-bold uppercase"
              >
                Stop &amp; Send
              </button>
            </div>
          )}

          {isTranscribing && (
            <div className="flex items-center gap-2 text-cyan-400">
              <svg className="animate-spin h-3.5 w-3.5" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
              <span>Whisper transcribing vernacular audio...</span>
            </div>
          )}

          {voiceError && (
            <div className="text-red-400 text-xs truncate">
              ⚠️ {voiceError}
            </div>
          )}
        </div>
      )}

      {/* Fixed Bottom Input Bar */}
      <form
        id="chat-form"
        data-testid="chat-form"
        onSubmit={handleSubmit}
        className="pt-2"
      >
        <div className={`flex items-center gap-2 rounded-2xl p-2.5 shadow-2xl transition-colors border ${
          isLight
            ? 'bg-white border-cyan-300 shadow-sky-900/10'
            : 'glass-panel bg-slate-950/95 border-2 border-cyan-500/40'
        }`}>
          {/* Vernacular Voice Microphone Button */}
          <button
            type="button"
            id="chat-voice-record-button"
            data-testid="chat-voice-record-button"
            aria-label={isRecording ? 'Stop recording vernacular query' : 'Speak query in vernacular language'}
            onClick={isRecording ? stopRecording : startRecording}
            disabled={isTranscribing}
            title={isRecording ? 'Stop recording' : 'Speak query in your language'}
            className={`p-2.5 rounded-xl transition-all flex items-center justify-center ${
              isRecording
                ? 'bg-red-600 text-white shadow-lg shadow-red-600/50 animate-pulse'
                : 'bg-slate-800 hover:bg-slate-700 text-cyan-400 border border-slate-700'
            }`}
          >
            {isRecording ? (
              <span className="text-base font-bold">⏹</span>
            ) : (
              <svg
                className="w-5 h-5"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="2"
                  d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m-4 0h8m-4-18a3 3 0 00-3 3v8a3 3 0 006 0V5a3 3 0 00-3-3z"
                />
              </svg>
            )}
          </button>

          <input
            ref={inputRef}
            id="chat-input"
            data-testid="chat-input"
            aria-label="Chat input query"
            type="text"
            value={inputVal}
            onChange={(e) => setInputVal(e.target.value)}
            placeholder={t('searchPlaceholder')}
            disabled={isStreaming || isRecording}
            className={`w-full bg-transparent text-sm focus:outline-none px-3 py-1.5 font-medium ${
              isLight ? 'text-slate-900 placeholder-slate-400' : 'text-slate-100 placeholder-slate-400'
            }`}
          />

          {/* Stop or Send Button */}
          {isStreaming ? (
            <button
              type="button"
              id="chat-stop-button"
              data-testid="chat-stop-button"
              aria-label="Stop response stream"
              onClick={stopStream}
              className="px-3.5 py-2.5 rounded-xl bg-amber-600 hover:bg-amber-500 text-white font-medium text-xs transition-colors shadow"
            >
              Stop
            </button>
          ) : (
            <button
              type="submit"
              id="chat-send-button"
              data-testid="chat-send-button"
              aria-label="Send message"
              disabled={!inputVal.trim() || isStreaming || isRecording}
              className="p-3 px-5 rounded-xl bg-gradient-to-r from-cyan-600 to-teal-600 text-white font-bold text-xs disabled:opacity-40 hover:scale-105 transition-transform shrink-0 shadow-md shadow-cyan-600/30 flex items-center gap-2"
            >
              <span>Send</span>
              <Send className="w-4 h-4" />
            </button>
          )}
        </div>
      </form>

      {/* Live Payload Inspector Modal */}
      <PayloadInspectorModal
        isOpen={inspectorData.isOpen}
        onClose={() => setInspectorData({ isOpen: false })}
        requestPayload={inspectorData.req}
        responsePayload={inspectorData.res}
      />
    </div>
  );
};

export default ChatScreen;
