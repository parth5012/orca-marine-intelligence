/**
 * ORCA Live AppContext (UI-MIG-T2)
 *
 * Owner: M-E (Frontend Chat & App Shell)
 * Module: frontend/context/AppContext.tsx
 *
 * DECISION (documented per ticket): single `frontend/context/AppContext.tsx`
 * is used instead of a separate `providers.tsx`. Rationale: smallest diff —
 * page.tsx imports one provider directly; no extra barrel/indirection.
 * LivingOceanBackground stays owned by `frontend/app/layout.tsx` (T1 landed
 * it there); page.tsx does NOT remount it.
 *
 * Live-only contract (no mock data, no simulators):
 * - NO mock imports, NO query-simulator handlers.
 * - Chat streaming lives in `frontend/chat/useSSEChat.ts` (ChatPanel).
 * - Map/PFZ data lives in MapView live props (highlightFeatures, center).
 * - This context owns ONLY: tab router state, theme, modals, language
 *   (localStorage `orca_language`), live GPS snapshot (synced FROM the
 *   page-shell geolocation effect), selected PFZ pointer, and a forced
 *   `authenticated` auth passthrough.
 */

'use client';

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';
import { TRANSLATIONS } from '@/lib/translations';

export type TabType =
  | 'home'
  | 'chat'
  | 'map'
  | 'alerts'
  | 'pfz-detail'
  | 'route'
  | 'profile';

export type ThemeMode = 'light' | 'dark';

export type AuthStep =
  | 'splash'
  | 'role-select'
  | 'official-login'
  | 'public-welcome'
  | 'authenticated';

export type UserRole = 'official' | 'public' | null;

export interface UserProfile {
  name: string;
  email?: string;
  org?: string;
  roleTitle: string;
}

/** Live GPS snapshot. Defaults to Kochi fallback until geolocation locks. */
export interface LiveUserLocation {
  lat: number;
  lon: number;
  name: string;
}

export type GpsStatus = 'acquiring' | 'locked' | 'default';

/**
 * Live alert ref (UI-MIG-T7).
 *
 * Shape mirrors the source design `AlertItem` (title/location/category/
 * severity/validity/description/coordinates) so AlertsScreen/AlertCard port
 * verbatim; all fields except id/severity stay optional for older writers.
 */
export type AlertCategory =
  | 'Critical'
  | 'Marine Warnings'
  | 'Weather'
  | 'Cyclone'
  | 'Lightning'
  | 'High Waves'
  | 'Wind';
export interface AlertRef {
  id: string;
  severity: string;
  title?: string;
  location?: string;
  category?: AlertCategory | string;
  validity?: string;
  description?: string;
  coordinates?: [number, number];
  radiusKm?: number;
}

/** Opaque selected-zone pointer (GeoJSON feature-ish, untyped on purpose). */
export type SelectedPFZ = {
  id?: string;
  name?: string;
  [key: string]: unknown;
} | null;

export const KOCHI_FALLBACK: LiveUserLocation = {
  lat: 9.93,
  lon: 76.27,
  name: 'Kochi, Kerala',
};

/** Minimal English labels for the tab router (vernacular labels stay in ChatPanel). */
const EN_LABELS: Record<string, string> = {
  home: 'Home',
  exploreMap: 'Explore Map',
  askOrca: 'Ask ORCA',
  alerts: 'Alerts',
  profile: 'Profile',
};

/** Pending home->chat query (UI-MIG-T3). HomeScreen writes, ChatPanel consumes. */
export interface PendingChatQuery {
  text: string;
  nonce: number;
}

/**
 * Map layer keys (UI-MIG-T5).
 *
 * Union of the 5 live engine keys (pfz/eez/mpa/imbl/weather, owned by
 * `frontend/map/MapInner`) and the 8 design-system pills from the source
 * `LayerControl` (sst/chlorophyll/waves/wind/currents/cyclone/lightning/
 * restricted). The 8 extra keys are VISUAL-ONLY filters over the same
 * live PFZ/weather/boundary sources — see `frontend/map/layers.ts`
 * LAYER_SOURCE_MAPPING. No new backend, no mock data.
 */
