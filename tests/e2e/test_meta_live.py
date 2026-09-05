"""Live end-to-end tests for MetaClient against the real Meta Model API.

Credential-gated: skips cleanly (not fail) when ``META_API_KEY`` is unset.
Mirrors the existing live-provider test convention (see
``tests/clients/test_anthropic_sdk_097.py::test_anthropic_live_smoke``).

.. warning::
    ``muse-spark-1.3-contributor`` is the Contributor tier: it grants Meta
    permission to **train on prompts and completions**. All prompts in
    this suite are deliberately synthetic — never send real user, company,
    or repository content through it.

Guards F015 (the feature's highest-risk finding): Muse Spark spends most
of its output budget on private reasoning — 199 of 210 completion tokens
(Chat Completions) and 142 of 153 output tokens (Responses) were
``reasoning_tokens`` for a reply whose visible text was the single word
``pong``. A low ``max_tokens`` therefore returns empty or truncated
visible text; ``test_live_chat_completion_returns_nonempty_visible_text``
exists to catch exactly that.
"""

import os
import sys

import pytest
from navconfig import config
from pydantic import BaseModel

from parrot.clients.factory import LLMFactory

pytestmark = [
    pytest.mark.live,
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not config.get("META_API_KEY"),
        reason="META_API_KEY not configured — live Meta tests skipped",
    ),
]

# Contributor tier — synthetic e2e prompts only (spec §7 gotcha 6).
E2E_MODEL = "meta:muse-spark-1.3-contributor"

# Reuse the shared calculator tool fixture (spec §4 Test Data / Fixtures)
# rather than defining a second one for this feature.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "examples", "clients", "smoke"))
from _runner import calculator  # noqa: E402


class _Fruit(BaseModel):
    """Minimal structured-output schema for the live structured-output test."""

    name: str
    color: str


class TestMetaLive:
    """Live coverage for MetaClient (FEAT-526 Module 5)."""

    async def test_live_chat_completion_returns_nonempty_visible_text(self):
        """Guards F015: reasoning tokens can swallow the whole output budget."""
        client = LLMFactory.create(E2E_MODEL, use_responses=False)
        async with client:
            result = await client.ask("Reply with exactly: pong")
        assert result.output.strip(), "empty visible text — reasoning likely consumed the output budget"

    async def test_live_tool_calling_roundtrip(self):
        """A full tool-calling round trip on the (default) Responses path.

        Muse Spark can (and, observed live, sometimes does) answer simple
        arithmetic without invoking a tool at all, so the prompt must make
        tool use mandatory rather than merely available — a system prompt
        instructing it to never compute mentally, per a documented pattern
        for steering tool-eager vs. tool-reluctant models.
        """
        client = LLMFactory.create(E2E_MODEL)
        client.register_tool(calculator)
        async with client:
            result = await client.ask(
                "What is 87361 + 45213? Compute it using the calculator " "tool and reply with only the final number.",
                system_prompt=(
                    "You MUST use the calculator tool for every arithmetic "
                    "computation, no matter how simple. Never compute "
                    "mentally — always call the tool first."
                ),
                use_tools=True,
            )
        assert result.output.strip(), "empty visible text after tool round trip"
        assert any(tc.name == "calculator" for tc in result.tool_calls), "calculator tool was never called"

    async def test_live_structured_output(self):
        """Structured output on the Chat Completions path (not yet
        supported on Responses — see MetaClient.ask() docstring)."""
        client = LLMFactory.create(E2E_MODEL, use_responses=False)
        async with client:
            result = await client.ask(
                "A banana is yellow. Return its name and color.",
                structured_output=_Fruit,
            )
        assert isinstance(result.structured_output, (dict, _Fruit))

    async def test_live_responses_completed(self):
        """The (default) Responses path returns completed non-empty text."""
        client = LLMFactory.create(E2E_MODEL)
        async with client:
            result = await client.ask("Reply with exactly: pong")
        assert result.output.strip(), "empty visible text — reasoning likely consumed the output budget"

    async def test_live_search_grounding_emits_web_search_call(self):
        """Search grounding surfaces a web_search_call output item."""
        client = LLMFactory.create(E2E_MODEL)
        async with client:
            result = await client.ask(
                "Search the web: what year is it right now?",
                search_grounding=True,
            )
        assert result.metadata.get("web_search_calls"), "no web_search_call output item surfaced for a grounded request"

    async def test_live_count_input_tokens(self):
        """count_input_tokens() is standalone and returns a positive int."""
        client = LLMFactory.create(E2E_MODEL)
        async with client:
            count = await client.count_input_tokens(input="Count these tokens.")
        assert isinstance(count, int)
        assert count > 0

    async def test_live_tool_choice_required_raises(self):
        """Meta supports only tool_choice='auto'; anything else is HTTP 400.

        ``ask()`` never exposes a raw ``tool_choice`` override (the base
        always forces ``"auto"`` when tools are prepared), so this
        constraint is exercised directly against the wire-protocol funnel.
        """
        client = LLMFactory.create(E2E_MODEL, use_responses=False)
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "calculator",
                    "description": "Evaluate an arithmetic expression.",
                    "parameters": {
                        "type": "object",
                        "properties": {"expression": {"type": "string"}},
                        "required": ["expression"],
                    },
                },
            }
        ]
        async with client:
            with pytest.raises(Exception):
                await client._chat_completion(
                    model=client._resolve_model(None),
                    messages=[{"role": "user", "content": "What is 2+2?"}],
                    use_tools=True,
                    tools=tools,
                    tool_choice="required",
                )
