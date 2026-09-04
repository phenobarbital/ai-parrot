"""Integration tests for the §27 ingest orchestrator (FEAT-481, spec
Module 6 / TASK-2672): end-to-end compile, chronological batch order,
§34 validation-failure rollback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from parrot.flows.wiki_ingest import conf
from parrot.flows.wiki_ingest import graph as graph_module
from parrot.flows.wiki_ingest import runner as runner_module
from parrot.flows.wiki_ingest.nodes.classify import Classification
from parrot.flows.wiki_ingest.nodes.concepts import ConceptExtraction
from parrot.flows.wiki_ingest.nodes.contradictions import ContradictionDetectionResult
from parrot.flows.wiki_ingest.nodes.daily import DailySynthesisProposal
from parrot.flows.wiki_ingest.nodes.entities import EntityExtraction
from parrot.flows.wiki_ingest.nodes.indexes import OverviewChangeAssessment
from parrot.flows.wiki_ingest.nodes.meeting_page import MeetingPageExtraction
from parrot.flows.wiki_ingest.nodes.project_reconcile import (
    NewProjectJustification,
    ProjectUpdateProposal,
)
from parrot.flows.wiki_ingest.runner import WikiIngestContext, run_ingest
from parrot.tools.abstract import ToolResult


class _FakeInvokeResult:
    def __init__(self, output: Any) -> None:
        self.output = output


def _make_strong_client() -> AsyncMock:
    """A strong-client whose invoke() returns per output_type."""

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
        if output_type is EntityExtraction:
            return _FakeInvokeResult(EntityExtraction(materially_relevant=True, summary="Key contact.", known_roles=[]))
        if output_type is ConceptExtraction:
            return _FakeInvokeResult(
                ConceptExtraction(materially_relevant=True, definition="A concept.", why_it_matters="It matters.")
            )
        if output_type is OverviewChangeAssessment:
            return _FakeInvokeResult(OverviewChangeAssessment(materially_changed=False, reason="No major shift."))
        return _FakeInvokeResult(None)

    client = AsyncMock()
    client.invoke = AsyncMock(side_effect=_invoke)
    return client


def _make_cheap_client() -> AsyncMock:
    async def _invoke(prompt, *, output_type=None, **kwargs):
        if output_type is MeetingPageExtraction:
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


_LISTING_TEMPLATE = """[{count}]:
{entries}
"""


def _listing_entry(meeting_id: str, title: str, date_iso: str) -> str:
    return f'  - id: {meeting_id}\n    title: "{title}"\n    dateString: "{date_iso}"\n    duration: 30\n'


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
    """Never build a real GraphIndex/PageIndex plane in these tests —
    that plane is derived-only and orthogonal to the orchestrator logic
    under test here (spec Module 13, TASK-2671)."""
    monkeypatch.setattr(graph_module, "build_wiki_kb_graph_toolkit", AsyncMock(return_value=AsyncMock()))
    monkeypatch.setattr(graph_module, "rebuild_graph_index", AsyncMock(return_value={}))


@pytest.mark.asyncio
async def test_ingest_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A Raw/Incoming bundle produces meeting + project + entities +
    concepts + daily + indexes + registry mirror; §34 passes."""
    monkeypatch.setattr(conf, "WIKI_KB_VAULT_PATH", str(tmp_path))
    monkeypatch.setattr(conf, "WIKI_KB_PARTICIPANTS", [])

    listing = _LISTING_TEMPLATE.format(
        count=1, entries=_listing_entry("id-1", "Acme Weekly Sync", "2026-08-20T10:00:00-05:00")
    )
    strong_client = _make_strong_client()
    cheap_client = _make_cheap_client()
    agent = _make_agent(listing, strong_client, cheap_client)

    ctx = WikiIngestContext(agent=agent)
    report = await run_ingest(ctx)

    assert report.processed == 1
    assert report.failed == 0
    assert any("Wiki/Sources/Meetings/" in p for p in report.created)
    assert any(p.startswith("Projects/Acme Rollout/") for p in report.created)
    assert (tmp_path / "Wiki" / "Registry" / "processed-sources.md").exists()
    assert "fireflies:id-1" in (tmp_path / "Wiki" / "Registry" / "processed-sources.md").read_text()
    # The daily note is produced; the §31 archive policy (active window, D7) may
    # relocate an old date from Diary/Daily Notes/ to Diary/Archive/<year>/ — so
    # assert it exists anywhere under Diary/ (avoids a fixed-date time-bomb).
    assert list((tmp_path / "Diary").rglob("2026-08-20.md")), "daily note for 2026-08-20 not found"
    assert (tmp_path / "Wiki" / "log.md").read_text().count("ingest |") == 1


