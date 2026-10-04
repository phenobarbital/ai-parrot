"""FEAT-590 M6: LlamaCppDelegate (mocked HTTP)."""

from __future__ import annotations

import os
from typing import Any, Dict
import pytest

from parrot.bots.flows.plan.delegate import DelegateBackendError, ToolCallDelegate, ToolSpec
from parrot.bots.flows.plan.delegate.llamacpp import LlamaCppDelegate


def test_satisfies_protocol_and_opens_no_session() -> None:
    delegate = LlamaCppDelegate("http://localhost:8080")
    assert isinstance(delegate, ToolCallDelegate)
    assert delegate._session is None


def test_llamacpp_schema_oneof() -> None:
    delegate = LlamaCppDelegate("http://localhost:8080")
    tools = [
        ToolSpec(
            name="tool_a", description="Tool A", parameters={"type": "object", "properties": {"x": {"type": "integer"}}}
        ),
        ToolSpec(
            name="tool_b", description="Tool B", parameters={"type": "object", "properties": {"y": {"type": "string"}}}
        ),
    ]
    schema = delegate._call_schema(tools)
    assert "oneOf" in schema
    assert len(schema["oneOf"]) == 3  # tool_a, tool_b, decline
    assert schema["oneOf"][0]["properties"]["name"]["const"] == "tool_a"
    assert schema["oneOf"][1]["properties"]["name"]["const"] == "tool_b"
    assert schema["oneOf"][2]["properties"]["name"]["type"] == "null"


@pytest.mark.asyncio
async def test_propose_parses_call(monkeypatch) -> None:
    delegate = LlamaCppDelegate("http://localhost:8080", use_logprobs=True)

    mock_response = {
        "choices": [
            {
                "message": {"content": '{"name": "tool_a", "arguments": {"x": 42}}'},
                "logprobs": {
                    "content": [
                        {"token": "{", "logprob": -0.1},
                        {"token": "name", "logprob": -0.2},
                    ]
                },
            }
        ]
    }

    async def mock_post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return mock_response

    monkeypatch.setattr(LlamaCppDelegate, "_post", mock_post)

    tools = [
        ToolSpec(
            name="tool_a", description="Tool A", parameters={"type": "object", "properties": {"x": {"type": "integer"}}}
        )
    ]
    proposal = await delegate.propose_call("run tool a with 42", tools)
    assert proposal.name == "tool_a"
    assert proposal.arguments == {"x": 42}
    assert proposal.confidence is not None
    assert proposal.confidence > 0.0
    assert proposal.backend == "llamacpp"
    assert proposal.latency_ms >= 0.0


@pytest.mark.asyncio
async def test_propose_decline(monkeypatch) -> None:
    delegate = LlamaCppDelegate("http://localhost:8080")

    mock_response = {"choices": [{"message": {"content": '{"name": null}'}}]}

    async def mock_post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return mock_response

    monkeypatch.setattr(LlamaCppDelegate, "_post", mock_post)

    tools = [
        ToolSpec(
            name="tool_a", description="Tool A", parameters={"type": "object", "properties": {"x": {"type": "integer"}}}
        )
    ]
    proposal = await delegate.propose_call("do something unrelated", tools)
    assert proposal.name is None
    assert proposal.arguments == {}
    assert proposal.confidence is None


@pytest.mark.asyncio
async def test_http_error_is_backend_error(monkeypatch) -> None:
    delegate = LlamaCppDelegate("http://localhost:8080")

    async def mock_post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise DelegateBackendError("HTTP 500 Internal Server Error")

    monkeypatch.setattr(LlamaCppDelegate, "_post", mock_post)

    tools = [
        ToolSpec(
            name="tool_a", description="Tool A", parameters={"type": "object", "properties": {"x": {"type": "integer"}}}
        )
    ]
    with pytest.raises(DelegateBackendError):
        await delegate.propose_call("run tool a", tools)


@pytest.mark.asyncio
async def test_aclose_idempotent() -> None:
    delegate = LlamaCppDelegate("http://localhost:8080")
    await delegate.aclose()
    await delegate.aclose()


@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("LLAMACPP_URL"), reason="needs a live llama-server")
@pytest.mark.asyncio
async def test_live_llamacpp_delegate() -> None:
    url = os.environ["LLAMACPP_URL"]
    delegate = LlamaCppDelegate(url)
    tools = [
        ToolSpec(
            name="tool_a", description="Tool A", parameters={"type": "object", "properties": {"x": {"type": "integer"}}}
        )
    ]
    proposal = await delegate.propose_call("run tool a with 42", tools)
    assert proposal.backend == "llamacpp"
    await delegate.aclose()
