"""Regression contract: Agent example with guarded DatasetManager facade."""

from __future__ import annotations

import importlib.util
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType

import pytest

from parrot.semantic.context import bind_semantic_context
from parrot.semantic.errors import SemanticResultError
from parrot.semantic.handoff import GovernedSinkRegistry
from parrot.semantic.models import SemanticQuery

pytest.importorskip("duckdb")

_EXAMPLE_PATH = Path(__file__).resolve().parents[3] / "examples" / "semantic" / "agent_semantic_example.py"
_QUERY = SemanticQuery(model="orders", metrics=["revenue"], dimensions=["region"])
_FACADE_TOOLS = ("list_datasets", "describe_dataset", "query_dataset", "export_dataset", "cached_dataset")


@pytest.fixture(scope="module")
def example() -> ModuleType:
    """Load the example module lazily, after the duckdb skip check."""
    spec = importlib.util.spec_from_file_location("semantic_agent_example", _EXAMPLE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(spec.name, None)


@pytest.fixture
def warehouse_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, example: ModuleType) -> Path:
    """Point the example connection at the per-test warehouse, restored by monkeypatch."""
    monkeypatch.setenv(example.CONNECTION_ENV, str(tmp_path / "semantic-example.duckdb"))
    return tmp_path


async def _publish(example: ModuleType, semantic: object, owner: object) -> object:
    """Query and publish ``eu_revenue`` as the owner, returning the query result."""
    async with bind_semantic_context(owner.ctx, identity=owner):
        result = await semantic.query_metrics(_QUERY)
        await semantic.save_result_as_dataset(result.result_id or "", "eu_revenue")
    return result


def _tool_names(agent: object) -> set[str]:
    """Return registered Agent tool names without relying on a provider call."""
    return set(agent.tool_manager.list_tools())


@pytest.mark.asyncio
async def test_agent_has_semantic_and_guarded_facade_tools(warehouse_env: Path, example: ModuleType) -> None:
    """Verify agent has semantic and guarded facade tools."""
    semantic, facade = example.build_toolkits(warehouse_env)
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


def test_pbac_is_wired_through_a_real_guard(warehouse_env: Path, example: ModuleType) -> None:
    """The gate is available because a configured DataPlanePolicyGuard is supplied, not forced."""
    semantic, _ = example.build_toolkits(warehouse_env)
    assert semantic._pbac.available is True
    assert type(semantic._pbac.guard).__name__ == "DataPlanePolicyGuard"
    assert "_pbac.available" not in _EXAMPLE_PATH.read_text(encoding="utf-8")


def test_build_toolkits_does_not_mutate_environment(tmp_path: Path, example: ModuleType) -> None:
    """Building the toolkits leaves os.environ untouched; connection_env restores it."""
    before = dict(os.environ)
    example.build_toolkits(tmp_path)
    assert dict(os.environ) == before
    with example.connection_env(tmp_path):
        assert os.environ[example.CONNECTION_ENV].endswith("semantic-example.duckdb")
    assert dict(os.environ) == before


@pytest.mark.asyncio
async def test_scripted_no_llm_full_chain(warehouse_env: Path, example: ModuleType) -> None:
    """Verify scripted no llm full chain across every guarded facade tool."""
    semantic, facade = example.build_toolkits(warehouse_env)
    owner = example._example_identity("analyst-1", "session-1", "eu")
    async with bind_semantic_context(owner.ctx, identity=owner):
        assert [member["name"] for member in await semantic.list_metrics("orders")] == ["revenue"]
    result = await _publish(example, semantic, owner)
    assert result.rows == [{"region": "eu", "revenue": 12.5}]
    async with bind_semantic_context(owner.ctx, identity=owner):
        assert (await facade.list_datasets())["datasets"] == ["eu_revenue"]
        description = await facade.describe_dataset("eu_revenue")
        assert description["model"] == "orders" and description["rows"] == 1
        assert (await facade.query_dataset("eu_revenue"))["rows"] == result.rows
        assert (await facade.cached_dataset("eu_revenue"))["rows"] == result.rows
        assert set((await facade.export_dataset("eu_revenue"))["columns"]) == {"region", "revenue"}
        assert (await facade.derive_dataset("eu_revenue"))["policy_digest"]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", (*_FACADE_TOOLS, "derive_dataset"))
