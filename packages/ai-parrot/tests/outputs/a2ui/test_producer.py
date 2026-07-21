"""Unit tests for the LLM envelope producer (TASK-1737 / Module 9)."""

from types import SimpleNamespace

import pytest

# Register the v1 catalog so validation resolves real components.
import parrot.outputs.a2ui.catalog.components  # noqa: F401
from parrot.outputs.a2ui.models import Component, CreateSurface
from parrot.outputs.a2ui.producer import (
    DEFAULT_MAX_ATTEMPTS,
    ProducerResult,
    generate_envelope,
)
from parrot.outputs.a2ui.serialization import serialize

pytestmark = pytest.mark.asyncio


class FakeClient:
    """Scripted client: each ask() returns the next queued output (in order)."""

    def __init__(self, outputs, response_text="plain answer"):
        self._outputs = list(outputs)
        self.response_text = response_text
        self.prompts: list[str] = []

    async def ask(self, prompt, *, model="", system_prompt=None, structured_output=None):
        self.prompts.append(prompt)
        output = self._outputs.pop(0) if self._outputs else self.response_text
        return SimpleNamespace(output=output, response=self.response_text)


def _valid_envelope() -> CreateSurface:
    return CreateSurface(
        surfaceId="main",
        catalogId="https://parrot.dev/catalogs/v1",
        components=[Component(id="b0", component="Card", properties={"title": "Hi"})],
    )


def _requires_actions_envelope() -> CreateSurface:
    return CreateSurface(
        surfaceId="main",
        catalogId="https://parrot.dev/catalogs/v1",
        components=[
            Component(
                id="b0",
                component="Form",
                properties={"fields": [{"name": "e", "input": "text"}], "submit": {"action": "s"}},
            )
        ],
    )


class TestGenerateEnvelope:
    async def test_valid_envelope_first_attempt(self):
        client = FakeClient([_valid_envelope()])
        result = await generate_envelope(client, "make a card", model="m")
        assert isinstance(result, ProducerResult)
        assert result.degraded is False
        assert result.attempts == 1
        assert result.envelope is not None
        assert len(client.prompts) == 1

    async def test_retry_reprompts_with_error_context(self):
        # First: unknown-component envelope; second: valid.
        bad = CreateSurface(
            surfaceId="m", catalogId="c",
            components=[Component(id="b0", component="Bogus")],
        )
        client = FakeClient([bad, _valid_envelope()])
        result = await generate_envelope(client, "make a card", model="m")
        assert result.degraded is False
        assert result.attempts == 2
        # The retry prompt carries validation error context.
        assert "rejected" in client.prompts[1].lower()
        assert "Bogus" in client.prompts[1]

    async def test_producer_retry_bounded_then_degrades(self):
        bad = CreateSurface(
            surfaceId="m", catalogId="c",
            components=[Component(id="b0", component="Bogus")],
        )
        client = FakeClient([bad, bad, bad, bad, bad])
        result = await generate_envelope(client, "make a card", model="m", max_attempts=3)
        assert result.degraded is True
        assert result.attempts == 3
        assert len(client.prompts) == 3  # bounded — no more than max_attempts
        assert result.envelope is None  # invalid payload never returned (G1)
        assert result.text == "plain answer"
        assert "Bogus" in result.failure_reason

    async def test_llm_envelope_rejects_requires_actions(self):
        client = FakeClient([_requires_actions_envelope(), _requires_actions_envelope()])
        result = await generate_envelope(client, "make a form", model="m", max_attempts=2)
        assert result.degraded is True
        assert result.envelope is None
        assert "Form" in result.failure_reason

    async def test_raw_text_fallback_counts_as_failed_attempt(self):
        # Client degraded to raw text (str) on first call, then a valid envelope.
        client = FakeClient(["I could not produce JSON", _valid_envelope()])
        result = await generate_envelope(client, "make a card", model="m")
        assert result.degraded is False
        assert result.attempts == 2

    async def test_accepts_dict_output(self):
        client = FakeClient([serialize(_valid_envelope())])  # dict, not CreateSurface
        result = await generate_envelope(client, "make a card", model="m")
        assert result.degraded is False
        assert result.envelope is not None

    async def test_default_budget_is_spk3_number(self):
        assert DEFAULT_MAX_ATTEMPTS == 3
