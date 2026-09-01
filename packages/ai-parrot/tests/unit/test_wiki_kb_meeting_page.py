"""Unit tests for the canonical meeting source page renderer (FEAT-481,
spec Module 8 / TASK-2666): §17 template fidelity, verified-quotes gate.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from parrot.flows.wiki_ingest.models import ActionItem, Classification
from parrot.flows.wiki_ingest.nodes.classify import ClassificationResult
from parrot.flows.wiki_ingest.nodes.fetch_gate import GatedMeeting
from parrot.flows.wiki_ingest.nodes.meeting_page import (
    MeetingPageExtraction,
    run_meeting_page,
)

#: The exact §17 heading sequence, verbatim.
_EXPECTED_HEADINGS = [
    "## Executive Summary",
    "## Purpose",
    "## Participants",
    "## Projects and Clients",
    "## Key Discussion",
    "## Decisions",
    "## Requirements",
    "## Action Items",
    "## Risks and Blockers",
    "## Open Questions",
    "## Concepts and Connections",
    "## Contradictions",
    "## Verified Quotes",
    "## Source Provenance",
]


def _meeting(**overrides: Any) -> GatedMeeting:
    defaults: dict[str, Any] = {
        "fireflies_id": "id-1",
        "source_id": "fireflies:id-1",
        "title": "Weekly Sync",
        "meeting_date": "2026-08-20",
        "participants": ["alice@example.com"],
        "outcome": "fetch",
        "transcript_text": "Full transcript text.",
        "summary_text": "Fireflies summary text.",
    }
    defaults.update(overrides)
    return GatedMeeting(**defaults)


def _classification_result(*, transcript_read: bool, confidence: str = "high") -> ClassificationResult:
    return ClassificationResult(
        classification=Classification(confidence=confidence, primary_project="Acme Rollout"),
        processing_mode="summary-and-transcript" if transcript_read else "summary-only",
        transcript_read=transcript_read,
        review_required=confidence == "low",
    )


class _FakeInvokeResult:
    def __init__(self, output: Any) -> None:
        self.output = output


def _fake_client() -> AsyncMock:
    extraction = MeetingPageExtraction(
        executive_summary="A synthesis of the meeting.",
        purpose="To align on the Q3 roadmap.",
        decisions=["Ship feature X by Q3."],
        requirements=["Requirement A."],
        action_items=[ActionItem(action="Follow up with legal", owner="Bob", due_date="2026-09-01")],
        risks=["Timeline risk."],
        open_questions=["Who owns the migration?"],
    )
    client = AsyncMock()
    client.invoke = AsyncMock(return_value=_FakeInvokeResult(extraction))
    return client


@pytest.mark.asyncio
async def test_meeting_page_heading_fidelity() -> None:
    """Every §17 heading appears verbatim, in the exact contract order."""
    client = _fake_client()
    result = await run_meeting_page(
        client,
        _meeting(),
        _classification_result(transcript_read=True),
        raw_summary_path="Raw/Processed/Uncategorized/id-1/summary.md",
        raw_transcript_path="Raw/Processed/Uncategorized/id-1/transcript.md",
        summary_sha256="a" * 64,
        transcript_sha256="b" * 64,
    )

    body = result.content
    positions = [body.index(h) for h in _EXPECTED_HEADINGS]
    assert positions == sorted(positions), "headings out of order"
    assert body.startswith("---\n")
    assert "# Weekly Sync" in body


@pytest.mark.asyncio
async def test_verified_quotes_only_with_transcript() -> None:
    """## Verified Quotes body reflects whether the transcript was read."""
    client = _fake_client()

    with_transcript = await run_meeting_page(
        client,
        _meeting(),
        _classification_result(transcript_read=True),
        raw_summary_path="Raw/Processed/Uncategorized/id-1/summary.md",
        raw_transcript_path="Raw/Processed/Uncategorized/id-1/transcript.md",
        summary_sha256="a" * 64,
        transcript_sha256="b" * 64,
    )
    without_transcript = await run_meeting_page(
        client,
        _meeting(fireflies_id="id-2", source_id="fireflies:id-2"),
        _classification_result(transcript_read=False),
        raw_summary_path="Raw/Processed/Uncategorized/id-2/summary.md",
        raw_transcript_path="Raw/Processed/Uncategorized/id-2/transcript.md",
        summary_sha256="c" * 64,
        transcript_sha256="d" * 64,
    )

    assert "No quotes selected." in with_transcript.content
    assert "transcript was not read" in without_transcript.content
    assert with_transcript.frontmatter.processing_mode == "summary-and-transcript"
    assert without_transcript.frontmatter.processing_mode == "summary-only"


@pytest.mark.asyncio
async def test_raw_provenance_plain_paths_and_action_items_table() -> None:
    client = _fake_client()
    result = await run_meeting_page(
        client,
        _meeting(),
        _classification_result(transcript_read=True),
        raw_summary_path="Raw/Processed/Uncategorized/id-1/summary.md",
        raw_transcript_path="Raw/Processed/Uncategorized/id-1/transcript.md",
        summary_sha256="a" * 64,
        transcript_sha256="b" * 64,
    )

    assert "Raw summary: `Raw/Processed/Uncategorized/id-1/summary.md`" in result.content
    assert "[[Raw/Processed" not in result.content
    assert "| Follow up with legal | Bob | 2026-09-01 | Open | Medium |" in result.content


@pytest.mark.asyncio
async def test_filename_uses_original_tz_date() -> None:
    client = _fake_client()
    result = await run_meeting_page(
        client,
        _meeting(),
        _classification_result(transcript_read=True),
        raw_summary_path="Raw/Processed/Uncategorized/id-1/summary.md",
        raw_transcript_path="Raw/Processed/Uncategorized/id-1/transcript.md",
        summary_sha256="a" * 64,
        transcript_sha256="b" * 64,
        meeting_date_local="2026-08-19",  # e.g. meeting ran late in a UTC-X timezone
    )

    assert result.filename.startswith("2026-08-19 - Weekly Sync")
    assert result.vault_path == f"Wiki/Sources/Meetings/{result.filename}"


@pytest.mark.asyncio
async def test_unresolved_project_uses_unknown_placeholder() -> None:
    client = _fake_client()
    unresolved = ClassificationResult(
        classification=Classification(confidence="low"),
        processing_mode="summary-and-transcript",
        transcript_read=True,
        review_required=True,
    )
    result = await run_meeting_page(
        client,
        _meeting(),
        unresolved,
        raw_summary_path="Raw/Processed/Uncategorized/id-1/summary.md",
        raw_transcript_path="Raw/Processed/Uncategorized/id-1/transcript.md",
        summary_sha256="a" * 64,
        transcript_sha256="b" * 64,
    )

    assert result.frontmatter.primary_project == "Unknown"
    assert result.frontmatter.projects == ["Unknown"]
