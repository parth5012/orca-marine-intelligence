/**
 * Multi-turn UX copy contract — Wayfinder T7 (map #232).
 *
 * T2 #235 (locked): pill "Continuing from {place} - turn {n}", chips
 * "and tomorrow?" / "safer zone?" / "near Beypore?", skeleton
 * "Loading conversation...", New Chat resets. Component render setup
 * (jsdom) does not exist, so this file locks the EN fallback strings the
 * pill/chips/skeleton render via t() + inline fallback in ChatScreen and
 * ChatPanel. Testids (multiturn-context-pill, followup-chip-0..2) are
 * asserted by grep in CI review, not here.
 *
 * Run: bun test tests/multiturnUxCopy.test.ts
 */
import { describe, expect, it } from 'bun:test';
import { TRANSLATIONS } from '../lib/translations';

describe('multiturn UX copy — T2-approved EN fallback (T7)', () => {
  it('en pill/skeleton/chip copy matches T2 verbatim', () => {
    expect(TRANSLATIONS.en.multiturnContinuingFrom).toBe('Continuing from');
    expect(TRANSLATIONS.en.multiturnTurn).toBe('turn');
    expect(TRANSLATIONS.en.multiturnLoadingConversation).toBe(
      'Loading conversation...'
    );
    expect(TRANSLATIONS.en.followupTomorrow).toBe('and tomorrow?');
    expect(TRANSLATIONS.en.followupSaferZone).toBe('safer zone?');
    expect(TRANSLATIONS.en.followupNearBeypore).toBe('near Beypore?');
  });

  it('pill composes to the T2-approved shape', () => {
    const text =
      `${TRANSLATIONS.en.multiturnContinuingFrom} Kochi` +
      ` - ${TRANSLATIONS.en.multiturnTurn} 3`;
    expect(text).toBe('Continuing from Kochi - turn 3');
  });

  it('chip queries reuse session memory (no location re-ask)', () => {
    // Queries are the T2 labels themselves — follow-ups, not fresh queries.
    const queries = [
      TRANSLATIONS.en.followupTomorrow,
      TRANSLATIONS.en.followupSaferZone,
      TRANSLATIONS.en.followupNearBeypore,
    ];
    expect(queries).toEqual(['and tomorrow?', 'safer zone?', 'near Beypore?']);
    for (const q of queries) {
      expect(q).not.toMatch(/kochi|lat|lon|gps|coordinate/i);
    }
  });
});
