"""Unit tests for the project reconciler + new-project creation (FEAT-481,
spec Module 9 / TASK-2667): Q2 diff-guard, chronological supersession,
locked-page queueing, §16 negative criteria.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from parrot.flows.wiki_ingest.models import (
    Classification,
    MeetingExtraction,
    ProjectFrontmatter,
)
from parrot.flows.wiki_ingest.nodes.fetch_gate import GatedMeeting
from parrot.flows.wiki_ingest.nodes.project_reconcile import (
    NewProjectJustification,
    ProjectUpdateProposal,
    run_project_reconcile,
)
from parrot.flows.wiki_ingest.render.project import (
    ProjectState,
    SourcedClaim,
    render_project_page,
)


def _meeting(meeting_date: str = "2026-08-20") -> GatedMeeting:
    return GatedMeeting(
        fireflies_id="id-1",
        source_id="fireflies:id-1",
        title="Acme Weekly Sync",
        meeting_date=meeting_date,
        outcome="fetch",
    )


class _FakeInvokeResult:
    def __init__(self, output: Any) -> None:
        self.output = output


def _fake_client(output: Any) -> AsyncMock:
    client = AsyncMock()
    client.invoke = AsyncMock(return_value=_FakeInvokeResult(output))
    return client


def _extraction(**overrides: Any) -> MeetingExtraction:
    defaults: dict[str, Any] = {
        "decisions": ["Ship v2 by Q4."],
        "requirements": ["Support SSO."],
        "risks": ["Vendor delay risk."],
        "open_questions": ["Who owns rollout comms?"],
    }
    defaults.update(overrides)
    return MeetingExtraction(**defaults)


def _classification() -> Classification:
    return Classification(confidence="high", primary_project="Acme Rollout", primary_client="Acme Corp")


def _existing_project(*, last_meeting: str) -> tuple[ProjectFrontmatter, str]:
    state = ProjectState(
        executive_summary="Acme Rollout modernizes the onboarding flow.",
        current_status="In progress.",
        current_requirements=[SourcedClaim(text="Support SSO.", source="Wiki/Sources/Meetings/prior")],
        current_decisions=[SourcedClaim(text="Use OAuth2.", source="Wiki/Sources/Meetings/prior")],
        risks=[SourcedClaim(text="Vendor delay risk.", source="Wiki/Sources/Meetings/prior")],
        clients=["Acme Corp"],
    )
    frontmatter = ProjectFrontmatter(
        id="project:acme-rollout",
        title="Acme Rollout",
        status="active",
        clients=["Acme Corp"],
        last_meeting=last_meeting,
        created="2026-01-01T00:00:00+00:00",
        updated="2026-01-01T00:00:00+00:00",
    )
    return frontmatter, render_project_page(frontmatter, state)


@pytest.mark.asyncio
async def test_diff_guard_keeps_live_sourced_claim() -> None:
    """A claim with a live source is never dropped, even when the LLM
    proposal omits it (Q2)."""
    frontmatter, content = _existing_project(last_meeting="2026-08-01")

    # The proposal DROPS "Use OAuth2." and "Support SSO." — the diff-guard
    # must reinsert both.
    proposal = ProjectUpdateProposal(
        executive_summary="Acme Rollout modernizes onboarding.",
        current_status="On track for Q4.",
        current_decisions=[SourcedClaim(text="Ship v2 by Q4.", source="Wiki/Sources/Meetings/new")],
        current_requirements=[],
        risks=[SourcedClaim(text="Vendor delay risk.", source="Wiki/Sources/Meetings/prior")],
        change_summary="Added Q4 ship decision.",
    )
    client = _fake_client(proposal)

    result = await run_project_reconcile(
        client,
        existing_content=content,
        existing_frontmatter=frontmatter,
        locked=False,
        project_name="Acme Rollout",
        meeting=_meeting(meeting_date="2026-08-20"),
        meeting_extraction=_extraction(),
        meeting_source_link="Wiki/Sources/Meetings/new",
        classification=_classification(),
    )

    assert result.action == "updated"
    assert "Use OAuth2." in result.diff_guard_violations
    assert "Support SSO." in result.diff_guard_violations
    assert "Use OAuth2." in result.content
    assert "Support SSO." in result.content
    assert "Ship v2 by Q4." in result.content


@pytest.mark.asyncio
async def test_chronological_no_regression() -> None:
    """An older late-arriving meeting integrates as historical context
    only — current-state fields are untouched (§19 rule 10)."""
    frontmatter, content = _existing_project(last_meeting="2026-08-20")
    client = _fake_client(
        ProjectUpdateProposal(executive_summary="SHOULD NOT APPEAR", current_status="x", change_summary="x")
    )

    result = await run_project_reconcile(
        client,
        existing_content=content,
        existing_frontmatter=frontmatter,
        locked=False,
        project_name="Acme Rollout",
        meeting=_meeting(meeting_date="2026-08-10"),  # older than last_meeting
        meeting_extraction=_extraction(),
        meeting_source_link="Wiki/Sources/Meetings/older",
        classification=_classification(),
    )

    assert result.action == "chronological_supersede_only"
    client.invoke.assert_not_called()
    assert "SHOULD NOT APPEAR" not in result.content
    assert "Acme Rollout modernizes the onboarding flow." in result.content
    assert "integrated as historical context" in result.content


@pytest.mark.asyncio
async def test_locked_page_is_queued_not_edited() -> None:
    frontmatter, content = _existing_project(last_meeting="2026-08-01")
    client = _fake_client(ProjectUpdateProposal(executive_summary="x", current_status="x", change_summary="x"))

    result = await run_project_reconcile(
        client,
        existing_content=content,
        existing_frontmatter=frontmatter,
        locked=True,
        project_name="Acme Rollout",
        meeting=_meeting(),
        meeting_extraction=_extraction(),
        meeting_source_link="Wiki/Sources/Meetings/new",
        classification=_classification(),
    )

    assert result.action == "queued"
    assert result.review_item is not None
    assert result.review_item.review_type == "locked-page-update"
    client.invoke.assert_not_called()


@pytest.mark.asyncio
async def test_new_project_created_when_justified() -> None:
    client = _fake_client(
        NewProjectJustification(justified=True, reason="Ongoing rollout with decisions/requirements.")
    )

    result = await run_project_reconcile(
        client,
        existing_content=None,
        existing_frontmatter=None,
        locked=False,
        project_name="Acme Rollout",
        meeting=_meeting(),
        meeting_extraction=_extraction(),
        meeting_source_link="Wiki/Sources/Meetings/new",
        classification=_classification(),
    )

    assert result.action == "created"
    assert result.vault_path == "Projects/Acme Rollout/Acme Rollout.md"
    assert result.frontmatter is not None
    assert result.frontmatter.title == "Acme Rollout"


@pytest.mark.asyncio
async def test_new_project_negative_criteria() -> None:
    """A passing topic / lone company mention does NOT create a project (§16)."""
    client = _fake_client(NewProjectJustification(justified=False, reason="A single company mention, no active work."))

    result = await run_project_reconcile(
        client,
        existing_content=None,
        existing_frontmatter=None,
        locked=False,
        project_name="Random Chat",
        meeting=_meeting(),
        meeting_extraction=MeetingExtraction(),
        meeting_source_link="Wiki/Sources/Meetings/new",
        classification=Classification(confidence="low"),
    )

    assert result.action == "not_created"
    assert result.frontmatter is None
    assert result.content is None
