/**
 * LayerControl (UI-MIG-T5 & T12 #128).
 *
 * Owner: M-D (Frontend & Maps)
 * Module: frontend/map/LayerControl.tsx
 *
 * Visual copy of source design-system `LayerControl` (glass-panel card,
 * pill grid, semantic legend) rewired to LIVE state:
 * - Uses AppContext.activeLayers/toggleLayer when provider exists
 *   (AppContext-compatible per ticket); otherwise falls back to
 *   props.activeLayers/props.onToggle, otherwise internal default bag.
 * - Every pill keeps `id="layer-toggle-{key}"` + `data-testid` + `aria-label`
 *   + `aria-pressed`. 5 old keys (pfz/eez/mpa/imbl/weather) keep
 *   exact testids; 8 new visual-only keys gain `layer-toggle-*` too.
 * - Includes Base Cartography selector with Bhuvan Satellite (ISRO),
 *   CARTO Dark Matter, Esri Ocean, and OpenStreetMap (T12 #128).
 */

'use client';

import React, { useState } from 'react';
import {
  Layers,
  Thermometer,
  Waves,
  Wind,
  Zap,
  ShieldAlert,
  Anchor,
  Compass,
  CloudRain,
  Navigation,
  CloudSun,
  Leaf,
  Shield,
} from 'lucide-react';
import { useApp, DEFAULT_ACTIVE_LAYERS } from '@/context/AppContext';
import type { MapLayerKey } from '@/context/AppContext';
import type { BasemapStyle } from './carto';

interface LayerItem {
  key: MapLayerKey;
  label: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
  color: string;
}

const LAYER_ITEMS: LayerItem[] = [
  { key: 'pfz', label: 'PFZ Zones', description: 'Potential Fishing Zones', icon: Anchor, color: 'text-emerald-400' },
  { key: 'sst', label: 'SST Thermal', description: 'Sea Surface Temp (°C)', icon: Thermometer, color: 'text-amber-400' },
  { key: 'chlorophyll', label: 'Chlorophyll-a', description: 'Plankton Density (mg/m³)', icon: Leaf, color: 'text-cyan-400' },
  { key: 'waves', label: 'Wave Heights', description: 'Swell & Wave Surge (m)', icon: Waves, color: 'text-blue-400' },
  { key: 'wind', label: 'Wind Vectors', description: 'Surface Wind Speed & Dir', icon: Wind, color: 'text-sky-300' },
  { key: 'currents', label: 'Currents', description: 'Sea Surface Currents (kt)', icon: Navigation, color: 'text-teal-300' },
  { key: 'cyclone', label: 'Cyclone Track', description: 'Tropical Storm Radar', icon: CloudRain, color: 'text-rose-400' },
  { key: 'lightning', label: 'Lightning Strikes', description: 'Convective Cloud Alert', icon: Zap, color: 'text-yellow-400' },
  { key: 'restricted', label: 'Restricted Zones', description: 'Naval & Firing Buffer', icon: ShieldAlert, color: 'text-purple-400' },
  { key: 'eez', label: 'EEZ Boundary', description: 'Maritime Border Line', icon: Compass, color: 'text-teal-300' },
  { key: 'mpa', label: 'MPA Sanctuaries', description: 'Protected No-Take Zones', icon: Shield, color: 'text-red-400' },
  { key: 'imbl', label: 'IMBL Border', description: 'India–Sri Lanka Line', icon: Navigation, color: 'text-orange-400' },
  { key: 'weather', label: 'Weather Telemetry', description: 'Live Ocean Telemetry', icon: CloudSun, color: 'text-cyan-300' },
];

export interface LayerControlProps {
  activeLayers?: Partial<Record<MapLayerKey, boolean>>;
  onToggle?: (key: MapLayerKey) => void;
  basemapStyle?: BasemapStyle;
  onSelectBasemap?: (style: BasemapStyle) => void;
}

