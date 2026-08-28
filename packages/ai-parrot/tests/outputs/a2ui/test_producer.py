"""Unit tests for the LLM envelope producer (TASK-1737 / Module 9, FEAT-470 TASK-2547).

v1.0 wire throughout (spec FEAT-470): ``Component`` props are top-level (no legacy
``properties`` nesting), every valid fixture carries a component with ``id="root"``,
and the catalog registration import is the current path (``catalog.parrot`` — moved
from the retired ``catalog.components`` in TASK-2539).
"""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

# Register the v1.0 parrot catalog so validation resolves real components
# (moved from `parrot.outputs.a2ui.catalog.components` in TASK-2539).
import parrot.outputs.a2ui.catalog.parrot  # noqa: F401
import pytest
from parrot.outputs.a2ui.catalog import DEFAULT_CATALOG_ID
from parrot.outputs.a2ui.catalog.base import CatalogValidationError
from parrot.outputs.a2ui.models import Action, Component, CreateSurface, EventAction
from parrot.outputs.a2ui.producer import (
    DEFAULT_MAX_ATTEMPTS,
    ProducerResult,
    _repair_prompt,
    generate_envelope,
)
from parrot.outputs.a2ui.serialization import serialize


class FakeClient:
    """Scripted client: each ask() returns the next queued output (in order).

    Records every ``system_prompt``/``structured_output`` it was called with so
    tests can assert on what ``generate_envelope`` actually sent.
    """

    def __init__(self, outputs, response_text="plain answer"):
        self._outputs = list(outputs)
        self.response_text = response_text
        self.prompts: list[str] = []
        self.system_prompts: list[str] = []
        self.structured_outputs: list = []

    async def ask(self, prompt, *, model="", system_prompt=None, structured_output=None):
        self.prompts.append(prompt)
        self.system_prompts.append(system_prompt)
        self.structured_outputs.append(structured_output)
        output = self._outputs.pop(0) if self._outputs else self.response_text
        return SimpleNamespace(output=output, response=self.response_text)


def _valid_envelope() -> CreateSurface:
    return CreateSurface(
        surfaceId="main",
        catalogId=DEFAULT_CATALOG_ID,
        components=[Component(id="root", component="InfoCard", title="Hi")],
    )


def _action_envelope() -> CreateSurface:
    """A component carrying a non-null ``action`` — rejected for LLM origin."""
    return CreateSurface(
        surfaceId="main",
        catalogId=DEFAULT_CATALOG_ID,
        components=[
            Component(
                id="root",
                component="Button",
                child="lbl",
                action=Action(event=EventAction(name="submit")),
            ),
            Component(id="lbl", component="Text", text="Go"),
        ],
    )


def _bad_envelope() -> CreateSurface:
    """Carries a component the catalog does not know (``Bogus``), plus a valid root."""
    return CreateSurface(
        surfaceId="m",
        catalogId=DEFAULT_CATALOG_ID,
        components=[
            Component(id="root", component="Column", children=["b0"]),
            Component(id="b0", component="Bogus"),
        ],
    )


