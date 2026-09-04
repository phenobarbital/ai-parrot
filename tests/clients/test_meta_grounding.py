"""Unit tests for MetaClient search grounding and count_input_tokens().

No live Meta API calls are made.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.clients.meta import MetaClient

GROUNDED = {
    "status": "completed",
    "output_text": None,
    "output": [
        {"type": "reasoning", "content": []},
        {"type": "web_search_call", "id": "ws_1"},
        {
            "type": "message",
            "content": [
                {
                    "type": "output_text",
                    "text": "Spain won 2026 World Cup",
                    "annotations": [],
                }
            ],
        },
    ],
    "usage": MagicMock(
        input_tokens=169,
        input_tokens_details={"cached_tokens": 12},
        output_tokens=50,
        prompt_tokens_details=None,
    ),
}


def _sdk_with_grounded_response():
    sdk = MagicMock()
    sdk.responses.create = AsyncMock(return_value=MagicMock(**GROUNDED))
    return sdk


class TestSearchGrounding:
    @pytest.mark.asyncio
    async def test_injects_web_search_tool(self, monkeypatch):
        client = MetaClient(api_key="k", use_responses=True)
        sdk = _sdk_with_grounded_response()
        monkeypatch.setattr(client, "get_client", AsyncMock(return_value=sdk))

        await client.ask("Who won the 2026 World Cup?", search_grounding=True)

        _, kwargs = sdk.responses.create.call_args
        assert {"type": "web_search"} in kwargs["tools"]

    @pytest.mark.asyncio
    async def test_defaults_to_off(self, monkeypatch):
        client = MetaClient(api_key="k", use_responses=True)
        sdk = _sdk_with_grounded_response()
        monkeypatch.setattr(client, "get_client", AsyncMock(return_value=sdk))

        await client.ask("hi")

        _, kwargs = sdk.responses.create.call_args
        assert "tools" not in kwargs or {"type": "web_search"} not in (kwargs.get("tools") or [])

    @pytest.mark.asyncio
    async def test_raises_when_responses_disabled(self):
        client = MetaClient(api_key="k", use_responses=False)
        with pytest.raises(ValueError, match="[Rr]esponses"):
            await client.ask("q", search_grounding=True)

    @pytest.mark.asyncio
    async def test_surfaces_web_search_call(self, monkeypatch):
        client = MetaClient(api_key="k", use_responses=True)
        sdk = _sdk_with_grounded_response()
        monkeypatch.setattr(client, "get_client", AsyncMock(return_value=sdk))

        result = await client.ask("Who won?", search_grounding=True)

        assert result.metadata["web_search_calls"] == ["ws_1"]
        assert result.metadata["search_grounded"] is True
        assert result.output == "Spain won 2026 World Cup"

    @pytest.mark.asyncio
    async def test_no_grounding_means_no_web_search_metadata(self, monkeypatch):
        client = MetaClient(api_key="k", use_responses=True)
        sdk = MagicMock()
        sdk.responses.create = AsyncMock(
            return_value=MagicMock(
                status="completed",
                output_text=None,
                output=[{"type": "message", "content": [{"type": "output_text", "text": "hi"}]}],
                usage=None,
            )
        )
        monkeypatch.setattr(client, "get_client", AsyncMock(return_value=sdk))

        result = await client.ask("hi")

        assert "web_search_calls" not in result.metadata
        assert "search_grounded" not in result.metadata


class TestCachedTokens:
    def test_extracts_from_responses_shape(self):
        usage = MagicMock(input_tokens_details={"cached_tokens": 12})
        del usage.prompt_tokens_details
        assert MetaClient._extract_cached_tokens(usage) == 12

    def test_extracts_from_chat_completions_shape(self):
        usage = MagicMock(prompt_tokens_details={"cached_tokens": 7})
        assert MetaClient._extract_cached_tokens(usage) == 7

    def test_returns_none_when_absent(self):
        assert MetaClient._extract_cached_tokens(None) is None

    @pytest.mark.asyncio
    async def test_surfaced_on_ai_message_usage(self, monkeypatch):
        client = MetaClient(api_key="k", use_responses=True)
        sdk = _sdk_with_grounded_response()
        monkeypatch.setattr(client, "get_client", AsyncMock(return_value=sdk))

        result = await client.ask("Who won?")

        assert result.usage.extra_usage["cached_tokens"] == 12


class TestCountInputTokens:
    @pytest.mark.asyncio
    async def test_returns_positive_int(self, monkeypatch):
        client = MetaClient(api_key="k")
        sdk = MagicMock()
        sdk.responses.input_tokens = AsyncMock(return_value=MagicMock(input_tokens=169))
        monkeypatch.setattr(client, "get_client", AsyncMock(return_value=sdk))
        assert await client.count_input_tokens(input="Count these.") == 169

    @pytest.mark.asyncio
    async def test_works_with_responses_disabled(self, monkeypatch):
        client = MetaClient(api_key="k", use_responses=False)
        sdk = MagicMock()
        sdk.responses.input_tokens = AsyncMock(return_value=MagicMock(input_tokens=42))
        monkeypatch.setattr(client, "get_client", AsyncMock(return_value=sdk))
        assert await client.count_input_tokens(input="Count these too.") == 42

    @pytest.mark.asyncio
    async def test_passes_resolved_model_and_input(self, monkeypatch):
        client = MetaClient(api_key="k")
        sdk = MagicMock()
        sdk.responses.input_tokens = AsyncMock(return_value=MagicMock(input_tokens=5))
        monkeypatch.setattr(client, "get_client", AsyncMock(return_value=sdk))

        await client.count_input_tokens(input="hi")

        _, kwargs = sdk.responses.input_tokens.call_args
        assert kwargs["model"] == "muse-spark-1.3"
        assert kwargs["input"] == "hi"
