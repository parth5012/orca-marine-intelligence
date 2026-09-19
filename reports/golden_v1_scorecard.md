==================================================================
        ORCA MARINE INTELLIGENCE — LANGSMITH EVAL SCORECARD       
==================================================================
Total Evaluated Examples:         150
Passed Examples:                  99 (66.0%)
Mean Marine Groundedness:         100.0%
Safety Adherence Rate:            100.0%
Metric Preservation Rate:         100.0%
Risk Calibration Rate:            100.0%
Mean Language Purity Score:       66.0%
Numeral Invariant Rate:           100.0%
Cross-Lang Tier Equality Rate:    100.0%
Execution Latency:                0.01s
------------------------------------------------------------------
STATUS: MEASURE-ONLY (Baseline tracked)
==================================================================

## 14x23 Evaluation Matrix (Buckets x Languages)

| Bucket | en | as | bn | brx | doi | gu | hi | kn | ks | gom | mai | ml | mni | mr | ne | or | pa | sa | sat | sd | ta | te | ur |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| pfz | 1.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1.00 | 0.00 | 1.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1.00 | 1.00 | 0.00 |
| sea | 1.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1.00 | 0.00 | 1.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1.00 | 1.00 | 0.00 |
| weather | 1.00 | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - |
| geofence_veto | 1.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1.00 | 0.00 | 1.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1.00 | 1.00 | 0.00 |
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

1. **GOLDEN_V1_AS_01** (Kochi): language_purity: Output does not contain native script for language 'as'.
2. **GOLDEN_V1_AS_02** (Gulf of Mannar): language_purity: Output does not contain native script for language 'as'.
3. **GOLDEN_V1_AS_03** (Kochi): language_purity: Output does not contain native script for language 'as'.
4. **GOLDEN_V1_BN_01** (Kochi): language_purity: Output does not contain native script for language 'bn'.
5. **GOLDEN_V1_BN_02** (Gulf of Mannar): language_purity: Output does not contain native script for language 'bn'.
6. **GOLDEN_V1_BN_03** (Kochi): language_purity: Output does not contain native script for language 'bn'.
7. **GOLDEN_V1_BRX_01** (Kochi): language_purity: Output does not contain native script for language 'brx'.
8. **GOLDEN_V1_BRX_02** (Gulf of Mannar): language_purity: Output does not contain native script for language 'brx'.
9. **GOLDEN_V1_BRX_03** (Kochi): language_purity: Output does not contain native script for language 'brx'.
10. **GOLDEN_V1_DOI_01** (Kochi): language_purity: Output does not contain native script for language 'doi'.