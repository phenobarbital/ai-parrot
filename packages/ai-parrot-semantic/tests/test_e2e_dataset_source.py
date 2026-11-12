"""End-to-end: DatasetManager.add_semantic over the real DuckDB fixture (FEAT-880 M5)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from parrot.auth import PermissionContext, UserSession
from parrot.auth.context import _pctx_var
from parrot.auth.exceptions import AuthorizationRequired
from parrot.semantic import SemanticLayerToolkit
from parrot.semantic.context import bind_semantic_context
from parrot.semantic.governance import pbac
from parrot.semantic.governance.pipeline import subject_digest
from parrot.tools.dataset_manager import DatasetManager

from ._models import duckdb_warehouse, models_dir  # noqa: F401

_Q = {"metrics": ["revenue"], "dimensions": ["region"]}


class _EvaluatorGuard:
    """Deterministic PBAC evaluator used while exercising the real DuckDB source."""

    def __init__(self, *, deny: bool = False) -> None:
        """Create a guard that records manifest and post-compile authorization."""
        self._evaluator = object()
        self.deny = deny
        self.calls: list[object] = []

    async def authorize_source(self, ctx: PermissionContext, resources: object) -> None:
        """Authorize the supplied resources or deterministically deny them."""
        self.calls.append(resources)
        if self.deny:
            raise AuthorizationRequired("semantic_query", "denied")


def _context(user_id: str, program: str, roles: frozenset[str] = frozenset({"analyst"})) -> PermissionContext:
    """Build subjects with identical role and tenant claims but distinct programs."""
    return PermissionContext(
        session=UserSession(
            user_id=user_id,
            tenant_id="tenant-a",
            roles=roles,
            metadata={"programs": [program]},
        )
    )


def _prepare(models_dir: Path, warehouse: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bind the fixture connection and widen the analyst usage grant."""
    monkeypatch.setattr(pbac.importlib.util, "find_spec", lambda _: object())
    monkeypatch.setenv("PARROT_SEMANTIC_CONN_SEMANTIC_TEST_DATABASE", str(warehouse))
    policy_path = models_dir / "orders.policy.yaml"
    policy_path.write_text(
        policy_path.read_text(encoding="utf-8").replace("usage: [sales.orders.region]", 'usage: "*"'),
        encoding="utf-8",
    )


def _toolkit(
    models_dir: Path,
    warehouse: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    guard: _EvaluatorGuard | None = None,
) -> SemanticLayerToolkit:
    """Configure a toolkit whose executor resolves to the real fixture database."""
    _prepare(models_dir, warehouse, monkeypatch)
    return SemanticLayerToolkit(models_dir=models_dir, dialect="duckdb", dataplane_guard=guard or _EvaluatorGuard())


def _manager(toolkit: SemanticLayerToolkit, **kwargs) -> DatasetManager:
    """Register the ``orders`` model as the ``sales`` dataset."""
    dm = DatasetManager(generate_guide=False)
    dm.add_semantic("sales", model="orders", toolkit=toolkit, **kwargs)
    return dm


@pytest.mark.asyncio
async def test_e2e_semantic_dataset_fetch(models_dir: Path, duckdb_warehouse: Path, monkeypatch) -> None:
    """add_semantic -> fetch_dataset with a dynamic query returns governed rows as a DataFrame."""
    dm = _manager(_toolkit(models_dir, duckdb_warehouse, monkeypatch))
    async with bind_semantic_context(_context("first", "eu")):
        response = await dm.fetch_dataset("sales", conditions=_Q)
        frame = dm._datasets["sales"]._df
    assert response.get("error") is None, response
    assert frame is not None
    assert frame.to_dict("records") == [{"region": "eu", "revenue": 12.5}]
    assert response["semantic"]["model"] == "orders"
    assert response["semantic"]["truncated"] is False