@pytest.mark.asyncio
async def test_ingest_chronological_batch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A multi-meeting batch is processed oldest→newest regardless of
    listing order (G5)."""
    monkeypatch.setattr(conf, "WIKI_KB_VAULT_PATH", str(tmp_path))
    monkeypatch.setattr(conf, "WIKI_KB_PARTICIPANTS", [])

    # Listing order is NEWEST first — the orchestrator must still process
    # oldest -> newest.
    listing = _LISTING_TEMPLATE.format(
        count=2,
        entries=(
            _listing_entry("id-new", "Acme Later Sync", "2026-08-25T10:00:00-05:00")
            + _listing_entry("id-old", "Acme Earlier Sync", "2026-08-10T10:00:00-05:00")
        ),
    )
    strong_client = _make_strong_client()
    cheap_client = _make_cheap_client()
    agent = _make_agent(listing, strong_client, cheap_client)

    processed_order: list[str] = []
    original = runner_module._process_one_meeting

    async def _spy(agent_, toolkit, registry, vault_path, meeting, **kwargs):
        processed_order.append(meeting.fireflies_id)
        return await original(agent_, toolkit, registry, vault_path, meeting, **kwargs)

    monkeypatch.setattr(runner_module, "_process_one_meeting", _spy)

    ctx = WikiIngestContext(agent=agent)
    report = await run_ingest(ctx)

    assert report.processed == 2
    assert processed_order == ["id-old", "id-new"]

    project_note = (tmp_path / "Projects" / "Acme Rollout" / "Acme Rollout.md").read_text()
    assert "last_meeting: '2026-08-25'" in project_note or "last_meeting: 2026-08-25" in project_note


@pytest.mark.asyncio
async def test_ingest_validation_failure_rolls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A §34 validation failure rolls back compiled changes, queues a
    review item, writes no log entry, and leaves raw untouched."""
    monkeypatch.setattr(conf, "WIKI_KB_VAULT_PATH", str(tmp_path))
    monkeypatch.setattr(conf, "WIKI_KB_PARTICIPANTS", [])

    listing = _LISTING_TEMPLATE.format(
        count=1, entries=_listing_entry("id-1", "Acme Weekly Sync", "2026-08-20T10:00:00-05:00")
    )
    strong_client = _make_strong_client()
    cheap_client = _make_cheap_client()
    agent = _make_agent(listing, strong_client, cheap_client)

    from parrot.flows.wiki_ingest.validation import ValidationResult

    monkeypatch.setattr(
        runner_module,
        "validate",
        lambda ctx: ValidationResult(passed=False, failures=["forced failure for test"]),
    )

    ctx = WikiIngestContext(agent=agent)
    report = await run_ingest(ctx)

    assert report.failed == 1
    assert report.processed == 0
    assert any("forced failure for test" in e for e in report.errors)

    # Compiled meeting page was rolled back (created, so deleted).
    meetings_dir = tmp_path / "Wiki" / "Sources" / "Meetings"
    assert not any(meetings_dir.iterdir()) if meetings_dir.exists() else True

    # No successful ingest log entry.
    log_path = tmp_path / "Wiki" / "log.md"
    if log_path.exists():
        assert "ingest |" not in log_path.read_text()

    # Module 17 — raw bytes preserved but QUARANTINED to Raw/Failed (not Processed),
    # never deleted; the id stays reprocessable.
    processed_root = tmp_path / conf.WIKI_KB_RAW_ROOT / "Processed"
    failed_root = tmp_path / conf.WIKI_KB_RAW_ROOT / "Failed"
    assert not list(processed_root.rglob("id-1/transcript.md"))
    assert (failed_root / "id-1" / "transcript.md").is_file()
    assert (failed_root / "id-1" / "failure.json").is_file()

    # Module 17 — a §34 validation failure quarantines + queues exactly one
    # failed-processing review item (attempt 1 < cap).
    queue_path = tmp_path / "Wiki" / "Review Queue.md"
    assert queue_path.exists()
    queue_content = queue_path.read_text()
    assert queue_content.count("failed-processing") == 1
    assert "`fireflies:id-1`" in queue_content


