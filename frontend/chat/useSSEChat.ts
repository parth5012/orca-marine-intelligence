/**
 * useSSEChat Hook
 *
 * Owner: M-E (Frontend Chat & App Shell) - SSE hook & consumer
 * Module: frontend/chat/useSSEChat.ts
 *
 * Manages chat messages, streaming state, session persistence,
 * SSE event stream parsing, subagent reasoning traces,
 * marine zone cards, safety warnings, and vernacular voice transcription.
 */

import { useState, useEffect, useRef, useCallback } from 'react';

export interface ReasoningStep {
  agent: string;
  state: 'running' | 'done' | 'timeout' | 'error' | 'fallback';
  elapsed_ms?: number;
  title: string;
  description?: string;
  timestamp: number;
}

export interface MarineZoneCard {
  id: string;
  name: string;
  bearing?: string | number;
  distance_km?: number;
  depth_m?: number;
  sst_c?: number;
  chlorophyll?: number;
  safety_status?: 'safe' | 'caution' | 'danger' | 'unknown';
  coordinates?: [number, number]; // [lat, lon]
  feature?: any;
}

export interface SafetyData {
  waves_m?: number | null;
  wind_kts?: number | null;
  danger?: string; // 'none' | 'caution' | 'danger' | 'cyclone' | 'eez' | 'mpa' | 'unknown'
  badge?: 'green' | 'amber' | 'red';
  warning_text?: string; // e.g. "DO NOT SAIL", "CAUTION", "SAFE"
  message?: string;
}

export interface MapEventData {
  center?: [number, number] | null;
  pfz_features?: any[];
  route?: any[];
  provisional?: boolean;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  created_at: number;
  isStreaming?: boolean;
  reasoning_steps: ReasoningStep[];
  zone_cards: MarineZoneCard[];
  map_data?: MapEventData;
  safety?: SafetyData;
  evidence: string[];
  latency_ms?: number;
  confidence?: number;
  error?: string;
  fallback?: boolean;
  fallback_message?: string;
}

export interface UseSSEChatOptions {
  initialLocation?: { lat: number; lon: number } | null;
  initialLanguage?: string;
  onMapHighlight?: (features: any[]) => void;
  onLocationUpdate?: (lat: number, lon: number) => void;
  onSafetyUpdate?: (safety: SafetyData) => void;
}

const AGENT_TITLE_MAP: Record<string, string> = {
  planner: 'Planner decomposed intent',
  fish_finder: 'FishFinder queried PFZ zones',
  sea_checker: 'SeaChecker analyzed ocean conditions',
  weather_agent: 'WeatherAgent checked wind/waves',
  danger_agent: 'DangerAgent verified geofence & security',
  parallel_analysis: 'Parallel multi-agent analysis',
  decision_agent: 'DecisionAgent synthesized recommendations',
  orchestrator: 'Orchestrator coordinated agents',
};

function getBackendBaseUrl(): string {
  if (typeof window === 'undefined') {
    return process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
  }
  const envUrl = process.env.NEXT_PUBLIC_API_URL;
  if (envUrl && envUrl.trim().length > 0) {
    return envUrl.replace(/\/$/, '');
  }
  // Default to localhost:8000 in dev or relative if served together
  return 'http://localhost:8000';
}

function generateUUID(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return 'session-' + Math.random().toString(36).substring(2, 15);
}

