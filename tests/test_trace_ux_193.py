"""Trace UX allowlist tests (wayfinder #193, map #191).

Mobile chat must read as advisory, not a debug log: multi-agent
reasoning stays in ``reasoning_trace`` (Workflow modal) while
``evidence`` carries only human-readable items — INCOIS citation,
Wave/Wind human labels, geofence verdict, forecast window.

Covers:
  - backend allowlist unit (graph.is_human_evidence / filter_human_evidence
    / human_source_label, planner_service.is_internal_trace_line)
  - ChatPanel collapsed-by-default (no streaming auto-open effect)
  - danger banner keeps color + icon but no pulse animation
  - no raw ``__M*__`` / ``open_meteo_live`` / ``selected_*`` strings reach
    rendered evidence output
"""

from __future__ import annotations

import pathlib

import pytest

from backend.agents import graph as g
from backend.agents import planner_service as ps

REPO = pathlib.Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Backend allowlist unit
# ---------------------------------------------------------------------------


class TestHumanEvidenceAllowlist:
    @pytest.mark.parametrize(
        "item",
        [
            "INCOIS TextData",
            "INCOIS TextData SEC005 KERALA 2026-09-18",
            "Wave: live model",
            "Wind: live model",
            "Wave: archived climatology",
            "Wind: model estimate",
            "No EEZ/MPA violation",
            "EEZ boundary warning: 2.1km from IMBL",
            "MPA restriction: Malvan sanctuary buffer",
            "Zone inside EEZ, no violation",
            # Spelled-out geofence verdicts (danger_agent wording).
            "Inside Marine Protected Area: Malvan — fishing strictly banned",
            "Outside Indian Exclusive Economic Zone — fishing not permitted",
            "Within 5km of International Maritime Boundary Line — risk of crossing (4.2km to boundary)",
            "Cyclone warning: Remal within 320km",
            "Lightning warning active in area",
            "Departure forecast window analyzed (Tomorrow morning)",
            "Departure forecast unavailable — verify official bulletins",
            # System lines for non-advisory turns stay verbatim.
            "conversational reply — no marine data queried",
            "Clarification requested — GPS/location required for PFZ search",
            "Location not provided — cannot search PFZ zones",
        ],
    )
    def test_allowlisted_items_pass(self, item: str) -> None:
        assert g.is_human_evidence(item) is True

    @pytest.mark.parametrize(
        "item",
        [
            # Planner audit lines (explicit LLM justification or skip notes).
            "SELECT find_fishing_zones: fish intent needs candidates",
            "SKIP find_fishing_zones: safety-only query, no PFZ discovery needed",
            "SKIP check_weather: fish-only, no safety keywords — save latency",
            # Auto-filler completion lines.
            "find_fishing_zones selected by planner (trace line auto-added; LLM gave no explicit justification)",
            "SKIP check_ocean_state: planner gave no justification; treated as not selected (trace completion, auditable)",
            # Fuzzy-match audit note (surfaced in reply text, not evidence).
            "fuzzy port match: 'mulambam' ~ Munambam — auto-resolved; please confirm (did you mean Munambam?)",
            # Bare tool-prefix lines.
            "check_geofence verified",
            # Raw internal source ids / fields.
            "Wave: open_meteo_live",
            "Wind: open_meteo_live",
            "selected_tools: ['find_fishing_zones']",
            # Masked metric spans must never reach chat.
            "wind __MKNOTS_12__ kts offshore",
            "bearing __MBEARING_NE__ at __MDIST_5__ km",
            # Empty / non-string.
            "",
            "   ",
            None,
            42,
        ],
    )
    def test_internal_items_rejected(self, item: object) -> None:
        assert g.is_human_evidence(item) is False

    def test_raw_token_inside_valid_line_rejected(self) -> None:
        assert g.is_human_evidence("Wave: open_meteo_live (live)") is False
        assert g.is_human_evidence("INCOIS TextData __MCOORD_9__") is False


class TestFilterHumanEvidence:
    def test_keeps_allowlist_drops_trace_order_stable(self) -> None:
        items = [
            "INCOIS TextData SEC005 KERALA",
            "SELECT find_fishing_zones: fish intent needs candidates",
            "Wave: live model",
            "find_fishing_zones selected by planner (trace line auto-added; LLM gave no explicit justification)",
            "No EEZ/MPA violation",
            "Wind: open_meteo_live",
            "Departure forecast window analyzed (Tomorrow morning)",
            "INCOIS TextData SEC005 KERALA",  # dupe
        ]
        assert g.filter_human_evidence(items) == [
            "INCOIS TextData SEC005 KERALA",
            "Wave: live model",
            "No EEZ/MPA violation",
            "Departure forecast window analyzed (Tomorrow morning)",
        ]

    def test_old_style_evidence_gets_cleaned(self) -> None:
        # What the pre-#193 pipeline appended: raw source ids + full trace.
        old_style = [
            "INCOIS TextData",
            "Wave: open_meteo_live",
            "Wind: open_meteo_live",
            "No EEZ/MPA violation",
            "SKIP find_fishing_zones: safety-only query",
            "check_weather selected by planner (trace line auto-added; LLM gave no explicit justification)",
        ]
        out = g.filter_human_evidence(old_style)
        assert out == ["INCOIS TextData", "No EEZ/MPA violation"]
        assert not any("open_meteo" in e for e in out)
        assert not any("auto-added" in e for e in out)

    def test_accepts_single_string_and_rejects_non_list(self) -> None:
        assert g.filter_human_evidence("INCOIS TextData") == ["INCOIS TextData"]
        assert g.filter_human_evidence("SELECT find_fishing_zones: x") == []
        assert g.filter_human_evidence(None) == []
        assert g.filter_human_evidence(42) == []


