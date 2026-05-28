"""Tests for parrot.knowledge.pageindex.ingest.TwoStepIngester."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.knowledge.pageindex.ingest import IngestedMarkdown, TwoStepIngester


def _adapter(*, ask_return: str = "", structured: IngestedMarkdown | dict | None = None):
    a = MagicMock()
    a.client = MagicMock()
    a.model = "heavy-model"
    a.ask = AsyncMock(return_value=ask_return)
    a.ask_structured = AsyncMock(return_value=structured)
    return a


@pytest.mark.asyncio
async def test_two_step_ingest_returns_model():
    light = _adapter(ask_return="step-1 prose analysis")
    heavy = _adapter(
        structured=IngestedMarkdown(
            title="My Doc",
            summary="A summary.",
            markdown="# My Doc\n\n## Intro\nHello.",
        ),
    )
    ingester = TwoStepIngester(adapter=heavy, lightweight_adapter=light)

    result = await ingester.ingest("Some raw content", hint="documentation")

    assert isinstance(result, IngestedMarkdown)
    assert result.title == "My Doc"
    light.ask.assert_awaited_once()
    heavy.ask_structured.assert_awaited_once()


@pytest.mark.asyncio
async def test_step1_uses_light_adapter_not_heavy():
    light = _adapter(ask_return="cot analysis")
    heavy = _adapter(structured=IngestedMarkdown(title="t", summary="s", markdown="# t"))
    ingester = TwoStepIngester(adapter=heavy, lightweight_adapter=light)

    await ingester.ingest("payload")

    assert light.ask.await_count == 1
    assert heavy.ask.await_count == 0
    assert heavy.ask_structured.await_count == 1


@pytest.mark.asyncio
async def test_falls_back_to_single_adapter_when_no_light():
    heavy = _adapter(
        ask_return="analysis",
        structured=IngestedMarkdown(title="t", summary="s", markdown="# t"),
    )
    ingester = TwoStepIngester(adapter=heavy)
    await ingester.ingest("payload")
    assert heavy.ask.await_count == 1
    assert heavy.ask_structured.await_count == 1


@pytest.mark.asyncio
async def test_step2_dict_response_is_validated():
    light = _adapter(ask_return="analysis")
    heavy = _adapter(structured={"title": "t", "summary": "s", "markdown": "# t"})
    ingester = TwoStepIngester(adapter=heavy, lightweight_adapter=light)
    result = await ingester.ingest("payload")
    assert isinstance(result, IngestedMarkdown)
    assert result.title == "t"


@pytest.mark.asyncio
async def test_step2_unexpected_payload_raises():
    light = _adapter(ask_return="analysis")
    heavy = _adapter(structured="not-a-model")
    ingester = TwoStepIngester(adapter=heavy, lightweight_adapter=light)
    with pytest.raises(ValueError):
        await ingester.ingest("payload")


@pytest.mark.asyncio
async def test_step1_content_truncated_to_8000_chars():
    light = _adapter(ask_return="analysis")
    heavy = _adapter(structured=IngestedMarkdown(title="t", summary="s", markdown="# t"))
    ingester = TwoStepIngester(adapter=heavy, lightweight_adapter=light)

    huge = "x" * 12000
    await ingester.ingest(huge)
    prompt_arg = light.ask.call_args.kwargs["prompt"]
    # The prompt embeds {content}; only the first 8000 characters of the raw
    # input should appear inside its <<< ... >>> block.
    inside = prompt_arg.split("<<<", 1)[1].split(">>>", 1)[0]
    assert len(inside) == 8000
