"""Focused budget-hook coverage for ``GoogleGenAIClient.ask``."""

from __future__ import annotations

import importlib
import pathlib
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import parrot.clients.google as google_package

_GOOGLE_SOURCE = pathlib.Path(__file__).resolve().parents[2] / "src" / "parrot" / "clients" / "google"
google_package.__path__.insert(0, str(_GOOGLE_SOURCE))
sys.modules.pop("parrot.clients.google.client", None)
_client_module = importlib.import_module("parrot.clients.google.client")
_budget_module = importlib.import_module("parrot.clients.google.budget")
GoogleGenAIClient = _client_module.GoogleGenAIClient
GenerationBudget = _budget_module.GenerationBudget
GenerationBudgetExceeded = _budget_module.GenerationBudgetExceeded


def _response(*, finish_reason: str | None = None, text: str = "done") -> MagicMock:
    """Build the minimal Gemini response shape consumed by ``ask``."""
    response = MagicMock()
    response.candidates = [MagicMock()]
    response.candidates[0].finish_reason = MagicMock(name=finish_reason) if finish_reason else None
    part = MagicMock()
    part.function_call = None
    part.text = text
    part.executable_code = None
    part.code_execution_result = None
    part.inline_data = None
    part.as_image = None
    part.thought = False
    response.candidates[0].content.parts = [part]
    response.usage_metadata = None
    return response


async def _client(*, budget: GenerationBudget | None, responses: list[object]) -> tuple[GoogleGenAIClient, MagicMock]:
    """Create a client whose chat transport records only synthetic sends."""
    client = GoogleGenAIClient(api_key="test-key", generation_budget=budget)
    client.logger = MagicMock()
    transport = MagicMock()
    transport.send_message = AsyncMock(side_effect=responses)
    sdk_client = MagicMock()
    sdk_client.aio.chats.create.return_value = transport
    client.get_client = AsyncMock(return_value=sdk_client)
    return client, transport


@pytest.mark.asyncio
async def test_budget_exhaustion_prevents_retry_and_fallback_send() -> None:
    """A failed initial send consumes its reservation; retry cannot dispatch again."""
    budget = GenerationBudget(max_calls=1, max_output_tokens=512, max_request_bytes=16384, timeout_s=60)
    client, transport = await _client(budget=budget, responses=[RuntimeError("503 unavailable")])
    client._should_use_fallback = MagicMock(return_value=True)

    with pytest.raises(GenerationBudgetExceeded) as excinfo:
        await client.ask("retry me", max_retries=2)

    assert excinfo.value.reason_code == "max_calls"
    assert transport.send_message.await_count == 1
    assert budget.calls_used == 1
    client._should_use_fallback.assert_called_once()


@pytest.mark.asyncio
async def test_budgeted_send_disables_afc_clamps_tokens_and_counts_full_payload() -> None:
    """Budgeted calls use one AFC-disabled, ceiling-clamped, fully rendered request."""
    budget = GenerationBudget(max_calls=2, max_output_tokens=512, max_request_bytes=16384, timeout_s=60)
    client, transport = await _client(budget=budget, responses=[_response(text="budgeted")])

    message = await client.ask(
        "new prompt",
        max_tokens=4096,
        system_prompt="system context",
        history=[SimpleNamespace(role="user", content="history context")],
    )

    sent_config = transport.send_message.await_args.kwargs["config"]
    assert message.output == "budgeted"
    assert budget.calls_used == 1
    assert budget.bytes_used > len("new prompt".encode("utf-8"))
    assert sent_config.max_output_tokens == 512
    assert sent_config.automatic_function_calling.disable is True


@pytest.mark.asyncio
async def test_no_budget_retains_retry_behavior() -> None:
    """Legacy callers without the optional hook retain their wrapper retry."""
    client, transport = await _client(budget=None, responses=[RuntimeError("temporary"), _response(text="recovered")])

    message = await client.ask("retry me", max_retries=2)

    assert message.output == "recovered"
    assert transport.send_message.await_count == 2


@pytest.mark.asyncio
async def test_budgeted_ask_rejects_excluded_modes_before_dispatch() -> None:
    """Media, deep research, caching, and grounding have no budgeted bypass."""
    budget = GenerationBudget(max_calls=1, max_output_tokens=512, max_request_bytes=16384, timeout_s=60)
    client, transport = await _client(budget=budget, responses=[])

    with pytest.raises(GenerationBudgetExceeded) as excinfo:
        await client.ask("research", deep_research=True)

    assert excinfo.value.reason_code == "unsupported_mode"
    assert transport.send_message.await_count == 0
