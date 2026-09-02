/**
 * ORCA — Root Page
 *
 * Owner: M-D (Frontend & Maps) � full shell: ChatPanel + MapView + flyTo + offline
 * Module: frontend/app/page.tsx
 *
 * Main application layout combining:
 *     - Left panel: ChatPanel for conversational queries
 *     - Right panel: MapView for spatial visualization
 *     - Top bar: LanguageSwitch + SafetyBadge
 *
 * Layout:
 *     ┌──────────────────────────────────────┐
 *     │ LanguageSwitch        SafetyBadge    │
 *     ├──────────────┬───────────────────────┤
 *     │              │                       │
 *     │  ChatPanel   │      MapView          │
 *     │              │                       │
 *     │              │                       │
 *     └──────────────┴───────────────────────┘
 *
 * TODO:
 *     - [ ] Implement responsive layout (mobile: stacked, desktop: split)
 *     - [ ] Wire ChatPanel → MapView communication
 *     - [ ] Add GPS location detection on mount
 *     - [ ] Initialize language from localStorage
 *     - [ ] Add loading state for initial data fetch
 */

export default function HomePage() {
  // TODO: Implement home page layout
  return (
    <main>
      <h1>ORCA — Agentic Marine Intelligence</h1>
      <p>Coming soon — loading map and chat...</p>
    </main>
  );
}
