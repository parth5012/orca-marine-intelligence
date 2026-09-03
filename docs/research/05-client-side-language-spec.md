# Client-Side Script Detection & UI Language Synchronization Specification

**Ticket:** [#6 Define Client-Side Fast-Path Script Detection & UI Sync in LanguageSwitch and ChatPanel](https://github.com/parth5012/orca-marine-intelligence/issues/6)  
**Target Codebase:** `frontend/chat/bhashini.ts`, `frontend/chat/LanguageSwitch.tsx`, `frontend/chat/ChatPanel.tsx`  
**Owner:** M-E (Frontend Chat & App Shell)  
**Type:** Implementation Task Specification

---

## 1. Plain Explanation of How It Works

When a user uses the ORCA app:
1. **Instant Typing Detection**: As soon as a fisherman types or pastes words into the chat box, the browser instantly recognizes the script (within 0 milliseconds, with zero internet delay).
   - If they type Malayalam letters (`എവിടെ മത്സ്യം?`), the language badge in the top bar immediately switches to **Malayalam**.
   - If they type Tamil letters (`மீன் எங்கே?`), it immediately switches to **Tamil**.
   - If they type Hindi / Marathi letters (`मछली कहाँ मिलेगी?`), it switches to **Hindi/Marathi**.
2. **User Control (Dropdown Override)**:
   - A fisherman can also manually pick their preferred language from the dropdown menu (e.g., selecting Tamil or Malayalam).
   - Once picked, their choice is remembered in the browser (`localStorage`) so they don't have to pick it again on their next visit.
3. **Seamless Handshake with Backend**:
   - When the user sends a message, `ChatPanel` attaches their manual selection as `language_hint`.
   - If left on "Auto", the backend automatically runs the 3-tier cascade and confirms the language in the response, updating the top-bar badge.

---

## 2. Fast 0ms Client-Side Script Detector (`frontend/chat/bhashini.ts`)

Replace the stub in `frontend/chat/bhashini.ts` with this pure, zero-dependency script detector:

```typescript
/**
 * Fast client-side script and language detector for Indian languages.
 * Executes in < 0.05ms inside the browser with zero network calls.
 */

export interface DetectedLanguage {
  code: string;       // ISO 639-1: 'ml', 'ta', 'te', 'hi', etc.
  name: string;       // Display name: 'Malayalam', 'Tamil', etc.
  nativeName: string; // Native script name: 'മലയാളം', 'தமிழ்', etc.
  isAuto: boolean;
}

export const SUPPORTED_LANGUAGES: Record<string, { name: string; nativeName: string }> = {
  en: { name: 'English', nativeName: 'English' },
  ml: { name: 'Malayalam', nativeName: 'മലയാളം' },
  ta: { name: 'Tamil', nativeName: 'தமிழ்' },
  te: { name: 'Telugu', nativeName: 'తెలుగు' },
  kn: { name: 'Kannada', nativeName: 'ಕನ್ನಡ' },
  hi: { name: 'Hindi', nativeName: 'हिन्दी' },
  mr: { name: 'Marathi', nativeName: 'मराठी' },
  gu: { name: 'Gujarati', nativeName: 'ગુજરાતી' },
  bn: { name: 'Bengali', nativeName: 'বাংলা' },
  or: { name: 'Odia', nativeName: 'ଓଡ଼ିଆ' },
  pa: { name: 'Punjabi', nativeName: 'ਪੰਜਾਬੀ' },
  as: { name: 'Assamese', nativeName: 'অসমীয়া' },
  ur: { name: 'Urdu', nativeName: 'اردو' }
};

/**
 * Checks Unicode character ranges to instantly detect native Indic scripts.
 */
export function detectScriptInstant(text: string): string | null {
  if (!text || text.trim().length === 0) return null;

  for (let i = 0; i < text.length; i++) {
    const code = text.charCodeAt(i);
    // Malayalam: U+0D00 - U+0D7F
    if (code >= 0x0D00 && code <= 0x0D7F) return 'ml';
    // Tamil: U+0B80 - U+0BFF
    if (code >= 0x0B80 && code <= 0x0BFF) return 'ta';
    // Telugu: U+0C00 - U+0C7F
    if (code >= 0x0C00 && code <= 0x0C7F) return 'te';
    // Kannada: U+0C80 - U+0CFF
    if (code >= 0x0C80 && code <= 0x0CFF) return 'kn';
    // Gujarati: U+0A80 - U+0AFF
    if (code >= 0x0A80 && code <= 0x0AFF) return 'gu';
    // Bengali: U+0980 - U+09FF
    if (code >= 0x0980 && code <= 0x09FF) return 'bn';
    // Odia: U+0B00 - U+0B7F
    if (code >= 0x0B00 && code <= 0x0B7F) return 'or';
    // Devanagari (Hindi / Marathi): U+0900 - U+097F
    if (code >= 0x0900 && code <= 0x097F) {
      // Check for Marathi-specific letter ळ (U+0933)
      if (text.includes('ळ')) return 'mr';
      return 'hi';
    }
  }

  return null; // Return null if plain Latin / English or undetermined
}
```

---

## 3. Complete Dropdown Component (`frontend/chat/LanguageSwitch.tsx`)

Replace `frontend/chat/LanguageSwitch.tsx` with this clean, responsive selector:

```tsx
'use client';

import React, { useEffect, useState } from 'react';
import { SUPPORTED_LANGUAGES } from './bhashini';

export interface LanguageSwitchProps {
  currentLanguage: string;
  isAutoDetected?: boolean;
  onLanguageChange: (langCode: string, isManual: boolean) => void;
}

export default function LanguageSwitch({
  currentLanguage = 'en',
  isAutoDetected = true,
  onLanguageChange,
}: LanguageSwitchProps) {
  const [selectedLang, setSelectedLang] = useState<string>(currentLanguage);

  useEffect(() => {
    setSelectedLang(currentLanguage);
  }, [currentLanguage]);

  const handleChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const value = e.target.value;
    setSelectedLang(value);
    if (value === 'auto') {
      localStorage.removeItem('orca_preferred_language');
      onLanguageChange('en', false); // default to auto/en
    } else {
      localStorage.setItem('orca_preferred_language', value);
      onLanguageChange(value, true);
    }
  };

  return (
    <div className="flex items-center gap-2 bg-slate-900/80 border border-slate-700/60 rounded-lg px-2.5 py-1.5 text-xs text-slate-200">
      <span className="text-slate-400 font-medium">Language:</span>
      <select
        value={isAutoDetected ? 'auto' : selectedLang}
        onChange={handleChange}
        className="bg-transparent border-none outline-none font-semibold text-cyan-400 cursor-pointer pr-1"
      >
        <option value="auto" className="bg-slate-900 text-slate-200">
          Auto-Detect (স্বয়ংক্রিয়)
        </option>
        {Object.entries(SUPPORTED_LANGUAGES).map(([code, info]) => (
          <option key={code} value={code} className="bg-slate-900 text-slate-200">
            {info.name} ({info.nativeName})
          </option>
        ))}
      </select>
      {isAutoDetected && currentLanguage !== 'en' && (
        <span className="bg-cyan-500/20 text-cyan-300 px-1.5 py-0.5 rounded text-[10px] font-bold border border-cyan-500/30">
          {currentLanguage.toUpperCase()}
        </span>
      )}
    </div>
  );
}
```

---

## 4. Integration into `frontend/chat/ChatPanel.tsx`

When the user types into the chat input, trigger `detectScriptInstant` on `onChange`:

```tsx
// Inside ChatPanel.tsx
import { detectScriptInstant } from './bhashini';

// State management
const [inputMessage, setInputMessage] = useState('');
const [activeLanguage, setActiveLanguage] = useState('en');
const [isManualOverride, setIsManualOverride] = useState(false);

const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
  const text = e.target.value;
  setInputMessage(text);

  // If user has not manually locked a language, auto-detect script on keystroke
  if (!isManualOverride) {
    const detected = detectScriptInstant(text);
    if (detected && detected !== activeLanguage) {
      setActiveLanguage(detected);
    }
  }
};

const handleSend = async () => {
  if (!inputMessage.trim()) return;

  const payload = {
    message: inputMessage,
    lat: userLocation?.lat,
    lon: userLocation?.lon,
    session_id: sessionId,
    language_hint: isManualOverride ? activeLanguage : null
  };

  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });

  const data = await response.json();
  
  // Sync the language badge with whatever the backend confirmed
  if (data.language_meta?.detected_language) {
    setActiveLanguage(data.language_meta.detected_language);
  }
  
  // Render advisory and trigger map flyTo
  if (data.map?.center && onLocationUpdate) {
    onLocationUpdate(data.map.center[1], data.map.center[0]);
  }
};
```

---

## 5. Verification Checklist for Member E

- [ ] Typing Malayalam (`മീൻ എവിടെ`) switches the top-bar badge to `ML` in 0ms.
- [ ] Typing Tamil (`மீன் எங்கே`) switches the top-bar badge to `TA` in 0ms.
- [ ] Typing Hindi (`मछली कहाँ`) switches the top-bar badge to `HI` in 0ms.
- [ ] Selecting "Tamil" in the dropdown saves `ta` to `localStorage` and disables auto-override.
- [ ] Sending a query passes `language_hint` to `/api/chat`.
- [ ] Receiving a reply renders both the localized message and the numerical fact cards cleanly.