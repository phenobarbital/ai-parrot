"""Dispatch through the registry (FEAT-540 M7)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from parrot.knowledge.graphindex.backends import (
    GraphBackendSpec,
    register_graph_backend,
    _REGISTRY,
)
from parrot.knowledge.graphindex.factory import build_graph_memory_toolkit
from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence
from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.runtime import persistence_for_project

SRC = Path(__file__).resolve().parents[3] / "src" / "parrot"
# loader.py:_make_persistence is outside TASK-4321's file list (tracked for a follow-up task).
ALLOWED = {"backends.py", "persist_sqlite.py", "loader.py"}


def _config() -> WikiProjectConfig:
    return WikiProjectConfig(wiki_name="demo", store="memory")


@pytest.mark.asyncio
async def test_persistence_for_project_sqlite(tmp_path: Path) -> None:
    config = _config()
    persistence = await persistence_for_project(config, tmp_path)
    try:
        assert isinstance(persistence, SQLitePersistence)
    finally:
        await persistence.close()


@pytest.mark.asyncio
async def test_persistence_for_project_bad_project_options(tmp_path: Path, monkeypatch) -> None:
    config = _config()
    monkeypatch.setattr(config, "backend", "bogus_proj", raising=False)
    snapshot = dict(_REGISTRY)
    try:
        register_graph_backend(
            GraphBackendSpec(name="bogus_proj", factory="x:y", project_options="not-a-path")
        )
        with pytest.raises(ValueError, match="project_options"):
            await persistence_for_project(config, tmp_path)
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(snapshot)


@pytest.mark.asyncio
async def test_toolkit_requires_db_dir_for_sqlite() -> None:
    with pytest.raises(ValueError, match="db_dir"):
        await build_graph_memory_toolkit()


@pytest.mark.asyncio
async def test_toolkit_conflicting_db_dir_and_backend(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="conflicts"):
        await build_graph_memory_toolkit(db_dir=tmp_path, backend="postgres")


@pytest.mark.asyncio
async def test_toolkit_unknown_backend() -> None:
    with pytest.raises(ValueError, match="Unknown graph backend"):
        await build_graph_memory_toolkit(backend="nope")


@pytest.mark.asyncio
async def test_toolkit_db_dir_alone_is_sqlite(tmp_path: Path) -> None:
    toolkit = await build_graph_memory_toolkit(db_dir=tmp_path)
    assert toolkit is not None


def test_no_direct_sqlite_persistence_construction() -> None:
    offenders = []
    for path in SRC.rglob("*.py"):
        if path.name in ALLOWED:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "SQLitePersistence"
            ):
                offenders.append(f"{path}:{node.lineno}")
    assert not offenders, offenders
