/**
 * Chat history hydration — Wayfinder T6 (map #232).
 *
 * T1 #234 (locked): minimal+place {role,content,ts,place?,zone_id?},
 *   400->empty, 200 count:0->empty bubbles, limit 20, voice visible as text.
 * T3 #236 (locked): hide cards+keep banner both, hide tech both, verbatim
 *   lang, clarifications plain text, hide GPS (place names only).
 *
 * Engine only (no ChatPanel visuals — T7). Tests the pure hydrate mapper
 * + veto/filter gates that useSSEChat uses on sessionId init.
 *
 * Run: bun test tests/chatHistoryHydrate.test.ts
 */
import { describe, expect, it } from 'bun:test';
import {
  filterHumanEvidence,
  isDangerVeto,
  mapHistoryTurnsToMessages,
  getHistoryStorageKey,
  HISTORY_MESSAGE_CAP,
} from '../chat/useSSEChat';

describe('chat history hydrate — T1 minimal+place (T6)', () => {
  it('maps user+assistant turns verbatim with empty trace/cards', () => {
    const turns = [
      { role: 'user', content: 'fish near Kochi', ts: 1758600000.0, place: 'Kochi' },
      { role: 'assistant', content: 'Nearest zone ...', ts: 1758600001.0 },
    ];
    const msgs = mapHistoryTurnsToMessages(turns);
    expect(msgs).toHaveLength(2);
    expect(msgs[0].role).toBe('user');
    expect(msgs[0].content).toBe('fish near Kochi');
    expect(msgs[1].role).toBe('assistant');
    expect(msgs[1].content).toBe('Nearest zone ...');
    for (const m of msgs) {
      expect(m.reasoning_steps).toEqual([]);
      expect(m.zone_cards).toEqual([]);
      expect(m.isStreaming).toBe(false);
    }
    // ts seconds -> created_at ms
    expect(msgs[0].created_at).toBe(1758600000.0 * 1000);
    expect(msgs[1].created_at).toBe(1758600001.0 * 1000);
  });

  it('200 count:0 -> empty bubbles; malformed/legacy entries skipped', () => {
    expect(mapHistoryTurnsToMessages([])).toEqual([]);
    // legacy graph dead-persist shape {query,reply_summary} skipped on read (T4 untouched)
    expect(mapHistoryTurnsToMessages([{ query: 'x', reply_summary: 'y' } as any])).toEqual([]);
    expect(mapHistoryTurnsToMessages([{ role: 'user' } as any])).toEqual([]);
    expect(mapHistoryTurnsToMessages(null as any)).toEqual([]);
  });

  it('caps to last 20 (T1 limit 20)', () => {
    expect(HISTORY_MESSAGE_CAP).toBe(20);
    const many = Array.from({ length: 25 }, (_, i) => ({
      role: i % 2 === 0 ? 'user' : 'assistant',
      content: `q${i}`,
      ts: 1758600000 + i,
    }));
    const msgs = mapHistoryTurnsToMessages(many as any);
    expect(msgs).toHaveLength(20);
    expect(msgs[0].content).toBe('q5');
    expect(msgs[19].content).toBe('q24');
  });

  it('voice turns visible as text (verbatim)', () => {
    const msgs = mapHistoryTurnsToMessages([
      { role: 'user', content: 'meen pidikkan pattiya sthalam', ts: 1 },
    ]);
    expect(msgs).toHaveLength(1);
    expect(msgs[0].content).toBe('meen pidikkan pattiya sthalam');
  });

  it('storage key is orca_messages_<sid>', () => {
    expect(getHistoryStorageKey('abc123')).toBe('orca_messages_abc123');
  });
});

describe('chat history hydrate — T3 filters + veto (T6)', () => {
  it('hides tech: reasoning empty, tech evidence dropped, human kept', () => {
    const msgs = mapHistoryTurnsToMessages([
      { role: 'assistant', content: 'INCOIS SEC005 KERALA 02-Sep-2026', ts: 2 },
      { role: 'assistant', content: 'SELECT check_weather', ts: 3 },
      { role: 'assistant', content: 'open_meteo_live data', ts: 4 },
    ]);
    // verbatim content preserved
    expect(msgs[0].content).toBe('INCOIS SEC005 KERALA 02-Sep-2026');
    expect(msgs[1].content).toBe('SELECT check_weather');
    // trace hidden
    for (const m of msgs) expect(m.reasoning_steps).toEqual([]);
    // allowlist holds on hydrate
    expect(msgs[0].evidence).toEqual(['INCOIS SEC005 KERALA 02-Sep-2026']);
    expect(msgs[1].evidence).toEqual([]);
    expect(msgs[2].evidence).toEqual([]);
    // direct gate parity
    expect(filterHumanEvidence(['SELECT check_weather'])).toEqual([]);
    expect(filterHumanEvidence(['open_meteo_live data'])).toEqual([]);
  });

  it('veto: drop cards + keep banner text (no zone_cards ever)', () => {
    const msgs = mapHistoryTurnsToMessages([
      { role: 'assistant', content: 'DO NOT SAIL — cyclone near Kochi', ts: 5 },
    ]);
    expect(msgs[0].zone_cards).toEqual([]);
    // banner kept via verbatim text (no synthetic safety object)
    expect(msgs[0].content).toContain('DO NOT SAIL');
    expect(msgs[0].safety).toBeUndefined();
    // veto gate still authoritative for live safety objects
    expect(isDangerVeto({ danger: 'danger', badge: 'red', warning_text: 'DO NOT SAIL' })).toBe(true);
    expect(isDangerVeto({ danger: 'safe', badge: 'green', warning_text: 'SAFE' })).toBe(false);
  });

  it('clarifications stay plain text (no cards, no trace)', () => {
    const msgs = mapHistoryTurnsToMessages([
      { role: 'assistant', content: 'Which port? Kochi or Munambam?', ts: 6 },
    ]);
    expect(msgs[0].content).toBe('Which port? Kochi or Munambam?');
    expect(msgs[0].zone_cards).toEqual([]);
    expect(msgs[0].reasoning_steps).toEqual([]);
    expect(msgs[0].evidence).toEqual([]);
  });

  it('hides GPS: no map_data/coords/lat-lon numbers, place names only', () => {
    const msgs = mapHistoryTurnsToMessages([
      { role: 'user', content: 'fish near Kochi', ts: 7, place: 'Kochi' },
      { role: 'assistant', content: 'Nearest zone off Kochi', ts: 8, zone_id: 'SEC005-1' },
    ]);
    for (const m of msgs) {
      expect(m.map_data).toBeUndefined();
      expect(m.zone_cards).toEqual([]);
      const dumped = JSON.stringify(m);
      expect(dumped).not.toContain('pfz_features');
      expect(dumped).not.toContain('coordinates');
      expect(dumped).not.toContain('"lat"');
      expect(dumped).not.toContain('"lon"');
    }
    // place names survive only as verbatim text
    expect(msgs[0].content).toContain('Kochi');
  });
});
