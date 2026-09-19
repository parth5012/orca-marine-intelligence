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
  // US-ORCA-014 canonical fields (backend GeoJSON contract)
  safety?: 'safe' | 'caution' | 'danger' | 'unknown';
  wave_m?: number;
  wind_kph?: number;
  confidence?: number;
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
  warning?: string;
  fallback?: boolean;
  fallback_message?: string;
  /** Backend dual-gate decision (chat.py): effective reply language. */
  response_language?: string;
  ui_language?: string;
  language_gated?: boolean;
}

export interface UseSSEChatOptions {
  initialLocation?: { lat: number; lon: number } | null;
  initialLanguage?: string;
  onMapHighlight?: (features: any[]) => void;
  onLocationUpdate?: (lat: number, lon: number) => void;
  onSafetyUpdate?: (safety: SafetyData) => void;
  onRouteChange?: (route: [number, number][] | number[][] | null) => void;
}

const AGENT_TITLE_MAP: Record<string, string> = {
  conversational_router: 'Conversational router checked intent',
  chitchat_responder: 'Direct chat reply (no marine tools)',
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

// US-ORCA-014 canonical helpers: normalize legacy backend fields to the
// canonical GeoJSON contract (safety, distance_km, depth_m, wave_m, wind_kph).
const KT_TO_KPH = 1.852;

function toKm(props: any): number | undefined {
  const raw = props.distance_km ?? props.distance_from_user_km ?? props.distance;
  if (raw == null || raw === '') return undefined;
  const n = Number(raw);
  return Number.isFinite(n) ? Number(n.toFixed(1)) : undefined;
}

function toKph(props: any): number | undefined {
  // Canonical wind_kph wins only when no knot source is present (mirrors backend).
  if (
    props.wind_kph != null &&
    props.wind_kt == null &&
    props.wind_speed_kt == null &&
    props.wind_kts == null &&
    props.wind == null
  ) {
    const n = Number(props.wind_kph);
    return Number.isFinite(n) ? Number(n.toFixed(1)) : undefined;
  }
  const kt = props.wind_kt ?? props.wind_speed_kt ?? props.wind_kts ?? props.wind;
  if (kt == null || kt === '') return undefined;
  const n = Number(kt);
  return Number.isFinite(n) ? Number((n * KT_TO_KPH).toFixed(1)) : undefined;
}

function toWaveM(props: any): number | undefined {
  const raw = props.wave_m ?? props.wave_height_m ?? props.wave ?? props.waves_m ?? props.waves;
  if (raw == null || raw === '') return undefined;
  const n = Number(raw);
  return Number.isFinite(n) ? Number(n.toFixed(2)) : undefined;
}

function toDepthM(props: any): number | undefined {
  const raw = props.depth_m ?? props.depth ?? props.depth_range ?? props.bathymetry;
  if (raw == null || raw === '') return undefined;
  if (typeof raw === 'number' && Number.isFinite(raw)) return raw;
  // depth_range string like "20-30" -> midpoint (mirrors backend _parse_depth_m)
  const nums = String(raw).match(/\d+(?:\.\d+)?/g);
  if (!nums || nums.length === 0) return undefined;
  const vals = nums.map(Number).filter(Number.isFinite);
  if (vals.length === 0) return undefined;
  if (vals.length >= 2) return Number(((vals[0] + vals[1]) / 2).toFixed(2));
  return vals[0];
}

function toSafety(props: any): 'safe' | 'caution' | 'danger' | 'unknown' {
  // Canonical `safety` first, then legacy danger/safety_status/danger_status.
  const raw = props.safety ?? props.danger ?? props.danger_status ?? props.safety_status ?? '';
  const v = String(raw).toLowerCase();
  if (v.includes('danger') || v.includes('red') || v.includes('cyclone') || v.includes('violation') || v === 'eez' || v === 'mpa') {
    return 'danger';
  }
  if (v.includes('caution') || v.includes('amber') || v.includes('warn')) {
    return 'caution';
  }
  if (v.includes('safe') || v.includes('green') || v === 'none') {
    return 'safe';
  }
  return 'unknown';
}

// ---------------------------------------------------------------------------
// Trace UX (#193) — human-readable evidence allowlist (mirrors
// backend/agents/graph.py::is_human_evidence). Mobile chat reads as
// advisory, not a debug log: multi-agent reasoning stays in
// `reasoning_steps` (Workflow modal) while `evidence` carries only the
// INCOIS citation, Wave/Wind human labels, geofence verdict, and
// forecast window. Raw internals (planner SELECT/SKIP lines, auto-filler
// completion lines, open_meteo source ids, selected_* fields, __M*__
// mask spans) are dropped here as defense-in-depth even though the
// backend already filters before streaming.
// ---------------------------------------------------------------------------

const INTERNAL_TRACE_MARKERS = [
  'trace line auto-added',
  'trace completion',
  'planner gave no justification',
  'llm gave no explicit justification',
];

const TRACE_PREFIXES = ['SELECT ', 'SKIP '];

const TRACE_TOOL_PREFIXES = [
  'find_fishing_zones',
  'check_ocean_state',
  'check_weather',
  'check_geofence',
];

// Geofence/safety verdict vocabulary (danger_agent warnings are spelled
// out — "Exclusive Economic Zone", "Marine Protected Area" — so match
// words, not just the EEZ/MPA abbreviations). Mirrors backend
// graph.py::_GEOFENCE_TOKENS.
const GEOFENCE_TOKENS = [
  'eez',
  'mpa',
  'violation',
  'warning',
  'banned',
  'not permitted',
  'protected area',
  'exclusive economic zone',
  'boundary',
  'imbl',
  'geofence',
  'cyclone',
  'lightning',
];

export function isHumanEvidence(item: unknown): boolean {
  if (typeof item !== 'string' || !item.trim()) return false;
  const s = item.trim();
  const lowered = s.toLowerCase();
  // Raw internals never pass, even inside otherwise-valid lines.
  if (s.includes('__M') || s.includes('open_meteo') || lowered.includes('selected_')) {
    return false;
  }
  if (INTERNAL_TRACE_MARKERS.some((m) => lowered.includes(m))) return false;
  if (TRACE_PREFIXES.some((p) => s.startsWith(p))) return false;
  if (lowered.startsWith('fuzzy port match:')) return false;
  if (TRACE_TOOL_PREFIXES.some((t) => lowered.startsWith(t))) return false;
  // System lines for non-advisory turns stay verbatim.
  if (
    lowered.includes('conversational reply') ||
    lowered.includes('clarification requested') ||
    lowered.includes('location not provided')
  ) {
    return true;
  }
  // Advisory allowlist: INCOIS citation, Wave/Wind labels,
  // geofence verdict, forecast window.
  if (s.startsWith('INCOIS')) return true;
  if (s.startsWith('Wave:') || s.startsWith('Wind:')) {
    // Reject raw source ids (marine_data_package, mock_heuristic,
    // open_meteo_live) — only human labels pass (no underscores).
    const value = s.slice(5);
    if (value.includes('_')) return false;
    return true;
  }
  if (GEOFENCE_TOKENS.some((t) => lowered.includes(t))) return true;
  if (lowered.includes('forecast')) return true;
  return false;
}

export function filterHumanEvidence(items: unknown): string[] {
  const list = Array.isArray(items) ? items : typeof items === 'string' ? [items] : [];
  const out: string[] = [];
  for (const e of list) {
    if (typeof e === 'string' && e.trim() && isHumanEvidence(e) && !out.includes(e)) {
      out.push(e);
    }
  }
  return out;
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
    options.onRouteChange?.(null);
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
      const depth = toDepthM(props);
      const bearing = props.bearing ?? (props.direction ? `${props.direction}` : undefined);
      const dist = toKm(props);
      const waveM = toWaveM(props);
      const windKph = toKph(props);
      const confidenceRaw = props.confidence;
      const confidence =
        confidenceRaw != null && Number.isFinite(Number(confidenceRaw))
          ? Number(Number(confidenceRaw).toFixed(2))
          : undefined;

      const safetyStatus = toSafety(props);

      const cardId = props.zone_id ? String(props.zone_id) : `zone-${idx}-${Date.now()}`;
      // Guard: backend occasionally sends the same zone twice with different
      // zone_ids (PostGIS yesterday+today rows, synthetic vs dated ids).
      // Canonical key = normalized name + rounded coords (~11m). Skip dupes.
      const normName = String(zoneName || '').trim().toLowerCase();
      const latR = coords ? Number(coords[0]).toFixed(4) : '';
      const lonR = coords ? Number(coords[1]).toFixed(4) : '';
      const canonKey = `${normName}|${latR}|${lonR}`;
      if (cards.some((c) => c.id === cardId)) return;
      if (canonKey !== '|' && cards.some((c) => {
        const cn = String((c as any).name || '').trim().toLowerCase();
        const cc = (c as any).coordinates as [number, number] | undefined;
        const clat = cc ? Number(cc[0]).toFixed(4) : '';
        const clon = cc ? Number(cc[1]).toFixed(4) : '';
        return `${cn}|${clat}|${clon}` === canonKey;
      })) return;
      cards.push({
        id: cardId,        name: zoneName,
        bearing,
        distance_km: dist,
        depth_m: depth,
        sst_c: typeof sst === 'number' ? Number(sst.toFixed(1)) : sst,
        chlorophyll: typeof chlorophyll === 'number' ? Number(chlorophyll.toFixed(2)) : chlorophyll,
        safety_status: safetyStatus,
        safety: safetyStatus,
        wave_m: waveM,
        wind_kph: windKph,
        confidence,
        coordinates: coords,
        feature: feat,
      });
    });

    return cards;
  }, []);

  const sendMessage = useCallback(
    async (text: string) => {
      if (!text.trim() || isStreaming) return;
      options.onRouteChange?.(null);

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

      // No client-side stream timeout — backend owns budgets (if needed later).
      // AbortController retained for manual cancel via stopStream only.

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
        let streamedContent = '';

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
            const agent = parsed.agent;
            const fallback = parsed.fallback;
            const isSynthError =
              agent === 'decision_agent' || fallback === 'none' || agent === 'none';
            if (streamedContent.trim() && isSynthError) {
              const warnMsg = parsed.message || 'Stream error occurred';
              setMessages((prevMsgs) =>
                prevMsgs.map((m) =>
                  m.id === assistantMessageId
                    ? { ...m, warning: warnMsg }
                    : m
                )
              );
              continue;
            }
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

          // Track streamed reply synchronously for non-fatal synth-error check above.
          if (type === 'token') {
            const tokenText = parsed.text ?? parsed.content ?? '';
            if (typeof tokenText === 'string') streamedContent += tokenText;
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
          case 'agent_progress':
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
              updated.fallback_message =
                parsed.message || 'using fallback (LLM unavailable)';
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

          if (route && Array.isArray(route) && route.length > 0) {
            options.onRouteChange?.(route);
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
                  const waves =
                    parsed.waves_m ?? parsed.wave_m ?? parsed.waves ?? null;
                  const windRaw =
                    parsed.wind_kts ??
                    parsed.wind ??
                    (parsed.wind_kph != null
                      ? Number(parsed.wind_kph) / KT_TO_KPH
                      : parsed.wind_kt != null
                      ? Number(parsed.wind_kt)
                      : null);
                  const wind =
                    typeof windRaw === 'number' && Number.isFinite(windRaw)
                      ? Number(windRaw.toFixed(1))
                      : windRaw;
                  const danger = parsed.danger || parsed.safety || 'unknown';
                  const badge = parsed.badge || (danger === 'safe' ? 'green' : 'amber');

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
                  // Ticket #193: allowlisted human pills only — raw trace /
                  // internals never enter chat state (Workflow modal keeps
                  // the full trace via reasoning_steps).
                  const humanItems = filterHumanEvidence(items);
                  const combined = Array.from(
                    new Set([...(updated.evidence || []), ...humanItems])
                  );
                  updated.evidence = combined;
                  break;
                }

                case 'done': {
                  updated.isStreaming = false;
                  updated.latency_ms = Date.now() - startTime;
                  updated.confidence = parsed.confidence;
                  if (typeof parsed.response_language === 'string') {
                    updated.response_language = parsed.response_language;
                  }
                  if (typeof parsed.ui_language === 'string') {
                    updated.ui_language = parsed.ui_language;
                  }
                  if (typeof parsed.language_gated === 'boolean') {
                    updated.language_gated = parsed.language_gated;
                  } else if (typeof parsed.language === 'string' && !updated.response_language) {
                    // Back-compat: older backend only sends `language`.
                    updated.response_language = parsed.language;
                  }
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
