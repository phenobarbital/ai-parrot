"""Tests for PageIndexLLMAdapter with mocked AbstractClient."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.pageindex.llm_adapter import PageIndexLLMAdapter, extract_json
from parrot.pageindex.schemas import TocDetectionResult


def _make_mock_client(output: str = "test output", structured: object = None):
    """Create a mock AbstractClient with configurable responses."""
    client = MagicMock()
    response = MagicMock()
    response.output = output
    response.structured_output = structured
    response.finish_reason = "stop"
    client.ask = AsyncMock(return_value=response)
    client.default_model = "test-model"
    return client


class TestExtractJson:

    def test_plain(self):
        assert extract_json('{"key": "value"}') == {"key": "value"}

    def test_fenced(self):
        assert extract_json('```json\n{"key": "value"}\n```') == {"key": "value"}

    def test_array(self):
        result = extract_json('[1, 2, 3]')
        assert result == [1, 2, 3]

    def test_trailing_comma(self):
        result = extract_json('{"a": 1, "b": 2,}')
        assert result == {"a": 1, "b": 2}

    def test_invalid(self):
        result = extract_json("not json")
        assert result == {}


class TestPageIndexLLMAdapter:

    @pytest.mark.asyncio
    async def test_ask_returns_text(self):
        client = _make_mock_client(output="hello world")
        adapter = PageIndexLLMAdapter(client)

        result = await adapter.ask("test prompt")
        assert result == "hello world"
        client.ask.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ask_returns_structured(self):
        detection = TocDetectionResult(thinking="test", toc_detected="yes")
        client = _make_mock_client(structured=detection)
        adapter = PageIndexLLMAdapter(client)

        result = await adapter.ask(
            "test prompt",
            structured_output=TocDetectionResult,
        )
        assert isinstance(result, TocDetectionResult)
        assert result.toc_detected == "yes"

    @pytest.mark.asyncio
    async def test_ask_structured_native(self):
        detection = TocDetectionResult(thinking="test", toc_detected="no")
        client = _make_mock_client(structured=detection)
        adapter = PageIndexLLMAdapter(client)

        result = await adapter.ask_structured("test", TocDetectionResult)
        assert isinstance(result, TocDetectionResult)
        assert result.toc_detected == "no"

    @pytest.mark.asyncio
    async def test_ask_structured_fallback_to_json(self):
        raw_json = '{"thinking": "fallback", "toc_detected": "yes"}'
        client = _make_mock_client(output=raw_json, structured=None)
        adapter = PageIndexLLMAdapter(client)

        result = await adapter.ask_structured("test", TocDetectionResult)
        assert isinstance(result, TocDetectionResult)
        assert result.toc_detected == "yes"

    @pytest.mark.asyncio
    async def test_ask_json(self):
        client = _make_mock_client(output='```json\n{"a": 1}\n```')
        adapter = PageIndexLLMAdapter(client)

        result = await adapter.ask_json("test")
        assert result == {"a": 1}

    @pytest.mark.asyncio
    async def test_ask_with_finish_info(self):
        client = _make_mock_client(output="some text")
        adapter = PageIndexLLMAdapter(client)

        text, reason = await adapter.ask_with_finish_info("test")
        assert text == "some text"
        assert reason == "finished"

    @pytest.mark.asyncio
    async def test_ask_with_finish_info_truncated(self):
        client = _make_mock_client(output="truncated text")
        response = MagicMock()
        response.output = "truncated text"
        response.finish_reason = "length"
        client.ask = AsyncMock(return_value=response)
        adapter = PageIndexLLMAdapter(client)

        text, reason = await adapter.ask_with_finish_info("test")
        assert reason == "max_output_reached"

    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        client = MagicMock()
        client.default_model = "test-model"

        success_response = MagicMock()
        success_response.output = "success"
        success_response.structured_output = None

        client.ask = AsyncMock(
            side_effect=[Exception("fail"), success_response]
        )
        adapter = PageIndexLLMAdapter(client, max_retries=2, retry_delay=0.01)

        result = await adapter.ask("test")
        assert result == "success"
        assert client.ask.await_count == 2

    @pytest.mark.asyncio
    async def test_max_retries_exceeded_raises(self):
        client = MagicMock()
        client.default_model = "test-model"
        client.ask = AsyncMock(side_effect=Exception("always fails"))
        adapter = PageIndexLLMAdapter(client, max_retries=2, retry_delay=0.01)

        with pytest.raises(Exception, match="always fails"):
            await adapter.ask("test")

    @pytest.mark.asyncio
    async def test_model_override(self):
        client = _make_mock_client()
        adapter = PageIndexLLMAdapter(client, model="custom-model")

        await adapter.ask("test")
        call_kwargs = client.ask.call_args
        assert call_kwargs.kwargs.get("model") == "custom-model"
