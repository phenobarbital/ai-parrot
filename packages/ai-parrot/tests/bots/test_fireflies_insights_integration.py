"""Integration: FirefliesInsightsAgent end to end with every external system stubbed (FEAT-715)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from parrot.bots.fireflies_insights import (
    ActionItem,
    FirefliesInsightsAgent,
    MeetingInsights,
)
from parrot.integrations.telegram.context import telegram_chat_scope


class RecordingBot:
    """Stub Telegram bot that records every send_message call."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_message(self, **kwargs) -> None:
        self.sent.append(kwargs)


class RecordingJira:
    """Stub Jira toolkit that records every jira_create_issue call."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def jira_create_issue(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        return {"ok": True, "id": "1", "key": "NAV-1", "issue": {}}


def _stub_insights(meeting_id: str = "m1", title: str = "Sync") -> MeetingInsights:
    """Build a representative MeetingInsights for test assertions."""
    return MeetingInsights(
        meeting_id=meeting_id,
        meeting_title=title,
        meeting_date="2026-10-22",
        decisions=["Ship the release"],
        risks=["Delay risk"],
        action_items=[
            ActionItem(title="Deploy staging", owner="Ana", evidence="Ana said: deploy staging"),
        ],
    )


@pytest.fixture
def agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FirefliesInsightsAgent:
    """Build a fully stubbed agent ready for sync_meetings / cmd_create_ticket."""
    monkeypatch.setattr("parrot.bots.fireflies_insights.FIREFLIES_REGISTRY_DIR", tmp_path)

    agent = FirefliesInsightsAgent.__new__(FirefliesInsightsAgent)
    agent.name = "FirefliesInsights"
    agent.logger = logging.getLogger("test.fireflies-integration")
    agent._skill_registry = None
    agent._skill_file_registry = None
    agent._agents_dir = tmp_path / "agents"
    agent.tenant_based = False
    agent._tenant_views = {}
    agent._prompt_pipeline = None
    agent._prompt_builder = None
    agent._tools = []
    agent._wrapper = SimpleNamespace(bot=RecordingBot())
    agent.working_memory = None
    agent.public_channel_id = "-100"
    agent.wiki_root = None
    agent.jira_toolkit = RecordingJira()
    agent.inbox_dir = tmp_path / "inbox"
    agent.inbox_dir.mkdir()

    # Stub registry as unavailable so _gate_meeting takes the simple path
    agent.registry = SimpleNamespace(available=False)
    agent._state_lock = asyncio.Lock()

    # Stub MCP
    agent._ensure_fireflies_mcp = AsyncMock()

    # Canned listing
    listing_data = [
        {"id": "m1", "title": "Sync", "date": "2026-10-22", "participants": ["Ana"]},
    ]

    async def fake_fetch_listing(limit=50, from_date=None):
        return listing_data

    agent._fetch_listing = fake_fetch_listing

    # Canned transcript / summary
    async def fake_fetch_transcript(fid):
        return "Ana: deploy staging\nBob: agreed"

    async def fake_fetch_summary(fid):
        return "Discussed deployment"

    agent._fetch_transcript = fake_fetch_transcript
    agent._fetch_summary = fake_fetch_summary

    # Stub LLM that returns insights
    insights = _stub_insights()

    async def fake_invoke(prompt, output_type=None, system_prompt=None):
        return SimpleNamespace(output=insights)

    agent._llm = SimpleNamespace(invoke=fake_invoke)

    return agent


@pytest.mark.asyncio
async def test_insights_survive_drop_failure(agent: FirefliesInsightsAgent, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC9: when _drop_to_inbox fails, insights for that meeting are still generated.

    The drop and insight paths are independent (AC9/G6): a drop failure must
    not suppress insight generation for the same meeting.
    """
    # Two meetings: first one will fail to drop, second succeeds
    listing = [
        {"id": "m-fail", "title": "Fail", "date": "2026-10-22"},
        {"id": "m-ok", "title": "OK", "date": "2026-10-22"},
    ]
    agent._fetch_listing = AsyncMock(return_value=listing)

    original_drop = agent._drop_to_inbox
    call_count = 0

    def failing_then_ok(meeting):
        nonlocal call_count
        call_count += 1
        if meeting.fireflies_id == "m-fail":
            raise OSError("disk full")
        return original_drop(meeting)

    monkeypatch.setattr(agent, "_drop_to_inbox", failing_then_ok)

    report = await agent.sync_meetings(limit=2)

    # The drop failure is reported in errors
    assert any("m-fail" in err for err in report.errors)
    # Both meetings' insights were sent (drop is independent of insights)
    assert report.insights_sent == 2
    # Only the second meeting was dropped to inbox
    assert report.dropped_to_inbox == 1


