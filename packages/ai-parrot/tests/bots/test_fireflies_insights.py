"""Unit tests for the FEAT-715 FirefliesInsightsAgent data contracts and core."""

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from parrot.agents.obsidian import FirefliesObsidianAgent
from parrot.bots.fireflies_insights import (
    ActionItem,
    FirefliesMeeting,
    FirefliesInsightsAgent,
    InsightRunReport,
    MeetingInsights,
    PendingApproval,
)
from parrot.bots.agent import Agent


def _bare_agent() -> FirefliesInsightsAgent:
    """Return an uninitialized agent with just enough state for isolated methods."""
    agent = FirefliesInsightsAgent.__new__(FirefliesInsightsAgent)
    agent.name = "FirefliesInsights"
    agent.logger = logging.getLogger("test.fireflies-insights")
    agent._skill_registry = None
    agent._skill_file_registry = None
    agent._agents_dir = None
    agent.tenant_based = False
    agent._tenant_views = {}
    agent._prompt_pipeline = None
    agent._prompt_builder = None
    agent._tools = []
    return agent


def test_meeting_requires_fingerprint() -> None:
    with pytest.raises(ValidationError):
        FirefliesMeeting(fireflies_id="m1", title="Sync", meeting_date="2026-10-22", transcript="hi")


def test_meeting_defaults_are_independent() -> None:
    a = FirefliesMeeting(fireflies_id="a", title="A", meeting_date="2026-10-22", transcript="x", fingerprint="f")
    b = FirefliesMeeting(fireflies_id="b", title="B", meeting_date="2026-10-22", transcript="y", fingerprint="g")
    a.participants.append("ana@example.test")
    assert b.participants == []
    assert a.summary == ""
    assert a.summary_fingerprint is None


def test_insights_round_trip() -> None:
    item = ActionItem(title="Ship it", owner="Ana", due_date="2026-11-01", evidence="Ana: I'll ship it")
    insights = MeetingInsights(
        meeting_id="m1",
        meeting_title="Sync",
        meeting_date="2026-10-22",
        decisions=["Go"],
        risks=["Late"],
        action_items=[item],
    )
    restored = MeetingInsights.model_validate_json(insights.model_dump_json())
    assert restored == insights


def test_action_item_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        ActionItem(title="No evidence")


def test_pending_approval_ticket_marker_defaults_empty() -> None:
    approval = PendingApproval(
        insight_id="i1", fireflies_id="m1", action_index=0, chat_id="-100", expires_at="2026-10-23T00:00:00+00:00"
    )
    assert approval.created_ticket is None
    assert approval.user_id is None


def test_run_report_starts_at_zero() -> None:
    report = InsightRunReport()
    assert (report.fetched, report.skipped, report.dropped_to_inbox, report.insights_sent) == (0, 0, 0, 0)
    assert report.errors == []


@pytest.mark.asyncio
async def test_configure_uses_file_skills_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure explicit skills without creating the database-backed registry."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "meeting.md").write_text(
        "---\nname: meeting\ndescription: Meeting workflow\ntriggers:\n  - /meeting\n---\n\nUse the meeting workflow.\n"
    )
    agent = _bare_agent()
    agent.skill_paths = [skills_dir]
    agent.wiki_root = tmp_path
    agent.inbox_dir = None

    async def no_op_configure(self, app=None) -> None:
        return None

    monkeypatch.setattr(Agent, "configure", no_op_configure)
    monkeypatch.setattr(
        "parrot.bots.fireflies_insights.load_effective_config",
        lambda root: SimpleNamespace(config=SimpleNamespace(inbox_path=lambda _: root / "inbox")),
    )

    await agent.configure()

    assert agent._skill_registry is None
    assert agent._skill_file_registry is not None
    assert agent._skill_file_registry.get("/meeting") is not None
    assert agent.inbox_dir == tmp_path / "inbox"
    assert agent.inbox_dir.is_dir()


@pytest.mark.asyncio
async def test_fetch_listing_paginates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fetch enough full pages to satisfy a total limit above one MCP page."""
    agent = _bare_agent()
    calls: list[dict[str, int | str]] = []

    async def fake_call(tool_name: str, args: dict[str, int | str]) -> SimpleNamespace:
        calls.append(args)
        return SimpleNamespace(success=True, result="ignored")

    def parse_response(_: str) -> list[dict[str, str]]:
        return [{"id": str(index)} for index in range(calls[-1]["limit"])]

    monkeypatch.setattr(agent, "_call_fireflies_tool", fake_call)
    monkeypatch.setattr(FirefliesObsidianAgent, "_parse_fireflies_response", parse_response)

    listing = await agent._fetch_listing(limit=120, from_date="2026-10-01")

    assert [call["limit"] for call in calls] == [50, 50, 20]
    assert [call["skip"] for call in calls] == [0, 50, 100]
    assert all(call["fromDate"] == "2026-10-01" for call in calls)
    assert len(listing) == 120


@pytest.mark.asyncio
async def test_fetch_summary_failure_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """An MCP summary failure leaves the transcript-only path available."""
    agent = _bare_agent()

    async def failing_call(tool_name: str, args: dict[str, str]) -> None:
        raise RuntimeError("MCP unavailable")

    monkeypatch.setattr(agent, "_call_fireflies_tool", failing_call)

    assert await agent._fetch_summary("meeting-1") is None
