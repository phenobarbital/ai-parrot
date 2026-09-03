"""Live ``real_llm`` verification for OpenAI reasoning-model support.

Hotfix ``openai-max-completion-tokens`` (no Jira ticket, FEAT-466) — see
``sdd/specs/openai-max-completion-tokens.spec.md`` §4 Integration Tests.

These tests make real calls against the OpenAI API and prove the exact
calls that returned a 400 on ``main`` before this hotfix now succeed. They
are skipped unless both ``PARROT_TEST_REAL_LLM=1`` (repo-wide gate,
``packages/ai-parrot/tests/conftest.py``) and ``OPENAI_API_KEY`` are set.
"""
import os

import pytest
from parrot.clients.factory import LLMFactory
from pydantic import BaseModel

pytestmark = [
    pytest.mark.real_llm,
    pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set"),
]


class _Verdict(BaseModel):
    """Minimal structured-output fixture model for invoke() coverage."""

    answer: str


@pytest.mark.asyncio
async def test_default_openai_client_ask_succeeds():
    """The exact call that 400s on main: the default OpenAI client's ask()."""
    client = LLMFactory.create("openai")
    msg = await client.ask("Say OK.")
    assert msg.content.strip()


@pytest.mark.asyncio
async def test_gpt5_ask_succeeds():
    """gpt-5-mini via ask() returns non-empty content."""
    client = LLMFactory.create("openai:gpt-5-mini")
    msg = await client.ask("Say OK.")
    assert msg.content.strip()


@pytest.mark.asyncio
async def test_gpt5_ask_stream_succeeds():
    """gpt-5-mini via ask_stream() — each kwargs-assembly path is covered."""
    client = LLMFactory.create("openai:gpt-5-mini")
    chunks = []
    async for chunk in client.ask_stream("Say OK."):
        if isinstance(chunk, str):
            chunks.append(chunk)
    assert "".join(chunks).strip()


@pytest.mark.asyncio
async def test_gpt5_invoke_structured_succeeds():
    """invoke() with a Pydantic output_type returns the typed model."""
    client = LLMFactory.create("openai:gpt-5-mini")
    result = await client.invoke(
        "Answer with a short verdict.", output_type=_Verdict
    )
    assert isinstance(result.output, _Verdict)


@pytest.mark.asyncio
async def test_gpt41_still_succeeds():
    """Regression guard: the non-reasoning path is untouched — temperature
    is still sent and accepted.

    Uses a non-zero temperature deliberately: ``OpenAIClient.ask()`` has a
    pre-existing, unrelated ``if temperature:`` truthiness check that drops
    an explicit ``temperature=0.0`` before it is ever added to the request
    args, on every model — not something this hotfix touches (see
    HOTFIX-openai-max-completion-tokens-2's Completion Note). A non-zero
    value is what actually exercises "temperature reaches the wire and is
    accepted" for gpt-4.1.
    """
    client = LLMFactory.create("openai:gpt-4.1")
    msg = await client.ask("Say OK.", temperature=0.7)
    assert msg.content.strip()
