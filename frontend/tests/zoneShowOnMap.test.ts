/**
 * Zone-card "Show on Map" contract.
 *
 * Production symptom (2026-09-23): the per-zone button only flew the map
 * highlight and never switched tabs. `page.tsx` renders exactly one tab
 * panel at a time, so clicking "Show on Map" left the user on Chat and the
 * button looked dead. The toolbar path already did both; this locks the
 * shared action so both call sites behave identically.
 *
 * Run: bun test tests/zoneShowOnMap.test.ts
 */
import { describe, expect, it } from 'bun:test';
import { showZoneOnMap } from '../lib/zoneMapAction';

interface FakeCard {
  id: string;
}

function makeDeps(order: string[]) {
  return {
    flyToZone: (card: FakeCard) => order.push(`fly:${card.id}`),
    setActiveTab: (tab: string) => order.push(`tab:${tab}`),
  };
}

describe('zone show-on-map action', () => {
  it('flies to the zone AND switches to the map tab', () => {
    const order: string[] = [];
    showZoneOnMap<FakeCard>({ id: 'SEC005-A' }, makeDeps(order));
    expect(order).toEqual(['fly:SEC005-A', 'tab:map']);
  });

  it('never switches tab without flying first', () => {
    const order: string[] = [];
    showZoneOnMap<FakeCard>({ id: 'z2' }, makeDeps(order));
    expect(order[0]).toBe('fly:z2');
    expect(order.indexOf('tab:map')).toBeGreaterThan(order.indexOf('fly:z2'));
  });

  it('passes the exact card through to flyToZone', () => {
    const card: FakeCard = { id: 'keep-identity' };
    let seen: FakeCard | null = null;
    showZoneOnMap<FakeCard>(card, {
      flyToZone: (c) => {
        seen = c;
      },
      setActiveTab: () => {},
    });
    expect(seen).toBe(card);
  });
});