export type MapLayerKey =
  | 'pfz'
  | 'eez'
  | 'mpa'
  | 'imbl'
  | 'weather'
  | 'sst'
  | 'chlorophyll'
  | 'waves'
  | 'wind'
  | 'currents'
  | 'cyclone'
  | 'lightning'
  | 'restricted';

export type ActiveLayers = Record<MapLayerKey, boolean>;

export const DEFAULT_ACTIVE_LAYERS: ActiveLayers = {
  pfz: true,
  eez: true,
  mpa: true,
  imbl: true,
  weather: true,
  sst: true,
  chlorophyll: true,
  waves: true,
  wind: true,
  currents: false,
  cyclone: false,
  lightning: false,
  restricted: false,
};

interface AppContextType {
  activeTab: TabType;
  setActiveTab: (tab: TabType) => void;
  themeMode: ThemeMode;
  setThemeMode: (theme: ThemeMode) => void;
  toggleThemeMode: () => void;
  workflowModalOpen: boolean;
  setWorkflowModalOpen: (open: boolean) => void;
  voiceModalOpen: boolean;
  setVoiceModalOpen: (open: boolean) => void;
  selectedLanguage: string;
  setSelectedLanguage: (lang: string) => void;
  t: (key: string) => string;
  /** Pending home->chat query (UI-MIG-T3). HomeScreen writes, ChatPanel consumes. */
  pendingChatQuery: PendingChatQuery | null;
  submitChatQuery: (text: string) => void;
  consumeChatQuery: () => void;
  /** Live GPS snapshot (page shell syncs geolocation here). */
  userLocation: LiveUserLocation;
  setUserLocation: (loc: LiveUserLocation) => void;
  gpsStatus: GpsStatus;
  setGpsStatus: (status: GpsStatus) => void;
  /** Live alerts (UI-MIG-T7: wired to GET /api/weather/cyclone + current). */
  alertsList: AlertRef[];
  setAlertsList: (alerts: AlertRef[]) => void;
  /** Alert category filter (UI-MIG-T7, ported from source AlertsScreen). */
  selectedAlertFilter: string;
  setSelectedAlertFilter: (filter: string) => void;
  selectedPFZ: SelectedPFZ;
  setSelectedPFZ: (pfz: SelectedPFZ) => void;
  openPFZDetail: (pfz: Exclude<SelectedPFZ, null>) => void;
  startRouteNavigation: (pfz: Exclude<SelectedPFZ, null>) => void;
  /**
   * Pending map focus (UI-MIG-T6). `viewOnMap` sets the selected zone,
   * queues the raw live feature for the Shell to flyTo+highlight through
   * its guarded handleMapHighlight path, then switches to the map tab.
   * `mapFocusNonce` lets the Shell `useEffect` fire once per request.
   */
  mapFocusFeature: any | null;
  mapFocusNonce: number;
  requestMapFocus: (feature: any) => void;
  viewOnMap: (pfz: Exclude<SelectedPFZ, null>) => void;
  /** Shared map layers (UI-MIG-T5). toggleLayer stays AppContext-compatible. */
  activeLayers: ActiveLayers;
  setActiveLayers: (layers: ActiveLayers) => void;
  toggleLayer: (key: MapLayerKey) => void;
  activeRoute: [number, number][] | number[][] | null;
  setActiveRoute: (route: [number, number][] | number[][] | null) => void;
  // Auth passthrough — always authenticated (overlay forced authenticated).
  authStep: AuthStep;
  setAuthStep: (step: AuthStep) => void;
  userRole: UserRole;
  userProfile: UserProfile;
  loginAsOfficial: (email?: string, org?: string, name?: string) => void;
  loginAsPublic: (initialAction?: 'chat' | 'map' | 'voice') => void;
  logoutOrSwitchRole: () => void;
}

