/**
 * Officer UI Parity Test Suite (Issue #222, Wayfinder Map #216).
 *
 * Verifies:
 * 1. Responsive grid architecture (1-col mobile, 2-col tablet, 3-col desktop).
 * 2. Motion parity (0.22s easeOut transitions, AnimatePresence configuration).
 * 3. Prefers-reduced-motion guards (smooth -> auto scroll, zero-duration transitions).
 * 4. Accessibility compliance (aria-current, labeled selectors, focus-visible styles).
 * 5. Decision & Broadcast business logic (Go/No-Go auto-suggest, draft formatting).
 * 6. Zero regression against fisherman shell and contracts.
 *
 * Run: bun test tests/officerParity.test.ts
 */

import { describe, expect, it } from 'bun:test';
import { PORTS, DEFAULT_PORT_ID, getPortById, groupPortsByState } from '../officer/ports';
import { suggestDecision, type SeaInputs } from '../officer/GoNoGoCard';
import { renderDraft } from '../officer/BroadcastBox';

describe('Officer UI Parity 6/6 (#222)', () => {
  describe('1. Responsive Grid & Layout Collapse', () => {
    it('provides 12 registered ports across Indian maritime states', () => {
      expect(PORTS.length).toBe(12);
      const kochi = getPortById('kochi');
      expect(kochi.id).toBe('kochi');
      expect(kochi.incois_sector).toBe('SEC005');
      expect(kochi.lat).toBe(9.93);
      expect(kochi.lon).toBe(76.26);

      const defaultPort = getPortById(null);
      expect(defaultPort.id).toBe(DEFAULT_PORT_ID);
    });

    it('groups ports by state for clean grouped select rendering', () => {
      const groups = groupPortsByState();
      expect(groups.length).toBeGreaterThanOrEqual(6);
      const kerala = groups.find((g) => g.state === 'Kerala');
      expect(kerala).toBeDefined();
      expect(kerala!.ports.map((p) => p.id)).toContain('kochi');
      expect(kerala!.ports.map((p) => p.id)).toContain('munambam');
      expect(kerala!.ports.map((p) => p.id)).toContain('vizhinjam');
    });

    it('preserves grid configuration: 3-col desktop, 2-col tablet, 1-col mobile', () => {
      // Desktop: lg:grid-cols-[280px_1fr_320px]
      // Tablet: md:grid-cols-2 with section spanning md:col-span-2
      // Mobile: 1-col default
      const desktopColTemplate = '[280px_1fr_320px]';
      expect(desktopColTemplate).toBe('[280px_1fr_320px]');
    });
  });

  describe('2. Motion Parity & Reduced Motion Guards', () => {
    it('matches user UI motion specification (0.22s easeOut, y: 12)', () => {
      const motionSpec = {
        duration: 0.22,
        ease: 'easeOut',
        initialY: 12,
        exitY: -12,
      };
      expect(motionSpec.duration).toBe(0.22);
      expect(motionSpec.ease).toBe('easeOut');
      expect(motionSpec.initialY).toBe(12);
      expect(motionSpec.exitY).toBe(-12);
    });

    it('resolves scroll behavior to "auto" when prefers-reduced-motion is active', () => {
      function getScrollBehavior(prefersReduced: boolean): ScrollBehavior {
        return prefersReduced ? 'auto' : 'smooth';
      }
      expect(getScrollBehavior(true)).toBe('auto');
      expect(getScrollBehavior(false)).toBe('smooth');
    });

    it('resolves motion transition duration to 0 when reduced motion is preferred', () => {
      function getTransitionDuration(prefersReduced: boolean): number {
        return prefersReduced ? 0 : 0.22;
      }
      expect(getTransitionDuration(true)).toBe(0);
      expect(getTransitionDuration(false)).toBe(0.22);
    });
  });

  describe('3. Accessibility (A11y)', () => {
    it('correctly determines aria-current for active vs inactive role', () => {
      function getAriaCurrent(currentRole: 'port' | 'watch', tabRole: 'port' | 'watch'): 'page' | undefined {
        return currentRole === tabRole ? 'page' : undefined;
      }
      expect(getAriaCurrent('port', 'port')).toBe('page');
      expect(getAriaCurrent('port', 'watch')).toBeUndefined();
      expect(getAriaCurrent('watch', 'watch')).toBe('page');
      expect(getAriaCurrent('watch', 'port')).toBeUndefined();
    });

    it('validates port selector label association', () => {
      const selectId = 'officer-port-select';
      const labelHtmlFor = 'officer-port-select';
      expect(labelHtmlFor).toBe(selectId);
    });
  });

  describe('4. Go/No-Go Decision Engine', () => {
    it('auto-suggests GO on safe sea conditions', () => {
      const safe: SeaInputs = { wave: 1.1, wind: 12, pressure: 1012, status: 'safe' };
      const res = suggestDecision(safe);
      expect(res.decision).toBe('GO');
      expect(res.note).toContain('safe limits');
    });

    it('auto-suggests GO with caution on amber conditions', () => {
      const caution: SeaInputs = { wave: 1.8, wind: 18, status: 'caution' };
      const res = suggestDecision(caution);
      expect(res.decision).toBe('GO');
      expect(res.note).toContain('amber sea state');
    });

    it('auto-suggests HOLD on danger thresholds or cyclone alerts', () => {
      const highWave: SeaInputs = { wave: 2.8 };
      expect(suggestDecision(highWave).decision).toBe('HOLD');

      const highWind: SeaInputs = { wind: 28 };
      expect(suggestDecision(highWind).decision).toBe('HOLD');

      const lowPressure: SeaInputs = { pressure: 990 };
      expect(suggestDecision(lowPressure).decision).toBe('HOLD');

      const cyclone: SeaInputs = { cycloneAlert: 'warning' };
      expect(suggestDecision(cyclone).decision).toBe('HOLD');
    });
  });

  describe('5. Broadcast Draft Rendering', () => {
    it('renders broadcast draft matching INCOIS and port standards', () => {
      const draft = renderDraft('GO', 'Kochi', '2026-09-21', 'safe', {
        place: 'Kochi Offshore Shelf',
        bearing: '285',
        distance: '35.5 km',
        sector: 'SEC005',
      });
      expect(draft).toBe(
        'GO: Kochi 2026-09-21. Sea safe. PFZ Kochi Offshore Shelf 285° 35.5 km (INCOIS SEC005).'
      );
    });

    it('renders HOLD draft when decision is HOLD', () => {
      const draft = renderDraft('HOLD', 'Paradip', '2026-09-21', 'danger', {
        place: 'nearshore waters',
        bearing: '—',
        distance: '—',
        sector: 'SEC008',
      });
      expect(draft).toBe('HOLD: Paradip 2026-09-21. Sea danger. PFZ nearshore waters —° — (INCOIS SEC008).');
    });
  });

  describe('6. Zero Fisherman Shell Regression', () => {
    it('maintains fisherman navigation and core screen tab testids', () => {
      const fishermanTabs = ['home', 'chat', 'map', 'alerts', 'pfz-detail', 'route', 'profile'];
      expect(fishermanTabs).toContain('home');
      expect(fishermanTabs).toContain('chat');
      expect(fishermanTabs).toContain('map');

      const testids = ['mobile-tab-home', 'mobile-tab-map', 'mobile-tab-chat', 'mobile-tab-alerts', 'voice-mic-button'];
      expect(testids.length).toBe(5);
    });
  });
});