export function useSSEChat(options: UseSSEChatOptions = {}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState<boolean>(false);
  const [sessionId, setSessionId] = useState<string>('');
  const [language, setLanguage] = useState<string>(options.initialLanguage || 'en');
  const [location, setLocation] = useState<{ lat: number; lon: number } | null>(
    options.initialLocation || null
  );
  const [isTranscribing, setIsTranscribing] = useState<boolean>(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);

  const abortControllerRef = useRef<AbortController | null>(null);

  // Initialize session_id from localStorage or generate fresh
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const storedSession = localStorage.getItem('orca_session_id');
      if (storedSession) {
        setSessionId(storedSession);
      } else {
        const fresh = generateUUID();
        setSessionId(fresh);
        localStorage.setItem('orca_session_id', fresh);
      }

      const storedLang = localStorage.getItem('orca_language');
      if (storedLang) {
        setLanguage(storedLang);
      }
    }
  }, []);

  // Sync external location changes
  useEffect(() => {
    if (options.initialLocation) {
      setLocation(options.initialLocation);
    }
  }, [options.initialLocation]);

  const updateLanguage = useCallback((newLang: string) => {
    setLanguage(newLang);
    if (typeof window !== 'undefined') {
      localStorage.setItem('orca_language', newLang);
    }
  }, []);

  const updateLocation = useCallback((lat: number, lon: number) => {
    setLocation({ lat, lon });
    options.onLocationUpdate?.(lat, lon);
  }, [options]);

  const clearSession = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    const fresh = generateUUID();
    setSessionId(fresh);
    if (typeof window !== 'undefined') {
      localStorage.setItem('orca_session_id', fresh);
    }
    setMessages([]);
    setIsStreaming(false);
  }, []);

  const parseZoneFeatures = useCallback((features: any[] = [], center?: [number, number] | null): MarineZoneCard[] => {
    const cards: MarineZoneCard[] = [];
    if (!Array.isArray(features)) return cards;

    features.forEach((feat, idx) => {
      const props = feat?.properties || feat || {};
      const geom = feat?.geometry;
      let coords: [number, number] | undefined = undefined;

      if (geom?.coordinates) {
        if (geom.type === 'Point' && Array.isArray(geom.coordinates)) {
          // GeoJSON is [lon, lat]
          coords = [geom.coordinates[1], geom.coordinates[0]];
        } else if (geom.type === 'Polygon' && Array.isArray(geom.coordinates[0]?.[0])) {
          coords = [geom.coordinates[0][0][1], geom.coordinates[0][0][0]];
        }
      } else if (props.latitude && props.longitude) {
        coords = [Number(props.latitude), Number(props.longitude)];
      } else if (center && Array.isArray(center) && center.length === 2) {
        // Center is [lon, lat] from GeoJSON; convert to [lat, lon] for Leaflet
        coords = center[0] > 50 && center[1] < 40 ? [center[1], center[0]] : [center[0], center[1]];
      }

      const zoneName =
        props.place ||
        props.zone_name ||
        props.name ||
        props.title ||
        (props.zone_id ? `PFZ Zone #${props.zone_id}` : `Potential Fishing Zone ${idx + 1}`);

      const sst = props.sst ?? props.sst_c ?? (props.sea_surface_temp ? Number(props.sea_surface_temp) : undefined);
      const chlorophyll = props.chlorophyll ?? (props.chla ? Number(props.chla) : undefined);
      const depth = props.depth ?? props.depth_m ?? (props.bathymetry ? Number(props.bathymetry) : undefined);
      const bearing = props.bearing ?? (props.direction ? `${props.direction}` : undefined);
      const dist = props.distance_km ?? props.distance ?? undefined;

      let safetyStatus: 'safe' | 'caution' | 'danger' | 'unknown' = 'safe';
      const dangerVal = String(props.danger || props.danger_status || '').toLowerCase();
      if (dangerVal.includes('danger') || dangerVal.includes('red') || dangerVal.includes('cyclone') || dangerVal.includes('violation')) {
        safetyStatus = 'danger';
      } else if (dangerVal.includes('caution') || dangerVal.includes('amber') || dangerVal.includes('warn')) {
        safetyStatus = 'caution';
      }

      cards.push({
        id: props.zone_id ? String(props.zone_id) : `zone-${idx}-${Date.now()}`,
        name: zoneName,
        bearing,
        distance_km: typeof dist === 'number' ? Number(dist.toFixed(1)) : dist,
        depth_m: depth,
        sst_c: typeof sst === 'number' ? Number(sst.toFixed(1)) : sst,
        chlorophyll: typeof chlorophyll === 'number' ? Number(chlorophyll.toFixed(2)) : chlorophyll,
        safety_status: safetyStatus,
        coordinates: coords,
        feature: feat,
      });
    });

    return cards;
  }, []);

  const sendMessage = useCallback(
    async (text: string) => {
      if (!text.trim() || isStreaming) return;

      const userMessageId = `user-${Date.now()}`;
      const assistantMessageId = `asst-${Date.now()}`;
      const startTime = Date.now();

      const userMsg: ChatMessage = {
        id: userMessageId,
        role: 'user',
        content: text.trim(),
        created_at: startTime,
        reasoning_steps: [],
        zone_cards: [],
        evidence: [],
      };

      const assistantMsg: ChatMessage = {
        id: assistantMessageId,
        role: 'assistant',
        content: '',
        created_at: startTime,
        isStreaming: true,
        reasoning_steps: [],
        zone_cards: [],
        evidence: [],
      };

      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      setIsStreaming(true);

      const controller = new AbortController();
      abortControllerRef.current = controller;

      const activeSession = sessionId || generateUUID();
      const baseUrl = getBackendBaseUrl();
      const endpoint = `${baseUrl}/api/chat`;

      const payload = {
        message: text.trim(),
        session_id: activeSession,
        lat: location?.lat ?? null,
        lon: location?.lon ?? null,
        language: language || 'en',
      };

      try {
        let response: Response;
        try {
          response = await fetch(endpoint, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              Accept: 'text/event-stream',
            },
            body: JSON.stringify(payload),
            signal: controller.signal,
          });
        } catch (fetchErr: any) {
          // If connection to baseUrl failed (e.g. backend at relative /api/chat or proxy), try relative /api/chat
          if (baseUrl !== '' && baseUrl !== window.location.origin) {
            response = await fetch('/api/chat', {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                Accept: 'text/event-stream',
              },
              body: JSON.stringify(payload),
              signal: controller.signal,
            });
          } else {
            throw fetchErr;
          }
        }

        if (!response.ok) {
          throw new Error(`Chat API error: ${response.status} ${response.statusText}`);
        }

        if (!response.body) {
          throw new Error('ReadableStream not supported by browser response.');
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const parts = buffer.split('\n\n');
          buffer = parts.pop() || '';

          for (const part of parts) {
            if (!part.trim()) continue;

            const lines = part.split('\n');
            let eventType = 'message';
            let dataStr = '';

            for (const line of lines) {
              if (line.startsWith('event:')) {
                eventType = line.slice(6).trim();
              } else if (line.startsWith('data:')) {
                const dataPart = line.slice(5).trim();
                dataStr = dataStr ? `${dataStr}\n${dataPart}` : dataPart;
              }
            }

            if (!dataStr) continue;

            let parsed: any;
            try {
              parsed = JSON.parse(dataStr);
            } catch {
              continue;
            }

          const type = parsed.type || eventType;

          // Don't abort 'status' events. Only abort fatal 'error'.
          if (type === 'error') {
            setMessages((prevMsgs) => {
              const current = prevMsgs.find((m) => m.id === assistantMessageId);
              if (!current) return prevMsgs;
              return prevMsgs.map((m) =>
                m.id === assistantMessageId
                  ? {
                      ...m,
                      isStreaming: false,
                      error: parsed.message || 'Stream error occurred',
                    }
                  : m
              );
            });
            try {
              await reader.cancel();
            } catch {
              // ignore
            }
            break;
          }

          setMessages((prevMsgs) => {
              const current = prevMsgs.find((m) => m.id === assistantMessageId);
              if (!current) return prevMsgs;

              let updated = { ...current };

              switch (type) {
                case 'token': {
                  const tokenText = parsed.text ?? parsed.content ?? '';
                  updated.content = (updated.content || '') + tokenText;
                  break;
                }

          case 'status':
          case 'reasoning_step':
          case 'tool_call': {
            const agentKey = parsed.agent || parsed.name || 'orchestrator';
            const title =
              parsed.title ||
              parsed.description ||
              (parsed.state === 'fallback'
                ? 'Planner fallback advisory'
                : AGENT_TITLE_MAP[agentKey]) ||
              `Agent ${agentKey} active`;
            const state = parsed.state || 'running';
            const elapsed = parsed.elapsed_ms ?? undefined;

            if (state === 'fallback' || parsed.fallback === true) {
              updated.fallback = true;
              updated.fallback_message = 'using fallback (LLM unavailable)';
            }

            const existingIdx = updated.reasoning_steps.findIndex(
              (s) => s.agent === agentKey
            );

            const step: ReasoningStep = {
              agent: agentKey,
              state,
              elapsed_ms: elapsed,
              title,
              description:
                parsed.description ||
                parsed.summary ||
                (state === 'fallback' ? parsed.message : undefined),
              timestamp: Date.now(),
            };

            if (existingIdx >= 0) {
              const newSteps = [...updated.reasoning_steps];
              newSteps[existingIdx] = { ...newSteps[existingIdx], ...step };
              updated.reasoning_steps = newSteps;
            } else {
              updated.reasoning_steps = [...updated.reasoning_steps, step];
            }
            break;
          }

                case 'map':
                case 'zone_card': {
                  const center = parsed.center || null;
                  const pfzFeatures = parsed.pfz_features || parsed.features || [];
                  const route = parsed.route || [];

                  updated.map_data = {
                    center,
                    pfz_features: pfzFeatures,
                    route,
                    provisional: parsed.provisional,
                  };

                  const parsedCards = parseZoneFeatures(pfzFeatures, center);
                  if (parsedCards.length > 0) {
                    updated.zone_cards = parsedCards;
                  } else if (parsed.zones && Array.isArray(parsed.zones)) {
                    updated.zone_cards = parsed.zones;
                  }

                  if (pfzFeatures.length > 0) {
                    options.onMapHighlight?.(pfzFeatures);
                  }
          if (center && Array.isArray(center) && center.length === 2) {
            const actualLat = center[0] > 50 && center[1] < 40 ? center[1] : center[0];
            const actualLon = center[0] > 50 && center[1] < 40 ? center[0] : center[1];
            options.onLocationUpdate?.(actualLat, actualLon);
          }
                  break;
                }

                case 'safety':
                case 'safety_warning': {
                  const waves = parsed.waves_m ?? parsed.waves ?? null;
                  const wind = parsed.wind_kts ?? parsed.wind ?? null;
                  const danger = parsed.danger || 'none';
                  const badge = parsed.badge || (danger === 'none' ? 'green' : 'amber');

                  let warningText = 'SAFE';
                  const isHighDanger =
                    danger === 'danger' ||
                    danger === 'cyclone' ||
                    badge === 'red' ||
                    (typeof waves === 'number' && waves >= 2.5) ||
                    (typeof wind === 'number' && wind >= 30);

                  const isCaution =
                    danger === 'caution' ||
                    badge === 'amber' ||
                    (typeof waves === 'number' && waves >= 1.5) ||
                    (typeof wind === 'number' && wind >= 20);

                  if (danger === 'cyclone') {
                    warningText = 'CYCLONE WARNING - DO NOT SAIL';
                  } else if (isHighDanger) {
                    warningText = 'DO NOT SAIL';
                  } else if (isCaution) {
                    warningText = 'CAUTION';
                  } else if (badge === 'green') {
                    warningText = 'SAFE';
                  } else {
                    warningText = String(danger).toUpperCase();
                  }

                  const safetyObj: SafetyData = {
                    waves_m: waves,
                    wind_kts: wind,
                    danger,
                    badge,
                    warning_text: parsed.warning || warningText,
                    message: parsed.message || parsed.warning,
                  };

                  updated.safety = safetyObj;
                  options.onSafetyUpdate?.(safetyObj);
                  break;
                }

                case 'evidence': {
                  const items = Array.isArray(parsed.items)
                    ? parsed.items
                    : parsed.item
                    ? [parsed.item]
                    : [];
                  const combined = Array.from(
                    new Set([...(updated.evidence || []), ...items])
                  );
                  updated.evidence = combined;
                  break;
                }

                case 'done': {
                  updated.isStreaming = false;
                  updated.latency_ms = Date.now() - startTime;
                  updated.confidence = parsed.confidence;
                  if (parsed.session_id) {
                    setSessionId(parsed.session_id);
                    if (typeof window !== 'undefined') {
                      localStorage.setItem('orca_session_id', parsed.session_id);
                    }
                  }
                  break;
                }

          case 'error': {
            updated.isStreaming = false;
            updated.error = parsed.message || 'Stream error occurred';
            break;
          }

                default: {
                  if (parsed.text) {
                    updated.content = (updated.content || '') + parsed.text;
                  }
                  break;
                }
              }

              return prevMsgs.map((m) => (m.id === assistantMessageId ? updated : m));
            });
          }
        }
      } catch (err: any) {
        if (err.name === 'AbortError') {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMessageId
                ? { ...m, isStreaming: false, error: 'Query cancelled.' }
                : m
            )
          );
        } else {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMessageId
                ? {
                    ...m,
                    isStreaming: false,
                    error: err.message || 'Failed to connect to ORCA advisory stream.',
                  }
                : m
            )
          );
        }
      } finally {
        setIsStreaming(false);
        abortControllerRef.current = null;
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMessageId
              ? {
                  ...m,
                  isStreaming: false,
                  latency_ms: m.latency_ms || Date.now() - startTime,
                }
              : m
          )
        );
      }
    },
    [
      isStreaming,
      sessionId,
      location,
      language,
      parseZoneFeatures,
      options,
    ]
  );

  const stopStream = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
      setIsStreaming(false);
    }
  }, []);

  const sendVoiceAudio = useCallback(
    async (audioBlob: Blob): Promise<{ transcription: string } | null> => {
      setIsTranscribing(true);
      setVoiceError(null);

      const baseUrl = getBackendBaseUrl();
      const endpoint = `${baseUrl}/api/chat/voice`;
      const activeSession = sessionId || generateUUID();

      const formData = new FormData();
      formData.append('file', audioBlob, 'voice.wav');
      formData.append('session_id', activeSession);
      if (location?.lat != null) formData.append('lat', String(location.lat));
      if (location?.lon != null) formData.append('lon', String(location.lon));
      if (language) formData.append('language', language);

      try {
        let res: Response;
        try {
          res = await fetch(endpoint, {
            method: 'POST',
            body: formData,
          });
        } catch {
          // Fallback to relative /api/chat/voice if proxy configured
          res = await fetch('/api/chat/voice', {
            method: 'POST',
            body: formData,
          });
        }

        if (!res.ok) {
          throw new Error(`Voice transcription failed: ${res.status} ${res.statusText}`);
        }

        const data = await res.json();
        const transcription = data?.transcription || '';

        if (data?.session_id) {
          setSessionId(data.session_id);
          if (typeof window !== 'undefined') {
            localStorage.setItem('orca_session_id', data.session_id);
          }
        }

        if (transcription && transcription.trim()) {
          // Auto-trigger streaming advisory query with transcribed text
          await sendMessage(transcription.trim());
          return { transcription };
        } else {
          setVoiceError('No speech detected in audio.');
          return null;
        }
      } catch (err: any) {
        setVoiceError(err.message || 'Voice transcription failed.');
        return null;
      } finally {
        setIsTranscribing(false);
      }
    },
    [sessionId, location, language, sendMessage]
  );

  return {
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
    updateLocation,
    clearSession,
  };
}