@pytest.mark.asyncio
async def test_ingest_survives_insight_failure(agent: FirefliesInsightsAgent, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC9: when generate_insights raises, the file is still in the inbox."""
    async def failing_invoke(prompt, output_type=None, system_prompt=None):
        raise RuntimeError("LLM unavailable")

    agent._llm = SimpleNamespace(invoke=failing_invoke)

    report = await agent.sync_meetings(limit=1)

    assert report.dropped_to_inbox == 1
    assert report.insights_sent == 0
    assert any("insights" in err for err in report.errors)
    # The inbox file is present
    inbox_files = list(agent.inbox_dir.iterdir())
    assert len(inbox_files) == 1


@pytest.mark.asyncio
async def test_confirm_and_replay(agent: FirefliesInsightsAgent) -> None:
    """AC12/AC13: report, confirm via /fireflies_ticket, replay returns same key."""
    report = await agent.sync_meetings(limit=1)
    assert report.insights_sent == 1

    # Find the insight_id from the bot's sent messages
    bot = agent._wrapper.bot
    sent_text = "".join(msg.get("text", "") for msg in bot.sent)
    import re
    ids = re.findall(r"/fireflies_ticket (\S+)", sent_text)
    assert len(ids) >= 1
    insight_id = ids[0]

    # Confirm from the reporting chat
    with telegram_chat_scope("-100"):
        first = await agent.cmd_create_ticket(insight_id)
        replay = await agent.cmd_create_ticket(insight_id)

    assert first == "Created NAV-1"
    assert replay == "Already created: NAV-1"
    assert len(agent.jira_toolkit.calls) == 1  # only one Jira call


@pytest.mark.asyncio
async def test_foreign_chat_refused(agent: FirefliesInsightsAgent) -> None:
    """AC23: confirm from another chat is refused with no Jira call."""
    await agent.sync_meetings(limit=1)

    bot = agent._wrapper.bot
    sent_text = "".join(msg.get("text", "") for msg in bot.sent)
    import re
    ids = re.findall(r"/fireflies_ticket (\S+)", sent_text)
    assert len(ids) >= 1
    insight_id = ids[0]

    with telegram_chat_scope("other-chat"):
        result = await agent.cmd_create_ticket(insight_id)

    assert "refused" in result.lower() or "not the reporting chat" in result.lower()
    assert len(agent.jira_toolkit.calls) == 0


@pytest.mark.asyncio
async def test_long_transcript_chunks_within_limit(agent: FirefliesInsightsAgent) -> None:
    """AC10: a long transcript with many action items keeps every chunk <= 4096."""
    long_insights = MeetingInsights(
        meeting_id="m1",
        meeting_title="Planning",
        meeting_date="2026-10-22",
        decisions=["Decision " * 50],
        risks=["Risk " * 50],
        action_items=[
            ActionItem(title=f"Action item {i} with detail", owner=f"Person{i}", evidence="Evidence " * 20)
            for i in range(15)
        ],
    )

    async def long_invoke(prompt, output_type=None, system_prompt=None):
        return SimpleNamespace(output=long_insights)

    agent._llm = SimpleNamespace(invoke=long_invoke)

    await agent.sync_meetings(limit=1)

    bot = agent._wrapper.bot
    budget = agent._TELEGRAM_MAX_MESSAGE
    for msg in bot.sent:
        assert len(msg.get("text", "")) <= budget, (
            f"Chunk length {len(msg['text'])} exceeds {budget}"
        )
