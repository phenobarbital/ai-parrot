"""Regression contract: shared scaffolding for the semantic examples (FEAT-769 M2)."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

pytest.importorskip("duckdb")

_COMMON_PATH = Path(__file__).resolve().parents[3] / "examples" / "agents" / "semantic" / "_common.py"


@pytest.fixture(scope="module")
def common() -> ModuleType:
    """Load the shared module by absolute path, after the duckdb skip check."""
    spec = importlib.util.spec_from_file_location("semantic_examples_common", _COMMON_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(spec.name, None)


def test_guard_is_a_real_dataplane_guard(common: ModuleType) -> None:
    """The example evaluator is plugged into the core guard; no gate is forced open."""
    from parrot.auth import DataPlanePolicyGuard, RlsRegistry

    guard = common.build_guard(common.ExamplePolicyEvaluator(), RlsRegistry())
    assert isinstance(guard, DataPlanePolicyGuard)


def test_evaluator_denies_once_revoked(common: ModuleType) -> None:
    """``revoke()`` fails closed for every subsequent decision."""
    evaluator = common.ExamplePolicyEvaluator()
    eval_ctx = SimpleNamespace(store={"userinfo": {"roles": ["analyst"]}})
    assert evaluator.check_access(eval_ctx, "driver", "duckdb", "driver:connect", None).allowed is True
    evaluator.revoke()
    assert evaluator.check_access(eval_ctx, "driver", "duckdb", "driver:connect", None).allowed is False


def test_connection_env_restores_both_variables(common: ModuleType, tmp_path: Path) -> None:
    """Spec AC3: nothing leaks process-wide, for a previously-set and an unset variable."""
    before = dict(os.environ)
    with common.connection_env(tmp_path / "a.duckdb", tmp_path / "b.duckdb"):
        assert os.environ[common.CONNECTION_ENV] == str(tmp_path / "a.duckdb")
        assert os.environ[common.CONNECTION_ENV_DIM] == str(tmp_path / "b.duckdb")
    assert dict(os.environ) == before


def test_connection_env_restores_a_preexisting_value(
    common: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A variable that was already set is restored to its old value, not popped."""
    monkeypatch.setenv(common.CONNECTION_ENV, "/previous.duckdb")
    with common.connection_env(tmp_path / "a.duckdb"):
        assert os.environ[common.CONNECTION_ENV] == str(tmp_path / "a.duckdb")
    assert os.environ[common.CONNECTION_ENV] == "/previous.duckdb"


def test_warehouses_are_seeded_and_distinct(common: ModuleType, tmp_path: Path) -> None:
    """Orders warehouse has both tables; dim warehouse has only ``dim.customers``."""
    import duckdb

    warehouse = common.build_warehouse(tmp_path)
    dim_warehouse = common.build_dim_warehouse(tmp_path)
    with duckdb.connect(str(warehouse), read_only=True) as connection:
        tables = set(connection.execute("SELECT schema_name || '.' || table_name FROM duckdb_tables()").fetchall())
    with duckdb.connect(str(dim_warehouse), read_only=True) as connection:
        dim_tables = set(connection.execute("SELECT schema_name || '.' || table_name FROM duckdb_tables()").fetchall())
    assert tables == {("dim.customers",), ("sales.orders",)}
    assert dim_tables == {("dim.customers",)}


def test_build_toolkit_exposes_the_sl_tools(common: ModuleType, tmp_path: Path) -> None:
    """The toolkit loads committed fixtures and exposes prefixed tools without reload."""
    warehouse = common.build_warehouse(tmp_path)
    with common.connection_env(warehouse):
        toolkit = common.build_toolkit(warehouse)
    names = {tool.name for tool in toolkit.get_tools()}
    assert any(name.startswith("sl_") for name in names)
    assert "sl_reload" not in names
