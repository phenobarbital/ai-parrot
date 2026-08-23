"""Unit tests for FirefliesWikiAgent (agents/fireflies_wiki.py).

The agent lives in the gitignored ``agents/`` tree, so it is imported by
path rather than as a package module — same situation as
``tests/test_security_advisor.py``.

No network, no real LLM, no real vault: the Fireflies/Obsidian/wiki seams
are all injected as mocks onto an instance built without ``__init__``.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_PATH = REPO_ROOT / "agents" / "fireflies_wiki.py"

pytestmark = pytest.mark.skipif(
    not AGENT_PATH.exists(),
    reason="agents/fireflies_wiki.py not present (agents/ is gitignored)",
)


def _load_agent_module():
    """Import agents/fireflies_wiki.py by path.

    Returns:
        The imported module object.
    """
    if "fireflies_wiki_agent_under_test" in sys.modules:
        return sys.modules["fireflies_wiki_agent_under_test"]
    spec = importlib.util.spec_from_file_location(
        "fireflies_wiki_agent_under_test", AGENT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["fireflies_wiki_agent_under_test"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def agent_module():
    """The imported agent module."""
    return _load_agent_module()


@pytest.fixture
def agent(agent_module, tmp_path):
    """A FirefliesWikiAgent with every external seam mocked.

    Built via ``__new__`` so no LLM client, MCP server, or vault is touched.
    ``vault_path`` points at a real temp directory with a ``meetings/``
    subfolder present, so the G6 scoping check in
    ``_ingest_vault_into_wiki`` (TASK-2378) finds it by default.
    """
    cls = agent_module.FirefliesWikiAgent
    inst = cls.__new__(cls)

    vault_root = tmp_path / "vault"
    (vault_root / "meetings").mkdir(parents=True)

    inst.name = "FirefliesWikiTest"
    inst.logger = MagicMock()
    inst.meetings_folder = "meetings"
    inst.vault_path = vault_root
    inst.wiki_name = "meetings"
    inst.wiki_storage_dir = Path("/tmp/wiki")
    inst.daily_recipients = ["daily@example.com"]
    inst.weekly_recipients = ["weekly@example.com"]
    inst._wiki = None

    inst.notes_wiki_name = "notes"
    inst.notes_wiki_storage_dir = tmp_path / "wiki-notes"
    inst.notes_folder = "audio-notes"
    inst._notes_wiki = None

    inst.obsidian_toolkit = MagicMock()
    inst.obsidian_toolkit.read_note = AsyncMock(return_value={"content": ""})
    inst.client = MagicMock()
    inst.client.complete = AsyncMock(return_value="- a bullet")
    inst.send_notification = AsyncMock(return_value={"status": "success"})
    inst._get_existing_meeting_titles = AsyncMock(return_value=set())

    inst.sync_fireflies_transcripts = AsyncMock(
        return_value={"status": "ok", "synced": 1, "skipped": 0, "notes": [], "errors": []}
    )
    inst.summarize_pending_transcripts = AsyncMock(
        return_value={"status": "ok", "analyzed": [], "skipped": [], "errors": []}
    )
    return inst


ANALYSIS_HEADING = "## Analysis"


def _note(analysis: str | None) -> Dict[str, Any]:
    """Build a fake note body, optionally carrying an Analysis section."""
    body = "Raw transcript text.\n"
    if analysis is not None:
        body += f"\n---\n\n{ANALYSIS_HEADING}\n\n{analysis}\n"
    return {"content": body}


# ---------------------------------------------------------------------------
# _notes_in_window
# ---------------------------------------------------------------------------

class TestNotesInWindow:
    """Date-prefix windowing over meeting note titles."""

    @pytest.mark.asyncio
    async def test_includes_today_and_excludes_older(self, agent):
        """Notes inside the window are returned; older ones are not."""
        agent._get_existing_meeting_titles = AsyncMock(
            return_value={
                "2026-08-23-standup",
                "2026-08-22-planning",
                "2026-08-01-old-meeting",
            }
        )
        now = datetime(2026, 8, 23, 8, 0, tzinfo=timezone.utc)

        result = await agent._notes_in_window(1, now=now)

        assert result == ["2026-08-22-planning", "2026-08-23-standup"]

    @pytest.mark.asyncio
    async def test_window_boundary_is_inclusive(self, agent):
        """A note dated exactly `days` ago is inside the window."""
        agent._get_existing_meeting_titles = AsyncMock(
            return_value={"2026-08-16-retro", "2026-08-15-too-old"}
        )
        now = datetime(2026, 8, 23, 9, 0, tzinfo=timezone.utc)

        result = await agent._notes_in_window(7, now=now)

        assert result == ["2026-08-16-retro"]

    @pytest.mark.asyncio
    async def test_ignores_titles_without_date_prefix(self, agent):
        """Malformed titles are skipped, not raised on."""
        agent._get_existing_meeting_titles = AsyncMock(
            return_value={"README", "notes-about-things", "2026-08-23-ok"}
        )
        now = datetime(2026, 8, 23, 9, 0, tzinfo=timezone.utc)

        result = await agent._notes_in_window(1, now=now)

        assert result == ["2026-08-23-ok"]

    @pytest.mark.asyncio
    async def test_window_uses_schedule_timezone_not_utc(self, agent, agent_module, monkeypatch):
        """The window must be computed in the timezone the triggers fire in.

        Regression: with FIREFLIES_WIKI_TZ=Asia/Tokyo the 08:00 job runs at
        23:00 the PREVIOUS day UTC, so a UTC-based "today" selected the wrong
        day's meetings and silently shifted the whole window.
        """
        from zoneinfo import ZoneInfo

        monkeypatch.setattr(
            agent_module, "_schedule_tzinfo", lambda: ZoneInfo("Asia/Tokyo")
        )
        agent._get_existing_meeting_titles = AsyncMock(
            return_value={"2026-08-23-tokyo-standup"}
        )

        # 2026-08-23 08:00 Tokyo == 2026-08-22 23:00 UTC.
        result = await agent._notes_in_window(0)

        # Only correct if "today" is resolved in Tokyo, not UTC.
        tokyo_today = datetime.now(ZoneInfo("Asia/Tokyo")).date()
        expected = (
            ["2026-08-23-tokyo-standup"]
            if tokyo_today.isoformat() == "2026-08-23"
            else []
        )
        assert result == expected

    def test_unknown_timezone_falls_back_to_utc(self, agent_module):
        """A bogus timezone name degrades to UTC rather than raising."""
        original = agent_module._TZ
        try:
            agent_module._TZ = "Not/AZone"
            assert agent_module._schedule_tzinfo() is timezone.utc
        finally:
            agent_module._TZ = original

    @pytest.mark.asyncio
    async def test_future_dated_notes_excluded(self, agent):
        """A note dated after the reference date is outside the window."""
        agent._get_existing_meeting_titles = AsyncMock(
            return_value={"2026-08-25-future", "2026-08-23-today"}
        )
        now = datetime(2026, 8, 23, 9, 0, tzinfo=timezone.utc)

        result = await agent._notes_in_window(1, now=now)

        assert result == ["2026-08-23-today"]


# ---------------------------------------------------------------------------
# _collect_analyses
# ---------------------------------------------------------------------------

class TestCollectAnalyses:
    """Extraction of the generated Analysis section from notes."""

    @pytest.mark.asyncio
    async def test_extracts_only_the_analysis_block(self, agent):
        """The raw transcript is excluded; only the Analysis text is kept."""
        agent.ANALYSIS_HEADING = ANALYSIS_HEADING
        agent.obsidian_toolkit.read_note = AsyncMock(
            return_value=_note("Summary of the meeting.")
        )

        result = await agent._collect_analyses(["2026-08-23-standup"])

        assert len(result) == 1
        assert result[0]["note"] == "2026-08-23-standup"
        assert result[0]["analysis"] == "Summary of the meeting."
        assert "Raw transcript text" not in result[0]["analysis"]

    @pytest.mark.asyncio
    async def test_skips_notes_without_analysis(self, agent):
        """A note that was never summarized contributes nothing."""
        agent.ANALYSIS_HEADING = ANALYSIS_HEADING
        agent.obsidian_toolkit.read_note = AsyncMock(return_value=_note(None))

        result = await agent._collect_analyses(["2026-08-23-standup"])

        assert result == []

    @pytest.mark.asyncio
    async def test_unreadable_note_does_not_stop_the_digest(self, agent):
        """One failing note is skipped; the rest are still collected."""
        agent.ANALYSIS_HEADING = ANALYSIS_HEADING

        async def _read(path: str, **_: Any):
            if "broken" in path:
                raise OSError("disk error")
            return _note("Good summary.")

        agent.obsidian_toolkit.read_note = AsyncMock(side_effect=_read)

        result = await agent._collect_analyses(
            ["2026-08-23-broken", "2026-08-23-fine"]
        )

        assert [entry["note"] for entry in result] == ["2026-08-23-fine"]


# ---------------------------------------------------------------------------
# sync_meetings_to_wiki
# ---------------------------------------------------------------------------

class TestSyncMeetingsToWiki:
    """The 07:00 job: sync -> summarize -> wiki ingest."""

    @pytest.mark.asyncio
    async def test_runs_steps_in_order(self, agent):
        """Summarize must run before the wiki ingest, after the sync."""
        calls: List[str] = []

        agent.sync_fireflies_transcripts = AsyncMock(
            side_effect=lambda **_: calls.append("sync")
            or {"status": "ok", "synced": 1, "notes": [], "errors": []}
        )
        agent.summarize_pending_transcripts = AsyncMock(
            side_effect=lambda **_: calls.append("summarize")
            or {"status": "ok", "analyzed": [], "skipped": [], "errors": []}
        )
        wiki = MagicMock()
        wiki.ingest_obsidian_vault = AsyncMock(
            side_effect=lambda *a, **k: calls.append("ingest") or {"raw_ingest": {}}
        )
        agent._wiki = wiki

        report = await agent.sync_meetings_to_wiki()

        assert calls == ["sync", "summarize", "ingest"]
        assert report["status"] == "ok"
        assert report["wiki"]["ingested"] is True

    @pytest.mark.asyncio
    async def test_ingest_is_incremental(self, agent):
        """The vault ingest must be incremental so the job is idempotent."""
        wiki = MagicMock()
        wiki.ingest_obsidian_vault = AsyncMock(return_value={})
        agent._wiki = wiki

        await agent.sync_meetings_to_wiki()

        _, kwargs = wiki.ingest_obsidian_vault.call_args
        assert kwargs["incremental"] is True

    @pytest.mark.asyncio
    async def test_missing_wiki_does_not_fail_the_sync(self, agent):
        """With no wiki plane the sync still succeeds; ingest is reported off."""
        agent._wiki = None

        report = await agent.sync_meetings_to_wiki()

        assert report["status"] == "ok"
        assert report["wiki"]["ingested"] is False
        assert report["wiki"]["reason"] == "wiki toolkit unavailable"
        agent.sync_fireflies_transcripts.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ingest_failure_is_contained(self, agent):
        """A raising wiki ingest degrades to a report field, not an exception."""
        wiki = MagicMock()
        wiki.ingest_obsidian_vault = AsyncMock(side_effect=RuntimeError("boom"))
        agent._wiki = wiki

        report = await agent.sync_meetings_to_wiki()

        assert report["status"] == "ok"
        assert report["wiki"]["ingested"] is False
        assert "boom" in report["wiki"]["reason"]

    @pytest.mark.asyncio
    async def test_never_raises(self, agent):
        """A failing sync step is captured in the report, not raised."""
        agent.sync_fireflies_transcripts = AsyncMock(
            side_effect=RuntimeError("fireflies down")
        )

        report = await agent.sync_meetings_to_wiki()

        assert report["status"] == "error"
        assert "fireflies down" in report["error"]


# ---------------------------------------------------------------------------
# Notes wiki plane (TASK-2379, G2) — _build_notes_wiki_toolkit
# ---------------------------------------------------------------------------

class TestNotesWikiPlane:
    """A separate LLMWikiToolkit instance backs audio-note captures."""

    @staticmethod
    def _patch_wiki_construction(monkeypatch, agent, *, create_wiki_error=None):
        """Patch the graph/wiki-config/toolkit seams _build_notes_wiki_toolkit uses.

        Returns:
            The ``fake_toolkit`` MagicMock returned by the patched
            ``LLMWikiToolkit(...)`` constructor, with ``create_wiki`` as an
            ``AsyncMock`` (optionally raising ``create_wiki_error``).
        """
        import parrot.knowledge.graphindex.factory as graphindex_factory
        import parrot.knowledge.wiki.models as wiki_models
        import parrot.knowledge.wiki.toolkit as wiki_toolkit_module

        monkeypatch.setattr(
            graphindex_factory,
            "build_graph_memory_toolkit",
            AsyncMock(return_value=MagicMock(name="graph_toolkit")),
        )
        monkeypatch.setattr(wiki_models, "WikiConfig", MagicMock(name="WikiConfig"))

        fake_toolkit = MagicMock(name="LLMWikiToolkit_instance")
        fake_toolkit.create_wiki = AsyncMock(
            side_effect=create_wiki_error, return_value={}
        )
        monkeypatch.setattr(
            wiki_toolkit_module,
            "LLMWikiToolkit",
            MagicMock(return_value=fake_toolkit),
        )
        monkeypatch.setattr(agent, "_build_pageindex_toolkit", MagicMock(return_value=None))
        return fake_toolkit

    @pytest.mark.asyncio
    async def test_separate_instance_from_meetings(self, agent, monkeypatch):
        """The notes plane is a distinct toolkit from the meetings plane."""
        self._patch_wiki_construction(monkeypatch, agent)
        agent._wiki = MagicMock(name="meetings_toolkit")

        agent._notes_wiki = await agent._build_notes_wiki_toolkit()

        assert agent._notes_wiki is not None
        assert agent._notes_wiki is not agent._wiki

    def test_defaults(self, agent):
        """Unset env yields notes / ~/.parrot/wikis/notes / audio-notes."""
        assert agent.notes_wiki_name == "notes"
        assert agent.notes_folder == "audio-notes"

    @pytest.mark.asyncio
    async def test_create_wiki_called_and_idempotent(self, agent, monkeypatch):
        """create_wiki bootstraps the plane and tolerates a second configure()."""
        fake_toolkit = self._patch_wiki_construction(monkeypatch, agent)

        await agent._build_notes_wiki_toolkit()
        await agent._build_notes_wiki_toolkit()  # second configure() pass

        assert fake_toolkit.create_wiki.await_count == 2
        fake_toolkit.create_wiki.assert_awaited_with(agent.notes_wiki_name)

    @pytest.mark.asyncio
    async def test_create_wiki_failure_does_not_null_the_toolkit(self, agent, monkeypatch):
        """A create_wiki error is logged but the toolkit is still returned."""
        self._patch_wiki_construction(
            monkeypatch, agent, create_wiki_error=RuntimeError("disk full")
        )

        result = await agent._build_notes_wiki_toolkit()

        assert result is not None

    @pytest.mark.asyncio
    async def test_build_failure_returns_none(self, agent, monkeypatch):
        """A construction error leaves _notes_wiki as None without raising."""
        import parrot.knowledge.graphindex.factory as graphindex_factory

        monkeypatch.setattr(
            graphindex_factory,
            "build_graph_memory_toolkit",
            AsyncMock(side_effect=RuntimeError("graph plane unavailable")),
        )

        agent._notes_wiki = await agent._build_notes_wiki_toolkit()

        assert agent._notes_wiki is None

    @pytest.mark.asyncio
    async def test_meetings_plane_unaffected(self, agent, monkeypatch):
        """self._wiki still builds via the unmodified meetings code path."""
        import parrot.knowledge.graphindex.factory as graphindex_factory
        import parrot.knowledge.wiki.models as wiki_models
        import parrot.knowledge.wiki.toolkit as wiki_toolkit_module

        monkeypatch.setattr(
            graphindex_factory,
            "build_graph_memory_toolkit",
            AsyncMock(return_value=MagicMock(name="graph_toolkit")),
        )
        monkeypatch.setattr(wiki_models, "WikiConfig", MagicMock(name="WikiConfig"))
        meetings_toolkit = MagicMock(name="meetings_toolkit_instance")
        monkeypatch.setattr(
            wiki_toolkit_module,
            "LLMWikiToolkit",
            MagicMock(return_value=meetings_toolkit),
        )
        monkeypatch.setattr(agent, "_build_pageindex_toolkit", MagicMock(return_value=None))

        agent._wiki = await agent._build_wiki_toolkit()

        assert agent._wiki is meetings_toolkit

    @pytest.mark.asyncio
    async def test_graph_tenant_isolated(self, agent, monkeypatch):
        """build_graph_memory_toolkit receives tenant_id=notes_wiki_name."""
        import parrot.knowledge.graphindex.factory as graphindex_factory
        import parrot.knowledge.wiki.models as wiki_models
        import parrot.knowledge.wiki.toolkit as wiki_toolkit_module

        graph_mock = AsyncMock(return_value=MagicMock(name="graph_toolkit"))
        monkeypatch.setattr(
            graphindex_factory, "build_graph_memory_toolkit", graph_mock
        )
        monkeypatch.setattr(wiki_models, "WikiConfig", MagicMock(name="WikiConfig"))
        fake_toolkit = MagicMock(name="LLMWikiToolkit_instance")
        fake_toolkit.create_wiki = AsyncMock(return_value={})
        monkeypatch.setattr(
            wiki_toolkit_module,
            "LLMWikiToolkit",
            MagicMock(return_value=fake_toolkit),
        )
        monkeypatch.setattr(agent, "_build_pageindex_toolkit", MagicMock(return_value=None))

        await agent._build_notes_wiki_toolkit()

        _args, kwargs = graph_mock.call_args
        assert kwargs["tenant_id"] == agent.notes_wiki_name
        assert kwargs["tenant_id"] != agent.wiki_name


# ---------------------------------------------------------------------------
# Vault scoping (TASK-2378, G6) — _ingest_vault_into_wiki
# ---------------------------------------------------------------------------

class TestVaultScoping:
    """The nightly ingest must target <vault>/<meetings_folder>, not the whole vault."""

    @pytest.mark.asyncio
    async def test_ingest_scoped_to_meetings_folder(self, agent):
        """The nightly ingest targets <vault>/meetings, not the whole vault."""
        wiki = MagicMock()
        wiki.ingest_obsidian_vault = AsyncMock(return_value={})
        agent._wiki = wiki

        await agent._ingest_vault_into_wiki()

        args, _kwargs = wiki.ingest_obsidian_vault.call_args
        assert args[1] == str(agent.vault_path / "meetings")
        assert args[1] != str(agent.vault_path)

    @pytest.mark.asyncio
    async def test_extract_entities_unchanged(self, agent, agent_module):
        """Entity extraction stays at the module default (a non-goal of FEAT-452)."""
        wiki = MagicMock()
        wiki.ingest_obsidian_vault = AsyncMock(return_value={})
        agent._wiki = wiki

        await agent._ingest_vault_into_wiki()

        _args, kwargs = wiki.ingest_obsidian_vault.call_args
        assert kwargs["extract_entities"] == agent_module._EXTRACT_ENTITIES

    @pytest.mark.asyncio
    async def test_missing_meetings_folder_reports_not_ingested(self, agent):
        """A missing folder returns the not-ingested shape rather than raising."""
        wiki = MagicMock()
        wiki.ingest_obsidian_vault = AsyncMock(return_value={})
        agent._wiki = wiki
        # Point at a meetings subfolder that does not exist on disk.
        agent.vault_path = agent.vault_path.parent / "other-vault"

        result = await agent._ingest_vault_into_wiki()

        assert result["ingested"] is False
        assert result["reason"]
        wiki.ingest_obsidian_vault.assert_not_called()

    @pytest.mark.asyncio
    async def test_never_raises_on_toolkit_error(self, agent):
        """An ingest exception is swallowed into the report (existing behavior)."""
        wiki = MagicMock()
        wiki.ingest_obsidian_vault = AsyncMock(side_effect=RuntimeError("disk full"))
        agent._wiki = wiki

        result = await agent._ingest_vault_into_wiki()

        assert result["ingested"] is False
        assert "disk full" in result["reason"]


# ---------------------------------------------------------------------------
# Digest emails
# ---------------------------------------------------------------------------

class TestDailyDigest:
    """The 08:00 job."""

    @pytest.mark.asyncio
    async def test_empty_window_sends_nothing(self, agent):
        """No meetings means no email at all — not an empty bullet list."""
        agent._get_existing_meeting_titles = AsyncMock(return_value=set())

        result = await agent.email_daily_meeting_digest()

        assert result["emailed"] is False
        assert result["reason"] == "no meetings"
        agent.send_notification.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_to_daily_recipients(self, agent):
        """A populated window emails the condensed digest."""
        agent.ANALYSIS_HEADING = ANALYSIS_HEADING
        agent._notes_in_window = AsyncMock(return_value=["2026-08-23-standup"])
        agent.obsidian_toolkit.read_note = AsyncMock(
            return_value=_note("Decided to ship on Friday.")
        )
        agent.client.complete = AsyncMock(return_value="- Ship on Friday")

        result = await agent.email_daily_meeting_digest()

        assert result["emailed"] is True
        assert result["meetings"] == 1
        _, kwargs = agent.send_notification.call_args
        assert kwargs["recipients"] == ["daily@example.com"]
        assert kwargs["provider"] == "email"
        assert kwargs["message"] == "- Ship on Friday"

    @pytest.mark.asyncio
    async def test_no_recipients_configured(self, agent):
        """Nothing is sent when no addresses are configured."""
        agent.ANALYSIS_HEADING = ANALYSIS_HEADING
        agent.daily_recipients = []
        agent._notes_in_window = AsyncMock(return_value=["2026-08-23-standup"])
        agent.obsidian_toolkit.read_note = AsyncMock(return_value=_note("Something."))

        result = await agent.email_daily_meeting_digest()

        assert result["emailed"] is False
        assert result["reason"] == "no recipients configured"
        agent.send_notification.assert_not_called()

    @pytest.mark.asyncio
    async def test_uses_the_configured_daily_window(self, agent):
        """The daily job asks for its configured lookback."""
        agent._notes_in_window = AsyncMock(return_value=[])

        await agent.email_daily_meeting_digest(days=3)

        agent._notes_in_window.assert_awaited_once_with(3)


class TestWeeklyInsights:
    """The Monday 09:00 job."""

    @pytest.mark.asyncio
    async def test_uses_seven_day_window_and_weekly_recipients(self, agent):
        """Weekly insights look back a week and go to the weekly list."""
        agent.ANALYSIS_HEADING = ANALYSIS_HEADING
        agent._notes_in_window = AsyncMock(return_value=["2026-08-20-planning"])
        agent.obsidian_toolkit.read_note = AsyncMock(
            return_value=_note("Blocked on vendor API.")
        )
        agent.client.complete = AsyncMock(return_value="- Vendor API still blocking")

        result = await agent.email_weekly_insights()

        assert result["emailed"] is True
        agent._notes_in_window.assert_awaited_once_with(7)
        _, kwargs = agent.send_notification.call_args
        assert kwargs["recipients"] == ["weekly@example.com"]

    @pytest.mark.asyncio
    async def test_never_raises(self, agent):
        """An LLM failure is captured in the report, not raised."""
        agent.ANALYSIS_HEADING = ANALYSIS_HEADING
        agent._notes_in_window = AsyncMock(return_value=["2026-08-20-planning"])
        agent.obsidian_toolkit.read_note = AsyncMock(return_value=_note("Text."))
        agent.client.complete = AsyncMock(side_effect=RuntimeError("llm down"))

        result = await agent.email_weekly_insights()

        assert result["status"] == "error"
        assert "llm down" in result["error"]


# ---------------------------------------------------------------------------
# _email
# ---------------------------------------------------------------------------

class TestEmailHelper:
    """send_notification swallows provider errors — the status must be read."""

    @pytest.mark.asyncio
    async def test_returns_false_on_error_status(self, agent):
        """A reported error status is a failure, despite the await succeeding."""
        agent.send_notification = AsyncMock(
            return_value={"status": "error", "error": "smtp refused"}
        )

        assert await agent._email("Subject", "Body", ["a@example.com"]) is False

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self, agent):
        """A raising provider is caught and reported as failure."""
        agent.send_notification = AsyncMock(side_effect=RuntimeError("boom"))

        assert await agent._email("Subject", "Body", ["a@example.com"]) is False

    @pytest.mark.asyncio
    async def test_returns_true_on_success(self, agent):
        """A success status is the only path that returns True."""
        agent.send_notification = AsyncMock(return_value={"status": "success"})

        assert await agent._email("Subject", "Body", ["a@example.com"]) is True


# ---------------------------------------------------------------------------
# Schedule metadata
# ---------------------------------------------------------------------------

class TestScheduleMetadata:
    """The three methods must carry the expected @schedule configuration."""

    def test_sync_scheduled_daily_at_seven(self, agent_module):
        """The sync job fires daily at 07:00 in the configured timezone."""
        cfg = agent_module.FirefliesWikiAgent.sync_meetings_to_wiki._schedule_config

        assert cfg["schedule_type"] == "cron"
        assert cfg["schedule_config"]["hour"] == 7
        assert cfg["schedule_config"]["minute"] == 0
        assert cfg["schedule_config"]["timezone"] == "UTC"

    def test_digest_scheduled_daily_at_eight(self, agent_module):
        """The daily digest fires at 08:00, an hour after the sync."""
        cfg = (
            agent_module.FirefliesWikiAgent
            .email_daily_meeting_digest._schedule_config
        )

        assert cfg["schedule_type"] == "cron"
        assert cfg["schedule_config"]["hour"] == 8
        assert cfg["schedule_config"]["minute"] == 0

    def test_weekly_scheduled_monday(self, agent_module):
        """The weekly insights job fires on Monday."""
        cfg = agent_module.FirefliesWikiAgent.email_weekly_insights._schedule_config

        assert cfg["schedule_type"] == "cron"
        assert cfg["schedule_config"]["day_of_week"] == "mon"
        assert cfg["schedule_config"]["hour"] == 9

    def test_all_three_jobs_carry_a_timezone(self, agent_module):
        """CRON is used precisely so a timezone can be pinned on every job."""
        cls = agent_module.FirefliesWikiAgent
        for method in (
            cls.sync_meetings_to_wiki,
            cls.email_daily_meeting_digest,
            cls.email_weekly_insights,
        ):
            assert "timezone" in method._schedule_config["schedule_config"]
