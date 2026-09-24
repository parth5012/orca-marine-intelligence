/**
 * Zone-card "Show on Map" shared action (M-E).
 *
 * `page.tsx` renders exactly one tab panel at a time, so a zone card action
 * MUST switch to the map tab or the user keeps staring at Chat and the
 * button looks dead. Both the per-zone card button and the toolbar button
 * route through here so they cannot drift apart.
 */

export const ZONE_MAP_TAB = 'map';

export interface ZoneShowOnMapDeps<TCard> {
  flyToZone: (card: TCard) => void;
  /** Contravariant: callers may pass a wider tab union than 'map'. */
  setActiveTab: (tab: typeof ZONE_MAP_TAB) => void;
}

export function showZoneOnMap<TCard>(
  card: TCard,
  { flyToZone, setActiveTab }: ZoneShowOnMapDeps<TCard>
): void {
  flyToZone(card);
  setActiveTab(ZONE_MAP_TAB);
}
