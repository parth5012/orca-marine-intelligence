/**
 * Owner: M-E (Frontend Chat & App Shell) - barrel chat
 *
 * Chat Barrel Export
 * Re-exports core chat modules for clean imports:
 * import { ChatPanel, LanguageSwitch, useSSEChat } from "@/chat";
 */

export { default as ChatPanel } from './ChatPanel';
export type { ChatPanelProps } from './ChatPanel';

export { default as LanguageSwitch, SUPPORTED_LANGUAGES } from './LanguageSwitch';
export type { LanguageSwitchProps, LanguageOption } from './LanguageSwitch';

export { useSSEChat } from './useSSEChat';
export type {
  ChatMessage,
  ReasoningStep,
  MarineZoneCard,
  SafetyData,
  MapEventData,
  UseSSEChatOptions,
} from './useSSEChat';

export * from './bhashini';
