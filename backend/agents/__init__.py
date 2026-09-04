"""ORCA Agents Package.

Core orchestration and multi-agent system:
  - Supervisor: graph.py (LangGraph StateGraph), planner_schema.py, orchestrator.py
  - Specialist subagents: backend.agents.subagents (fish_finder, sea_checker, weather_agent, danger_agent)
  - Fusion & vernacular grounding: combiner.py, lexical_mask.py
"""

import sys
from backend.agents.subagents import danger_agent, fish_finder, sea_checker, weather_agent

# Backward compatibility aliases in sys.modules so existing test mocks and imports
# continue to resolve smoothly:
sys.modules["backend.agents.fish_finder"] = fish_finder
sys.modules["backend.agents.sea_checker"] = sea_checker
sys.modules["backend.agents.weather_agent"] = weather_agent
sys.modules["backend.agents.danger_agent"] = danger_agent

__all__ = [
    "danger_agent",
    "fish_finder",
    "sea_checker",
    "weather_agent",
]
