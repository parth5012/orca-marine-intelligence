/**
 * ChatPanel Component
 *
 * Owner: M-E (Frontend Chat & App Shell) - Conversational Chat UI & SSE Consumer
 * Module: frontend/chat/ChatPanel.tsx
 *
 * Provides:
 * 1. Multi-turn conversational interface with SSE streaming
 * 2. Collapsible subagent reasoning trace accordion (Planner, FishFinder, WeatherAgent, DangerAgent, DecisionAgent)
 * 3. High-visibility danger banner ("DO NOT SAIL", "CAUTION", "SAFE", cyclone alerts)
 * 4. Structured Marine Zone Cards with bearing, distance km, depth, SST/Chlorophyll, safety status, and "Show on Map"
 * 5. Vernacular Voice Input (browser MediaRecorder -> POST /api/chat/voice -> Whisper -> auto-stream query)
 * 6. Quick action chips for common marine queries
 */

'use client';

import React, { useState, useRef, useEffect } from 'react';
import {
  useSSEChat,
  ChatMessage,
  ReasoningStep,
  MarineZoneCard,
  SafetyData,
} from './useSSEChat';

export interface ChatPanelProps {
  onLocationUpdate?: (lat: number, lon: number) => void;
  onMapHighlight?: (features: any[]) => void;
  currentLanguage?: string;
  onLanguageChange?: (lang: string) => void;
  userLocation?: { lat: number; lon: number } | null;
  onSafetyUpdate?: (safety: SafetyData) => void;
}

const QUICK_ACTIONS = [
  { label: '🐟 Fish near Kochi', query: 'Where are the nearest fishing zones near Kochi today?' },
  { label: '🌊 Weather report', query: 'What is the current wind and wave weather advisory?' },
  { label: '⚓ Is it safe to sail today?', query: 'Is it safe for a small motorized boat to sail right now?' },
  { label: '🌪️ Cyclone alert', query: 'Are there any cyclone or high-wave alerts for Kerala coast?' },
  { label: '📍 Munambam PFZ', query: 'Check PFZ fishing coordinates near Munambam.' },
];

