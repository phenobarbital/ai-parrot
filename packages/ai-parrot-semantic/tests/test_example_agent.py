"""Regression contract: Agent example with guarded DatasetManager facade."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from parrot.semantic.context import bind_semantic_context
from parrot.semantic.errors import SemanticResultError
from parrot.semantic.handoff import GovernedSinkRegistry
from parrot.semantic.models import SemanticQuery

_EXAMPLE_PATH = Path(__file__).resolve().parents[3] / "examples" / "semantic" / "agent_semantic_example.py"
_SPEC = importlib.util.spec_from_file_location("semantic_agent_example", _EXAMPLE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
example = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = example
_SPEC.loader.exec_module(example)


def _tool_names(agent: object) -> set[str]:
    """Return registered Agent tool names without relying on a provider call."""
    return set(agent.tool_manager.list_tools())


@pytest.mark.asyncio
async def test_agent_has_semantic_and_guarded_facade_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify agent has semantic and guarded facade tools."""
    monkeypatch.setattr("parrot.semantic.governance.pbac.importlib.util.find_spec", lambda _: object())
    semantic, facade = example.build_toolkits(tmp_path)
    agent = example.build_agent((semantic, facade))
    names = _tool_names(agent)
    assert "sl_query_metrics" in names
    assert "sl_save_result_as_dataset" in names
    assert "guarded_dataset_query_dataset" in names
    assert "guarded_dataset_publish" not in names
    assert not any(name.startswith("dataset_") for name in names)
    assert facade._manager.get_tools()
    assert all(tool.name not in names for tool in facade._manager.get_tools())
    with pytest.raises(SemanticResultError):
        GovernedSinkRegistry().register(facade)


@pytest.mark.asyncio
async def test_scripted_no_llm_full_chain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify scripted no llm full chain."""
    monkeypatch.setattr("parrot.semantic.governance.pbac.importlib.util.find_spec", lambda _: object())
    semantic, facade = example.build_toolkits(tmp_path)
    owner = example._example_identity("analyst-1", "session-1", "eu")
    async with bind_semantic_context(owner.ctx, identity=owner):
        assert [member["name"] for member in await semantic.list_metrics("orders")] == ["revenue"]
        result = await semantic.query_metrics(SemanticQuery(model="orders", metrics=["revenue"], dimensions=["region"]))
        assert result.rows == [{"region": "eu", "revenue": 12.5}]
        published = await semantic.save_result_as_dataset(result.result_id or "", "eu_revenue")
        assert published["rows"] == 1
        assert (await facade.query_dataset("eu_revenue"))["rows"] == result.rows
        assert set((await facade.export_dataset("eu_revenue"))["columns"]) == {"region", "revenue"}


@pytest.mark.asyncio
async def test_two_sessions_and_stale_cached_reads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify two sessions and stale cached reads."""
    monkeypatch.setattr("parrot.semantic.governance.pbac.importlib.util.find_spec", lambda _: object())
    semantic, facade = example.build_toolkits(tmp_path)
    owner = example._example_identity("analyst-1", "session-1", "eu")
    async with bind_semantic_context(owner.ctx, identity=owner):
        result = await semantic.query_metrics(SemanticQuery(model="orders", metrics=["revenue"], dimensions=["region"]))
        await semantic.save_result_as_dataset(result.result_id or "", "eu_revenue")
        assert (await facade.cached_dataset("eu_revenue"))["rows"]
        assert (await facade.derive_dataset("eu_revenue"))["policy_digest"]

    other = example._example_identity("analyst-2", "session-2", "us")
    async with bind_semantic_context(other.ctx, identity=other):
        with pytest.raises(SemanticResultError):
            await facade.cached_dataset("eu_revenue")

    semantic._models["orders"] = semantic._models["orders"].model_copy(update={"policy_digest": "revoked"})
    async with bind_semantic_context(owner.ctx, identity=owner):
        with pytest.raises(SemanticResultError):
            await facade.derive_dataset("eu_revenue")