@pytest.mark.asyncio
async def test_add_semantic_from_models_dir(models_dir: Path, duckdb_warehouse: Path, monkeypatch) -> None:
    """models_dir + dialect builds the toolkit with the manager's own dataplane guard."""
    _prepare(models_dir, duckdb_warehouse, monkeypatch)
    guard = _EvaluatorGuard()
    dm = DatasetManager(generate_guide=False, dataplane_guard=guard)
    message = dm.add_semantic("sales", model="orders", models_dir=str(models_dir), dialect="duckdb")
    assert "sales" in message
    entry = dm._datasets["sales"]
    assert entry.source.toolkit._dialect == "duckdb"
    assert entry.description and entry.source.describe().startswith(entry.description)
    async with bind_semantic_context(_context("first", "eu")):
        response = await dm.fetch_dataset("sales", conditions=_Q)
    assert response.get("error") is None, response
    assert guard.calls, "the manager's dataplane guard must reach the built toolkit"


@pytest.mark.asyncio
async def test_e2e_semantic_dataset_rls_per_subject(models_dir: Path, duckdb_warehouse: Path, monkeypatch) -> None:
    """Two subjects on one entry: each reads only its own frame, never the other's."""
    dm = _manager(_toolkit(models_dir, duckdb_warehouse, monkeypatch))
    entry = dm._datasets["sales"]
    first, second = _context("first", "eu"), _context("second", "us")

    async with bind_semantic_context(first):
        await dm.fetch_dataset("sales", conditions=_Q)
        assert entry.loaded
    async with bind_semantic_context(second):
        assert not entry.loaded
        assert entry._df is None
        await dm.fetch_dataset("sales", conditions=_Q)
        assert entry._df.to_dict("records") == [{"region": "us", "revenue": 25.0}]
    async with bind_semantic_context(first):
        assert entry._df.to_dict("records") == [{"region": "eu", "revenue": 12.5}]
    async with bind_semantic_context(second):
        assert entry._df.to_dict("records") == [{"region": "us", "revenue": 25.0}]
    # No subject → nothing is visible.
    assert entry._df is None
    assert set(entry._frame_slots) == {subject_digest(first), subject_digest(second)}


@pytest.mark.asyncio
async def test_e2e_semantic_dataset_masking(models_dir: Path, duckdb_warehouse: Path, monkeypatch) -> None:
    """A masked column arrives masked for a non-exempt role and raw for the exempt one."""
    _prepare(models_dir, duckdb_warehouse, monkeypatch)
    policy_path = models_dir / "orders.policy.yaml"
    policy_path.write_text(
        policy_path.read_text(encoding="utf-8")
        + "masks:\n  sales.orders.region: {strategy: 'null', projection_roles: [admin], usage_roles: [analyst, admin]}\n",
        encoding="utf-8",
    )
    toolkit = SemanticLayerToolkit(models_dir=models_dir, dialect="duckdb", dataplane_guard=_EvaluatorGuard())
    dm = _manager(toolkit)
    async with bind_semantic_context(_context("analyst", "eu")):
        await dm.fetch_dataset("sales", conditions=_Q)
        masked = dm._datasets["sales"]._df
    async with bind_semantic_context(_context("admin", "eu", roles=frozenset({"admin"}))):
        await dm.fetch_dataset("sales", conditions=_Q)
        raw = dm._datasets["sales"]._df
    assert masked is not None and len(masked) == 1
    assert masked["region"].isna().all()
    assert raw is not None and raw["region"].tolist() == ["eu"]


@pytest.mark.asyncio
async def test_e2e_semantic_dataset_truncation(models_dir: Path, duckdb_warehouse: Path, monkeypatch) -> None:
    """A result capped at 100 rows reports truncation in attrs, response and a visible warning."""
    duckdb = pytest.importorskip("duckdb")
    connection = duckdb.connect(str(duckdb_warehouse))
    try:
        connection.execute(
            "INSERT INTO sales.orders SELECT 100 + i, 10, 'tenant-a', 'eu', "
            "TIMESTAMP '2000-01-01' + INTERVAL (i) MONTH, 1.0 FROM range(150) AS t(i)"
        )
    finally:
        connection.close()
    _prepare(models_dir, duckdb_warehouse, monkeypatch)
    policy_path = models_dir / "orders.policy.yaml"
    policy_path.write_text(
        policy_path.read_text(encoding="utf-8").replace("limits: {default: 1000, max: 10000}", "limits: {default: 100, max: 100}"),
        encoding="utf-8",
    )
    toolkit = SemanticLayerToolkit(models_dir=models_dir, dialect="duckdb", dataplane_guard=_EvaluatorGuard())
    dm = _manager(toolkit)
    query = {"metrics": ["revenue"], "time_dimensions": [{"name": "order_date", "grain": "month"}]}
    async with bind_semantic_context(_context("first", "eu")):
        response = await dm.fetch_dataset("sales", conditions=query)
        frame = dm._datasets["sales"]._df
    assert response.get("error") is None, response
    assert len(frame) == 100
    attrs = frame.attrs["semantic"]
    assert attrs["truncated"] is True and attrs["row_count"] == 100
    assert response["semantic"]["truncated"] is True
    assert response["semantic"]["audit_id"] == attrs["audit_id"]
    assert response["inline_complete"] is True
    assert response["complete"] is False
    assert any("TRUNCATED" in warning for warning in response["warnings"])


