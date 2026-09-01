"""Unit tests for the connective-tissue nodes (FEAT-481, spec Module 12 /
TASK-2670): daily synthesis, index reachability, review queue, append-only
log.
"""
from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import AsyncMock

import pytest
from parrot.flows.wiki_ingest.nodes.daily import (
    DailySynthesisProposal,
    run_daily_synthesis,
)
from parrot.flows.wiki_ingest.nodes.indexes import (
    render_project_meeting_index_active,
    render_project_meeting_index_archive,
    render_wiki_index,
    split_active_and_archived,
)
from parrot.flows.wiki_ingest.nodes.log import (
    ALLOWED_LOG_OPS,
    append_log_entry,
    render_ingest_log_entry,
)
from parrot.flows.wiki_ingest.nodes.review_queue import (
    ALLOWED_REVIEW_TYPES,
    append_review_item,
    render_review_item,
    resolve_review_item,
)
from parrot.flows.wiki_ingest.render.daily import ProjectUpdateEntry


class _FakeInvokeResult:
    def __init__(self, output: Any) -> None:
        self.output = output


def _fake_client(output: Any) -> AsyncMock:
    client = AsyncMock()
    client.invoke = AsyncMock(return_value=_FakeInvokeResult(output))
    return client


# ---------------------------------------------------------------------------
# §23 Daily synthesis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_synthesizes_not_concatenates() -> None:
    """A second meeting on the same day merges into ONE synthesized
    summary — the note doesn't grow by simple concatenation."""
    first_proposal = DailySynthesisProposal(
        daily_summary="Acme discussed the Q4 rollout timeline.",
        project_updates=[ProjectUpdateEntry(project_name="Acme Rollout", updates=["Timeline confirmed for Q4."])],
        decisions=["Ship v2 by Q4."],
    )
    client = _fake_client(first_proposal)

    first = await run_daily_synthesis(
        client,
        existing_content=None,
        day="2026-08-20",
        meeting_source_link="Wiki/Sources/Meetings/first",
        project_name="Acme Rollout",
        new_project_updates=["Timeline confirmed for Q4."],
        new_decisions=["Ship v2 by Q4."],
        new_action_items=[],
        new_risks=[],
    )

    # A SECOND meeting the same day proposes a synthesized (already
    # de-duplicated + merged) summary reflecting BOTH meetings — the
    # cheap client, not this function, does the de-duplication; here we
    # verify the merge machinery folds it into one state, not two.
    second_proposal = DailySynthesisProposal(
        daily_summary="Acme confirmed the Q4 rollout timeline and reviewed onboarding risk.",
        project_updates=[
            ProjectUpdateEntry(
                project_name="Acme Rollout", updates=["Timeline confirmed for Q4.", "Onboarding risk reviewed."]
            )
        ],
        decisions=["Ship v2 by Q4."],
    )
    client.invoke = AsyncMock(return_value=_FakeInvokeResult(second_proposal))

    second = await run_daily_synthesis(
        client,
        existing_content=first.content,
        day="2026-08-20",
        meeting_source_link="Wiki/Sources/Meetings/second",
        project_name="Acme Rollout",
        new_project_updates=["Onboarding risk reviewed."],
        new_decisions=[],
        new_action_items=[],
        new_risks=[],
    )

    # Only ONE occurrence of the shared decision — not doubled.
    assert second.content.count("Ship v2 by Q4.") == 1
    assert second.content.count("Timeline confirmed for Q4.") == 1
    assert "[[Wiki/Sources/Meetings/first]]" in second.content
    assert "[[Wiki/Sources/Meetings/second]]" in second.content
    assert second.frontmatter.meetings == [
        "Wiki/Sources/Meetings/first",
        "Wiki/Sources/Meetings/second",
    ]


@pytest.mark.asyncio
async def test_daily_synthesis_creates_fresh_note() -> None:
    client = _fake_client(DailySynthesisProposal(daily_summary="A quiet day.", decisions=[]))

    result = await run_daily_synthesis(
        client,
        existing_content=None,
        day="2026-08-21",
        meeting_source_link="Wiki/Sources/Meetings/only",
        project_name=None,
        new_project_updates=[],
        new_decisions=[],
        new_action_items=[],
        new_risks=[],
    )

    assert result.vault_path == "Diary/Daily Notes/2026-08-21.md"
    assert "## Daily Summary\nA quiet day." in result.content