class TestGenerateEnvelope:
    pytestmark = pytest.mark.asyncio

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
        client = FakeClient([_bad_envelope(), _valid_envelope()])
        result = await generate_envelope(client, "make a card", model="m")
        assert result.degraded is False
        assert result.attempts == 2
        # The retry prompt carries validation error context.
        assert "rejected" in client.prompts[1].lower()
        assert "Bogus" in client.prompts[1]

    async def test_producer_retry_bounded_then_degrades(self):
        bad = _bad_envelope()
        client = FakeClient([bad, bad, bad, bad, bad])
        result = await generate_envelope(client, "make a card", model="m", max_attempts=3)
        assert result.degraded is True
        assert result.attempts == 3
        assert len(client.prompts) == 3  # bounded — no more than max_attempts
        assert result.envelope is None  # invalid payload never returned (G1)
        assert result.text == "plain answer"
        assert "Bogus" in result.failure_reason

    async def test_llm_envelope_rejects_action(self):
        client = FakeClient([_action_envelope(), _action_envelope()])
        result = await generate_envelope(client, "make a button", model="m", max_attempts=2)
        assert result.degraded is True
        assert result.envelope is None
        assert "ACTION_NOT_ALLOWED_FOR_LLM" in result.failure_reason

    async def test_raw_text_fallback_counts_as_failed_attempt(self):
        # Client degraded to raw text (str) on first call, then a valid envelope.
        client = FakeClient(["I could not produce JSON", _valid_envelope()])
        result = await generate_envelope(client, "make a card", model="m")
        assert result.degraded is False
        assert result.attempts == 2

    async def test_accepts_bare_dict_output(self):
        # The realistic structured_output(output_type=CreateSurface) shape: a
        # bare dict of CreateSurface fields, no wire envelope wrapper.
        bare = _valid_envelope().model_dump(by_alias=True, mode="json")
        client = FakeClient([bare])
        result = await generate_envelope(client, "make a card", model="m")
        assert result.degraded is False
        assert result.envelope is not None

    async def test_accepts_envelope_by_key_dict_output(self):
        # Also accepted: the full wire envelope-by-key dict, e.g. if a caller
        # round-trips through serialize() before handing it back here.
        enveloped = serialize(_valid_envelope())
        assert set(enveloped) == {"version", "createSurface"}
        client = FakeClient([enveloped])
        result = await generate_envelope(client, "make a card", model="m")
        assert result.degraded is False
        assert result.envelope is not None

    async def test_default_budget_is_spk3_number(self):
        assert DEFAULT_MAX_ATTEMPTS == 3

    async def test_catalog_param_is_effective_as_surface_catalog_id(self):
        """The (formerly no-op) ``catalog=`` kwarg now drives resolution.

        A component with NO ``catalogId`` of its own only resolves (and passes
        catalog validation) when ``catalog=`` supplies the surface default —
        omitting it must fail with ``CATALOG_UNRESOLVED``.
        """
        bare = CreateSurface(
            surfaceId="main",
            components=[Component(id="root", component="InfoCard", title="Hi")],
        )
        client_without = FakeClient([bare])
        result_without = await generate_envelope(client_without, "make a card", model="m", max_attempts=1)
        assert result_without.degraded is True
        assert "CATALOG_UNRESOLVED" in result_without.failure_reason

        client_with = FakeClient([bare.model_copy(deep=True)])
        result_with = await generate_envelope(
            client_with, "make a card", model="m", max_attempts=1, catalog=DEFAULT_CATALOG_ID
        )
        assert result_with.degraded is False
        assert result_with.envelope is not None


class TestProducerUsesV1StructuredOutput:
    """TASK-2547 Test Specification: ``test_producer_uses_v1_structured_output``."""

    pytestmark = pytest.mark.asyncio

    async def test_structured_output_targets_v1_create_surface(self):
        client = FakeClient([_valid_envelope()])
        await generate_envelope(client, "make a card", model="m")
        assert len(client.structured_outputs) == 1
        config = client.structured_outputs[0]
        assert config is not None
        assert config.output_type is CreateSurface

    async def test_system_prompt_covers_basic_and_parrot_catalogs(self):
        client = FakeClient([_valid_envelope()])
        await generate_envelope(client, "make a card", model="m")
        system = client.system_prompts[0]
        # Basic Catalog primitive (Text) and Parrot catalog component (InfoCard)
        # must both be present — catalog_instructions() aggregates both registries.
        assert "Text:" in system
        assert "InfoCard:" in system

    async def test_system_prompt_states_the_root_rule(self):
        client = FakeClient([_valid_envelope()])
        await generate_envelope(client, "make a card", model="m")
        system = client.system_prompts[0]
        assert "root" in system.lower()


