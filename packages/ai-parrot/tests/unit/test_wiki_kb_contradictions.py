"""Unit tests for the contradiction protocol (FEAT-481, spec Module 11 /
TASK-2669): detection, linking, never-resolve-by-recency.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from parrot.flows.wiki_ingest.nodes.contradictions import (
    ConflictCandidate,
    ContradictionDetectionResult,
    ExistingClaimRef,
    run_contradiction_detection,
)


class _FakeInvokeResult:
    def __init__(self, output: Any) -> None:
        self.output = output


def _fake_client(output: Any) -> AsyncMock:
    client = AsyncMock()
    client.invoke = AsyncMock(return_value=_FakeInvokeResult(output))
    return client


@pytest.mark.asyncio
async def test_conflict_creates_linked_contradiction() -> None:
    """An incompatible claim produces a linked §22 page with both claims
    preserved."""
    existing = ExistingClaimRef(text="Launch date is Q3.", source="Wiki/Sources/Meetings/old", date="2026-07-01")
    detection = ContradictionDetectionResult(
        conflicts=[
            ConflictCandidate(
                title="Launch Date Conflict",
                existing_claim_text="Launch date is Q3.",
                new_claim_text="Launch date is Q4.",
                why_conflict="The two meetings state incompatible launch quarters.",
                impact="Affects roadmap commitments and stakeholder reporting.",
                severity="high",
                resolution_needed="Confirm with the program lead which date is authoritative.",
            )
        ]
    )
    client = _fake_client(detection)

    pages = await run_contradiction_detection(
        client,
        [existing],
        ["Launch date is Q4."],
        new_claim_source="Wiki/Sources/Meetings/new",
        new_claim_date="2026-08-20",
        affected_pages=["Projects/Acme Rollout/Acme Rollout"],
    )

    assert len(pages) == 1
    page = pages[0]
    assert page.vault_path == "Wiki/Contradictions/Launch Date Conflict.md"
    assert page.frontmatter.status == "open"
    assert page.frontmatter.severity == "high"
    assert "Launch date is Q3." in page.content
    assert "Launch date is Q4." in page.content
    assert "[[Wiki/Sources/Meetings/old]]" in page.content
    assert "[[Wiki/Sources/Meetings/new]]" in page.content
    assert page.affected_pages == ["Projects/Acme Rollout/Acme Rollout"]
    assert page.review_item is not None  # high severity → review queue


@pytest.mark.asyncio
async def test_not_resolved_by_recency() -> None:
    """A contradiction is never auto-resolved even though the new claim
    is chronologically newer — status stays open, resolution stays empty."""
    existing = ExistingClaimRef(text="Budget is $50k.", source="Wiki/Sources/Meetings/old", date="2026-06-01")
    detection = ContradictionDetectionResult(
        conflicts=[
            ConflictCandidate(
                title="Budget Conflict",
                existing_claim_text="Budget is $50k.",
                new_claim_text="Budget is $80k.",
                why_conflict="Two different budget figures were stated.",
                impact="Affects financial planning.",
                severity="medium",
                resolution_needed="Confirm with finance.",
            )
        ]
    )
    client = _fake_client(detection)

    pages = await run_contradiction_detection(
        client,
        [existing],
        ["Budget is $80k."],
        new_claim_source="Wiki/Sources/Meetings/new",
        new_claim_date="2026-08-20",
        affected_pages=[],
    )

    page = pages[0]
    assert page.frontmatter.status == "open"
    assert page.frontmatter.resolved_at is None
    assert "Leave unresolved until supported." in page.content
    assert "Budget is $50k." in page.content  # older claim preserved, not overwritten


@pytest.mark.asyncio
async def test_no_conflict_produces_no_pages() -> None:
    client = _fake_client(ContradictionDetectionResult(conflicts=[]))

    pages = await run_contradiction_detection(
        client,
        [ExistingClaimRef(text="Support SSO.", source="Wiki/Sources/Meetings/old", date="2026-06-01")],
        ["Also support SAML."],
        new_claim_source="Wiki/Sources/Meetings/new",
        new_claim_date="2026-08-20",
        affected_pages=[],
    )

    assert pages == []


@pytest.mark.asyncio
async def test_empty_existing_or_new_claims_skips_llm_call() -> None:
    client = _fake_client(ContradictionDetectionResult())

    pages = await run_contradiction_detection(
        client, [], ["Some new claim."], new_claim_source="Wiki/Sources/Meetings/new", new_claim_date="2026-08-20", affected_pages=[]
    )

    assert pages == []
    client.invoke.assert_not_called()


@pytest.mark.asyncio
async def test_unrecognized_existing_claim_is_skipped_not_fabricated() -> None:
    """If the LLM cites an existing claim we never supplied, skip it
    rather than fabricate a source/date for Claim A (rule #12)."""
    detection = ContradictionDetectionResult(
        conflicts=[
            ConflictCandidate(
                title="Phantom Conflict",
                existing_claim_text="This claim was never supplied.",
                new_claim_text="New claim.",
                why_conflict="x",
                impact="x",
                severity="low",
                resolution_needed="x",
            )
        ]
    )
    client = _fake_client(detection)

    pages = await run_contradiction_detection(
        client,
        [ExistingClaimRef(text="Actual existing claim.", source="Wiki/Sources/Meetings/old", date="2026-06-01")],
        ["New claim."],
        new_claim_source="Wiki/Sources/Meetings/new",
        new_claim_date="2026-08-20",
        affected_pages=[],
    )

    assert pages == []
