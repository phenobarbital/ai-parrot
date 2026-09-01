"""Unit tests for the classification node (FEAT-481, spec Module 7 /
TASK-2665): summary-first, confidence, transcript fallback, §15.5 routing.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from parrot.flows.wiki_ingest.models import Classification
from parrot.flows.wiki_ingest.nodes import classify
from parrot.flows.wiki_ingest.nodes.fetch_gate import GatedMeeting


def _meeting(title: str = "Weekly Sync") -> GatedMeeting:
    return GatedMeeting(
        fireflies_id="id-1",
        source_id="fireflies:id-1",
        title=title,
        meeting_date="2026-08-20",
        outcome="fetch",
        transcript_text="Full transcript text.",
        summary_text="Fireflies summary text.",
    )


class _FakeInvokeResult:
    def __init__(self, output: Any) -> None:
        self.output = output


def _fake_client(*outputs: Classification) -> AsyncMock:
    client = AsyncMock()
    client.invoke = AsyncMock(side_effect=[_FakeInvokeResult(o) for o in outputs])
    return client


@pytest.mark.asyncio
async def test_summary_first_no_transcript_when_high_confidence() -> None:
    """High confidence on the summary-only pass never reads the transcript."""
    client = _fake_client(Classification(confidence="high", primary_project="Acme"))

    result = await classify.run_classify(client, _meeting())

    assert client.invoke.call_count == 1
    prompt_used = client.invoke.call_args.args[0]
    assert "Full transcript text." not in prompt_used
    assert result.processing_mode == "summary-only"
    assert result.transcript_read is False
    assert result.review_required is False


@pytest.mark.asyncio
async def test_medium_confidence_triggers_transcript_fallback() -> None:
    """A medium-confidence summary-only pass triggers a second,
    transcript-informed classification (§15.4)."""
    client = _fake_client(
        Classification(confidence="medium", primary_project="Acme"),
        Classification(confidence="high", primary_project="Acme"),
    )

    result = await classify.run_classify(client, _meeting())

    assert client.invoke.call_count == 2
    second_prompt = client.invoke.call_args_list[1].args[0]
    assert "Full transcript text." in second_prompt
    assert result.processing_mode == "summary-and-transcript"
    assert result.transcript_read is True
    assert result.classification.confidence == "high"


@pytest.mark.asyncio
async def test_low_confidence_routes_uncategorized() -> None:
    """Low confidence even after the transcript fallback sets
    review_required and produces a review-item draft (§15.5) — no
    project update is implied by the result."""
    client = _fake_client(
        Classification(confidence="low"),
        Classification(confidence="low", transcript_fallback_reason="ambiguous ownership"),
    )

    result = await classify.run_classify(client, _meeting())

    assert result.review_required is True
    assert result.review_item is not None
    assert result.review_item.source_id == "fireflies:id-1"
    assert result.review_item.review_type == "classification"


@pytest.mark.asyncio
async def test_high_impact_keyword_forces_transcript_even_on_high_confidence() -> None:
    """§15.4 — HR/legal/security/etc. content always reads the
    transcript, even if the LLM would report high confidence."""
    client = _fake_client(Classification(confidence="high", primary_project="Acme"))

    result = await classify.run_classify(client, _meeting(title="Legal Review of Contract"))

    assert client.invoke.call_count == 1  # confidence was high — no second pass needed
    prompt_used = client.invoke.call_args.args[0]
    assert "Full transcript text." in prompt_used
    assert result.processing_mode == "summary-and-transcript"
    assert result.transcript_read is True


@pytest.mark.asyncio
async def test_force_transcript_flag_reads_transcript_immediately() -> None:
    client = _fake_client(Classification(confidence="high", primary_project="Acme"))

    result = await classify.run_classify(client, _meeting(), force_transcript=True)

    assert result.transcript_read is True
    assert client.invoke.call_count == 1


@pytest.mark.asyncio
async def test_existing_context_included_in_prompt() -> None:
    client = _fake_client(Classification(confidence="high", primary_project="Acme"))
    context = classify.ExistingContext(candidate_projects=["Acme Rollout"])

    await classify.run_classify(client, _meeting(), context=context)

    prompt_used = client.invoke.call_args.args[0]
    assert "Acme Rollout" in prompt_used
