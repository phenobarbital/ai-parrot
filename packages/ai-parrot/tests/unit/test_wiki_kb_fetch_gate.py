"""Unit tests for the fetch-gate node (FEAT-481, spec Module 2 /
TASK-2663): dedup gate, watermark/catch-up, participant allowlist.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from parrot.agents.meeting_registry import Classified
from parrot.flows.wiki_ingest import conf
from parrot.flows.wiki_ingest.nodes import fetch_gate
from parrot.tools.abstract import ToolResult

_LISTING = """[2]:
  - id: id-1
    title: "Meeting One"
    dateString: "2026-08-20T10:00:00-05:00"
    organizer_email: "a@x.com"
    duration: 30
  - id: id-2
    title: "Meeting Two"
    dateString: "2026-08-21T10:00:00-05:00"
    duration: 45
"""


class _FakeTool:
    def __init__(self, execute: AsyncMock) -> None:
        self.execute = execute


class _FakeToolManager:
    def __init__(self, tools: dict[str, _FakeTool]) -> None:
        self._tools = tools

    def get_tool(self, name: str) -> _FakeTool | None:
        return self._tools.get(name)


class _FakeAgent:
    def __init__(self, tools: dict[str, _FakeTool]) -> None:
        self.tool_manager = _FakeToolManager(tools)
        self.add_fireflies_mcp_server = AsyncMock(return_value=["mcp_fireflies_fireflies_get_transcripts"])


class _FakeRegistry:
    """Duck-typed MeetingRegistry stand-in."""

    def __init__(self, classify_result: Classified, *, suggested: str | None = None) -> None:
        self._classify_result = classify_result
        self._suggested = suggested
        self.classify_calls: list[dict[str, Any]] = []

    async def suggest_from_date(self, *, overlap_days: int) -> str | None:
        return self._suggested

    async def classify(self, item, *, fetch, fetch_summary=None, force_refetch=False) -> Classified:
        self.classify_calls.append(item)
        if self._classify_result.action == "create" and fetch_summary is not None:
            # Mirrors real MeetingRegistry.classify(): fetch_summary is
            # invoked as a side effect, but its text is not returned.
            await fetch_summary(item["id"])
        return self._classify_result


def _tools(get_transcripts_result: ToolResult, transcript_calls: list[str]) -> dict[str, _FakeTool]:
    async def _get_transcripts(**kwargs):
        return get_transcripts_result

    async def _get_transcript(**kwargs):
        transcript_calls.append(kwargs["transcriptId"])
        return ToolResult(success=True, result="full transcript text")

    async def _get_summary(**kwargs):
        return ToolResult(success=True, result="fireflies summary text")

    return {
        "mcp_fireflies_fireflies_get_transcripts": _FakeTool(AsyncMock(side_effect=_get_transcripts)),
        "mcp_fireflies_fireflies_get_transcript": _FakeTool(AsyncMock(side_effect=_get_transcript)),
        "mcp_fireflies_fireflies_get_summary": _FakeTool(AsyncMock(side_effect=_get_summary)),
    }


def test_resolve_from_date_precedence() -> None:
    """since > lookback_days > suggested watermark; every override is
    still bounded by the max-catchup floor (G10 large-backlog guard)."""
    assert (
        fetch_gate._resolve_from_date(
            since="2026-08-25", lookback_days=5, suggested="2026-08-01", max_catchup_days=90
        )
        == "2026-08-25"
    )
    assert fetch_gate._resolve_from_date(since=None, lookback_days=None, suggested=None, max_catchup_days=90) is None


def test_resolve_from_date_clamped_to_max_catchup(monkeypatch: pytest.MonkeyPatch) -> None:
    """A suggested/explicit date older than WIKI_KB_MAX_CATCHUP_DAYS is
    clamped to the floor (large-backlog guard)."""
    result = fetch_gate._resolve_from_date(
        since="2000-01-01", lookback_days=None, suggested=None, max_catchup_days=30
    )
    # Clamped: never earlier than today - 30 days.
    assert result != "2000-01-01"


def test_scan_raw_processed_ids(tmp_path: Path) -> None:
    (tmp_path / "abc123").mkdir()
    (tmp_path / "abc123" / "transcript.md").write_text("x", encoding="utf-8")
    (tmp_path / "def456").mkdir()
    (tmp_path / "def456" / "transcript.txt").write_text("x", encoding="utf-8")
    (tmp_path / "no-transcript").mkdir()

    ids = fetch_gate._scan_raw_processed_ids(tmp_path)
    assert ids == {"abc123", "def456"}


def test_scan_raw_processed_ids_missing_dir(tmp_path: Path) -> None:
    assert fetch_gate._scan_raw_processed_ids(tmp_path / "does-not-exist") == set()


@pytest.mark.asyncio
async def test_skips_known_id_without_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """A processed source_id is skipped without a transcript fetch."""
    transcript_calls: list[str] = []
    listing_result = ToolResult(success=True, result=_LISTING)
    agent = _FakeAgent(_tools(listing_result, transcript_calls))
    registry = _FakeRegistry(Classified(action="skip"))

    monkeypatch.setattr(conf, "WIKI_KB_PARTICIPANTS", [])

    gated = await fetch_gate.run_fetch_gate(agent, registry=registry)

    assert len(gated) == 2
    assert all(m.outcome == "skip" for m in gated)
    assert transcript_calls == []


@pytest.mark.asyncio
async def test_raw_known_id_skips_without_registry_classify(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A source id already captured under Raw/Processed/ is skipped via
    the ∪ scan — MeetingRegistry.classify() is never called for it."""
    (tmp_path / "id-1").mkdir()
    (tmp_path / "id-1" / "transcript.md").write_text("x", encoding="utf-8")

    transcript_calls: list[str] = []
    listing_result = ToolResult(success=True, result=_LISTING)
    agent = _FakeAgent(_tools(listing_result, transcript_calls))
    registry = _FakeRegistry(Classified(action="create"))
    monkeypatch.setattr(conf, "WIKI_KB_PARTICIPANTS", [])

    gated = await fetch_gate.run_fetch_gate(agent, registry=registry, raw_processed_root=tmp_path)

    by_id = {m.fireflies_id: m for m in gated}
    assert by_id["id-1"].outcome == "skip"
    assert by_id["id-2"].outcome == "fetch"
    assert registry.classify_calls == [{"id": "id-2", "title": "Meeting Two", "date": "2026-08-21", "date_iso": "2026-08-21T10:00:00-05:00", "participants": [], "duration": 45.0}]


