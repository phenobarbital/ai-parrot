"""Unit tests for parrot.registry.routing.llm_helper (TASK-787)."""
import asyncio
import pytest
from parrot.registry.routing import extract_json_from_response, run_llm_ranking


class FakeAIMessage:
    def __init__(self, output):
        self.output = output


class FakeAIMessageContent:
    def __init__(self, content):
        self.content = content


def test_extract_from_ai_message_dict():
    m = FakeAIMessage({"routing_type": "vector_search", "confidence": 0.9})
    result = extract_json_from_response(m)
    assert result["routing_type"] == "vector_search"
    assert result["confidence"] == 0.9


def test_extract_from_ai_message_content_str():
    m = FakeAIMessageContent('{"routing_type": "dataset", "confidence": 0.7}')
    result = extract_json_from_response(m)
    assert result["routing_type"] == "dataset"


def test_extract_from_json_string():
    raw = 'Some preamble {"routing_type": "dataset", "confidence": 0.7} trailing'
    result = extract_json_from_response(raw)
    assert result["routing_type"] == "dataset"


def test_extract_from_plain_dict():
    result = extract_json_from_response({"foo": 1})
    assert result == {"foo": 1}


def test_extract_unparseable_returns_none():
    assert extract_json_from_response("no json here") is None
    assert extract_json_from_response(None) is None


def test_extract_from_message_with_output_string():
    m = FakeAIMessage('prefix {"key": "val"} suffix')
    result = extract_json_from_response(m)
    assert result == {"key": "val"}


def test_extract_from_invalid_json_string():
    assert extract_json_from_response("{not valid json}") is None


@pytest.mark.asyncio
async def test_run_llm_ranking_timeout():
    async def slow(prompt):
        await asyncio.sleep(10)

    result = await run_llm_ranking(slow, "x", timeout_s=0.05)
    assert result is None


@pytest.mark.asyncio
async def test_run_llm_ranking_happy_path():
    async def fake(prompt):
        return FakeAIMessage({"routing_type": "vector_search", "confidence": 0.8})

    result = await run_llm_ranking(fake, "x", timeout_s=1.0)
    assert result["confidence"] == 0.8


@pytest.mark.asyncio
async def test_run_llm_ranking_exception_returns_none():
    async def boom(prompt):
        raise RuntimeError("bad")

    assert await run_llm_ranking(boom, "x", timeout_s=1.0) is None


@pytest.mark.asyncio
async def test_run_llm_ranking_unparseable_returns_none():
    async def bad_response(prompt):
        return FakeAIMessage("not json at all")

    assert await run_llm_ranking(bad_response, "x", timeout_s=1.0) is None