const AppContext = createContext<AppContextType | undefined>(undefined);

function readStored(key: string): string | null {
  if (typeof window === 'undefined') return null;
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function AppProvider({ children }: { children: React.ReactNode }) {
  // Reference UI lands on the home hero (greeting + live map preview).
  const [activeTab, setActiveTab] = useState<TabType>('home');
  const [themeMode, setThemeModeState] = useState<ThemeMode>('light');
  const [workflowModalOpen, setWorkflowModalOpen] = useState<boolean>(false);
  const [voiceModalOpen, setVoiceModalOpen] = useState<boolean>(false);
  const [selectedLanguage, setSelectedLanguageState] = useState<string>('en');
  const [userLocation, setUserLocation] =
    useState<LiveUserLocation>(KOCHI_FALLBACK);
  const [gpsStatus, setGpsStatus] = useState<GpsStatus>('acquiring');
  const [alertsList, setAlertsList] = useState<AlertRef[]>([]);
  const [selectedAlertFilter, setSelectedAlertFilter] = useState<string>('All');
  const [selectedPFZ, setSelectedPFZ] = useState<SelectedPFZ>(null);
  const [mapFocusFeature, setMapFocusFeature] = useState<any | null>(null);
  const [mapFocusNonce, setMapFocusNonce] = useState<number>(0);
  const [pendingChatQuery, setPendingChatQuery] =
    useState<PendingChatQuery | null>(null);
  const [activeLayers, setActiveLayers] =
    useState<ActiveLayers>(DEFAULT_ACTIVE_LAYERS);
  const [activeRoute, setActiveRoute] = useState<[number, number][] | number[][] | null>(null);

  // Hydrate theme + language from localStorage (layout init script owns .dark pre-paint).
  useEffect(() => {
    const storedTheme = readStored('orca_theme');
    if (storedTheme === 'dark' || storedTheme === 'light') {
      setThemeModeState(storedTheme);
      document.documentElement.classList.toggle('dark', storedTheme === 'dark');
    }
    const storedLang = readStored('orca_language');
    if (storedLang) setSelectedLanguageState(storedLang);
  }, []);

  const setThemeMode = useCallback((theme: ThemeMode) => {
    setThemeModeState(theme);
    try {
      localStorage.setItem('orca_theme', theme);
    } catch {
      /* storage unavailable — theme still applies in-memory */
    }
    if (typeof document !== 'undefined') {
      document.documentElement.classList.toggle('dark', theme === 'dark');
    }
  }, []);

  const toggleThemeMode = useCallback(() => {
    setThemeModeState((prev) => {
      const next = prev === 'light' ? 'dark' : 'light';
      try {
        localStorage.setItem('orca_theme', next);
      } catch {
        /* storage unavailable */
      }
      if (typeof document !== 'undefined') {
        document.documentElement.classList.toggle('dark', next === 'dark');
      }
      return next;
    });
  }, []);

  const setSelectedLanguage = useCallback((lang: string) => {
    setSelectedLanguageState(lang);
    try {
      localStorage.setItem('orca_language', lang);
    } catch {
      /* storage unavailable */
    }
  }, []);

  const t = useCallback(
    (key: string): string => {
      const lang = selectedLanguage;
      const dict =
        TRANSLATIONS[lang as keyof typeof TRANSLATIONS] ?? TRANSLATIONS.en;
      return (
        (dict as unknown as Record<string, string>)[key] ??
        (TRANSLATIONS.en as unknown as Record<string, string>)[key] ??
        EN_LABELS[key] ??
        key
      );
    },
    [selectedLanguage]
  );

  // Home -> chat handoff (UI-MIG-T3): queue the query, switch to chat tab.
  // ChatPanel consumes via pendingChatQuery and calls the real SSE sendMessage.
  const submitChatQuery = useCallback((text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    setActiveRoute(null);
    setPendingChatQuery({ text: trimmed, nonce: Date.now() });
    setActiveTab('chat');
  }, []);

  const consumeChatQuery = useCallback(() => {
    setPendingChatQuery(null);
  }, []);

  const openPFZDetail = useCallback((pfz: Exclude<SelectedPFZ, null>) => {
    setSelectedPFZ(pfz);
    setActiveTab('pfz-detail');
  }, []);

  const startRouteNavigation = useCallback(
    (pfz: Exclude<SelectedPFZ, null>) => {
      setSelectedPFZ(pfz);
      setActiveTab('route');
    },
    []
  );

  const requestMapFocus = useCallback((feature: any) => {
    setMapFocusFeature(feature ?? null);
    setMapFocusNonce((n) => n + 1);
  }, []);

  const viewOnMap = useCallback(
    (pfz: Exclude<SelectedPFZ, null>) => {
      setSelectedPFZ(pfz);
      setMapFocusFeature(pfz ?? null);
      setMapFocusNonce((n) => n + 1);
      setActiveTab('map');
    },
    []
  );

  const toggleLayer = useCallback((key: MapLayerKey) => {
    setActiveLayers((prev) => ({ ...prev, [key]: !prev[key] }));
  }, []);

  // Auth passthrough: everything resolves to authenticated.
  const [authStep, setAuthStepState] = useState<AuthStep>('authenticated');
  const [userRole] = useState<UserRole>('official');
  const [userProfile] = useState<UserProfile>({
    name: 'ORCA Operator',
    email: 'officer@incois.gov.in',
    org: 'INCOIS Coastal Command',
    roleTitle: 'Maritime Operator',
  });

  const setAuthStep = useCallback((_step: AuthStep) => {
    // Forced authenticated: role/splash steps never block the shell.
    setAuthStepState('authenticated');
  }, []);

  const loginAsOfficial = useCallback(() => {
    setAuthStepState('authenticated');
  }, []);

  const loginAsPublic = useCallback(
    (initialAction?: 'chat' | 'map' | 'voice') => {
      setAuthStepState('authenticated');
      if (initialAction === 'chat' || initialAction === 'map') {
        setActiveTab(initialAction);
      } else if (initialAction === 'voice') {
        setActiveTab('home');
        setVoiceModalOpen(true);
      }
    },
    []
  );

  const logoutOrSwitchRole = useCallback(() => {
    // Passthrough: stay authenticated, return to home tab.
    setAuthStepState('authenticated');
    setActiveTab('home');
  }, []);

  return (
    <AppContext.Provider
      value={{
        activeTab,
        setActiveTab,
        themeMode,
        setThemeMode,
        toggleThemeMode,
        workflowModalOpen,
        setWorkflowModalOpen,
        voiceModalOpen,
        setVoiceModalOpen,
        selectedLanguage,
        setSelectedLanguage,
        t,
        pendingChatQuery,
        submitChatQuery,
        consumeChatQuery,
        userLocation,
        setUserLocation,
        gpsStatus,
        setGpsStatus,
        alertsList,
        setAlertsList,
        selectedAlertFilter,
        setSelectedAlertFilter,
        selectedPFZ,
        setSelectedPFZ,
        openPFZDetail,
        startRouteNavigation,
        mapFocusFeature,
        mapFocusNonce,
        requestMapFocus,
        viewOnMap,
      activeLayers,
      setActiveLayers,
      toggleLayer,
      activeRoute,
      setActiveRoute,
        authStep,
        setAuthStep,
        userRole,
        userProfile,
        loginAsOfficial,
        loginAsPublic,
        logoutOrSwitchRole,
      }}
    >
      {children}
    </AppContext.Provider>
  );
}

export function useApp(): AppContextType {
  const context = useContext(AppContext);
  if (!context) {
    throw new Error('useApp must be used within an AppProvider');
  }
  return context;
}

export function useThemeModeOptional(): 'light' | 'dark' | null {
  try {
    const ctx = useContext(AppContext);
    return ctx?.themeMode ?? null;
  } catch {
    return null;
  }
}

