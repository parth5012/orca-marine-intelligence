/**
 * Map Barrel Export
 *
 * Owner: M-D (Frontend & Maps)
 * Module: frontend/map/index.ts
 *
 * Re-exports map components and geo utilities for clean imports:
 * import MapView, { SafetyBadge, haversineDistance, bearing } from '@/map';
 */

export { default as MapView } from './MapView';
export { default } from './MapView';
export type { MapViewProps, MapLayerToggles } from './MapView';

export { default as SafetyBadge } from './SafetyBadge';
export type { SafetyBadgeProps, SeaStatus } from './SafetyBadge';
export { resolveSeaStatus } from './SafetyBadge';
export * from './drawerHonesty';

export { default as LayerControl } from './LayerControl';
export { default as MarineMap } from './MarineMap';
export type { MarineMapProps } from './MarineMap';
export { default as ExploreMap } from './ExploreMap';
export type { ExploreMapProps } from './ExploreMap';

export * from './geo';
export * from './boundaries';
export * from './carto';
export * from './layers';
