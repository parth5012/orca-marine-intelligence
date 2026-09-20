==================================================================
        ORCA MARINE INTELLIGENCE — LANGSMITH EVAL SCORECARD       
==================================================================
Total Evaluated Examples:         150
Passed Examples:                  150 (100.0%)
Mean Marine Groundedness:         100.0%
Safety Adherence Rate:            100.0%
Metric Preservation Rate:         100.0%
Risk Calibration Rate:            100.0%
Mean Language Purity Score:       100.0%
Numeral Invariant Rate:           100.0%
Cross-Lang Tier Equality Rate:    100.0%
LLM Quality Rate*:                100.0% (0 judged)
LLM Safety Rate*:                 100.0% (0 judged)
Execution Latency:                0.01s
------------------------------------------------------------------
STATUS: PASS (All gates met)
* LLM judges are measure-only sidecars; they never gate pass/fail.
==================================================================

## 14x23 Evaluation Matrix (Buckets x Languages)

| Bucket | en | as | bn | brx | doi | gu | hi | kn | ks | gom | mai | ml | mni | mr | ne | or | pa | sa | sat | sd | ta | te | ur |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| pfz | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| sea | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| weather | 1.00 | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - |
| geofence_veto | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| intent_split | 1.00 | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - |
| numerals | 1.00 | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - |
| adversarial | 1.00 | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - |
| resilience | 1.00 | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - |
| temporal_forecast | 1.00 | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - |
| sst_chlorophyll | 1.00 | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - |
| species_depth | 1.00 | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - |
| multi_turn_session | 1.00 | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - |
| lang_gate_voice_typo | 1.00 | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - |
| data_freshness | 1.00 | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - |

## Top Failures & Degradation Cases

No failures detected. All evaluated examples met benchmark criteria.