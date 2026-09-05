"""Integration tests for Module 17 — failure quarantine, rollback & bounded
reprocess (FEAT-481, TASK-2784).

A meeting the LLM cannot compile must (a) leave no partial pages, (b) be
quarantined to ``Raw/Failed/<id>/`` and NOT marked processed, (c) surface a
``failed-processing`` Review Queue item, and (d) be auto-retried up to
``WIKI_KB_MAX_REPROCESS_ATTEMPTS`` before parking as ``reprocess-exhausted``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from parrot.exceptions import InvokeError
from parrot.flows.wiki_ingest import conf
from parrot.flows.wiki_ingest import graph as graph_module
from parrot.flows.wiki_ingest.nodes.classify import Classification
from parrot.flows.wiki_ingest.nodes.contradictions import ContradictionDetectionResult
from parrot.flows.wiki_ingest.nodes.daily import DailySynthesisProposal
from parrot.flows.wiki_ingest.nodes.meeting_page import MeetingPageExtraction
from parrot.flows.wiki_ingest.nodes.project_reconcile import NewProjectJustification, ProjectUpdateProposal
from parrot.flows.wiki_ingest.runner import WikiIngestContext, run_ingest
from parrot.tools.abstract import ToolResult


class _FakeInvokeResult:
    def __init__(self, output: Any) -> None:
        self.output = output


def _make_strong_client() -> AsyncMock:
    async def _invoke(prompt, *, output_type=None, **kwargs):
        if output_type is Classification:
            return _FakeInvokeResult(
                Classification(confidence="high", primary_project="Acme Rollout", primary_client="Acme Corp")
            )
        if output_type is ContradictionDetectionResult:
            return _FakeInvokeResult(ContradictionDetectionResult(conflicts=[]))
        if output_type is NewProjectJustification:
            return _FakeInvokeResult(NewProjectJustification(justified=True, reason="Ongoing rollout."))
        if output_type is ProjectUpdateProposal:
            return _FakeInvokeResult(
                ProjectUpdateProposal(
                    executive_summary="Acme Rollout is progressing.",
                    current_status="On track.",
                    current_decisions=[],
                    change_summary="Initial update.",
                )
            )
        return _FakeInvokeResult(None)

    client = AsyncMock()
    client.invoke = AsyncMock(side_effect=_invoke)
    return client


def _make_cheap_client(*, fail: bool) -> AsyncMock:
    """Cheap client whose MeetingPageExtraction either raises (simulating a model
    that cannot produce valid structured output) or returns a valid extraction."""

    async def _invoke(prompt, *, output_type=None, **kwargs):
        if output_type is MeetingPageExtraction:
            if fail:
                raise InvokeError("model returned unparseable text even after reformat recovery")
            return _FakeInvokeResult(
                MeetingPageExtraction(
                    executive_summary="A productive sync.",
                    purpose="Align on rollout.",
                    decisions=["Ship v2 by Q4."],
                    requirements=["Support SSO."],
                )
            )
        if output_type is DailySynthesisProposal:
            return _FakeInvokeResult(DailySynthesisProposal(daily_summary="Acme progressed the rollout."))
        return _FakeInvokeResult(None)

    client = AsyncMock()
    client.invoke = AsyncMock(side_effect=_invoke)
    return client


def _listing(meeting_id: str = "id-1") -> str:
    return (
        "[1]:\n"
        f'  - id: {meeting_id}\n'
        '    title: "Acme Weekly Sync"\n'
        '    dateString: "2026-08-20T10:00:00-05:00"\n'
        "    duration: 30\n"
    )


class _FakeTool:
    def __init__(self, execute: AsyncMock) -> None:
        self.execute = execute


class _FakeToolManager:
    def __init__(self, tools: dict[str, _FakeTool]) -> None:
        self._tools = tools

    def get_tool(self, name: str):
        return self._tools.get(name)


def _make_agent(listing_text: str, strong_client: AsyncMock, cheap_client: AsyncMock) -> Any:
    async def _get_transcripts(**kwargs):
        return ToolResult(success=True, result=listing_text)

    async def _get_transcript(**kwargs):
        return ToolResult(success=True, result="Full transcript content for the meeting.")

    async def _get_summary(**kwargs):
        return ToolResult(success=True, result="Fireflies summary for the meeting.")

    tools = {
        "mcp_fireflies_fireflies_get_transcripts": _FakeTool(AsyncMock(side_effect=_get_transcripts)),
        "mcp_fireflies_fireflies_get_transcript": _FakeTool(AsyncMock(side_effect=_get_transcript)),
        "mcp_fireflies_fireflies_get_summary": _FakeTool(AsyncMock(side_effect=_get_summary)),
    }
    agent = AsyncMock()
    agent.tool_manager = _FakeToolManager(tools)
    agent.add_fireflies_mcp_server = AsyncMock(return_value=list(tools))
    agent.strong_client = strong_client
    agent.cheap_client = cheap_client
    return agent


@pytest.fixture(autouse=True)
def _stub_graph_rebuild(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph_module, "build_wiki_kb_graph_toolkit", AsyncMock(return_value=AsyncMock()))
    monkeypatch.setattr(graph_module, "rebuild_graph_index", AsyncMock(return_value={}))


def _raw(tmp_path: Path, *parts: str) -> Path:
    return tmp_path / conf.WIKI_KB_RAW_ROOT / Path(*parts)


async def _run(tmp_path: Path, *, fail: bool) -> Any:
    agent = _make_agent(_listing(), _make_strong_client(), _make_cheap_client(fail=fail))
    return await run_ingest(WikiIngestContext(agent=agent))


@pytest.mark.asyncio
async def test_compile_failure_rolls_back_and_quarantines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(conf, "WIKI_KB_VAULT_PATH", str(tmp_path))
    monkeypatch.setattr(conf, "WIKI_KB_PARTICIPANTS", [])

    report = await _run(tmp_path, fail=True)

    assert report.processed == 0
    assert report.failed == 1
    # (a) no partial compiled pages — the meeting/project pages were rolled back.
    assert not list((tmp_path / "Wiki" / "Sources" / "Meetings").glob("*.md"))
    assert not (tmp_path / "Projects" / "Acme Rollout").exists()
    # (b) quarantined to Raw/Failed/, NOT in Raw/Processed.
    failed_dir = _raw(tmp_path, "Failed", "id-1")
    assert (failed_dir / "transcript.md").is_file()
    assert (failed_dir / "failure.json").is_file()
    assert not any(_raw(tmp_path, "Processed").rglob("id-1/transcript.*"))
    # (c) id not marked processed in the registry mirror.
    mirror = tmp_path / "Wiki" / "Registry" / "processed-sources.md"
    assert not mirror.exists() or "fireflies:id-1" not in mirror.read_text()
    # (d) a failed-processing Review Queue item surfaced.
    queue = (tmp_path / "Wiki" / "Review Queue.md").read_text()
    assert "failed-processing" in queue
    assert "`fireflies:id-1`" in queue


@pytest.mark.asyncio
async def test_auto_retry_success_promotes_and_clears(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(conf, "WIKI_KB_VAULT_PATH", str(tmp_path))
    monkeypatch.setattr(conf, "WIKI_KB_PARTICIPANTS", [])

    first = await _run(tmp_path, fail=True)
    assert first.failed == 1 and first.processed == 0
    assert (_raw(tmp_path, "Failed", "id-1") / "failure.json").is_file()

    # Second ingest: the same meeting now compiles (no re-download — retried from
    # the local quarantined bytes).
    second = await _run(tmp_path, fail=False)
    assert second.processed == 1
    assert second.failed == 0
    assert list((tmp_path / "Wiki" / "Sources" / "Meetings").glob("*.md"))
    assert not _raw(tmp_path, "Failed", "id-1").exists()
    assert any(_raw(tmp_path, "Processed").rglob("id-1/transcript.*"))
    assert "fireflies:id-1" in (tmp_path / "Wiki" / "Registry" / "processed-sources.md").read_text()
    # The quarantine review item is cleared (resolved).
    queue = (tmp_path / "Wiki" / "Review Queue.md").read_text()
    assert "- Status: Resolved" in queue


@pytest.mark.asyncio
async def test_retry_cap_parks_reprocess_exhausted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(conf, "WIKI_KB_VAULT_PATH", str(tmp_path))
    monkeypatch.setattr(conf, "WIKI_KB_PARTICIPANTS", [])
    monkeypatch.setattr(conf, "WIKI_KB_MAX_REPROCESS_ATTEMPTS", 2)

    await _run(tmp_path, fail=True)  # attempt 1 -> failed-processing
    await _run(tmp_path, fail=True)  # attempt 2 -> reaches cap -> reprocess-exhausted
    queue = (tmp_path / "Wiki" / "Review Queue.md").read_text()
    assert "reprocess-exhausted" in queue

    # Third ingest: the exhausted bundle is skipped by auto-retry (no new failure).
    third = await _run(tmp_path, fail=True)
    assert third.failed == 0
    assert third.processed == 0
    assert (_raw(tmp_path, "Failed", "id-1") / "failure.json").is_file()


@pytest.mark.asyncio
async def test_failure_json_tracks_attempts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(conf, "WIKI_KB_VAULT_PATH", str(tmp_path))
    monkeypatch.setattr(conf, "WIKI_KB_PARTICIPANTS", [])
    monkeypatch.setattr(conf, "WIKI_KB_MAX_REPROCESS_ATTEMPTS", 5)

    import json

    await _run(tmp_path, fail=True)
    rec1 = json.loads((_raw(tmp_path, "Failed", "id-1") / "failure.json").read_text())
    assert rec1["attempts"] == 1
    assert rec1["source_id"] == "fireflies:id-1"

    await _run(tmp_path, fail=True)
    rec2 = json.loads((_raw(tmp_path, "Failed", "id-1") / "failure.json").read_text())
    assert rec2["attempts"] == 2
    assert rec2["first_failed_at"] == rec1["first_failed_at"]
