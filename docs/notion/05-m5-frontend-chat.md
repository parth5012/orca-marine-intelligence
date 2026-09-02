# M-E — Frontend Chat & App Shell (Copy to Notion → "M-E Chat & Shell")

> **Paste tip:** Create Notion page under "ORCA Core" → paste this markdown.

**You own:** `frontend/chat/` + `frontend/app/page.tsx` — the conversational UI and the shell that holds chat+map together.  
**Official PS:** [SIH26176 — ISRO](https://github.com/vedantchalke36/sih-2026-problem-statements/blob/main/ps_2026/SIH26176.md) — same-language reply + multi-turn are MVP, not polish.  
**Depends on:** M-C's `POST /api/chat` + M-D's `MapView` (you embed it). **Used by:** M-A's orchestrator also calls your `bhashini.ts` server-side.

**Your files (one stack: React + Bhashini):**

| File | What it does in plain words |
|------|-----------------------------|
| `frontend/chat/ChatPanel.tsx` | **The chat box.** Where fisherman types Malayalam/English, sees reply + evidence, triggers map flyTo. |
| `frontend/chat/LanguageSwitch.tsx` | **22-language switch.** Dropdown + auto-detect. |
| `frontend/chat/bhashini.ts` | **Translator helper.** `detectLanguage()` + `translate()` via Bhashini ULCA. Used by you and M-A. |
| `frontend/chat/index.ts` | **Barrel.** `export * from "./ChatPanel"` → shell does `import {ChatPanel} from "@/chat"` |
| `frontend/app/page.tsx` | **The full shell (your heaviest file).** Top bar `LanguageSwitch (from chat/)` + `SafetyBadge (from map/)`, left ChatPanel + right MapView. |

Every file has `Owner: M-E (Frontend Chat & App Shell)` + TODOs — open it.

---

## 1) Week 1 — Make chat understand and the shell wire it

### Task E1 — ChatPanel + LanguageSwitch + bhashini

1. Open `frontend/chat/ChatPanel.tsx` — text input + send button. On send:
   ```typescript
   const res = await fetch("/api/chat", { method:"POST", body: JSON.stringify({message, lat, lon, session_id}) });
   const {reply, map, safety, evidence, language} = await res.json();
   onMapFlyTo(map.center); // callback to shell
   ```
   Show reply + evidence citations. React `useState` for messages. W1 text only — no voice.

2. Open `frontend/chat/LanguageSwitch.tsx` — dropdown for 22 languages (`en/hi/ml/ta/te/...`) + auto-detect. Calls `bhashini.ts`.

3. Open `frontend/chat/bhashini.ts`:
   ```typescript
   export function detectLanguage(text: string): string {
     // W1: simple unicode check — if Malayalam chars → "ml" else "en" is enough
     // W2: call Bhashini ULCA detect API (URL in .env.example)
   }
   export async function translate(text: string, from: string, to: string): Promise<string> {
     // POST to BHASHINI_API_KEY endpoint
   }
   ```
   **MVP per ISRO PS:** Same-language reply is mandatory — if user types Malayalam, answer must be Malayalam. M-A's `orchestrator.py` also imports your `detectLanguage` server-side.

### Task E2 — The full shell `app/page.tsx`

This is your heaviest file. It holds everything:

```tsx
// frontend/app/page.tsx
import { ChatPanel, LanguageSwitch } from "@/chat";
import { MapView, SafetyBadge } from "@/map"; // M-D provides these

export default function HomePage() {
  const mapRef = useRef();
  return (
    <main className="flex flex-col md:flex-row">
      <header><LanguageSwitch /> <SafetyBadge /></header>
      <div className="flex w-full">
        <div className="w-[30%]"><ChatPanel onRecommend={c => mapRef.current.flyTo(c, 12)} /></div>
        <div className="w-[70%]"><MapView ref={mapRef} /></div>
      </div>
    </main>
  );
}
```

- Responsive: mobile stacked (`flex-col`), desktop split (`flex-row`).
- GPS on mount: `navigator.geolocation.getCurrentPosition` → blue dot + pass `lat/lon` to ChatPanel.
- Handle loading spinner while `GET /api/pfz/today` (M-C) fetches.

---

## 2) Week 2 — Polish

- **Memory:** M-A adds Redis `session_id → {lat,lon,boat,risk}` — your `ChatPanel` just sends `session_id` with each message, so follow-up "is it safe tomorrow?" works without re-asking location.
- **Why panel:** Show M-A's 4 score bars (closest, sea, wind, allowed) + citation in ChatPanel.
- **SMS display:** `POST /api/chat` also returns `sms_text` in Malayalam (M-C's SMS gateway) — show "Send SMS" button in ChatPanel.
- **Polish shell:** Loading states, `localStorage` for last language, mobile UX.

---

## 3) Who you talk to

- **You call:** M-C's `POST /api/chat` + M-D's `MapView` (embed) + `LanguageSwitch` ↔ `bhashini.ts`
- **You provide:** `bhashini.ts` helper that M-A's `orchestrator.py` also imports server-side for language detect
- **Your judge view:** `https://cron-system.vercel.app/orca/` (shell: chat left, map right)

---

## 4) Verify checklist

- [ ] `cd frontend && npm run dev` → `http://localhost:3000` shows shell (chat left, map right), responsive
- [ ] Type Malayalam "എവിടെ മത്സ്യം?" → `ChatPanel` calls `/api/chat` → reply in Malayalam + map flies + green route
- [ ] `LanguageSwitch` dropdown shows 22 languages, auto-detect `ml` for Malayalam
- [ ] `bhashini.ts` unit: `detectLanguage("എവിടെ") === "ml"`, `detectLanguage("Where is fish?") === "en"`
- [ ] Fri 05 Sep Global Test #1: same on live Vercel

---

*Source of truth: `docs/API.md` (`/api/chat` shape), `frontend/chat/` TODOs, `docs/ORCA_GeoJSON_Architecture.md` (language flow).*
