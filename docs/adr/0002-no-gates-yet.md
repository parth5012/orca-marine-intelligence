# Golden v1 is measure-only, no prod gates

We defined 14 edge buckets (PFZ, sea, weather, geofence-veto, intent split, numerals, adversarial, resilience, temporal/forecast, SST/chlorophyll, species+depth, multi-turn/session, lang-gate/voice-typo, data-freshness) and score all equally in v1. Nothing blocks production yet; gates are added after we see score distributions.