@pytest.mark.asyncio
async def test_ingest_mid_pipeline_exception_rolls_back_and_stays_recoverable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unhandled exception AFTER compiled writes have started (e.g. in
    daily synthesis) must roll back every compiled write made so far and
    report a normal §34-style failure — never leave partial pages in the
    vault with no registry/log entry and no review item (which would make
    the source permanently, silently un-recoverable via the raw-id gate).
    """
    monkeypatch.setattr(conf, "WIKI_KB_VAULT_PATH", str(tmp_path))
    monkeypatch.setattr(conf, "WIKI_KB_PARTICIPANTS", [])

    listing = _LISTING_TEMPLATE.format(
        count=1, entries=_listing_entry("id-1", "Acme Weekly Sync", "2026-08-20T10:00:00-05:00")
    )
    strong_client = _make_strong_client()
    cheap_client = _make_cheap_client()
    agent = _make_agent(listing, strong_client, cheap_client)

    from parrot.flows.wiki_ingest.nodes import daily as daily_module

    monkeypatch.setattr(daily_module, "run_daily_synthesis", AsyncMock(side_effect=RuntimeError("boom mid-pipeline")))

    ctx = WikiIngestContext(agent=agent)
    report = await run_ingest(ctx)

    assert report.processed == 0
    assert report.failed == 1
    assert any("boom mid-pipeline" in e for e in report.errors)

    # The meeting page (written before the daily-synthesis crash) was
    # rolled back — never left dangling in the vault.
    meetings_dir = tmp_path / "Wiki" / "Sources" / "Meetings"
    assert not any(meetings_dir.iterdir()) if meetings_dir.exists() else True

    # No successful ingest log entry for this meeting.
    log_path = tmp_path / "Wiki" / "log.md"
    if log_path.exists():
        assert "ingest |" not in log_path.read_text()

    # A review item was queued — the failure is surfaced, not silent.
    queue_path = tmp_path / "Wiki" / "Review Queue.md"
    assert queue_path.exists()
    assert "boom mid-pipeline" in queue_path.read_text()

    # Module 17 — raw bytes preserved, but QUARANTINED to Raw/Failed (not
    # Processed) and never marked processed in the registry, so the meeting is
    # auto-retried on a subsequent ingest rather than silently lost.
    processed_root = tmp_path / conf.WIKI_KB_RAW_ROOT / "Processed"
    failed_root = tmp_path / conf.WIKI_KB_RAW_ROOT / "Failed"
    assert not list(processed_root.rglob("id-1/transcript.md"))
    assert (failed_root / "id-1" / "transcript.md").is_file()


@pytest.mark.asyncio
async def test_ingest_links_contradiction_from_meeting_and_project_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Contract §22 rule 6 — a detected contradiction must be linked from
    BOTH the new meeting source page's ``## Contradictions`` section AND
    the affected project's ``## Unresolved Contradictions`` section, not
    just exist as a standalone ``Wiki/Contradictions/`` page.
    """
    monkeypatch.setattr(conf, "WIKI_KB_VAULT_PATH", str(tmp_path))
    monkeypatch.setattr(conf, "WIKI_KB_PARTICIPANTS", [])

    # Seed an existing project page so contradiction detection has
    # something to compare the new meeting's claims against.
    from parrot.flows.wiki_ingest import vault as vault_module

    toolkit = vault_module.build_vault_toolkit(str(tmp_path))
    await vault_module.initialize_vault(toolkit)
    from parrot.flows.wiki_ingest.models import ProjectFrontmatter
    from parrot.flows.wiki_ingest.render.project import (
        ProjectState,
        render_project_page,
    )

    frontmatter = ProjectFrontmatter(
        id="project:acme-rollout",
        title="Acme Rollout",
        status="active",
        source_pages=["Wiki/Sources/Meetings/Prior Meeting"],
        last_meeting="2026-08-01",
        created="2026-08-01T00:00:00+00:00",
        updated="2026-08-01T00:00:00+00:00",
    )
    state = ProjectState(
        current_decisions=[
            {"text": "Ship v1 by Q3.", "source": "Wiki/Sources/Meetings/Prior Meeting", "superseded": False}
        ]
    )
    await toolkit.create_note("Projects/Acme Rollout/Acme Rollout.md", render_project_page(frontmatter, state))

    listing = _LISTING_TEMPLATE.format(
        count=1, entries=_listing_entry("id-1", "Acme Weekly Sync", "2026-08-20T10:00:00-05:00")
    )
    strong_client = _make_strong_client()

    from parrot.flows.wiki_ingest.nodes.contradictions import ConflictCandidate

    async def _invoke_with_conflict(prompt, *, output_type=None, **kwargs):
        if output_type is ContradictionDetectionResult:
            return _FakeInvokeResult(
                ContradictionDetectionResult(
                    conflicts=[
                        ConflictCandidate(
                            title="Ship Date Conflict",
                            existing_claim_text="Ship v1 by Q3.",
                            new_claim_text="Ship v2 by Q4.",
                            why_conflict="The shipping quarter changed.",
                            impact="Timeline commitment shifted.",
                            severity="high",
                            resolution_needed="Confirm the authoritative ship date with stakeholders.",
                        )
                    ]
                )
            )
        return await _make_strong_client().invoke(prompt, output_type=output_type, **kwargs)

    strong_client.invoke = AsyncMock(side_effect=_invoke_with_conflict)
    cheap_client = _make_cheap_client()
    agent = _make_agent(listing, strong_client, cheap_client)

    ctx = WikiIngestContext(agent=agent)
    report = await run_ingest(ctx)

    assert report.processed == 1
    assert report.contradictions

    meeting_pages = list((tmp_path / "Wiki" / "Sources" / "Meetings").glob("*.md"))
    assert len(meeting_pages) == 1
    meeting_content = meeting_pages[0].read_text()
    assert "[[Wiki/Contradictions/Ship Date Conflict|Ship Date Conflict]]" in meeting_content

    project_content = (tmp_path / "Projects" / "Acme Rollout" / "Acme Rollout.md").read_text()
    assert "[[Wiki/Contradictions/Ship Date Conflict|Ship Date Conflict]]" in project_content


