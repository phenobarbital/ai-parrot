"""FEAT-653 TASK-4249 — LLM value refiner."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from parrot_formdesigner.audio.value_refiner import LLMValueRefiner, RefinedValue
from parrot_formdesigner.core.types import FieldType

KW = dict(
    transcript="john at gmail",
    candidate="john@gmail",
    field_type=FieldType.EMAIL,
    label="Email",
    locale="en",
    today="2026-10-12",
    timezone="America/New_York",
)


@pytest.mark.parametrize(
    "structured",
    [
        RefinedValue(value="john@gmail.com", confidence=0.9),
        {"value": "john@gmail.com", "confidence": 0.9},
        json.dumps({"value": "john@gmail.com", "confidence": 0.9}),
    ],
)
async def test_parses_structured_output_shapes(structured) -> None:
    client = AsyncMock()
    client.ask.return_value = SimpleNamespace(structured_output=structured, output=None)
    res = await LLMValueRefiner(client).refine(**KW)
    assert res == RefinedValue(value="john@gmail.com", confidence=0.9)
    prompt = client.ask.call_args.args[0]
    assert "john at gmail" in prompt and "lowercase email" in prompt
    assert client.ask.call_args.kwargs["structured_output"] is RefinedValue


async def test_falls_back_to_output_attribute() -> None:
    client = AsyncMock()
    client.ask.return_value = SimpleNamespace(structured_output=None, output={"value": None, "confidence": 0.2})
    assert await LLMValueRefiner(client).refine(**KW) == RefinedValue(value=None, confidence=0.2)


async def test_failure_returns_none() -> None:
    client = AsyncMock()
    client.ask.side_effect = RuntimeError("boom")
    assert await LLMValueRefiner(client).refine(**KW) is None


async def test_garbage_returns_none() -> None:
    client = AsyncMock()
    client.ask.return_value = SimpleNamespace(structured_output="not json", output=None)
    assert await LLMValueRefiner(client).refine(**KW) is None
    client.ask.return_value = SimpleNamespace(structured_output=None, output=None)
    assert await LLMValueRefiner(client).refine(**KW) is None


async def test_confidence_clamped() -> None:
    client = AsyncMock()
    client.ask.return_value = SimpleNamespace(structured_output={"value": "x", "confidence": 1.7}, output=None)
    res = await LLMValueRefiner(client).refine(**KW)
    assert res is not None and res.confidence == 1.0


async def test_prompt_carries_only_expected_keys() -> None:
    client = AsyncMock()
    client.ask.return_value = SimpleNamespace(structured_output={"value": None}, output=None)
    await LLMValueRefiner(client).refine(**{**KW, "timezone": None})
    payload = json.loads(client.ask.call_args.args[0])
    assert set(payload) == {
        "field_type",
        "label",
        "locale",
        "timezone",
        "today",
        "transcript",
        "rules_candidate",
        "required_format",
    }
    assert payload["timezone"] == "unknown"
