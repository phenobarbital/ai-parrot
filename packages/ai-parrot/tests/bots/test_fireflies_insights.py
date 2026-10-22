"""Unit tests for the FEAT-715 FirefliesInsightsAgent data contracts and core."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
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
from parrot.integrations.telegram.context import telegram_chat_scope


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
    agent._llm = None
    agent.working_memory = None
    agent.public_channel_id = None
    agent._wrapper = None
    agent._state_lock = asyncio.Lock()
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
        self.analyzed: list[tuple[str, str]] = []
        self.analysis_failures: list[tuple[str, str]] = []

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

    async def mark_analyzed(self, fireflies_id: str, meeting_fingerprint: str) -> None:
        self.analyzed.append((fireflies_id, meeting_fingerprint))

    async def mark_analysis_failed(self, fireflies_id: str, error: str) -> None:
        self.analysis_failures.append((fireflies_id, error))


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

    async def generate_insights(transcript: str, summary: str, meta: dict[str, object]) -> MeetingInsights:
        return MeetingInsights(
            meeting_id=str(meta["fireflies_id"]),
            meeting_title=str(meta["title"]),
            meeting_date=str(meta["date"]),
        )

    async def notify_insights(insights: MeetingInsights) -> dict[str, int]:
        return {"sent": 1}

    monkeypatch.setattr(agent, "generate_insights", generate_insights)
    monkeypatch.setattr(agent, "notify_insights", notify_insights)

    report = await agent.sync_meetings()

    assert report.fetched == 2
    assert report.dropped_to_inbox == 1
    assert report.insights_sent == 2  # AC9: insights run independently of drop
    assert report.errors == ["drop bad: disk failure"]
    assert (tmp_path / "2026-10-22-weekly-sync-good.md").is_file()


def test_format_escapes_hostile_title() -> None:
    agent = _bare_agent()
    insights = MeetingInsights(
        meeting_id="meeting-1",
        meeting_title='<b>Q3 & "risks"</b>',
        meeting_date="2026-10-22 <today>",
        decisions=["Use A & B"],
        risks=["<blocked>"],
        action_items=[
            ActionItem(
                title="Ship <release>",
                owner="Ana & Bob",
                due_date="2026-11-01 > now",
                evidence='Ana: "ship it"',
            )
        ],
    )

    message = agent._format_insights_message(insights)

    assert '<b>Q3 & "risks"</b>' not in message
    assert "&lt;b&gt;Q3 &amp; &quot;risks&quot;&lt;/b&gt;" in message
    assert "2026-10-22 &lt;today&gt;" in message
    assert "Use A &amp; B" in message
    assert "&lt;blocked&gt;" in message
    assert "Ship &lt;release&gt;" in message
    assert "Ana &amp; Bob" in message
    assert "2026-11-01 &gt; now" in message
    assert "Ana: &quot;ship it&quot;" in message


def test_chunk_never_exceeds_telegram_limit() -> None:
    agent = _bare_agent()

    chunks = agent._chunk_message("x" * 10_000)

    assert len(chunks) > 1
    assert all(len(chunk) <= agent._TELEGRAM_MAX_MESSAGE for chunk in chunks)
    assert chunks[0].startswith(f"(part 1/{len(chunks)})\n")
    assert chunks[-1].startswith(f"(part {len(chunks)}/{len(chunks)})\n")


@pytest.mark.asyncio
async def test_notify_without_wrapper_does_not_raise() -> None:
    agent = _bare_agent()
    insights = MeetingInsights(meeting_id="m1", meeting_title="Sync", meeting_date="2026-10-22")

    result = await agent.notify_insights(insights)

    assert result == {"sent": 0, "reason": "no telegram wrapper"}


@pytest.mark.asyncio
async def test_generate_insights_drops_working_memory_keys() -> None:
    class FakeWorkingMemory:
        def __init__(self) -> None:
            self.stored: dict[str, str] = {}
            self.dropped: list[str] = []

        async def store_result(self, key: str, data: str) -> dict[str, str]:
            self.stored[key] = data
            return {"status": "stored"}

        async def drop_stored(self, key: str) -> dict[str, str]:
            self.stored.pop(key, None)
            self.dropped.append(key)
            return {"status": "dropped"}

    class FakeLlm:
        def __init__(self, memory: FakeWorkingMemory) -> None:
            self.memory = memory
            self.snapshots: list[set[str]] = []

        async def invoke(self, prompt: str, **kwargs: object) -> SimpleNamespace:
            self.snapshots.append(set(self.memory.stored))
            meeting_id = next(iter(self.memory.stored)).split(":")[1]
            return SimpleNamespace(
                output=MeetingInsights(meeting_id=meeting_id, meeting_title="Sync", meeting_date="2026-10-22")
            )

    agent = _bare_agent()
    memory = FakeWorkingMemory()
    llm = FakeLlm(memory)
    agent.working_memory = memory
    agent._llm = llm

    for meeting_id in ("m1", "m2"):
        result = await agent.generate_insights(
            f"transcript {meeting_id}",
            f"summary {meeting_id}",
            {"fireflies_id": meeting_id, "title": "Sync", "date": "2026-10-22"},
        )
        assert result.meeting_id == meeting_id
        assert memory.stored == {}

    assert llm.snapshots == [
        {"meeting:m1:transcript", "meeting:m1:summary"},
        {"meeting:m2:transcript", "meeting:m2:summary"},
    ]
    assert memory.dropped == [
        "meeting:m1:transcript",
        "meeting:m1:summary",
        "meeting:m2:transcript",
        "meeting:m2:summary",
    ]


@pytest.mark.asyncio
async def test_cmd_sync_with_empty_text_reaches_sync_meetings(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = _bare_agent()
    limits: list[int] = []

    async def sync_meetings(limit: int = 10) -> InsightRunReport:
        limits.append(limit)
        return InsightRunReport(fetched=2, dropped_to_inbox=2, insights_sent=1)

    monkeypatch.setattr(agent, "sync_meetings", sync_meetings)

    result = await agent.cmd_sync("")

    assert limits == [10]
    assert result == "Fireflies: fetched=2 skipped=0 dropped=2 sent=1 errors=0"
    assert agent.cmd_sync._telegram_command["parse_mode"] == "raw"


@pytest.mark.asyncio
async def test_bad_llm_output_is_reported_not_sent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class BadLlm:
        async def invoke(self, prompt: str, **kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(output="not validated insights")

    agent = _bare_agent()
    agent.inbox_dir = tmp_path
    agent.registry = _Registry(available=False)
    agent._llm = BadLlm()
    _stub_sync_fetches(agent, monkeypatch, [_listing_item("bad-insights")])
    sent: list[MeetingInsights] = []

    async def notify_insights(insights: MeetingInsights) -> dict[str, int]:
        sent.append(insights)
        return {"sent": 1}

    monkeypatch.setattr(agent, "notify_insights", notify_insights)

    report = await agent.sync_meetings()

    assert report.dropped_to_inbox == 1
    assert report.insights_sent == 0
    assert report.errors == ["insights bad-insights: LLM did not return a valid MeetingInsights result"]
    assert sent == []


@pytest.mark.asyncio
async def test_notify_send_failure_names_chat_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class FailingBot:
        async def send_message(self, **kwargs: object) -> None:
            raise RuntimeError("telegram unavailable")

    monkeypatch.setattr("parrot.bots.fireflies_insights.FIREFLIES_REGISTRY_DIR", tmp_path)
    agent = _bare_agent()
    agent.public_channel_id = "-100123"
    agent.set_wrapper(SimpleNamespace(bot=FailingBot()))
    insights = MeetingInsights(meeting_id="m1", meeting_title="Sync", meeting_date="2026-10-22")

    with caplog.at_level(logging.WARNING):
        result = await agent.notify_insights(insights)

    assert result == {"sent": 0, "errors": ["-100123: telegram unavailable"], "chat_id": "-100123"}
    assert "send to chat -100123 failed" in caplog.text


def _ticket_insights() -> MeetingInsights:
    """Build one action item suitable for confirmation tests."""
    return MeetingInsights(
        meeting_id="meeting-1",
        meeting_title="Weekly sync",
        meeting_date="2026-10-22",
        decisions=["Ship the release"],
        risks=["Review delay"],
        action_items=[ActionItem(title="Ship <release>", owner="Ana", evidence="Ana: ship it")],
    )


async def _register_ticket(agent: FirefliesInsightsAgent) -> PendingApproval:
    """Store one approval and return it for a command test."""
    return (await agent._register_approvals(_ticket_insights(), "reporting"))[0]


@pytest.mark.asyncio
async def test_ticket_requires_known_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("parrot.bots.fireflies_insights.FIREFLIES_REGISTRY_DIR", tmp_path)
    assert await _bare_agent().cmd_create_ticket("unknown") == "Unknown insight id: unknown"


@pytest.mark.asyncio
async def test_replayed_confirmation_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeJira:
        def __init__(self) -> None:
            self.calls = 0

        async def jira_create_issue(self, **kwargs: object) -> dict[str, object]:
            self.calls += 1
            return {"ok": True, "key": "PROJ-1"}

    monkeypatch.setattr("parrot.bots.fireflies_insights.FIREFLIES_REGISTRY_DIR", tmp_path)
    agent = _bare_agent()
    agent.wiki_root = None
    agent.jira_toolkit = FakeJira()
    approval = await _register_ticket(agent)

    with telegram_chat_scope("reporting"):
        first = await agent.cmd_create_ticket(approval.insight_id)
        replay = await agent.cmd_create_ticket(approval.insight_id)

    assert (first, replay) == ("Created PROJ-1", "Already created: PROJ-1")
    assert agent.jira_toolkit.calls == 1


@pytest.mark.asyncio
async def test_foreign_chat_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("parrot.bots.fireflies_insights.FIREFLIES_REGISTRY_DIR", tmp_path)
    agent = _bare_agent()
    approval = await _register_ticket(agent)

    with telegram_chat_scope("other"):
        result = await agent.cmd_create_ticket(approval.insight_id)

    assert result == "Confirmation refused: not the reporting chat"


@pytest.mark.asyncio
async def test_expired_approval_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("parrot.bots.fireflies_insights.FIREFLIES_REGISTRY_DIR", tmp_path)
    agent = _bare_agent()
    approval = await _register_ticket(agent)
    state = agent._load_state()
    state["approvals"][approval.insight_id]["expires_at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=1)
    ).isoformat()
    agent._save_state(state)

    with telegram_chat_scope("reporting"):
        result = await agent.cmd_create_ticket(approval.insight_id)

    assert result == "Confirmation expired"


@pytest.mark.asyncio
async def test_failed_jira_call_does_not_mark_created(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class FailedJira:
        async def jira_create_issue(self, **kwargs: object) -> dict[str, object]:
            return {"ok": False, "error": "Jira unavailable"}

    monkeypatch.setattr("parrot.bots.fireflies_insights.FIREFLIES_REGISTRY_DIR", tmp_path)
    agent = _bare_agent()
    agent.wiki_root = None
    agent.jira_toolkit = FailedJira()
    approval = await _register_ticket(agent)

    with telegram_chat_scope("reporting"):
        result = await agent.cmd_create_ticket(approval.insight_id)

    assert result == "Jira ticket creation failed: Jira unavailable"
    assert agent._load_state()["approvals"][approval.insight_id]["created_ticket"] is None


@pytest.mark.asyncio
async def test_ticket_without_wiki_page_omits_backlink(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class CapturingJira:
        def __init__(self) -> None:
            self.kwargs: dict[str, object] | None = None

        async def jira_create_issue(self, **kwargs: object) -> dict[str, object]:
            self.kwargs = kwargs
            return {"ok": True, "key": "PROJ-2"}

    monkeypatch.setattr("parrot.bots.fireflies_insights.FIREFLIES_REGISTRY_DIR", tmp_path)
    agent = _bare_agent()
    agent.wiki_root = None
    jira = CapturingJira()
    agent.jira_toolkit = jira

    result = await agent._create_ticket(_ticket_insights(), _ticket_insights().action_items[0])

    assert result["ok"] is True
    assert jira.kwargs is not None
    assert jira.kwargs["template"] == "fireflies/action_item"
    assert jira.kwargs["template_params"]["wiki_url"] is None


@pytest.mark.asyncio
async def test_insight_ids_are_stable_across_reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("parrot.bots.fireflies_insights.FIREFLIES_REGISTRY_DIR", tmp_path)
    agent = _bare_agent()

    first = await _register_ticket(agent)
    second = (await agent._register_approvals(_ticket_insights(), "reporting"))[0]

    assert first.insight_id == second.insight_id