@pytest.mark.asyncio
async def test_ingest_preserves_action_items_in_daily_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Action items extracted onto the meeting page must survive the
    orchestrator's re-parse of that page and reach the daily-synthesis
    call as real content — never silently dropped as an always-empty
    list (owners/due dates/commitments)."""
    monkeypatch.setattr(conf, "WIKI_KB_VAULT_PATH", str(tmp_path))
    monkeypatch.setattr(conf, "WIKI_KB_PARTICIPANTS", [])

    listing = _LISTING_TEMPLATE.format(
        count=1, entries=_listing_entry("id-1", "Acme Weekly Sync", "2026-08-20T10:00:00-05:00")
    )
    strong_client = _make_strong_client()

    from parrot.flows.wiki_ingest.models import ActionItem

    async def _cheap_invoke(prompt, *, output_type=None, **kwargs):
        if output_type is MeetingPageExtraction:
            return _FakeInvokeResult(
                MeetingPageExtraction(
                    executive_summary="A productive sync.",
                    purpose="Align on rollout.",
                    decisions=["Ship v2 by Q4."],
                    requirements=["Support SSO."],
                    action_items=[ActionItem(action="Follow up with legal", owner="Bob", due_date="2026-09-01")],
                )
            )
        if output_type is DailySynthesisProposal:
            return _FakeInvokeResult(DailySynthesisProposal(daily_summary="Acme progressed the rollout."))
        return _FakeInvokeResult(None)

    cheap_client = AsyncMock()
    cheap_client.invoke = AsyncMock(side_effect=_cheap_invoke)
    agent = _make_agent(listing, strong_client, cheap_client)

    from parrot.flows.wiki_ingest.nodes import daily as daily_module

    original_run_daily_synthesis = daily_module.run_daily_synthesis
    captured_kwargs: dict = {}

    async def _spy(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return await original_run_daily_synthesis(*args, **kwargs)

    monkeypatch.setattr(daily_module, "run_daily_synthesis", _spy)

    ctx = WikiIngestContext(agent=agent)
    report = await run_ingest(ctx)

    assert report.processed == 1
    # The action item survived the meeting page's re-parse (previously
    # `_extraction_from_meeting` hardcoded `action_items=[]`) and reached
    # the daily-synthesis call as real content, not an empty list.
    assert any("Follow up with legal" in line and "Bob" in line for line in captured_kwargs["new_action_items"])


@pytest.mark.asyncio
async def test_ingest_wiki_index_lists_nested_project_pages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """§24.1 — ``Wiki/index.md`` must list canonical project pages, which
    live nested one level under ``Projects/<Name>/<Name>.md`` — a
    non-recursive listing of ``Projects/`` always finds none."""
    monkeypatch.setattr(conf, "WIKI_KB_VAULT_PATH", str(tmp_path))
    monkeypatch.setattr(conf, "WIKI_KB_PARTICIPANTS", [])

    listing = _LISTING_TEMPLATE.format(
        count=1, entries=_listing_entry("id-1", "Acme Weekly Sync", "2026-08-20T10:00:00-05:00")
    )
    strong_client = _make_strong_client()
    cheap_client = _make_cheap_client()
    agent = _make_agent(listing, strong_client, cheap_client)

    ctx = WikiIngestContext(agent=agent)
    report = await run_ingest(ctx)

    assert report.processed == 1
    index_content = (tmp_path / "Wiki" / "index.md").read_text()
    assert "Acme Rollout" in index_content
    assert "None yet" not in index_content


@pytest.mark.asyncio
async def test_ingest_creates_project_meeting_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """§18 — ingesting a meeting into a project must create/maintain that
    project's ``Meeting Summaries/index.md``. Regression: reconciliation
    wrote only ``Projects/<Name>/<Name>.md``, so new projects never got
    the required meeting-index structure (and the §31 archive workflow
    only re-splits an index that already exists)."""
    monkeypatch.setattr(conf, "WIKI_KB_VAULT_PATH", str(tmp_path))
    monkeypatch.setattr(conf, "WIKI_KB_PARTICIPANTS", [])

    listing = _LISTING_TEMPLATE.format(
        count=1, entries=_listing_entry("id-1", "Acme Weekly Sync", "2026-08-20T10:00:00-05:00")
    )
    agent = _make_agent(listing, _make_strong_client(), _make_cheap_client())

    ctx = WikiIngestContext(agent=agent)
    report = await run_ingest(ctx)

    assert report.processed == 1
    index_dir = tmp_path / "Projects" / "Acme Rollout" / "Meeting Summaries"
    # The active index is always created; the §31 archive step (which runs at
    # the end of ingest against the real wall-clock) may relocate an old entry
    # to Meeting Summaries/Archive/index.md — so assert across both to avoid a
    # fixed-date time-bomb.
    index_files = list(index_dir.rglob("index.md"))
    assert index_files, "project Meeting Summaries/index.md was not created"
    combined = "\n".join(f.read_text() for f in index_files)
    assert "2026-08-20" in combined
    assert "Wiki/Sources/Meetings/" in combined


@pytest.mark.asyncio
async def test_archive_discovers_nested_project_pages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """§31 — the archive workflow must find canonical project pages, which
    are nested at ``Projects/<Name>/<Name>.md``. Regression: it listed
    ``Projects/`` non-recursively (like the old Wiki-index bug), so it
    found zero projects and never split any meeting index."""
    from datetime import date

    from parrot.flows.wiki_ingest import vault as vault_module
    from parrot.flows.wiki_ingest.nodes.archive import run_archive

    toolkit = vault_module.build_vault_toolkit(str(tmp_path))
    await vault_module.initialize_vault(toolkit)

    # A nested canonical project page + a meeting index with one entry well
    # outside the active window (so archive must move it).
    await toolkit.create_note("Projects/Acme Rollout/Acme Rollout.md", "# Acme Rollout\n")
    await toolkit.create_note(
        "Projects/Acme Rollout/Meeting Summaries/index.md",
        "# Acme Rollout - Meeting Summaries\n\n## Active Meetings\n\n"
        "- 2020-01-01 - [[Wiki/Sources/Meetings/Old Sync|Old Sync]] - old sync\n",
    )

    registry = vault_module.build_meeting_registry(str(tmp_path))
    report = await run_archive(toolkit, registry, today=date(2026, 9, 1))

    # The nested project was discovered and its stale meeting entry archived.
    assert any(name == "Acme Rollout" for name, _ in report.archived_project_meeting_refs), report
    archive_index = tmp_path / "Projects" / "Acme Rollout" / "Meeting Summaries" / "Archive" / "index.md"
    assert archive_index.is_file()
    assert "Old Sync" in archive_index.read_text()


@pytest.mark.asyncio
async def test_ingest_entity_resolver_failure_surfaces_review_item(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A best-effort entity/concept resolver failure must be SURFACED to
    the Review Queue (not silently swallowed) while the meeting itself
    still compiles — one flaky entity must not discard an otherwise-good
    ingest."""
    monkeypatch.setattr(conf, "WIKI_KB_VAULT_PATH", str(tmp_path))
    monkeypatch.setattr(conf, "WIKI_KB_PARTICIPANTS", [])

    listing = _LISTING_TEMPLATE.format(
        count=1, entries=_listing_entry("id-1", "Acme Weekly Sync", "2026-08-20T10:00:00-05:00")
    )
    agent = _make_agent(listing, _make_strong_client(), _make_cheap_client())

    monkeypatch.setattr(
        runner_module.entities_node,
        "run_entity_resolve",
        AsyncMock(side_effect=RuntimeError("resolver boom")),
    )

    ctx = WikiIngestContext(agent=agent)
    report = await run_ingest(ctx)

    # The meeting still compiled successfully.
    assert report.processed == 1
    assert report.failed == 0
    # ...and the resolver failure was surfaced, not swallowed.
    queue_content = (tmp_path / "Wiki" / "Review Queue.md").read_text()
    assert "entity-resolution-failed" in queue_content
    assert "resolver boom" in queue_content


