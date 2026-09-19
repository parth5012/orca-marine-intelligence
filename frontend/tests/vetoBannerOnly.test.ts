/**
 * Veto banner-only (#197 choice a, lane M-E).
 *
 * DO NOT SAIL never ships fish zones — ChatPanel renders the safety
 * banner only, never Recommended Zones cards. CAUTION/SAFE still show
 * cards. Single gate: useSSEChat.isDangerVeto (backend red/danger is
 * authoritative; warning_text DO NOT SAIL also vetoes).
 *
 * Run: bun test tests/vetoBannerOnly.test.ts
 */
import { describe, expect, it } from 'bun:test';
import { isDangerVeto } from '../chat/useSSEChat';

// Mirrors ChatPanel's card gate: cards render iff cards exist AND no veto.
function shouldShowCards(zoneCount: number, safety: any): boolean {
  return zoneCount > 0 && !isDangerVeto(safety ?? undefined);
}

describe('veto banner-only (#197 choice a)', () => {
  it('DO NOT SAIL veto hides cards even with zones present', () => {
    expect(shouldShowCards(3, { danger: 'danger', badge: 'red', warning_text: 'DO NOT SAIL' })).toBe(false);
    expect(shouldShowCards(1, { danger: 'cyclone', badge: 'red', warning_text: 'CYCLONE WARNING - DO NOT SAIL' })).toBe(false);
    expect(shouldShowCards(2, { danger: 'danger', badge: 'amber', warning_text: 'DO NOT SAIL' })).toBe(false);
  });

  it('CAUTION/SAFE still show cards', () => {
    expect(shouldShowCards(2, { danger: 'caution', badge: 'amber', warning_text: 'CAUTION' })).toBe(true);
    expect(shouldShowCards(1, { danger: 'none', badge: 'green', warning_text: 'SAFE' })).toBe(true);
    expect(shouldShowCards(1, { danger: 'safe', badge: 'green', warning_text: 'SAFE' })).toBe(true);
  });

  it('zero cards never render regardless of safety', () => {
    expect(shouldShowCards(0, { danger: 'none', badge: 'green', warning_text: 'SAFE' })).toBe(false);
    expect(shouldShowCards(0, { danger: 'danger', badge: 'red', warning_text: 'DO NOT SAIL' })).toBe(false);
  });
});
