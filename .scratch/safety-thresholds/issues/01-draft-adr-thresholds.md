# Draft ADR-0003: IMD/INCOIS-aligned Safety Thresholds

Type: task
Status: closed
Blocked by: 

## Resolution
Drafted and codified `docs/adr/0003-safety-thresholds-alignment.md` documenting IMD/INCOIS-aligned thresholds:
- Wind: Safe < 22.0 kt, Caution 22.0–27.0 kt, Danger > 27.0 kt (50 kmph IMD Warning)
- Wave: Safe < 2.0 m (FAO Cat-C), Caution 2.0–3.5 m, Danger > 3.5 m (INCOIS wind-wave Warning)
- Current: Safe < 2.0 kt, Caution 2.0–3.0 kt, Danger > 3.0 kt
- Preserved invariants: Missing wave/wind -> CAUTION, Geofence violation -> DANGER, Code trumps LLM.

## Question

How should the new safety thresholds be formally codified in the project architecture documentation as `docs/adr/0003-safety-thresholds-alignment.md`?

### Context
We completed an evidence synthesis comparing existing ORCA thresholds to Indian government standards (IMD, INCOIS) and international maritime standards (FAO Cat-C, NOAA, Douglas scale). 
Evidence is documented in `docs/research/07-safety-thresholds-evidence.md`.

### Requirements
1. Follow existing ADR format in `docs/adr/` (`0001-golden-22-frozen.md`).
2. Document the decision:
   - Wind: Safe < 20.0 kt, Caution 20.0–27.0 kt, Danger > 27.0 kt (50 kmph IMD Warning: Do Not Venture)
   - Wave: Safe < 2.0 m (FAO Cat-C 6–12m craft limit), Caution 2.0–3.5 m, Danger > 3.5 m (INCOIS wind-wave Warning)
   - Current: Safe < 2.0 kt, Caution 2.0–3.0 kt, Danger > 3.0 kt (INCOIS alert range: 0.9–1.9 m/s)
   - Pressure / Cyclone: Caution < 1005 hPa, Danger < 995 hPa or cyclone within 500 km (preserved)
   - Invariants: Missing wave/wind -> CAUTION (fail-open), Geofence violation -> DANGER
3. Document considered options, trade-offs, and consequences for downstream evals and UI.