function useLayerState(props: LayerControlProps) {
  let ctx: ReturnType<typeof useApp> | null = null;
  try {
    ctx = useApp();
  } catch {
    ctx = null;
  }

  const [internal, setInternal] = useState<Record<MapLayerKey, boolean>>({
    ...DEFAULT_ACTIVE_LAYERS,
    ...props.activeLayers,
  });

  if (ctx && ctx.activeLayers && !props.activeLayers && !props.onToggle) {
    return {
      active: ctx.activeLayers as Record<MapLayerKey, boolean>,
      toggle: ctx.toggleLayer,
    };
  }

  if (props.activeLayers || props.onToggle) {
    return {
      active: { ...DEFAULT_ACTIVE_LAYERS, ...props.activeLayers },
      toggle: (key: MapLayerKey) => {
        if (props.onToggle) props.onToggle(key);
        else setInternal((prev) => ({ ...prev, [key]: !prev[key] }));
      },
    };
  }

  return {
    active: internal,
    toggle: (key: MapLayerKey) => {
      setInternal((prev) => ({ ...prev, [key]: !prev[key] }));
    },
  };
}

export const LayerControl: React.FC<LayerControlProps> = (props) => {
  const { active, toggle } = useLayerState(props);
  const activeCount = Object.values(active).filter(Boolean).length;

  return (
    <div
      id="layer-control"
      data-testid="layer-control"
      className="glass-panel rounded-2xl p-4 border border-cyan-900/40 bg-slate-950/90 shadow-xl"
    >
      <div className="flex items-center justify-between pb-3 mb-3 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <Layers className="w-5 h-5 text-cyan-400" />
          <h3 className="font-bold text-sm text-cyan-100 uppercase tracking-wider">
            Marine Map Layers
          </h3>
        </div>
        <span className="text-[11px] bg-cyan-950 text-cyan-400 px-2 py-0.5 rounded border border-cyan-800 font-mono">
          {activeCount} Active
        </span>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2.5">
        {LAYER_ITEMS.map((layer) => {
          const Icon = layer.icon;
          const isActive = !!active[layer.key];
          return (
            <button
              key={layer.key}
              type="button"
              id={`layer-toggle-${layer.key}`}
              data-testid={`layer-toggle-${layer.key}`}
              aria-label={`Toggle ${layer.label} Layer`}
              aria-pressed={isActive}
              onClick={() => toggle(layer.key)}
              className={`flex items-center gap-2.5 p-2.5 rounded-xl border text-left transition-all ${
                isActive
                  ? 'bg-cyan-500/20 border-cyan-500/50 text-cyan-100 shadow-md shadow-cyan-950/40'
                  : 'bg-slate-900/50 border-slate-800 text-slate-400 hover:bg-slate-800/80 hover:text-slate-200'
              }`}
            >
              <div
                className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${
                  isActive ? 'bg-cyan-950 border border-cyan-800' : 'bg-slate-950'
                }`}
              >
                <Icon className={`w-4 h-4 ${layer.color}`} />
              </div>
              <div className="overflow-hidden">
                <div className="font-semibold text-xs leading-snug truncate">{layer.label}</div>
                <div className="text-[10px] text-slate-400 leading-tight truncate">
                  {layer.description}
                </div>
              </div>
            </button>
          );
        })}
      </div>

      {/* Base Cartography Selector (T12 #128) */}
      <div className="mt-4 pt-3 border-t border-slate-800">
        <div className="flex items-center justify-between mb-2">
          <span className="text-slate-400 font-mono text-[11px] uppercase tracking-wider">
            Base Cartography
          </span>
          <span className="text-[10px] text-cyan-400 font-mono">ISRO Bhuvan Available</span>
        </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
        <button
          type="button"
          id="basemap-option-bhuvan"
          data-testid="basemap-option-bhuvan"
          aria-label="Select Bhuvan Satellite Base Layer"
          onClick={() => props.onSelectBasemap?.('bhuvan')}
          className={`flex items-center gap-2 p-2 rounded-xl border text-left transition-all ${
            props.basemapStyle === 'bhuvan'
              ? 'bg-cyan-500/20 border-cyan-500/50 text-cyan-100 shadow-md shadow-cyan-950/40'
              : 'bg-slate-900/50 border-slate-800 text-slate-300 hover:bg-slate-800/80 hover:text-white'
          }`}
        >
          <span className="text-lg">🛰️</span>
          <div className="overflow-hidden">
            <div className="font-semibold text-xs leading-snug truncate">Bhuvan Satellite</div>
            <div className="text-[10px] text-slate-400 leading-tight truncate">ISRO Satellite (WMS)</div>
          </div>
        </button>
        <button
          type="button"
          id="basemap-option-dark_all"
          data-testid="basemap-option-dark_all"
          aria-label="Select CARTO Dark Matter Base Layer"
          onClick={() => props.onSelectBasemap?.('dark_all')}
          className={`flex items-center gap-2 p-2 rounded-xl border text-left transition-all ${
            props.basemapStyle === 'dark_all'
              ? 'bg-cyan-500/20 border-cyan-500/50 text-cyan-100 shadow-md shadow-cyan-950/40'
              : 'bg-slate-900/50 border-slate-800 text-slate-300 hover:bg-slate-800/80 hover:text-white'
          }`}
        >
          <span className="text-lg">🌙</span>
          <div className="overflow-hidden">
            <div className="font-semibold text-xs leading-snug truncate">CARTO Dark</div>
            <div className="text-[10px] text-slate-400 leading-tight truncate">Tactical Night Radar</div>
          </div>
        </button>
        <button
          type="button"
          id="basemap-option-esri_ocean"
          data-testid="basemap-option-esri_ocean"
          aria-label="Select Esri Ocean Base Layer"
          onClick={() => props.onSelectBasemap?.('esri_ocean')}
          className={`flex items-center gap-2 p-2 rounded-xl border text-left transition-all ${
            props.basemapStyle === 'esri_ocean'
              ? 'bg-cyan-500/20 border-cyan-500/50 text-cyan-100 shadow-md shadow-cyan-950/40'
              : 'bg-slate-900/50 border-slate-800 text-slate-300 hover:bg-slate-800/80 hover:text-white'
          }`}
        >
          <span className="text-lg">🌊</span>
          <div className="overflow-hidden">
            <div className="font-semibold text-xs leading-snug truncate">Esri Ocean</div>
            <div className="text-[10px] text-slate-400 leading-tight truncate">Bathymetric Relief</div>
          </div>
        </button>
        <button
          type="button"
          id="basemap-option-esri_dark"
          data-testid="basemap-option-esri_dark"
          aria-label="Select Esri Dark Gray Base Layer"
          onClick={() => props.onSelectBasemap?.('esri_dark')}
          className={`flex items-center gap-2 p-2 rounded-xl border text-left transition-all ${
            props.basemapStyle === 'esri_dark'
              ? 'bg-cyan-500/20 border-cyan-500/50 text-cyan-100 shadow-md shadow-cyan-950/40'
              : 'bg-slate-900/50 border-slate-800 text-slate-300 hover:bg-slate-800/80 hover:text-white'
          }`}
        >
          <span className="text-lg">🌌</span>
          <div className="overflow-hidden">
            <div className="font-semibold text-xs leading-snug truncate">Esri Dark</div>
            <div className="text-[10px] text-slate-400 leading-tight truncate">Dark Gray Canvas</div>
          </div>
        </button>
        <button
          type="button"
          id="basemap-option-osm"
          data-testid="basemap-option-osm"
          aria-label="Select OpenStreetMap Base Layer"
          onClick={() => props.onSelectBasemap?.('osm')}
          className={`flex items-center gap-2 p-2 rounded-xl border text-left transition-all ${
            props.basemapStyle === 'osm'
              ? 'bg-cyan-500/20 border-cyan-500/50 text-cyan-100 shadow-md shadow-cyan-950/40'
              : 'bg-slate-900/50 border-slate-800 text-slate-300 hover:bg-slate-800/80 hover:text-white'
          }`}
        >
            <span className="text-lg">🌐</span>
            <div className="overflow-hidden">
              <div className="font-semibold text-xs leading-snug truncate">OpenStreetMap</div>
              <div className="text-[10px] text-slate-400 leading-tight truncate">Standard Cartography</div>
            </div>
          </button>
        </div>
      </div>

      <div className="mt-4 pt-3 border-t border-slate-800 flex flex-wrap items-center justify-between text-xs font-semibold gap-2">
        <span className="text-slate-400 font-mono text-[11px]">SEMANTIC LEGEND:</span>
        <div className="flex flex-wrap items-center gap-3 text-[11px]">
          <span className="flex items-center gap-1 text-emerald-400">🟢 Safe</span>
          <span className="flex items-center gap-1 text-amber-400">🟡 Caution</span>
          <span className="flex items-center gap-1 text-rose-400">🔴 Hazard</span>
          <span className="flex items-center gap-1 text-purple-400">🚫 Restricted</span>
          <span className="flex items-center gap-1 text-cyan-400">🔵 Current Location</span>
        </div>
      </div>
    </div>
  );
};

export default LayerControl;
