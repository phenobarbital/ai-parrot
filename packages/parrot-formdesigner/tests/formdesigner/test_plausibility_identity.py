"""Effective-model identity tests for plausibility reports (FEAT-732)."""

import json

import pytest

from parrot_formdesigner.core.llm_validation import LLMValidationConfig
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.plausibility import (
    AnswerPlausibilityChecker,
    PlausibilityBatch,
    PlausibilityBlocked,
)


class _Client:
    """Fake whose response attributes are configurable per test."""

    def __init__(self, batch: PlausibilityBatch, **attrs: object) -> None:
        self.batch = batch
        self.attrs = attrs

    async def ask(self, prompt: str, **kwargs: object) -> object:
        """Return an AIMessage-shaped response with configured identity attributes."""
        return type("Msg", (), {"structured_output": self.batch, "output": self.batch, **self.attrs})()


def _form(config: LLMValidationConfig) -> FormSchema:
    """Build a minimal form with one LLM-enabled text field."""
    return FormSchema(
        form_id="f",
        title="F",
        sections=[
            FormSection(
                section_id="s",
                fields=[FormField(field_id="name", field_type=FieldType.TEXT, label="Name")],
            )
        ],
        llm_validation=config,
    )


def _batch() -> PlausibilityBatch:
    """Build one deterministic verdict for the test form."""
    return PlausibilityBatch.model_validate(
        {"items": [{"field_id": "name", "plausible": True, "confidence": 0.9, "reason": "ok"}]}
    )


async def test_resolved_model_from_response() -> None:
    """Record the effective response model without changing the requested model."""
    config = LLMValidationConfig(enabled=True, model=None)
    client = _Client(_batch(), model="x", provider="fake", usage={"total_tokens": 3})

    report = await AnswerPlausibilityChecker(client, config=config).check(_form(config), {"name": "Ann"}, locale="en")

    assert report.status == "ok"
    assert report.model is None
    assert report.resolved_model == "x"
    assert report.provider == "fake"
    assert report.usage == {"total_tokens": 3}


async def test_model_field_meaning_unchanged() -> None:
    """Keep the configured model in the existing model field."""
    config = LLMValidationConfig(enabled=True, model="y")
    client = _Client(_batch(), model="x", provider="fake", usage={})

    report = await AnswerPlausibilityChecker(client, config=config).check(_form(config), {"name": "Ann"}, locale="en")

    assert report.status == "ok"
    assert report.model == "y"
    assert report.resolved_model == "x"


async def test_ok_without_model_skips_under_skip() -> None:
    """Route a parseable unattributed response through skip error handling."""
    config = LLMValidationConfig(enabled=True, on_error="skip")

    report = await AnswerPlausibilityChecker(_Client(_batch(), provider="fake"), config=config).check(
        _form(config), {"name": "Ann"}, locale="en"
    )

    assert report.status == "skipped"
    assert report.reason == "llm_error: unidentified_model"
    assert report.resolved_model is None


async def test_ok_without_model_blocks_under_block() -> None:
    """Route a parseable unattributed response through block error handling."""
    config = LLMValidationConfig(enabled=True, on_error="block")

    with pytest.raises(PlausibilityBlocked, match="llm_error: unidentified_model"):
        await AnswerPlausibilityChecker(_Client(_batch(), provider="fake"), config=config).check(
            _form(config), {"name": "Ann"}, locale="en"
        )


async def test_no_call_ok_unchanged() -> None:
    """Leave the no-eligible-fields success path unattributed and reasonless."""
    config = LLMValidationConfig(enabled=False)

    report = await AnswerPlausibilityChecker(_Client(_batch()), config=config).check(
        _form(config), {"name": "Ann"}, locale="en"
    )

    assert report.status == "ok"
    assert report.resolved_model is None
    assert report.reason is None


async def test_usage_is_json_safe() -> None:
    """Normalize Pydantic usage objects into a JSON-safe plain dictionary."""
    config = LLMValidationConfig(enabled=True)
    usage_model = PlausibilityBatch(items=[])
    client = _Client(_batch(), model="x", provider="fake", usage=usage_model)

    report = await AnswerPlausibilityChecker(client, config=config).check(_form(config), {"name": "Ann"}, locale="en")

    assert report.usage == {"items": []}
    json.dumps(report.model_dump(mode="json"))
