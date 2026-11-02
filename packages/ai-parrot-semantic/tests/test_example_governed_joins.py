"""Regression contract: grains, the governed-join denial, connection isolation (FEAT-769 M6)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from parrot.semantic.errors import SemanticAccessError

pytest.importorskip("duckdb")

_EXAMPLE_PATH = Path(__file__).resolve().parents[3] / "examples" / "agents" / "semantic" / "governed_joins_agent.py"


@pytest.fixture(scope="module")
def example() -> ModuleType:
    """Load the example by absolute path, after the duckdb skip check."""
    spec = importlib.util.spec_from_file_location("semantic_governed_joins_example", _EXAMPLE_PATH)
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
    """A governed toolkit with BOTH connections bound, plus the fixture identity."""
    warehouse = example._common.build_warehouse(tmp_path)
    dim_warehouse = example._common.build_dim_warehouse(tmp_path)
    identity = example._common.example_identity("analyst-1", "session-1", "eu")
    with example._common.connection_env(warehouse, dim_warehouse):
        yield example._common.build_toolkit(warehouse), identity


@pytest.mark.asyncio
async def test_governed_time_grain_succeeds(example: ModuleType, governed) -> None:
    """Grains work on a single model."""
    toolkit, identity = governed
    result = await example.run_time_grain(toolkit, identity)
    assert "revenue" in result.columns
    assert "order_date_month" in result.columns
    assert result.row_count > 0


@pytest.mark.asyncio
async def test_governed_cross_model_query_is_denied(example: ModuleType, governed) -> None:
    """Spec AC12: the governed cross-model query raises member_not_granted."""
    toolkit, identity = governed
    error = await example.show_governed_join_denial(toolkit, identity)
    assert isinstance(error, SemanticAccessError)
    assert error.code == "member_not_granted"
    assert error.details["member"] == example.UNGRANTABLE_MEMBER


@pytest.mark.asyncio
async def test_a_silently_succeeding_denial_fails_the_example(
    example: ModuleType, governed, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec AC7: if the denial stops happening, the example must raise."""
    toolkit, identity = governed

    async def _succeeds(query):
        return None

    monkeypatch.setattr(toolkit, "query_metrics", _succeeds)
    with pytest.raises(RuntimeError, match="unexpectedly succeeded"):
        await example.show_governed_join_denial(toolkit, identity)


@pytest.mark.asyncio
async def test_ungoverned_model_compiles_the_join(example: ModuleType, tmp_path: Path) -> None:
    """Q1(b): the compiler surface produces the join the gate refuses to authorize."""
    sql = await example.compile_ungoverned_join(tmp_path)
    assert "JOIN" in sql.upper()
    assert "dim.customers" in sql


@pytest.mark.asyncio
async def test_second_connection_reads_the_dim_warehouse(example: ModuleType, governed) -> None:
    """Q3: the connection is resolved from the ROOT model's policy, per model."""
    toolkit, identity = governed
    result = await example.run_on_second_connection(toolkit, identity)
    emails = {row["email"] for row in result.rows}
    assert emails == {"a@example.test", "b@example.test"}


@pytest.mark.asyncio
async def test_second_connection_is_not_a_refusal(example: ModuleType, governed) -> None:
    """The second connection demonstrates isolation, never a cross-connection refusal."""
    toolkit, identity = governed
    result = await example.run_on_second_connection(toolkit, identity)
    assert result.row_count > 0, "the second connection must SUCCEED; it is not a denial demo"


@pytest.mark.asyncio
async def test_smoke_labels_every_surface(example: ModuleType) -> None:
    """Spec AC3/AC12: offline, and no key presents a governed cross-model success."""
    summary = await example.smoke()
    assert set(summary) == {
        "governed_time_grain",
        "governed_join_denied",
        "compiler_only_join_sql",
        "governed_second_connection",
    }
    assert summary["governed_join_denied"]["code"] == "member_not_granted"
