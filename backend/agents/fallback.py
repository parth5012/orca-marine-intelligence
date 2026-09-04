"""
ORCA Fallback — Legacy Deterministic Gather (Reserved for Future)

Owner: M-A (Agents & Orchestration)
Module: backend/agents/fallback.py

This module preserves the W1 deterministic `asyncio.gather` orchestration
as a self-contained fallback, separated from the LangGraph supervisor.

It is NOT used by `backend/agents/orchestrator.py` in the
SIH26176 Agentic AI path (graph is now always-on per PS requirement).
It is retained for:
  - offline / P95<2s strict fallback (future: edge devices without langgraph)
  - regression comparison
  - future: hybrid planner that dynamically chooses gather vs graph

For current production, `orchestrator.orchestrate()` delegates to
`backend/agents/graph.py:orchestrate_via_graph` where sub-agents
(planner, fish_finder, sea_checker,
weather_agent, danger_agent, decision_agent)
decide and call tools (PostGIS, OSF, IMD, GeoJSON).

TODO (future):
  - [ ] Re-enable as `fallback_orchestrate()` when langgraph unavailable
  - [ ] Add feature-flag/edge-mode (e.g., ORCA_MODE=edge)
  - [ ] Benchmark gather vs graph latency for hybrid routing
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

# NOTE: Legacy gather implementation moved here verbatim from
# orchestrator.py W1. Intentionally not imported by orchestrator
# to enforce graph-always-on. Kept for future fallback.

# For reference, the legacy flow was:
#   1. _resolve_location(query, location) or Redis session reuse + _parse_relative_offset
#   2. fish_finder.find_fishing_zones(lat, lon) with 10s wait_for
#   3. asyncio.gather(
#         sea_checker.check_sea_conditions(shared_points),
#         weather_agent.check_weather(shared_points),
#         danger_agent.check_safety_batch(shared_points),
#         return_exceptions=True
#      ) each with 10s timeout → degraded to "unknown"
#   4. combiner.combine_and_rank(...)
#   5. assemble POST /api/chat payload + Redis save_session 24h TTL
#
# See git history orchestrator.py @bb4e01d..a7831f4 for full code.
# This stub exists so future work can re-implement without
# re-extracting from history.

async def fallback_orchestrate(*args: Any, **kwargs: Any) -> dict:
    """Placeholder — legacy gather reserved for future."""
    raise NotImplementedError(
        "fallback_orchestrate is reserved for future edge/offline mode. "
        "Use backend.agents.graph:orchestrate_via_graph (LangGraph supervisor) for SIH26176."
    )


async def fallback_orchestrate_stream(*args: Any, **kwargs: Any):  # type: ignore
    """Placeholder — legacy SSE streaming reserved for future."""
    raise NotImplementedError(
        "fallback_orchestrate_stream reserved for future. "
        "Use backend.agents.graph:orchestrate_stream_via_graph."
    )
    yield {}  # make it an async generator type