class TestHumanSourceLabel:
    def test_known_sources(self) -> None:
        assert g.human_source_label("open_meteo_live") == "live model"
        assert g.human_source_label("marine_data_package") == "archived climatology"
        assert g.human_source_label("mock_heuristic") == "model estimate"

    def test_unknown_and_empty_fall_back_to_human_text(self) -> None:
        assert g.human_source_label("unknown") == "live observation"
        assert g.human_source_label("") == "live observation"
        assert g.human_source_label(None) == "live observation"

    def test_never_emits_raw_snake_id(self) -> None:
        assert "_" not in g.human_source_label("open_meteo_live")
        assert "_" not in g.human_source_label("some_future_source")


class TestInternalTraceTagging:
    def test_auto_filler_lines_flagged_internal(self) -> None:
        assert ps.is_internal_trace_line(
            "find_fishing_zones selected by planner (trace line auto-added; LLM gave no explicit justification)"
        ) is True
        assert ps.is_internal_trace_line(
            "SKIP check_ocean_state: planner gave no justification; treated as not selected (trace completion, auditable)"
        ) is True

    def test_explicit_llm_lines_not_internal(self) -> None:
        assert ps.is_internal_trace_line("SELECT find_fishing_zones: fish intent needs candidates") is False
        assert ps.is_internal_trace_line("SKIP check_weather: fish-only, no safety keywords") is False

    def test_completed_trace_filler_excluded_from_evidence(self) -> None:
        plan = ps.PlannerOutput(
            detected_language="en",
            target_location=ps.TargetLocation(lat=9.93, lon=76.26, port_name="Kochi", confidence=0.9),
            intents=["find_fish"],
            confidence=0.9,
            reasoning_trace=["SELECT find_fishing_zones: fish intent needs candidates"],
            selected_tools=["find_fishing_zones"],
        )
        completed = ps.validate_and_normalize_plan(plan.model_dump())
        filler = [ln for ln in completed.reasoning_trace if ps.is_internal_trace_line(ln)]
        assert filler, "completion must still add auditable filler to reasoning_trace"
        # ...but none of it may enter human evidence.
        assert g.filter_human_evidence(completed.reasoning_trace) == []


# ---------------------------------------------------------------------------
# Frontend trace-UX source checks (no JS runner in repo; assert the
# collapsed-by-default / allowlist wiring statically)
# ---------------------------------------------------------------------------

CHAT_PANEL = REPO / "frontend" / "chat" / "ChatPanel.tsx"
CHAT_SCREEN = REPO / "frontend" / "components" / "screens" / "ChatScreen.tsx"
SSE_HOOK = REPO / "frontend" / "chat" / "useSSEChat.ts"
EVIDENCE_CARD = REPO / "frontend" / "components" / "common" / "EvidenceCard.tsx"


class TestChatCollapsedByDefault:
    def test_no_streaming_auto_open_effect(self) -> None:
        src = CHAT_PANEL.read_text()
        # The old effect forced expandedAccordions[msg.id] = true while
        # streaming; toggleAccordion must be the only opener now.
        assert "expandedAccordions[activeStreamingMsg.id]" not in src
        assert "activeStreamingMsg" not in src

    def test_accordion_defaults_to_collapsed(self) -> None:
        src = CHAT_PANEL.read_text()
        # Render gate is `expandedAccordions[msg.id] && ...` (falsy default).
        assert "{expandedAccordions[msg.id] && (" in src

    def test_workflow_modal_keeps_full_trace(self) -> None:
        for path in (CHAT_PANEL,):
            src = path.read_text()
            assert "AgentWorkflowModal" in src
            assert "reasoning_steps" in src


class TestDangerBannerAccessibility:
    @pytest.mark.parametrize("path", [CHAT_PANEL, CHAT_SCREEN])
    def test_danger_banner_has_no_pulse(self, path: pathlib.Path) -> None:
        lines = path.read_text().splitlines()
        for i, line in enumerate(lines):
            if 'data-testid="safety-banner-danger"' in line:
                block = "\n".join(lines[i : i + 3])
                assert "animate-pulse" not in block, f"{path.name}:{i + 1} danger banner must not pulse"

    @pytest.mark.parametrize("path", [CHAT_PANEL, CHAT_SCREEN])
    def test_danger_banner_keeps_color_and_icon(self, path: pathlib.Path) -> None:
        src = path.read_text()
        assert "bg-red-950" in src and "border-red-600" in src
        assert 'role="alert"' in src


class TestRenderedEvidenceHasNoInternals:
    @pytest.mark.parametrize("path", [CHAT_PANEL, CHAT_SCREEN, EVIDENCE_CARD])
    def test_renderers_use_allowlist_filter(self, path: pathlib.Path) -> None:
        src = path.read_text()
        assert "filterHumanEvidence" in src, f"{path.name} must render filterHumanEvidence() output only"

    def test_hook_defines_allowlist(self) -> None:
        src = SSE_HOOK.read_text()
        assert "export function isHumanEvidence" in src
        assert "export function filterHumanEvidence" in src
        for marker in ("open_meteo", "__M", "trace line auto-added", "SELECT "):
            assert marker in src, f"hook filter must handle {marker!r}"

    @pytest.mark.parametrize("path", [CHAT_PANEL, CHAT_SCREEN, EVIDENCE_CARD])
    def test_no_raw_evidence_map(self, path: pathlib.Path) -> None:
        src = path.read_text()
        assert "msg.evidence.map(" not in src, f"{path.name} must not render raw msg.evidence"
        assert "evidence.map(" not in src, f"{path.name} must not render raw evidence list"
