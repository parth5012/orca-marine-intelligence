/**
 * ChatPanel Component
 *
 * Owner: M-D (Frontend & Maps) � chat UI (calls M-C /api/chat)
 * Module: frontend/components/ChatPanel.tsx
 *
 * Conversational chat interface for the ORCA multi-agent system.
 * Supports text input in 22 Indian languages with auto-detection.
 * Displays agent responses with map references and safety badges.
 *
 * Features:
 *     - Multilingual text input with language auto-detection
 *     - Multi-turn conversation with session persistence
 *     - Streaming response display (SSE)
 *     - Quick action buttons for common queries
 *     - Voice input via Bhashini STT (Week 3+)
 *
 * Props:
 *     - onLocationUpdate: (lat, lon) => void — called when user shares GPS
 *     - onMapHighlight: (features) => void — highlight PFZ zones on map
 *
 * TODO:
 *     - [ ] Implement chat UI with message list and input
 *     - [ ] Add POST /api/chat integration with fetch
 *     - [ ] Implement SSE streaming for response display
 *     - [ ] Add language auto-detection display
 *     - [ ] Implement multi-turn session with session_id
 *     - [ ] Add voice input button (Bhashini STT, Week 3+)
 */

export interface ChatPanelProps {
  onLocationUpdate?: (lat: number, lon: number) => void;
  onMapHighlight?: (features: any[]) => void;
}

export default function ChatPanel({ onLocationUpdate, onMapHighlight }: ChatPanelProps) {
  // TODO: Implement ChatPanel component
  return (
    <div className="chat-panel">
      <p>ChatPanel — coming soon</p>
    </div>
  );
}
