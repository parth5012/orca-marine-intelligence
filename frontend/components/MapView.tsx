/**
 * MapView Component
 *
 * Owner: M4 (Maps)
 * Module: frontend/components/MapView.tsx
 *
 * Interactive map showing PFZ zones, EEZ/MPA boundaries,
 * agent recommendation overlays, and user location.
 * Uses React Leaflet with vector tile support.
 *
 * Features:
 *     - PFZ zone polygons with intensity coloring (low/medium/high)
 *     - EEZ boundary lines (dashed, gray)
 *     - MPA restricted zones (red overlay)
 *     - Agent recommendation highlight (green polygon with pulse)
 *     - User GPS location marker
 *     - Bearing and distance lines to recommended zone
 *     - Zoom-to-zone on chat response
 *
 * Map layers:
 *     - pfz        — PFZ zone polygons (GeoJSON overlay)
 *     - eez        — EEZ boundaries (vector tiles)
 *     - mpa        — MPA zones (vector tiles)
 *     - recommend  — Agent recommendation highlight
 *
 * TODO:
 *     - [ ] Initialize React Leaflet map centered on Indian coast
 *     - [ ] Add PFZ GeoJSON layer with popup for zone details
 *     - [ ] Add EEZ/MPA boundary layers from vector tiles
 *     - [ ] Implement recommendation highlight with fly-to animation
 *     - [ ] Add GPS location tracking with device API
 *     - [ ] Implement bearing/distance line overlay
 */

export interface MapViewProps {
  center?: [number, number];   // [lat, lon] default: Kochi [9.93, 76.27]
  zoom?: number;
  highlightFeatures?: any[];
}

export default function MapView({ center = [9.93, 76.27], zoom = 8, highlightFeatures }: MapViewProps) {
  // TODO: Implement MapView component with React Leaflet
  return (
    <div className="map-view" style={{ height: '100vh', width: '100%' }}>
      <p>MapView — coming soon</p>
    </div>
  );
}
