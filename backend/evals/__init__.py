"""
LangSmith Data Evals Framework for ORCA Marine Intelligence (PS 26176).

Owner: M-A (Agents & Orchestration) & M-C (Backend API)
Map: #53 (Child Tickets: #56, #57, #58)

Provides:
- Benchmark datasets extracted from coastal landing features, cyclone tracks, and boundary zones.
- Custom LangSmith evaluators:
  - MarineGroundednessEvaluator
  - GeofenceSafetyEvaluator
  - MetricPreservationEvaluator
  - RiskCalibrationEvaluator
- Evaluation runner with seamless LangSmith cloud logging and offline zero-crash execution.
"""

from backend.evals.dataset import (
    MarineEvalExample,
    load_marine_eval_dataset,
    export_dataset_to_json,
    sync_dataset_to_langsmith,
)
from backend.evals.evaluators import (
    MarineGroundednessEvaluator,
    GeofenceSafetyEvaluator,
    MetricPreservationEvaluator,
    RiskCalibrationEvaluator,
)
from backend.evals.runner import (
    EvaluationReport,
    run_marine_evals,
)

__all__ = [
    "MarineEvalExample",
    "load_marine_eval_dataset",
    "export_dataset_to_json",
    "sync_dataset_to_langsmith",
    "MarineGroundednessEvaluator",
    "GeofenceSafetyEvaluator",
    "MetricPreservationEvaluator",
    "RiskCalibrationEvaluator",
    "EvaluationReport",
    "run_marine_evals",
]
