# Next.js PWA now, Flutter later

The request was for a cross-platform PWA built with Flutter, but Flutter Web cannot reuse a single line of the existing React/Leaflet/SSE/Tailwind code — a Flutter-Web PWA would have been a full Dart rewrite (Leaflet → flutter_map, SSE → Dart streams, Tailwind → Flutter widgets) duplicating ~30 existing modules, while the current site had no manifest or service worker at all. We decided to make the existing Next.js 14 site the installable PWA now, and to defer Flutter to a later phase as a second client on a frozen contract rather than as a rewrite.

**Considered Options**

- **Next.js PWA now + Flutter later (chosen):** Adding a manifest and service worker to the existing site makes it installable cheaply and preserves the entire map/chat investment; Flutter ships later as a second client against a frozen contract.
- **Flutter Web PWA as a full Dart rewrite:** One codebase from day one, but zero code reuse — every module re-implemented in Dart — and nothing installable ships until the rewrite completes.
- **Flutter WebView shell wrapping the existing site:** Fastest path to a "Flutter app", but a wrapper, not a real cross-platform client — it inherits browser behavior, gains no native offline semantics, and does not reduce the cost of a later real client.

**Consequences**

The site becomes installable without touching application code; the Flutter phase starts from a documented contract instead of an open design, and its scope is a second client, not a replacement.
