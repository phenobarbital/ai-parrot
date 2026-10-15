"""Registry + conformance (FEAT-540 M7)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from parrot.knowledge.graphindex.backends import (
    GraphBackendSpec,
    NullPersistence,
    create_graph_persistence,
    graph_backend_names,
    graph_backend_spec,
    register_graph_backend,
)
from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence
from parrot.knowledge.graphindex.protocols import GraphPersistence, SourceCoherencePersistence
from parrot.knowledge.graphindex.schema import NodeKind, UniversalNode

from .persistence_conformance import (
    ALL_CASES,
    STATELESS_CASES,
    case_errors_propagate,
    case_slice_atomic_idempotent,
)


def _ctx(tenant: str = "t1") -> Any:
    ctx = MagicMock()
    ctx.tenant_id = tenant
    return ctx


def test_builtin_names() -> None:
    assert graph_backend_names() == ("sqlite", "null", "postgres", "arangodb")


def test_builtin_capabilities() -> None:
    assert "source_coherence" in graph_backend_spec("sqlite").capabilities
    assert "temporal" in graph_backend_spec("postgres").capabilities
    assert graph_backend_spec("postgres").extra == "graphindex-postgres"


@pytest.mark.asyncio
async def test_unknown_backend() -> None:
    with pytest.raises(ValueError, match="known"):
        await create_graph_persistence("nope")


@pytest.mark.asyncio
async def test_missing_required_option_is_named() -> None:
    with pytest.raises(ValueError, match="db_dir"):
        await create_graph_persistence("sqlite")


@pytest.mark.asyncio
async def test_create_sqlite_and_null(tmp_path: Path) -> None:
    sqlite = await create_graph_persistence("sqlite", db_dir=tmp_path)
    assert isinstance(sqlite, SQLitePersistence)
    assert isinstance(sqlite, GraphPersistence)
    assert isinstance(sqlite, SourceCoherencePersistence)
    null = await create_graph_persistence("null")
    assert isinstance(null, NullPersistence)
    assert isinstance(null, GraphPersistence)


@pytest.mark.asyncio
async def test_register_custom_backend_and_missing_driver() -> None:
    register_graph_backend(
        GraphBackendSpec(name="_ghost", factory="definitely_not_installed_mod:make", extra="ghost-extra")
    )
    try:
        with pytest.raises(ImportError, match="ghost-extra"):
            await create_graph_persistence("_ghost")
    finally:
        from parrot.knowledge.graphindex import backends

        backends._REGISTRY.pop("_ghost", None)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ALL_CASES, ids=lambda c: c.__name__)
async def test_sqlite_conformance(case: Any, tmp_path: Path) -> None:
    persistence = SQLitePersistence(tmp_path)
    await case(persistence, _ctx())
    await persistence.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", STATELESS_CASES, ids=lambda c: c.__name__)
async def test_null_conformance(case: Any) -> None:
    await case(NullPersistence(), _ctx())


@pytest.mark.asyncio
async def test_null_slice_idempotent() -> None:
    await case_slice_atomic_idempotent(NullPersistence(), _ctx(), stores=False)


@pytest.mark.asyncio
async def test_sqlite_errors_propagate(tmp_path: Path) -> None:
    persistence = SQLitePersistence(tmp_path)
    persistence._db_dir = tmp_path / "missing" / "dir"  # connecting to a nonexistent directory must raise
    await case_errors_propagate(persistence, _ctx())


@pytest.mark.asyncio
async def test_null_apply_update_returns_receipt_and_refuses_revert() -> None:
    from parrot.knowledge.graphindex.schema import GraphUpdate

    null = NullPersistence()
    node = UniversalNode(node_id="a", kind=NodeKind.SYMBOL, title="a", source_uri="x.py")
    r1 = await null.apply_update(_ctx(), GraphUpdate(nodes=[node], agent_id="a", asserted_by="a"))
    r2 = await null.apply_update(_ctx(), GraphUpdate(nodes=[node], agent_id="a", asserted_by="a"))
    assert r1.commit_id != r2.commit_id and r1.node_ids == ["a"]
    assert "error" in await null.revert_commit(_ctx(), r1.commit_id)
    assert await null.get_commit(_ctx(), r1.commit_id) is None


@pytest.mark.asyncio
async def test_sqlite_file_hashes_sorted(tmp_path: Path) -> None:
    persistence = SQLitePersistence(tmp_path)
    ctx = _ctx()
    assert await persistence.file_hashes(ctx) == []
    nodes = [
        UniversalNode(
            node_id=f"m{name}",
            kind=NodeKind.SYMBOL,
            title=name,
            source_uri=name,
            domain_tags={"mtime": 1.0, "sha1": f"sha-{name}"},
        )
        for name in ("b.py", "a.py", "c.py")
    ]
    await persistence.persist_graph(ctx, nodes, [])
    assert await persistence.file_hashes(ctx) == [("a.py", "sha-a.py"), ("b.py", "sha-b.py"), ("c.py", "sha-c.py")]
