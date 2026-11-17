"""Regression contract: the LLM-driven semantic example (FEAT-769 M3)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from parrot.clients.base import AbstractClient
from parrot.models.basic import CompletionUsage, ToolCall
from parrot.models.responses import AIMessage
from parrot.semantic.context import bind_semantic_context
from parrot.semantic.errors import SemanticAccessError

pytest.importorskip("duckdb")

_EXAMPLE_PATH = Path(__file__).resolve().parents[3] / "examples" / "agents" / "semantic" / "llm_metrics_agent.py"


class _OfflineToolClient(AbstractClient):
    """Offline client that dispatches one semantic tool through the real manager."""

    client_type = "stub"

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the no-network client with a deterministic model name."""
        kwargs.setdefault("model", "stub")
        super().__init__(**kwargs)
        self.executed_tools: list[str] = []

    async def get_client(self) -> "_OfflineToolClient":
        """Return this in-process client."""
        return self

    async def ask(self, prompt: Any, **kwargs: Any) -> AIMessage:
        """Execute ``sl_list_models`` using AbstractClient's manager dispatch."""
        result = await self._execute_tool("sl_list_models", {})
        self.executed_tools.append("sl_list_models")
        return AIMessage(
            input=str(prompt),
            output="catalog loaded",
            response="catalog loaded",
            model="stub",
            provider="stub",
            usage=CompletionUsage(),
            tool_calls=[ToolCall(id="call-1", name="sl_list_models", arguments={}, result=result)],
        )

    async def ask_stream(self, prompt: Any, **kwargs: Any):
        """Satisfy the abstract client contract without contacting a provider."""
        del prompt, kwargs
        yield "catalog loaded"

    async def resume(self, session_id: str, user_input: str, state: Any) -> AIMessage:
        """Satisfy the abstract client contract."""
        del session_id, state
        return await self.ask(user_input)

    async def invoke(self, prompt: Any, **kwargs: Any) -> AIMessage:
        """Satisfy the abstract client contract."""
        return await self.ask(prompt, **kwargs)


@pytest.fixture(scope="module")
def example() -> ModuleType:
    """Load the example by absolute path, after the duckdb skip check."""
    spec = importlib.util.spec_from_file_location("semantic_llm_metrics_example", _EXAMPLE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(spec.name, None)


@pytest.fixture
def governed(example: ModuleType, tmp_path: Path):
    """A governed toolkit and identity with the example connection bound."""
    warehouse = example._common.build_warehouse(tmp_path)
    identity = example._common.example_identity("analyst-1", "session-1", "eu")
    with example._common.connection_env(warehouse):
        yield example._common.build_toolkit(warehouse), identity


@pytest.mark.asyncio
async def test_smoke_walks_the_catalog_without_a_provider(example: ModuleType, governed) -> None:
    """Spec AC6: the deterministic path initializes no LLM provider."""
    toolkit, identity = governed
    summary = await example.smoke(toolkit, identity)
    assert "orders" in summary["models"]
    assert set(summary["dimensions"]) == {"order_date", "region"}
    assert summary["row_count"] == 1


@pytest.mark.asyncio
async def test_ask_dispatch_reaches_a_tool(example: ModuleType, governed, monkeypatch: pytest.MonkeyPatch) -> None:
    """Spec AC4: at least one sl_* tool is reached through ask(permission_context=...)."""
    toolkit, identity = governed
    calls: list[str] = []
    original = toolkit.list_models

    async def list_models() -> list[dict]:
        calls.append("list_models")
        return await original()

    monkeypatch.setattr(toolkit, "list_models", list_models)
    agent = example.build_agent(toolkit)
    client = _OfflineToolClient(tool_manager=agent.tool_manager)
    agent._llm = client
    agent.client = client

    response = await example.ask_llm(agent, "What models can I query?", identity)

    assert calls == ["list_models"]
    assert client.executed_tools == ["sl_list_models"]
    assert {model["name"] for model in response.tool_calls[0].result} >= {"orders"}


@pytest.mark.asyncio
async def test_missing_supplied_context_fails_closed(example: ModuleType, governed) -> None:
    """Bound but not supplied -> context_required (toolkit.py:110-116)."""
    toolkit, identity = governed
    tool = next(tool for tool in toolkit.get_tools() if tool.name.endswith("list_models"))
    async with bind_semantic_context(identity.ctx, identity=identity):
        with pytest.raises(SemanticAccessError) as excinfo:
            await tool._execute()
    assert excinfo.value.code == "context_required"


@pytest.mark.asyncio
async def test_mismatched_context_fails_closed(example: ModuleType, governed) -> None:
    """Supplied but not bound, and supplied-but-different, both fail closed (spec AC4/AC7)."""
    toolkit, identity = governed
    other = example._common.example_identity("other-user", "other-session", "us")
    tool = next(tool for tool in toolkit.get_tools() if tool.name.endswith("list_models"))

    with pytest.raises(SemanticAccessError) as excinfo:
        await tool._execute(_permission_context=identity.ctx)
    assert excinfo.value.code == "context_required"

    async with bind_semantic_context(identity.ctx, identity=identity):
        with pytest.raises(SemanticAccessError) as excinfo:
            await tool._execute(_permission_context=other.ctx)
    assert excinfo.value.code == "context_required"
