# Offline snapshot contract frozen now for Flutter

Because a future Flutter client must reproduce identical safety semantics — the same coordinates must never yield a different safety tier on web vs Flutter — the offline advisory snapshot schema and its staleness rules are frozen now as a documented contract in `docs/API.md`, rather than left to be re-invented later inside React components.

**Safety semantics**

- Offline, the app serves an *advisory snapshot*: PFZ GeoJSON, geofence/MPA layers, last-known wave/wind, system status, plus a bounded ~50 MB LRU tile cache. Chat is not available offline.
- PFZ data is **stale** when `now > valid_until`; if `valid_until` is absent, a 24-hour window measured from capture time applies. Capture time is the payload's `timestamp`, persisted by clients as `capturedAt` — never the time the client fetched it.
- Wave/wind measurements are **stale** after 3 hours, measured from the weather payload's `timestamp` (when the readings were obtained, not when they were downloaded).
- Map tiles are exempt from staleness.
- A stale advisory is still shown — but its safety tier is floored at CAUTION. It can never render "SEA SAFE". This extends the ADR-0003 invariant *Fail-Open Caution on missing data* to cover stale data as well as missing data; the age banner exists so the user knows why the verdict was downgraded.
- The deliberate trade-off: showing stale data risks over-warning; withdrawing it entirely would leave an offshore fisherman with zero guidance exactly when he needs it most. We chose over-warning.

**Considered Options**

- **Freeze API + snapshot schema now (chosen):** One written contract in `docs/API.md` pins payload fields, staleness thresholds, and the Caution floor before a second platform exists.
- **Defer the interface design to Flutter time:** Cheaper today, but risks platform divergence where the same lat/lon produces different safety tiers on web vs Flutter.
- **Contract plus shared design tokens for pixel parity:** Adds visual parity across platforms, but pixel-level matching is a UI concern — it does not affect safety semantics and would over-commit the contract to presentation.

**Consequences**

Any future client MUST apply these rules identically (ADR-0007 assumes this contract); schema or threshold changes now require updating `docs/API.md` and both clients in lockstep.
