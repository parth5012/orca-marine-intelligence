/**
 * LanguageGate (Hindi dual-gate)
 *
 * Owner: M-E (Frontend Chat & App Shell)
 * Module: frontend/lib/languageGate.ts
 *
 * Rule: Hindi response ONLY when BOTH conditions hold:
 *   1. website language (UI) == 'hi'
 *   2. user query itself is Hindi (Devanagari or Hinglish)
 * Otherwise everything renders in English.
 *
 * Mirrors backend/routers/chat.py resolve_response_language().
 */

export function normalizeUiLang(code: unknown): string {
  if (!code || typeof code !== 'string') return 'en';
  const c = code.trim().toLowerCase().split('-')[0].split('_')[0];
  return c || 'en';
}

const DEVANAGARI_RE = /[\u0900-\u097F]/;
const HINGLISH_RE =
  /\b(kya|kahan|kaise|kab|kyon|kyun|hai|hain|nahi|nahin|nahn|machhli|machhali|machli|samudra|samundra|lahrein|lehren|lahar|hawa|toofan|surakshit|mausam|madad|batao|batayen|mujhe|kripya|kal|subah|safe hai|kharab|achha|accha)\b/i;

export function isHindiQuery(text: string | null | undefined): boolean {
  if (!text || !text.trim()) return false;
  if (DEVANAGARI_RE.test(text)) return true;
  return HINGLISH_RE.test(text);
}

/**
 * Effective response language for rendering.
 * - uiLang 'hi' + Hindi query  -> 'hi'
 * - uiLang 'hi' + English query -> 'en'
 * - any other uiLang -> uiLang normalized (existing behaviour preserved;
 *   ml/ta/te; Hindi gate forces Hindi there).
 */
export function getEffectiveResponseLang(
  uiLang: string | null | undefined,
  queryText: string | null | undefined
): string {
  const ui = normalizeUiLang(uiLang);
  if (ui === 'hi') {
    return isHindiQuery(queryText ?? '') ? 'hi' : 'en';
  }
  return ui;
}

export function isHindiResponse(
  uiLang: string | null | undefined,
  queryText: string | null | undefined
): boolean {
  return getEffectiveResponseLang(uiLang, queryText) === 'hi';
}