@pytest.mark.asyncio
async def test_e2e_semantic_dataset_audited(models_dir: Path, duckdb_warehouse: Path, monkeypatch) -> None:
    """Each fetch writes exactly one audit entry, matching the response audit id."""
    toolkit = _toolkit(models_dir, duckdb_warehouse, monkeypatch)
    dm = _manager(toolkit)
    before = len(toolkit._ledger.entries)
    async with bind_semantic_context(_context("first", "eu")):
        first = await dm.fetch_dataset("sales", conditions=_Q)
        assert len(toolkit._ledger.entries) == before + 1
        second = await dm.fetch_dataset("sales", conditions=_Q)
    assert len(toolkit._ledger.entries) == before + 2
    audited = [entry.entry_id for entry in toolkit._ledger.entries][-2:]
    assert audited == [first["semantic"]["audit_id"], second["semantic"]["audit_id"]]


@pytest.mark.asyncio
async def test_e2e_semantic_dataset_bridged_identity(models_dir: Path, duckdb_warehouse: Path, monkeypatch) -> None:
    """The tool path bridges ``_permission_context``; without one the fetch fails closed."""
    dm = _manager(_toolkit(models_dir, duckdb_warehouse, monkeypatch))
    # DatasetManager registers its tools under the "dataset_" prefix.
    tool = dm.get_tool("dataset_fetch_dataset")
    assert tool is not None

    result = await tool.execute(name="sales", conditions=_Q, _permission_context=_context("first", "eu"))
    payload = result.result
    assert payload.get("error") is None, payload
    assert payload["semantic"]["model"] == "orders"
    assert _pctx_var.get(None) is None
    token = _pctx_var.set(_context("first", "eu"))
    try:
        assert dm._datasets["sales"]._df.to_dict("records") == [{"region": "eu", "revenue": 12.5}]
    finally:
        _pctx_var.reset(token)

    denied = await tool.execute(name="sales", conditions=_Q)
    # The error payload (status/success/result/error) is lifted into the ToolResult itself.
    assert denied.success is False
    assert "permission context is required" in str(denied.error)


def test_add_semantic_argument_validation(models_dir: Path, duckdb_warehouse: Path, monkeypatch) -> None:
    """Exactly one of toolkit or models_dir+dialect is accepted."""
    toolkit = _toolkit(models_dir, duckdb_warehouse, monkeypatch)
    dm = DatasetManager(generate_guide=False)
    with pytest.raises(ValueError):
        dm.add_semantic("sales", model="orders")
    with pytest.raises(ValueError):
        dm.add_semantic("sales", model="orders", models_dir=models_dir)
    with pytest.raises(ValueError):
        dm.add_semantic("sales", model="orders", dialect="duckdb")
    with pytest.raises(ValueError):
        dm.add_semantic("sales", model="orders", toolkit=toolkit, models_dir=models_dir, dialect="duckdb")
    assert "sales" not in dm._datasets


def test_add_semantic_missing_distribution(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing ai-parrot-semantic distribution raises an ImportError naming it."""
    monkeypatch.setitem(sys.modules, "parrot.semantic.dataset_source", None)
    dm = DatasetManager(generate_guide=False)
    with pytest.raises(ImportError, match="ai-parrot-semantic"):
        dm.add_semantic("sales", model="orders", models_dir="/nowhere", dialect="duckdb")