async def test_every_facade_tool_denies_other_session(warehouse_env: Path, example: ModuleType, tool: str) -> None:
    """Every facade route rejects a different owner before returning data."""
    semantic, facade = example.build_toolkits(warehouse_env)
    await _publish(example, semantic, example._example_identity("analyst-1", "session-1", "eu"))
    other = example._example_identity("analyst-2", "session-2", "us")
    async with bind_semantic_context(other.ctx, identity=other):
        with pytest.raises(SemanticResultError):
            if tool == "list_datasets":
                await facade.list_datasets()
            else:
                await getattr(facade, tool)("eu_revenue")


@pytest.mark.asyncio
async def test_facade_owner_check_precedes_authorizer(warehouse_env: Path, example: ModuleType) -> None:
    """A foreign identity is rejected by the facade itself, without calling the authorizer."""
    semantic, facade = example.build_toolkits(warehouse_env)
    await _publish(example, semantic, example._example_identity("analyst-1", "session-1", "eu"))
    calls: list[object] = []

    async def _spy(identity: object) -> None:
        calls.append(identity)

    facade._authorizers["eu_revenue"] = _spy
    other = example._example_identity("analyst-2", "session-2", "us")
    async with bind_semantic_context(other.ctx, identity=other):
        with pytest.raises(SemanticResultError):
            await facade.query_dataset("eu_revenue")
    assert calls == []


@pytest.mark.asyncio
async def test_stale_read_after_policy_change(warehouse_env: Path, example: ModuleType) -> None:
    """A policy digest change withholds the published result."""
    semantic, facade = example.build_toolkits(warehouse_env)
    owner = example._example_identity("analyst-1", "session-1", "eu")
    await _publish(example, semantic, owner)
    semantic._models["orders"] = semantic._models["orders"].model_copy(update={"policy_digest": "revoked"})
    async with bind_semantic_context(owner.ctx, identity=owner):
        with pytest.raises(SemanticResultError):
            await facade.derive_dataset("eu_revenue")


@pytest.mark.asyncio
async def test_stale_read_after_pbac_revocation(warehouse_env: Path, example: ModuleType) -> None:
    """Revoking the PBAC grant denies later reads of an already-published result."""
    evaluator = example.ExamplePolicyEvaluator()
    semantic, facade = example.build_toolkits(warehouse_env, evaluator)
    owner = example._example_identity("analyst-1", "session-1", "eu")
    await _publish(example, semantic, owner)
    async with bind_semantic_context(owner.ctx, identity=owner):
        assert (await facade.query_dataset("eu_revenue"))["rows"]
        evaluator.revoke()
        for tool in _FACADE_TOOLS:
            with pytest.raises(SemanticResultError):
                if tool == "list_datasets":
                    await facade.list_datasets()
                else:
                    await getattr(facade, tool)("eu_revenue")


@pytest.mark.asyncio
async def test_stale_read_after_ttl_expiry(
    warehouse_env: Path, example: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A result read after its TTL is withheld."""
    semantic, facade = example.build_toolkits(warehouse_env)
    owner = example._example_identity("analyst-1", "session-1", "eu")
    await _publish(example, semantic, owner)
    future = datetime.now(timezone.utc) + timedelta(days=1)

    class _Later(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return future

    monkeypatch.setattr("parrot.semantic.handoff.datetime", _Later)
    async with bind_semantic_context(owner.ctx, identity=owner):
        with pytest.raises(SemanticResultError):
            await facade.query_dataset("eu_revenue")


@pytest.mark.asyncio
async def test_run_demo_succeeds_and_denial_can_fail(tmp_path: Path, example: ModuleType) -> None:
    """The demo completes, restores the environment, and raises if the denial is skipped."""
    before = dict(os.environ)
    await example.run_demo(tmp_path / "ok")
    assert dict(os.environ) == before

    original = example.GuardedDatasetFacade._read

    async def _leaky_read(self: object, name: str) -> object:
        return self._results[name]

    example.GuardedDatasetFacade._read = _leaky_read
    try:
        with pytest.raises(RuntimeError, match="unexpectedly read"):
            await example.run_demo(tmp_path / "leaky")
    finally:
        example.GuardedDatasetFacade._read = original
