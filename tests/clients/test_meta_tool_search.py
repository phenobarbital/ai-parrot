"""Unit tests for MetaClient's opt-in native hosted ``tool_search`` (FEAT-526 Module 6).

No live Meta API calls are made.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.clients.meta import MetaClient

WEATHER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the weather for a city.",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
    },
}
STOCK_TOOL = {
    "type": "function",
    "function": {
        "name": "get_stock",
        "description": "Get a stock quote.",
        "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}}},
    },
}
SEARCH_TOOLS_TOOL = {
    "type": "function",
    "function": {
        "name": "search_tools",
        "description": "Search the available tools.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
    },
}

TOOL_SEARCH_ANSWER = {
    "status": "completed",
    "output_text": None,
    "output": [
        {"type": "reasoning", "content": []},
        {"type": "tool_search_call", "id": "ts_1", "paths": ["weather"]},
        {
            "type": "tool_search_output",
            "id": "tso_1",
            "tools": [{"type": "function", "name": "get_weather", "description": "Get the weather for a city."}],
        },
        {"type": "message", "content": [{"type": "output_text", "text": "It's sunny."}]},
    ],
    "usage": None,
}


def _response(**shape):
    """Build a MagicMock shaped like a Responses API result (``output_text`` pinned to ``None``)."""
    response = MagicMock(**{"usage": None, "status": "completed", **shape})
    response.output_text = None
    return response


def _client_with_tools(monkeypatch, tools, responses, **client_kwargs):
    """Return a MetaClient whose tool preparation and SDK are mocked."""
    client = MetaClient(api_key="k", use_responses=True, **client_kwargs)
    sdk = MagicMock()
    sdk.responses.create = AsyncMock(side_effect=responses)
    monkeypatch.setattr(client, "get_client", AsyncMock(return_value=sdk))
    monkeypatch.setattr(client, "_prepare_tools", lambda *args, **kwargs: list(tools))
    monkeypatch.setattr(client, "_prepare_lazy_tools", lambda *args, **kwargs: [SEARCH_TOOLS_TOOL])
    return client, sdk


def _sent_tools(call):
    """Return the ``tools`` kwarg of one recorded ``responses.create`` call."""
    return call.kwargs.get("tools") or []


class TestNativeToolSearch:
    def test_defaults_to_off(self):
        assert MetaClient(api_key="k").native_tool_search is False

    @pytest.mark.asyncio
    async def test_raises_when_responses_disabled(self):
        client = MetaClient(api_key="k", use_responses=False, native_tool_search=True)
        with pytest.raises(ValueError, match="[Rr]esponses"):
            await client.ask("q", tools=[WEATHER_TOOL])

    @pytest.mark.asyncio
    async def test_stream_raises_when_responses_disabled(self):
        client = MetaClient(api_key="k", use_responses=False, native_tool_search=True)
        with pytest.raises(ValueError, match="[Rr]esponses"):
            async for _ in client.ask_stream("q"):
                pass

    @pytest.mark.asyncio
    async def test_default_keeps_parrot_client_side_path(self, monkeypatch):
        client, sdk = _client_with_tools(monkeypatch, [WEATHER_TOOL], [_response(**TOOL_SEARCH_ANSWER)])

        await client.ask("weather?", use_tools=True, lazy_loading=True)

        tools = _sent_tools(sdk.responses.create.call_args)
        assert [tool.get("name") for tool in tools] == ["search_tools"]
        assert {"type": "tool_search"} not in tools
        assert not any(tool.get("defer_loading") for tool in tools)

    @pytest.mark.asyncio
    async def test_injects_tool_search_and_defer_loading(self, monkeypatch):
        client, sdk = _client_with_tools(
            monkeypatch,
            [WEATHER_TOOL, STOCK_TOOL, SEARCH_TOOLS_TOOL],
            [_response(**TOOL_SEARCH_ANSWER)],
            native_tool_search=True,
        )

        result = await client.ask("weather?", use_tools=True, lazy_loading=True)

        tools = _sent_tools(sdk.responses.create.call_args)
        assert {"type": "tool_search"} in tools
        functions = [tool for tool in tools if tool.get("type") == "function"]
        assert [tool["name"] for tool in functions] == ["get_weather", "get_stock"]
        assert all(tool["defer_loading"] is True for tool in functions)
        assert "function" not in functions[0]
        assert sdk.responses.create.call_args.kwargs["tool_choice"] == "auto"
        assert result.metadata["native_tool_search"] is True
        assert result.metadata["tool_search_calls"] == ["ts_1"]

    @pytest.mark.asyncio
    async def test_non_function_tools_are_not_deferred(self, monkeypatch):
        client, sdk = _client_with_tools(
            monkeypatch,
            [WEATHER_TOOL],
            [_response(**TOOL_SEARCH_ANSWER)],
            native_tool_search=True,
        )

        await client.ask("weather?", use_tools=True, search_grounding=True)

        tools = _sent_tools(sdk.responses.create.call_args)
        assert {"type": "web_search"} in tools
        assert {"type": "tool_search"} in tools

    @pytest.mark.asyncio
    async def test_no_deferred_tool_does_not_send_guaranteed_400(self, monkeypatch):
        """Meta 400s on tool_search with no deferred tool — never send that."""
        client, sdk = _client_with_tools(
            monkeypatch,
            [SEARCH_TOOLS_TOOL],
            [_response(**TOOL_SEARCH_ANSWER)],
            native_tool_search=True,
        )

        result = await client.ask("weather?", use_tools=True, lazy_loading=True)

        tools = _sent_tools(sdk.responses.create.call_args)
        assert {"type": "tool_search"} not in tools
        assert [tool.get("name") for tool in tools] == ["search_tools"]
        assert "native_tool_search" not in result.metadata

    @pytest.mark.asyncio
    async def test_no_tools_at_all_sends_no_tool_search(self, monkeypatch):
        client, sdk = _client_with_tools(monkeypatch, [], [_response(**TOOL_SEARCH_ANSWER)], native_tool_search=True)

        await client.ask("hi", use_tools=True)

        assert {"type": "tool_search"} not in _sent_tools(sdk.responses.create.call_args)

    @pytest.mark.asyncio
    async def test_tool_search_output_items_do_not_corrupt_text(self, monkeypatch):
        client, _ = _client_with_tools(
            monkeypatch, [WEATHER_TOOL], [_response(**TOOL_SEARCH_ANSWER)], native_tool_search=True
        )

        result = await client.ask("weather?", use_tools=True)

        assert result.output == "It's sunny."
        assert result.tool_calls == []

    @pytest.mark.asyncio
    async def test_called_tool_is_undeferred_on_the_next_round(self, monkeypatch):
        round1 = _response(
            output=[
                {"type": "tool_search_call", "id": "ts_1"},
                {"type": "tool_search_output", "id": "tso_1"},
                {"type": "function_call", "call_id": "call_1", "name": "get_weather", "arguments": '{"city": "NYC"}'},
            ]
        )
        round2 = _response(output=[{"type": "message", "content": [{"type": "output_text", "text": "Sunny."}]}])
        client, sdk = _client_with_tools(
            monkeypatch, [WEATHER_TOOL, STOCK_TOOL], [round1, round2], native_tool_search=True
        )
        monkeypatch.setattr(client, "_execute_tool", AsyncMock(return_value="sunny"))

        result = await client.ask("weather in NYC?", use_tools=True)

        assert sdk.responses.create.await_count == 2
        round2_tools = {
            tool.get("name") or tool["type"]: tool for tool in _sent_tools(sdk.responses.create.call_args_list[1])
        }
        assert "defer_loading" not in round2_tools["get_weather"]
        assert round2_tools["get_stock"]["defer_loading"] is True
        assert "tool_search" in round2_tools
        assert result.output == "Sunny."
        assert result.metadata["tool_search_calls"] == ["ts_1"]


class TestUndeferTools:
    def test_drops_tool_search_once_nothing_is_deferred(self):
        tools = [
            {"type": "function", "name": "get_weather", "defer_loading": True},
            {"type": "tool_search"},
        ]

        updated = MetaClient._undefer_tools(tools, {"get_weather"})

        assert updated == [{"type": "function", "name": "get_weather"}]
        assert tools[0]["defer_loading"] is True

    def test_keeps_tool_search_while_a_tool_stays_deferred(self):
        tools = [
            {"type": "function", "name": "get_weather", "defer_loading": True},
            {"type": "function", "name": "get_stock", "defer_loading": True},
            {"type": "tool_search"},
        ]

        updated = MetaClient._undefer_tools(tools, {"get_weather"})

        assert {"type": "tool_search"} in updated
        assert updated[1]["defer_loading"] is True


class TestNativeToolSearchStream:
    @pytest.mark.asyncio
    async def test_stream_injects_tool_search(self, monkeypatch):
        client = MetaClient(api_key="k", use_responses=True, native_tool_search=True)
        monkeypatch.setattr(client, "_prepare_tools", lambda *args, **kwargs: [WEATHER_TOOL])
        client.tools["get_weather"] = object()

        stream = MagicMock()
        stream.__aiter__.return_value = []
        stream.get_final_response = AsyncMock(return_value=_response(**TOOL_SEARCH_ANSWER))
        stream_cm = MagicMock()
        stream_cm.__aenter__ = AsyncMock(return_value=stream)
        stream_cm.__aexit__ = AsyncMock(return_value=False)
        sdk = MagicMock()
        sdk.responses.stream = MagicMock(return_value=stream_cm)
        monkeypatch.setattr(client, "get_client", AsyncMock(return_value=sdk))

        chunks = [item async for item in client.ask_stream("weather?")]

        tools = sdk.responses.stream.call_args.kwargs["tools"]
        assert {"type": "tool_search"} in tools
        assert tools[0]["defer_loading"] is True
        assert chunks[0] == "It's sunny."