@pytest.mark.asyncio
async def test_ingest_bookkeeping_failure_does_not_abort_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A post-validation bookkeeping failure (e.g. ``record_synced``
    raising) for one meeting must NOT abort the whole batch — the error is
    surfaced and the remaining meetings still process. Regression: the
    success path ran outside any try/except, so one failure aborted the
    entire run."""
    monkeypatch.setattr(conf, "WIKI_KB_VAULT_PATH", str(tmp_path))
    monkeypatch.setattr(conf, "WIKI_KB_PARTICIPANTS", [])

    listing = _LISTING_TEMPLATE.format(
        count=2,
        entries=(
            _listing_entry("id-old", "Acme Earlier Sync", "2026-08-10T10:00:00-05:00")
            + _listing_entry("id-new", "Acme Later Sync", "2026-08-25T10:00:00-05:00")
        ),
    )
    agent = _make_agent(listing, _make_strong_client(), _make_cheap_client())

    from parrot.agents.meeting_registry import MeetingRegistry

    real_record_synced = MeetingRegistry.record_synced
    calls = {"n": 0}

    async def _flaky_record_synced(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:  # fail the FIRST meeting only (id-old, oldest)
            raise RuntimeError("registry write boom")
        return await real_record_synced(self, *args, **kwargs)

    monkeypatch.setattr(MeetingRegistry, "record_synced", _flaky_record_synced)

    ctx = WikiIngestContext(agent=agent)
    report = await run_ingest(ctx)

    # The batch did NOT abort: the second meeting still processed.
    assert report.processed == 1
    assert any("id-old" in e and "bookkeeping" in e for e in report.errors), report.errors


@pytest.mark.asyncio
async def test_ingest_limit_caps_combined_fresh_and_retry_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The per-run limit bounds the COMBINED fresh + Module-17 retry
    batch, not just freshly-fetched meetings — oldest-first, so retries
    (older) get priority and the overflow stays quarantined for next run.
    Regression: retries were appended after the limit was applied, so
    ``limit=3`` with 2 fresh + 2 retries processed 4."""
    monkeypatch.setattr(conf, "WIKI_KB_VAULT_PATH", str(tmp_path))
    monkeypatch.setattr(conf, "WIKI_KB_PARTICIPANTS", [])

    listing = _LISTING_TEMPLATE.format(
        count=2,
        entries=(
            _listing_entry("id-a", "A", "2026-08-20T10:00:00-05:00")
            + _listing_entry("id-b", "B", "2026-08-21T10:00:00-05:00")
        ),
    )
    agent = _make_agent(listing, _make_strong_client(), _make_cheap_client())

    from parrot.flows.wiki_ingest.nodes.fetch_gate import GatedMeeting

    retries = [
        (GatedMeeting(fireflies_id="r1", source_id="fireflies:r1", title="R1", meeting_date="2026-08-01", outcome="fetch"), 1),
        (GatedMeeting(fireflies_id="r2", source_id="fireflies:r2", title="R2", meeting_date="2026-08-02", outcome="fetch"), 1),
    ]
    monkeypatch.setattr(runner_module.quarantine_node, "build_retry_batch", lambda vault_path, cap: retries)
    monkeypatch.setattr(runner_module.quarantine_node, "discard_failed_dir", lambda *a, **k: None)

    processed_ids: list[str] = []

    async def _spy(agent_, toolkit, registry, vault_path, meeting, **kwargs):
        processed_ids.append(meeting.fireflies_id)
        return runner_module._MeetingOutcome(
            validation_passed=True, meeting_source_link="Wiki/Sources/Meetings/x"
        )

    monkeypatch.setattr(runner_module, "_process_one_meeting", _spy)

    ctx = WikiIngestContext(agent=agent, limit=3)
    await run_ingest(ctx)

    # 4 candidates (2 fresh + 2 retry) but limit=3 → only 3 processed,
    # oldest-first: the two retries (Aug 1/2) then the oldest fresh (Aug 20);
    # the newest fresh (Aug 21) is dropped and stays for the next run.
    assert processed_ids == ["r1", "r2", "id-a"]