@pytest.mark.asyncio
async def test_revise_maps_to_duplicate_skip_not_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """R3 — a 'revise' classification (content changed for a known id)
    is a permanent duplicate-skip, never treated as an update/fetch."""
    transcript_calls: list[str] = []
    listing_result = ToolResult(success=True, result=_LISTING)
    agent = _FakeAgent(_tools(listing_result, transcript_calls))
    registry = _FakeRegistry(Classified(action="revise"))
    monkeypatch.setattr(conf, "WIKI_KB_PARTICIPANTS", [])

    gated = await fetch_gate.run_fetch_gate(agent, registry=registry)

    assert all(m.outcome == "duplicate-skip" for m in gated)
    assert all(m.transcript_text is None for m in gated)


@pytest.mark.asyncio
async def test_create_fetches_transcript_and_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    """A new meeting id is fetched (transcript + summary) and hashed."""
    transcript_calls: list[str] = []
    listing_result = ToolResult(success=True, result=_LISTING)
    agent = _FakeAgent(_tools(listing_result, transcript_calls))
    registry = _FakeRegistry(
        Classified(action="create", fetched_text="full transcript text", fingerprint="fp-1", summary_fingerprint="sfp-1")
    )
    monkeypatch.setattr(conf, "WIKI_KB_PARTICIPANTS", [])

    gated = await fetch_gate.run_fetch_gate(agent, registry=registry)

    assert all(m.outcome == "fetch" for m in gated)
    assert all(m.transcript_text == "full transcript text" for m in gated)
    assert all(m.summary_text == "fireflies summary text" for m in gated)
    assert all(m.fingerprint == "fp-1" for m in gated)


@pytest.mark.asyncio
async def test_participant_allowlist_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    """WIKI_KB_PARTICIPANTS is forwarded as the fireflies_get_transcripts
    'participants' filter."""
    captured_args: list[dict[str, Any]] = []

    async def _get_transcripts(**kwargs):
        captured_args.append(kwargs)
        return ToolResult(success=True, result="")

    agent = _FakeAgent({"mcp_fireflies_fireflies_get_transcripts": _FakeTool(AsyncMock(side_effect=_get_transcripts))})
    registry = _FakeRegistry(Classified(action="create"))
    monkeypatch.setattr(conf, "WIKI_KB_PARTICIPANTS", ["alice@example.com"])

    await fetch_gate.run_fetch_gate(agent, registry=registry)

    assert captured_args[0]["participants"] == ["alice@example.com"]