class TestRepairPromptIncludesCode:
    """TASK-2547 Test Specification: ``test_repair_prompt_includes_code``."""

    def test_repair_prompt_surfaces_code_and_path(self):
        error = CatalogValidationError(
            "Component 'Bogus' (id='b0') is not registered.",
            issues=[
                {"code": "UNKNOWN_COMPONENT", "message": "Bogus is unknown.", "path": "b0"},
            ],
        )
        prompt = _repair_prompt("make a card", error, None)
        assert "UNKNOWN_COMPONENT" in prompt
        assert "/components/b0" in prompt

    def test_repair_prompt_surfaces_every_issue(self):
        error = CatalogValidationError(
            "multiple problems",
            issues=[
                {"code": "MISSING_ROOT", "message": "No root.", "path": None},
                {"code": "DUPLICATE_ID", "message": "dup id 'x'.", "path": "x"},
            ],
        )
        prompt = _repair_prompt("make a card", error, None)
        assert "MISSING_ROOT" in prompt
        assert "DUPLICATE_ID" in prompt
        assert "/components/x" in prompt

    def test_repair_prompt_still_accepts_a_plain_string(self):
        # Schema-violation / raw-text failures pass a plain error string, not
        # a CatalogValidationError — must keep working unchanged.
        prompt = _repair_prompt("make a card", "schema violation: bad json", None)
        assert "schema violation: bad json" in prompt


#: 20 display-UI prompts for the Module 9 spike (spec §4 Integration Tests).
_SPIKE_PROMPTS: ClassVar[list[str]] = [
    "Show a welcome card titled 'Welcome' with a short greeting body.",
    "Display a KPI card for Monthly Revenue at $42,000 with a +5% trend.",
    "Show a bar chart of quarterly sales with x=quarter and y=[revenue].",
    "Render a data table of 3 employees with columns Name and Department.",
    "Show an info card summarizing today's weather: sunny, 25C.",
    "Display a card with a title 'Status' and a body describing system health.",
    "Show a line chart comparing 2024 vs 2025 monthly signups.",
    "Render a table of the top 5 products by units sold.",
    "Show a KPI card for Active Users at 1,204 with no trend.",
    "Display an info card titled 'Release Notes' with a short changelog body.",
    "Show a bar chart of support tickets opened per day this week.",
    "Render a data table of 4 invoices with columns Invoice and Amount.",
    "Show a card summarizing the current sprint goal.",
    "Display a KPI card for Churn Rate at 2.1% with a down trend.",
    "Show a pie-like chart of traffic sources (use a supported chart type).",
    "Render a table listing 3 open incidents with columns Id and Severity.",
    "Show an info card titled 'Reminder' about an upcoming deadline.",
    "Display a KPI card for Average Response Time at 320ms.",
    "Show a chart of daily active users over the last 7 days.",
    "Render a table of 3 team members with columns Name and Role.",
]

#: ``artifacts/logs/feat-470-producer-rate.md`` — repo root relative to this file.
_RATE_LOG_PATH = Path(__file__).resolve().parents[5] / "artifacts" / "logs" / "feat-470-producer-rate.md"


def _append_rate_log(successes: int, total: int, rate: float) -> None:
    """Append the live spike result to the evidence log (sync — run off-thread)."""
    with open(_RATE_LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write(f"\n## Live run — {successes}/{total} first-shot catalog-valid ({rate:.0%})\n")


@pytest.mark.real_llm
class TestE2ELLMProducerFirstShotRate:
    """TASK-2547 Test Specification: ``test_e2e_llm_producer_first_shot_rate``.

    Spec §4 Integration Tests: 20 prompts -> catalog-valid first-shot rate >= 85%,
    recorded in ``artifacts/logs/``. Requires a live LLM provider — skipped unless
    ``PARROT_TEST_REAL_LLM=1`` is set (repo convention, see ``tests/conftest.py``).
    """

    pytestmark = pytest.mark.asyncio

    async def test_first_shot_rate_at_least_85_percent(self):
        from parrot.clients.claude import AnthropicClient

        client = AnthropicClient()
        successes = 0
        total = len(_SPIKE_PROMPTS)
        for prompt in _SPIKE_PROMPTS:
            result = await generate_envelope(client, prompt, max_attempts=1)
            if not result.degraded:
                successes += 1
        rate = successes / total

        await asyncio.to_thread(_append_rate_log, successes, total, rate)

        assert rate >= 0.85, f"First-shot catalog-valid rate {rate:.0%} < 85% ({successes}/{total})"
