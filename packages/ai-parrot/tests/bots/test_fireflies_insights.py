"""Unit tests for the FEAT-715 FirefliesInsightsAgent data contracts and core."""

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from parrot.agents.meeting_registry import Classified, fingerprint
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
    agent._agents_dir = tmp_path / "agents"
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


def _meeting(**overrides: object) -> FirefliesMeeting:
    """Build a representative meeting for inbox tests."""
    values: dict[str, object] = {
        "fireflies_id": "meeting-1",
        "title": "Weekly: Bob's Update",
        "meeting_date": "2026-10-22T09:30:00Z",
        "transcript": "Ana: ship it.",
        "summary": "The team agreed to ship.",
        "participants": ["ana@example.test", "Bob's Team"],
        "duration_minutes": 30.0,
        "fingerprint": fingerprint("Ana: ship it."),
        "summary_fingerprint": fingerprint("The team agreed to ship."),
    }
    values.update(overrides)
    return FirefliesMeeting.model_validate(values)


def test_drop_is_atomic_and_leaves_no_tmp(tmp_path: Path) -> None:
    agent = _bare_agent()
    agent.inbox_dir = tmp_path

    final = agent._drop_to_inbox(_meeting())

    assert final == tmp_path / "2026-10-22-weekly-bob-s-update-meeting-1.md"
    assert final.is_file()
    assert list(tmp_path.glob("*.tmp")) == []
    assert list(tmp_path.glob(".*.tmp")) == []


def test_rendered_document_has_fireflies_id_frontmatter() -> None:
    document = _bare_agent()._render_inbox_document(_meeting())

    frontmatter, body = document.removeprefix("---\n").split("\n---\n", maxsplit=1)
    assert "fireflies_id: 'meeting-1'" in frontmatter
    assert "title: 'Weekly: Bob''s Update'" in frontmatter
    assert "  - 'Bob''s Team'" in frontmatter
    assert "## Fireflies Summary" in body
    assert "## Transcript" in body


class _Registry:
    """Minimal MeetingRegistry substitute for sync tests."""

    def __init__(self, *, available: bool, classification: str = "create") -> None:
        self.available = available
        self.classification = classification
        self.recorded: list[dict[str, object]] = []

    async def suggest_from_date(self, *, overlap_days: int) -> str | None:
        return None

    async def classify(self, item: dict[str, object], *, fetch, fetch_summary) -> Classified:
        if self.classification == "skip":
            return Classified(action="skip")
        transcript = await fetch(str(item["id"]))
        summary = await fetch_summary(str(item["id"]))
        return Classified(
            action=self.classification,
            fetched_text=transcript,
            fingerprint=fingerprint(transcript),
            summary_fingerprint=fingerprint(summary) if summary else None,
        )

    async def record_synced(self, **kwargs: object) -> None:
        self.recorded.append(kwargs)


def _listing_item(meeting_id: str, title: str = "Weekly Sync") -> dict[str, object]:
    """Return one Fireflies listing item."""
    return {
        "id": meeting_id,
        "title": title,
        "date": "2026-10-22T09:30:00Z",
        "participants": ["ana@example.test"],
        "duration": 30,
    }


def _stub_sync_fetches(
    agent: FirefliesInsightsAgent,
    monkeypatch: pytest.MonkeyPatch,
    listing: list[dict[str, object]],
) -> list[str]:
    """Stub MCP setup and fetches, returning transcript fetch ids."""
    transcript_calls: list[str] = []

    async def ensure_mcp() -> None:
        return None

    async def fetch_listing(limit: int, from_date: str | None) -> list[dict[str, object]]:
        return listing[:limit]

    async def fetch_transcript(meeting_id: str) -> str:
        transcript_calls.append(meeting_id)
        return f"Transcript for {meeting_id}"

    async def fetch_summary(meeting_id: str) -> str:
        return f"Summary for {meeting_id}"

    monkeypatch.setattr(agent, "_ensure_fireflies_mcp", ensure_mcp)
    monkeypatch.setattr(agent, "_fetch_listing", fetch_listing)
    monkeypatch.setattr(agent, "_fetch_transcript", fetch_transcript)
    monkeypatch.setattr(agent, "_fetch_summary", fetch_summary)
    return transcript_calls


@pytest.mark.asyncio
async def test_skip_classification_is_not_redropped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = _bare_agent()
    agent.inbox_dir = tmp_path
    agent.registry = _Registry(available=True, classification="skip")
    transcript_calls = _stub_sync_fetches(agent, monkeypatch, [_listing_item("known")])

    report = await agent.sync_meetings()

    assert report.fetched == 1
    assert report.skipped == 1
    assert report.dropped_to_inbox == 0
    assert transcript_calls == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_degraded_registry_skips_existing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = _bare_agent()
    agent.inbox_dir = tmp_path
    agent.registry = _Registry(available=False)
    item = _listing_item("known")
    existing = tmp_path / "2026-10-22-weekly-sync-known.md"
    existing.write_text("already dropped", encoding="utf-8")
    transcript_calls = _stub_sync_fetches(agent, monkeypatch, [item])

    report = await agent.sync_meetings()

    assert report.fetched == 1
    assert report.skipped == 1
    assert report.dropped_to_inbox == 0
    assert transcript_calls == []
    assert existing.read_text(encoding="utf-8") == "already dropped"


@pytest.mark.asyncio
async def test_one_failing_meeting_does_not_sink_the_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = _bare_agent()
    agent.inbox_dir = tmp_path
    agent.registry = _Registry(available=False)
    _stub_sync_fetches(agent, monkeypatch, [_listing_item("bad"), _listing_item("good")])
    real_drop = agent._drop_to_inbox

    def fail_one_drop(meeting: FirefliesMeeting) -> Path:
        if meeting.fireflies_id == "bad":
            raise OSError("disk failure")
        return real_drop(meeting)

    monkeypatch.setattr(agent, "_drop_to_inbox", fail_one_drop)

    report = await agent.sync_meetings()

    assert report.fetched == 2
    assert report.dropped_to_inbox == 1
    assert report.errors == ["bad: disk failure"]
    assert (tmp_path / "2026-10-22-weekly-sync-good.md").is_file()