@pytest.mark.asyncio
async def test_ingest_passes_existing_context_to_classify(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§12/§15.1 — the classifier must receive the vault's existing-knowledge
    candidates so it can match-before-create (rule #6). Regression:
    ``run_classify`` was called with no context, so the classifier always
    saw empty lists and could duplicate an existing project."""
    monkeypatch.setattr(conf, "WIKI_KB_VAULT_PATH", str(tmp_path))
    monkeypatch.setattr(conf, "WIKI_KB_PARTICIPANTS", [])

    from parrot.flows.wiki_ingest import vault as vault_module

    toolkit = vault_module.build_vault_toolkit(str(tmp_path))
    await vault_module.initialize_vault(toolkit)
    await toolkit.create_note("Projects/Existing Proj/Existing Proj.md", "# Existing Proj\n")
    await toolkit.create_note("Wiki/Entities/People/Jane Doe.md", "# Jane Doe\n")

    listing = _LISTING_TEMPLATE.format(
        count=1, entries=_listing_entry("id-1", "Acme Weekly Sync", "2026-08-20T10:00:00-05:00")
    )
    agent = _make_agent(listing, _make_strong_client(), _make_cheap_client())

    captured: dict = {}
    original = runner_module.classify_node.run_classify

    async def _spy_classify(client, meeting, *, context=None, **kwargs):
        captured["context"] = context
        return await original(client, meeting, context=context, **kwargs)

    monkeypatch.setattr(runner_module.classify_node, "run_classify", _spy_classify)

    ctx = WikiIngestContext(agent=agent)
    await run_ingest(ctx)

    context = captured["context"]
    assert context is not None
    assert "Existing Proj" in context.candidate_projects
    assert "Jane Doe" in context.candidate_people


@pytest.mark.asyncio
async def test_ingest_reconciles_additional_projects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every classified project (primary AND additional) is reconciled — each
    gets this meeting's source link + current-state update and its own
    Meeting Summaries index. Regression: only the primary was reconciled, so
    additional projects got a wikilink from the meeting page that could
    dangle and never received the meeting in their history."""
    monkeypatch.setattr(conf, "WIKI_KB_VAULT_PATH", str(tmp_path))
    monkeypatch.setattr(conf, "WIKI_KB_PARTICIPANTS", [])

    listing = _LISTING_TEMPLATE.format(
        count=1, entries=_listing_entry("id-1", "Joint Program Sync", "2026-08-20T10:00:00-05:00")
    )

    async def _strong_invoke(prompt, *, output_type=None, **kwargs):
        if output_type is Classification:
            return _FakeInvokeResult(
                Classification(
                    confidence="high",
                    primary_project="Acme Rollout",
                    primary_client="Acme Corp",
                    additional_projects=["Beta Initiative"],
                )
            )
        if output_type is ContradictionDetectionResult:
            return _FakeInvokeResult(ContradictionDetectionResult(conflicts=[]))
        if output_type is NewProjectJustification:
            return _FakeInvokeResult(NewProjectJustification(justified=True, reason="Ongoing body of work."))
        if output_type is EntityExtraction:
            return _FakeInvokeResult(EntityExtraction(materially_relevant=False, summary=""))
        if output_type is ConceptExtraction:
            return _FakeInvokeResult(ConceptExtraction(materially_relevant=False, definition="x", why_it_matters="y"))
        if output_type is OverviewChangeAssessment:
            return _FakeInvokeResult(OverviewChangeAssessment(materially_changed=False, reason="none"))
        return _FakeInvokeResult(None)

    strong_client = AsyncMock()
    strong_client.invoke = AsyncMock(side_effect=_strong_invoke)
    agent = _make_agent(listing, strong_client, _make_cheap_client())

    ctx = WikiIngestContext(agent=agent)
    report = await run_ingest(ctx)

    assert report.processed == 1
    primary = tmp_path / "Projects" / "Acme Rollout" / "Acme Rollout.md"
    additional = tmp_path / "Projects" / "Beta Initiative" / "Beta Initiative.md"
    assert primary.is_file()
    assert additional.is_file(), "additional project page was not reconciled"
    # Both projects link this meeting as a source (not just the meeting page).
    assert "Wiki/Sources/Meetings/" in primary.read_text()
    assert "Wiki/Sources/Meetings/" in additional.read_text()
    # Both projects get their own meeting index.
    assert list((tmp_path / "Projects" / "Beta Initiative" / "Meeting Summaries").rglob("index.md"))
