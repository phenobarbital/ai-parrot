"""Unit tests for FirefliesObsidianAgent's registry-driven sync/analysis
loops (FEAT-472, TASK-2556).

No network, no real LLM, no real MCP: ``_call_fireflies_tool`` is stubbed
via a keyed fake; the vault is a real local :class:`ObsidianToolkit` on a
tmp directory; the registry is a real :class:`MeetingRegistry` on a tmp
sqlite db (only the ``registry unavailable`` test fakes degradation).
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot.agents.meeting_registry import MeetingRegistry
from parrot.agents.obsidian import FirefliesFilters, FirefliesObsidianAgent
from parrot.tools.obsidian import ObsidianToolkit


def _fireflies_listing_text(items: list[dict]) -> str:
    """Build listing text in the format `_parse_fireflies_response` expects."""
    lines = [f"[{len(items)}]:"]
    for item in items:
        lines.append(f"  - id: {item['id']}")
        lines.append(f"    title: {item['title']}")
        lines.append(f"    dateString: {item['date']}T00:00:00.000Z")
        lines.append(f"    duration: {item.get('duration', 10)}")
    return "\n".join(lines)


@pytest.fixture
def fake_fireflies():
    """Stub state for `_call_fireflies_tool`.

    ``fake_fireflies["listing"]``: list of ``{id, title, date, duration}``.
    ``fake_fireflies["transcripts"]``: id -> transcript text.
    ``fake_fireflies["summaries"]``: id -> summary text (absent = unavailable).
    ``fake_fireflies["calls"]``: recorded ``(tool_name, args)`` calls.
    """
    state: dict = {
        "listing": [],
        "transcripts": {},
        "summaries": {},
        "calls": [],
    }

    async def _call(tool_name: str, args: dict):
        state["calls"].append((tool_name, dict(args)))
        if tool_name == "fireflies_get_transcripts":
            text = _fireflies_listing_text(state["listing"])
            return SimpleNamespace(success=True, result=text)
        if tool_name == "fireflies_get_transcript":
            tid = args["transcriptId"]
            return SimpleNamespace(success=True, result=state["transcripts"].get(tid, ""))
        if tool_name == "fireflies_get_summary":
            tid = args["transcriptId"]
            if tid in state["summaries"]:
                return SimpleNamespace(success=True, result=state["summaries"][tid])
            return SimpleNamespace(success=False, result="")
        raise AssertionError(f"unexpected Fireflies tool call: {tool_name}")

    state["call"] = _call
    return state


@pytest.fixture
def agent(tmp_path: Path, fake_fireflies) -> FirefliesObsidianAgent:
    """A FirefliesObsidianAgent with every external seam stubbed.

    Built via ``__new__`` (same pattern as ``tests/test_fireflies_wiki_agent.py``)
    so no LLM client, MCP server, or ToolManager is touched — only the
    vault (real local ObsidianToolkit) and the registry (real MeetingRegistry
    on a tmp sqlite db) are real.
    """
    inst = FirefliesObsidianAgent.__new__(FirefliesObsidianAgent)

    vault_root = tmp_path / "vault"
    (vault_root / "meetings").mkdir(parents=True)

    inst.name = "FirefliesObsidianTest"
    inst.logger = logging.getLogger("test-fireflies-obsidian-sync")
    inst.vault_path = vault_root
    inst.meetings_folder = "meetings"
    inst.default_filters = None
    inst.fireflies_token = "test-token"
    inst.registry_dir = tmp_path / "registry"
    inst.registry = None
    inst._mcp_fireflies_initialized = True
    inst.obsidian_toolkit = ObsidianToolkit(
        vault_path=str(vault_root),
        backend="local",
        allowed_operations={"read", "bulk_read", "list", "search", "create", "update", "move", "delete"},
    )
    inst._ensure_fireflies_mcp = AsyncMock(return_value=None)
    inst._call_fireflies_tool = AsyncMock(side_effect=fake_fireflies["call"])
    inst.client = MagicMock()

    return inst


def _tool_calls(fake_fireflies, tool_name: str) -> list[dict]:
    return [args for name, args in fake_fireflies["calls"] if name == tool_name]


class TestSyncSameIdChangedTitle:
    async def test_sync_same_id_changed_title_updates_in_place(
        self, agent: FirefliesObsidianAgent, fake_fireflies, tmp_path: Path
    ):
        agent.registry = MeetingRegistry(tmp_path / "registry")
        fake_fireflies["listing"] = [{"id": "abc", "title": "Standup", "date": "2026-08-01", "duration": 30}]
        fake_fireflies["transcripts"] = {"abc": "v1 transcript content"}

        first = await agent.sync_fireflies_transcripts(limit=10)
        assert first["synced"] == 1
        assert first["revised"] == 0

        meetings_dir = agent.vault_path / "meetings"
        assert len(list(meetings_dir.glob("*.md"))) == 1

        # Title AND content change -> a real revise (not a cheap skip).
        fake_fireflies["listing"] = [{"id": "abc", "title": "Standup Renamed", "date": "2026-08-01", "duration": 30}]
        fake_fireflies["transcripts"] = {"abc": "v2 transcript content, materially different"}
        agent.obsidian_toolkit.create_note = AsyncMock(
            side_effect=AssertionError("create_note must not be called for a known id")
        )

        second = await agent.sync_fireflies_transcripts(limit=10)

        assert second["revised"] == 1
        assert second["synced"] == 0
        assert len(list(meetings_dir.glob("*.md"))) == 1  # still exactly one file

        record = await agent.registry.lookup("abc")
        assert record.analysis_status == "pending"
        assert record.title == "Standup Renamed"


class TestSyncSameDaySameTitleTwoIds:
    async def test_sync_same_day_same_title_two_ids(
        self, agent: FirefliesObsidianAgent, fake_fireflies, tmp_path: Path
    ):
        agent.registry = MeetingRegistry(tmp_path / "registry")
        fake_fireflies["listing"] = [
            {"id": "a", "title": "Standup", "date": "2026-08-01", "duration": 10},
            {"id": "b", "title": "Standup", "date": "2026-08-01", "duration": 10},
        ]
        fake_fireflies["transcripts"] = {"a": "text a", "b": "text b"}

        report = await agent.sync_fireflies_transcripts(limit=10)

        assert report["synced"] == 2
        meetings_dir = agent.vault_path / "meetings"
        files = sorted(p.name for p in meetings_dir.glob("*.md"))
        assert files == ["2026-08-01-standup-2.md", "2026-08-01-standup.md"]


class TestSyncCheapSkipAndForceRefetch:
    async def test_sync_cheap_skip_and_force_refetch(
        self, agent: FirefliesObsidianAgent, fake_fireflies, tmp_path: Path
    ):
        agent.registry = MeetingRegistry(tmp_path / "registry")
        fake_fireflies["listing"] = [{"id": "abc", "title": "Standup", "date": "2026-08-01", "duration": 30}]
        fake_fireflies["transcripts"] = {"abc": "same content"}

        await agent.sync_fireflies_transcripts(limit=10)
        fake_fireflies["calls"].clear()

        cheap = await agent.sync_fireflies_transcripts(limit=10)
        assert cheap["skipped"] == 1
        assert _tool_calls(fake_fireflies, "fireflies_get_transcript") == []

        fake_fireflies["calls"].clear()
        forced = await agent.sync_fireflies_transcripts(limit=10, force_refetch=True)
        assert len(_tool_calls(fake_fireflies, "fireflies_get_transcript")) == 1
        assert forced["skipped"] == 1  # content unchanged -> still classified skip


class TestSyncFromDate:
    async def test_sync_from_date_from_registry(self, agent: FirefliesObsidianAgent, fake_fireflies, tmp_path: Path):
        agent.registry = MeetingRegistry(tmp_path / "registry")
        fake_fireflies["listing"] = [{"id": "abc", "title": "Standup", "date": "2026-08-01", "duration": 10}]
        fake_fireflies["transcripts"] = {"abc": "text"}
        await agent.sync_fireflies_transcripts(limit=10)
        fake_fireflies["calls"].clear()

        expected_from_date = await agent.registry.suggest_from_date(overlap_days=2)
        assert expected_from_date is not None

        report = await agent.sync_fireflies_transcripts(limit=10)

        listing_calls = _tool_calls(fake_fireflies, "fireflies_get_transcripts")
        assert listing_calls[0]["fromDate"] == expected_from_date
        assert report["from_date"] == expected_from_date

    async def test_sync_explicit_from_date_wins(self, agent: FirefliesObsidianAgent, fake_fireflies, tmp_path: Path):
        agent.registry = MeetingRegistry(tmp_path / "registry")
        fake_fireflies["listing"] = [{"id": "abc", "title": "Standup", "date": "2026-08-01", "duration": 10}]
        fake_fireflies["transcripts"] = {"abc": "text"}
        await agent.sync_fireflies_transcripts(limit=10)
        fake_fireflies["calls"].clear()

        report = await agent.sync_fireflies_transcripts(limit=10, filters=FirefliesFilters(from_date="2020-01-01"))

        listing_calls = _tool_calls(fake_fireflies, "fireflies_get_transcripts")
        assert listing_calls[0]["fromDate"] == "2020-01-01"
        assert report["from_date"] is None  # not derived from the registry

    async def test_sync_empty_registry_sends_no_from_date(
        self, agent: FirefliesObsidianAgent, fake_fireflies, tmp_path: Path
    ):
        agent.registry = MeetingRegistry(tmp_path / "registry")
        fake_fireflies["listing"] = []

        await agent.sync_fireflies_transcripts(limit=10)

        listing_calls = _tool_calls(fake_fireflies, "fireflies_get_transcripts")
        assert "fromDate" not in listing_calls[0]


class TestSyncRegistryUnavailable:
    async def test_sync_registry_unavailable_falls_back(self, agent: FirefliesObsidianAgent, fake_fireflies):
        agent.registry = None
        fake_fireflies["listing"] = [{"id": "abc", "title": "Standup", "date": "2026-08-01", "duration": 10}]
        fake_fireflies["transcripts"] = {"abc": "text"}

        report = await agent.sync_fireflies_transcripts(limit=10)

        assert report["registry"] == "unavailable"
        assert report["status"] == "ok"
        assert report["synced"] == 1
        assert report["errors"] == []


class TestSyncReportFields:
    async def test_sync_report_fields(self, agent: FirefliesObsidianAgent, fake_fireflies, tmp_path: Path):
        agent.registry = MeetingRegistry(tmp_path / "registry")
        fake_fireflies["listing"] = [{"id": "abc", "title": "Standup", "date": "2026-08-01", "duration": 10}]
        fake_fireflies["transcripts"] = {"abc": "text"}

        report = await agent.sync_fireflies_transcripts(limit=10)

        for key in ("revised", "repaired", "duplicates", "probable_duplicates", "from_date", "registry"):
            assert key in report


class TestSummarizePendingTranscripts:
    async def test_summarize_uses_registry_pending(self, agent: FirefliesObsidianAgent, fake_fireflies, tmp_path: Path):
        agent.registry = MeetingRegistry(tmp_path / "registry")
        fake_fireflies["listing"] = [{"id": "abc", "title": "Standup", "date": "2026-08-01", "duration": 10}]
        fake_fireflies["transcripts"] = {"abc": "Transcript content for analysis."}
        await agent.sync_fireflies_transcripts(limit=10)

        agent.client.complete = AsyncMock(return_value="##Summary\nAll good\n##Follow Ups\n1. q1\n##Insights\n- i1")
        agent._has_analysis = AsyncMock(side_effect=AssertionError("_has_analysis must not be called"))

        outcome = await agent.summarize_pending_transcripts()

        assert outcome["analyzed"] == ["2026-08-01-standup"]
        record = await agent.registry.lookup("abc")
        assert record.analysis_status == "done"
        assert record.analysis_fingerprint == record.fingerprint

    async def test_summarize_failure_marks_failed(self, agent: FirefliesObsidianAgent, fake_fireflies, tmp_path: Path):
        agent.registry = MeetingRegistry(tmp_path / "registry")
        fake_fireflies["listing"] = [{"id": "abc", "title": "Standup", "date": "2026-08-01", "duration": 10}]
        fake_fireflies["transcripts"] = {"abc": "Transcript content for analysis."}
        await agent.sync_fireflies_transcripts(limit=10)

        agent.client.complete = AsyncMock(side_effect=RuntimeError("LLM boom"))

        outcome = await agent.summarize_pending_transcripts()

        assert outcome["errors"]
        record = await agent.registry.lookup("abc")
        assert record.analysis_status == "failed"
        assert record.last_error is not None


class TestAllowedOperations:
    def test_allowed_operations_include_move_delete(self, agent: FirefliesObsidianAgent):
        assert {"move", "delete"} <= agent.obsidian_toolkit.allowed_operations


class TestConfigureRunsBackfillOnce:
    async def test_configure_runs_backfill_once(self, agent: FirefliesObsidianAgent, monkeypatch):
        from parrot.bots.agent import BasicAgent

        monkeypatch.setattr(BasicAgent, "configure", AsyncMock(return_value=None))
        agent._initialize_tools = MagicMock()

        await agent.configure()

        assert agent.registry is not None
        assert agent.registry.available is True