# ---------------------------------------------------------------------------
# §24 index reachability + §18 project meeting indexes
# ---------------------------------------------------------------------------


def test_index_reachability_and_append_only_log() -> None:
    """Every managed section is reachable from Wiki/index.md; the log
    entry appends after existing content without altering it."""
    index = render_wiki_index(
        projects=[("Acme Rollout", "On track for Q4")],
        recently_updated=[("2026-08-20", "Wiki/Sources/Meetings/new", "ingested")],
    )
    for section in (
        "[[Wiki/overview|Knowledge Overview]]",
        "[[Projects/Acme Rollout/Acme Rollout|Acme Rollout]]",
        "[[Wiki/Sources/index|Source Index]]",
        "[[Wiki/Entities/index|Entity Index]]",
        "[[Wiki/Concepts/index|Concept Index]]",
        "[[Wiki/Syntheses/index|Synthesis Index]]",
        "[[Wiki/Contradictions/index|Contradiction Index]]",
        "[[Wiki/Review Queue|Review Queue]]",
    ):
        assert section in index

    log_entry = render_ingest_log_entry(
        timestamp="2026-08-20T12:00:00+00:00",
        meeting_title="Weekly Sync",
        source_id="fireflies:id-1",
        source_page="Wiki/Sources/Meetings/new",
        projects=["Projects/Acme Rollout/Acme Rollout"],
        processing_mode="summary-only",
        validation="Passed",
    )
    existing_log = "## [2026-08-01T00:00:00+00:00] initialize | Vault init\n\n- Notes: none\n"
    updated_log = append_log_entry(existing_log, log_entry)

    assert updated_log.startswith(existing_log.rstrip("\n"))
    assert "ingest | Weekly Sync" in updated_log
    assert "revision-detected" not in ALLOWED_LOG_OPS


def test_project_meeting_index_active_and_archive() -> None:
    entries = [
        ("2026-08-20", "Wiki/Sources/Meetings/recent", "Timeline confirmed"),
        ("2026-01-05", "Wiki/Sources/Meetings/old", "Kickoff"),
    ]
    active, archived = split_active_and_archived(entries, active_window_days=14, today=date(2026, 8, 25))

    assert active == [("2026-08-20", "Wiki/Sources/Meetings/recent", "Timeline confirmed")]
    assert archived == [("2026-01-05", "Wiki/Sources/Meetings/old", "Kickoff")]

    active_index = render_project_meeting_index_active("Acme Rollout", active)
    archive_index = render_project_meeting_index_archive("Acme Rollout", archived)

    assert "## Active Meetings" in active_index
    assert "[[Wiki/Sources/Meetings/recent|recent]]" in active_index
    assert "## 2026" in archive_index
    assert "### 01" in archive_index


# ---------------------------------------------------------------------------
# §26 Review Queue
# ---------------------------------------------------------------------------


def test_review_types_exclude_source_revision() -> None:
    assert "source-revision" not in ALLOWED_REVIEW_TYPES
    with pytest.raises(ValueError, match="not allowed"):
        render_review_item(
            review_type="source-revision",
            timestamp="2026-08-20T12:00:00+00:00",
            title="x",
            source_id="fireflies:id-1",
            related_pages=[],
            issue="x",
            evidence="x",
            recommended_action="x",
        )


def test_review_item_append_and_resolve() -> None:
    entry = render_review_item(
        review_type="classification",
        timestamp="2026-08-20T12:00:00+00:00",
        title="Ambiguous project",
        source_id="fireflies:id-1",
        related_pages=["Wiki/Sources/Meetings/new"],
        issue="Low confidence classification.",
        evidence="Summary lacked project context.",
        recommended_action="Confirm project with the operator.",
    )
    queue = append_review_item("# Review Queue\n\n", entry)
    assert "- Status: Open" in queue
    assert "Ambiguous project" in queue

    resolved = resolve_review_item(
        queue, "Ambiguous project", resolution="Confirmed Acme Rollout.", resolved_at="2026-08-21T09:00:00+00:00"
    )
    assert "- Status: Resolved" in resolved
    assert "- Resolution: Confirmed Acme Rollout." in resolved
    assert "Issue: Low confidence classification." in resolved  # original issue preserved