export default function ChatPanel({
  onLocationUpdate,
  onMapHighlight,
  currentLanguage = 'en',
  onLanguageChange,
  userLocation,
  onSafetyUpdate,
}: ChatPanelProps) {
  const [inputText, setInputText] = useState<string>('');
  const [isRecording, setIsRecording] = useState<boolean>(false);
  const [recordingSeconds, setRecordingSeconds] = useState<number>(0);
  const [selectedZoneId, setSelectedZoneId] = useState<string | null>(null);
  const [expandedAccordions, setExpandedAccordions] = useState<Record<string, boolean>>({});

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
  });

  // Sync external language prop
  useEffect(() => {
    if (currentLanguage && currentLanguage !== language) {
      updateLanguage(currentLanguage);
    }
  }, [currentLanguage, language, updateLanguage]);

  // Auto-scroll on new messages or token stream
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isStreaming]);

  // Keep reasoning accordion open during streaming for active assistant turn
  useEffect(() => {
    const activeStreamingMsg = messages.find((m) => m.isStreaming && m.role === 'assistant');
    if (activeStreamingMsg && expandedAccordions[activeStreamingMsg.id] === undefined) {
      setExpandedAccordions((prev) => ({
        ...prev,
        [activeStreamingMsg.id]: true,
      }));
    }
  }, [messages, expandedAccordions]);

  const handleSend = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!inputText.trim() || isStreaming) return;
    const text = inputText;
    setInputText('');
    await sendMessage(text);
  };

  const handleQuickAction = async (query: string) => {
    if (isStreaming) return;
    setInputText('');
    await sendMessage(query);
  };

  const toggleAccordion = (msgId: string) => {
    setExpandedAccordions((prev) => ({
      ...prev,
      [msgId]: !prev[msgId],
    }));
  };

  const handleFlyToZone = (card: MarineZoneCard) => {
    setSelectedZoneId(card.id);
    if (card.coordinates && card.coordinates.length === 2) {
      onLocationUpdate?.(card.coordinates[0], card.coordinates[1]);
    }
    if (card.feature) {
      onMapHighlight?.([card.feature]);
    } else if (card.coordinates) {
      // Create lightweight GeoJSON point feature
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
          safety: card.safety_status,
        },
      };
      onMapHighlight?.([pointFeature]);
    }
  };

  // Vernacular Voice Recording handlers using browser MediaRecorder
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
        // Stop all audio tracks to release microphone hardware
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

      mediaRecorder.start(250); // Slice chunks every 250ms
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
    <div className="flex flex-col h-full bg-slate-950 text-slate-100 border-r border-slate-800 shadow-xl overflow-hidden">
      {/* Panel Header */}
      <div className="px-4 py-3 bg-slate-900/90 border-b border-slate-800 flex items-center justify-between backdrop-blur">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-tr from-cyan-600 to-blue-500 flex items-center justify-center text-white font-bold text-sm shadow-md shadow-cyan-900/30">
            🐬
          </div>
          <div>
            <h2 className="text-sm font-semibold text-white tracking-wide flex items-center gap-2">
              ORCA Advisory Stream
              <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-cyan-950 text-cyan-400 border border-cyan-800">
                SSE Live
              </span>
            </h2>
            <p className="text-[11px] text-slate-400">
              Multi-Agent Marine Brain • Session: <span className="font-mono text-cyan-300">{sessionId ? sessionId.slice(0, 8) : 'init'}</span>
            </p>
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={clearSession}
            disabled={isStreaming}
            title="Start new conversation"
            className="px-2.5 py-1 text-xs font-medium rounded-md bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors border border-slate-700 disabled:opacity-50"
          >
            New Chat
          </button>
        </div>
      </div>

      {/* Message History List */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {messages.length === 0 && (
          <div className="py-8 text-center space-y-3">
            <div className="w-14 h-14 mx-auto rounded-2xl bg-cyan-950/60 border border-cyan-800 flex items-center justify-center text-2xl shadow-inner">
              🌊
            </div>
            <h3 className="text-base font-semibold text-white">
              Welcome to ORCA Marine Intelligence
            </h3>
            <p className="text-xs text-slate-400 max-w-sm mx-auto leading-relaxed">
              Ask about potential fishing zones (PFZ), wave height, wind speeds, geofence safety, or weather conditions in your local vernacular.
            </p>
          </div>
        )}

        {messages.map((msg) => (
          <div key={msg.id} className="space-y-2">
            {/* User Message */}
            {msg.role === 'user' ? (
              <div className="flex justify-end">
                <div className="max-w-[85%] rounded-2xl rounded-tr-sm bg-gradient-to-r from-cyan-600 to-blue-600 px-4 py-2.5 text-sm text-white shadow-md">
                  <p className="whitespace-pre-wrap leading-relaxed">{msg.content}</p>
                  <span className="block text-[10px] text-cyan-200/70 text-right mt-1">
                    {new Date(msg.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </span>
                </div>
              </div>
            ) : (
              /* Assistant Message */
              <div className="flex flex-col space-y-2 max-w-[95%]">
                {/* Collapsible Reasoning Accordion */}
                {msg.reasoning_steps && msg.reasoning_steps.length > 0 && (
                  <div className="rounded-xl bg-slate-900/80 border border-slate-800 overflow-hidden shadow-sm">
                    <button
                      type="button"
                      onClick={() => toggleAccordion(msg.id)}
                      className="w-full px-3 py-2 flex items-center justify-between text-left text-xs bg-slate-900 hover:bg-slate-850 transition-colors border-b border-slate-800/60"
                    >
                      <div className="flex items-center gap-2">
                        {msg.isStreaming ? (
                          <span className="flex h-2 w-2 relative">
                            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75"></span>
                            <span className="relative inline-flex rounded-full h-2 w-2 bg-cyan-500"></span>
                          </span>
                        ) : (
                          <span className="text-emerald-400 text-xs">⚡</span>
                        )}
                        <span className="font-medium text-slate-300">
                          Multi-Agent Reasoning ({msg.reasoning_steps.length} {msg.reasoning_steps.length === 1 ? 'step' : 'steps'})
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        {msg.isStreaming && (
                          <span className="text-[10px] text-cyan-400 animate-pulse font-mono">
                            Analyzing telemetry...
                          </span>
                        )}
                        <svg
                          className={`w-3.5 h-3.5 text-slate-400 transition-transform ${
                            expandedAccordions[msg.id] ? 'rotate-180' : ''
                          }`}
                          fill="none"
                          stroke="currentColor"
                          viewBox="0 0 24 24"
                        >
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7" />
                        </svg>
                      </div>
                    </button>

                    {expandedAccordions[msg.id] && (
                      <div className="p-2.5 space-y-1.5 bg-slate-950/50">
                        {msg.reasoning_steps.map((step, sIdx) => (
                          <div
                            key={`${step.agent}-${sIdx}`}
                            className="flex items-center justify-between text-xs px-2 py-1.5 rounded-md bg-slate-900/60 border border-slate-800/60"
                          >
                            <div className="flex items-center gap-2">
                              {step.state === 'running' && (
                                <span className="w-2 h-2 rounded-full bg-cyan-400 animate-ping" />
                              )}
                              {step.state === 'done' && (
                                <span className="text-emerald-400 font-bold">✓</span>
                              )}
                              {step.state === 'timeout' && (
                                <span className="text-amber-400">⏱</span>
                              )}
                              {step.state === 'error' && (
                                <span className="text-red-400">✕</span>
                              )}
                              <span className="font-medium text-slate-200">
                                {step.title}
                              </span>
                            </div>

                            <div className="flex items-center gap-2 text-[10px] text-slate-400 font-mono">
                              {step.elapsed_ms != null && (
                                <span className="bg-slate-800 px-1.5 py-0.5 rounded text-slate-300">
                                  {step.elapsed_ms}ms
                                </span>
                              )}
                              <span className="capitalize text-slate-500">
                                {step.agent}
                              </span>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* High-Visibility Safety Danger Banner */}
                {msg.safety && (
                  <div>
                    {msg.safety.warning_text?.includes('DO NOT SAIL') ||
                    msg.safety.danger === 'danger' ||
                    msg.safety.danger === 'cyclone' ||
                    msg.safety.badge === 'red' ? (
                      <div className="rounded-xl bg-red-950/80 border-2 border-red-600/90 p-3 shadow-lg shadow-red-950/40 animate-pulse">
                        <div className="flex items-center gap-2.5">
                          <span className="text-xl" role="img" aria-label="Danger">
                            🚨
                          </span>
                          <div className="flex-1">
                            <div className="flex items-center justify-between">
                              <h4 className="text-xs font-black uppercase tracking-wider text-red-200">
                                HIGH RISK ADVISORY: {msg.safety.warning_text || 'DO NOT SAIL'}
                              </h4>
                              <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-red-800 text-white">
                                DANGER
                              </span>
                            </div>
                            <p className="text-xs text-red-100 font-medium mt-0.5">
                              Hazardous sea conditions. Wave height {msg.safety.waves_m ?? '--'}m, wind speed {msg.safety.wind_kts ?? '--'} kts.
                            </p>
                          </div>
                        </div>
                      </div>
                    ) : msg.safety.warning_text === 'CAUTION' ||
                      msg.safety.badge === 'amber' ||
                      msg.safety.danger === 'caution' ? (
                      <div className="rounded-xl bg-amber-950/70 border border-amber-500/80 p-3 shadow-md">
                        <div className="flex items-center gap-2.5">
                          <span className="text-xl">⚠️</span>
                          <div className="flex-1">
                            <div className="flex items-center justify-between">
                              <h4 className="text-xs font-bold uppercase tracking-wider text-amber-300">
                                SEA ADVISORY: CAUTION
                              </h4>
                              <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-700 text-white">
                                CAUTION
                              </span>
                            </div>
                            <p className="text-xs text-amber-200/90 mt-0.5">
                              Moderate sea conditions. Waves {msg.safety.waves_m ?? '--'}m, winds {msg.safety.wind_kts ?? '--'} kts. Proceed with vigilance.
                            </p>
                          </div>
                        </div>
                      </div>
                    ) : (
                      <div className="rounded-xl bg-emerald-950/50 border border-emerald-500/50 px-3 py-2 flex items-center justify-between">
                        <div className="flex items-center gap-2 text-xs text-emerald-300">
                          <span>✅</span>
                          <span className="font-semibold">SAFE CONDITIONS</span>
                          <span className="text-slate-400">
                            • Waves: {msg.safety.waves_m ?? '0.8'}m | Wind: {msg.safety.wind_kts ?? '10'} kts
                          </span>
                        </div>
                        <span className="text-[10px] font-bold bg-emerald-800 px-1.5 py-0.5 rounded text-white">
                          SAFE
                        </span>
                      </div>
                    )}
                  </div>
                )}

                {/* Assistant Message Bubble */}
                <div className="rounded-2xl rounded-tl-sm bg-slate-900 border border-slate-800 p-3.5 text-sm text-slate-100 shadow-md">
                  {msg.content ? (
                    <div className="prose prose-invert max-w-none text-sm leading-relaxed whitespace-pre-wrap">
                      {msg.content}
                    </div>
                  ) : msg.isStreaming ? (
                    <div className="flex items-center gap-2 text-xs text-cyan-300">
                      <span className="w-2 h-2 rounded-full bg-cyan-400 animate-ping"></span>
                      <span>ORCA Brain reasoning & translating advisory...</span>
                    </div>
                  ) : null}

                  {/* Error Indicator */}
                  {msg.error && (
                    <div className="mt-2 text-xs text-red-400 bg-red-950/40 p-2 rounded-lg border border-red-800/50">
                      ⚠️ {msg.error}
                    </div>
                  )}

                  {/* Evidence & Latency Footer */}
                  <div className="mt-3 pt-2 border-t border-slate-800/80 flex flex-wrap items-center justify-between gap-2 text-[10px] text-slate-400">
                    {msg.evidence && msg.evidence.length > 0 && (
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="text-slate-500 font-semibold">Evidence:</span>
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
                </div>

                {/* Structured Marine Zone Cards */}
                {msg.zone_cards && msg.zone_cards.length > 0 && (
                  <div className="space-y-2 pt-1">
                    <div className="flex items-center justify-between px-1">
                      <h4 className="text-xs font-semibold text-cyan-400 uppercase tracking-wider flex items-center gap-1.5">
                        <span>🎯</span> Recommended Fishing Zones ({msg.zone_cards.length})
                      </h4>
                      <span className="text-[10px] text-slate-400">Click to fly on map</span>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                      {msg.zone_cards.map((zone) => {
                        const isSelected = selectedZoneId === zone.id;
                        return (
                          <div
                            key={zone.id}
                            className={`rounded-xl p-3 text-xs transition-all border ${
                              isSelected
                                ? 'bg-cyan-950/80 border-cyan-400 shadow-md shadow-cyan-950/40'
                                : 'bg-slate-900 hover:bg-slate-850 border-slate-800'
                            }`}
                          >
                            <div className="flex items-start justify-between gap-2">
                              <h5 className="font-bold text-white text-sm truncate">
                                {zone.name}
                              </h5>
                              <span
                                className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${
                                  zone.safety_status === 'safe'
                                    ? 'bg-emerald-950 text-emerald-300 border border-emerald-700'
                                    : zone.safety_status === 'caution'
                                    ? 'bg-amber-950 text-amber-300 border border-amber-700'
                                    : 'bg-red-950 text-red-300 border border-red-700'
                                }`}
                              >
                                {zone.safety_status || 'Safe'}
                              </span>
                            </div>

                            <div className="grid grid-cols-2 gap-x-2 gap-y-1 mt-2 text-[11px] text-slate-300">
                              {zone.distance_km != null && (
                                <div>
                                  <span className="text-slate-500">Distance: </span>
                                  <span className="font-semibold text-white">
                                    {zone.distance_km} km
                                  </span>
                                </div>
                              )}
                              {zone.bearing != null && (
                                <div>
                                  <span className="text-slate-500">Bearing: </span>
                                  <span className="font-semibold text-cyan-300">
                                    {zone.bearing}°
                                  </span>
                                </div>
                              )}
                              {zone.depth_m != null && (
                                <div>
                                  <span className="text-slate-500">Depth: </span>
                                  <span className="font-semibold text-white">
                                    {zone.depth_m}m
                                  </span>
                                </div>
                              )}
                              {zone.sst_c != null && (
                                <div>
                                  <span className="text-slate-500">SST: </span>
                                  <span className="font-semibold text-amber-300">
                                    {zone.sst_c}°C
                                  </span>
                                </div>
                              )}
                              {zone.chlorophyll != null && (
                                <div className="col-span-2">
                                  <span className="text-slate-500">Chlorophyll: </span>
                                  <span className="font-semibold text-emerald-300">
                                    {zone.chlorophyll} mg/m³
                                  </span>
                                </div>
                              )}
                            </div>

                            <div className="mt-2.5 pt-2 border-t border-slate-800 flex items-center justify-end">
                              <button
                                type="button"
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
              </div>
            )}
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Quick Action Chips */}
      <div className="px-4 py-2 border-t border-slate-800/80 bg-slate-950/80">
        <div className="flex items-center gap-1.5 overflow-x-auto pb-1 text-xs no-scrollbar">
          {QUICK_ACTIONS.map((chip, idx) => (
            <button
              key={idx}
              type="button"
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
        <div className="px-4 py-1.5 bg-slate-900 border-t border-slate-800 text-xs flex items-center justify-between">
          {isRecording && (
            <div className="flex items-center gap-2 text-red-400">
              <span className="w-2.5 h-2.5 rounded-full bg-red-500 animate-ping"></span>
              <span className="font-semibold">Listening vernacular query... {formatTimer(recordingSeconds)}</span>
              <button
                type="button"
                onClick={stopRecording}
                className="ml-2 px-2 py-0.5 rounded bg-red-900 text-red-100 hover:bg-red-800 text-[10px] font-bold uppercase"
              >
                Stop & Send
              </button>
            </div>
          )}

          {isTranscribing && (
            <div className="flex items-center gap-2 text-cyan-400">
              <svg className="animate-spin h-3.5 w-3.5" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
              <span>Groq Whisper transcribing vernacular audio...</span>
            </div>
          )}

          {voiceError && (
            <div className="text-red-400 text-xs truncate">
              ⚠️ {voiceError}
            </div>
          )}
        </div>
      )}

      {/* Chat Input Bar */}
      <form
        onSubmit={handleSend}
        className="p-3 bg-slate-900 border-t border-slate-800 flex items-center gap-2"
      >
        {/* Vernacular Voice Microphone Button */}
        <button
          type="button"
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

        {/* Text Input */}
        <input
          ref={inputRef}
          type="text"
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          placeholder={
            isRecording
              ? 'Recording audio...'
              : language === 'ml'
              ? 'മീൻപിടുത്ത മേഖലകൾ ചോദിക്കുക...'
              : language === 'ta'
              ? 'மீன்பிடி மண்டலங்களை கேளுங்கள்...'
              : language === 'hi'
              ? 'मछली पकड़ने के क्षेत्र या मौसम पूछें...'
              : 'Ask ORCA in your vernacular language...'
          }
          disabled={isStreaming || isRecording}
          className="flex-1 bg-slate-950 border border-slate-700/80 rounded-xl px-3.5 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:border-transparent transition-all disabled:opacity-60"
        />

        {/* Stop or Send Button */}
        {isStreaming ? (
          <button
            type="button"
            onClick={stopStream}
            className="px-3.5 py-2.5 rounded-xl bg-amber-600 hover:bg-amber-500 text-white font-medium text-xs transition-colors shadow"
          >
            Stop
          </button>
        ) : (
          <button
            type="submit"
            disabled={!inputText.trim() || isStreaming || isRecording}
            className="px-3.5 py-2.5 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-bold text-sm transition-colors shadow-md shadow-cyan-500/20 disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center"
          >
            <svg
              className="w-4 h-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="2.5"
                d="M14 5l7 7m0 0l-7 7m7-7H3"
              />
            </svg>
          </button>
        )}
      </form>
    </div>
  );
}
