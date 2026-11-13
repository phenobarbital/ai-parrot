"""Tests for the compiled procedure index and the plane (FEAT-891)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from parrot.knowledge.wiki.procedure import index as index_mod
from parrot.knowledge.wiki.procedure.index import compile_index, is_stale, publish_index, read_index
from parrot.knowledge.wiki.procedure.models import (
    INDEX_SCHEMA_VERSION,
    PLANE_DIR,
    GuardSpec,
    ProbeCheck,
    ProcedureSpec,
    ScopeArg,
)
from parrot.knowledge.wiki.procedure.plane import ProcedurePlane
from parrot.knowledge.wiki.store import SQLiteWikiStore
from parrot.sdd.scripts import procedure_advice

COSTS = {"task.status": "local", "pr.open": "remote"}


def _source(root: Path, name: str = "sdd-workflow.yaml", text: str = "graph: sdd\n") -> Path:
    """Write sdd/procedures/<name> under root and return its path."""
    path = root / "sdd" / "procedures" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _specs() -> list[ProcedureSpec]:
    """One mandatory node with an entry guard (scope task argv 0) and a `task.status` precondition, one plain node."""
    return [
        ProcedureSpec(
            id="sdd:close-task",
            title="Close task",
            kind="command",
            mode="mandatory",
            command="parrot sdd task close <TASK>",
            advice="Use the close command.",
            preconditions=[ProbeCheck(probe="task.status", expect="done"), ProbeCheck(probe="mystery")],
            guards=[
                GuardSpec(
                    kind="entry",
                    executable="parrot",
                    argv_prefix=["sdd", "task", "close"],
                    scope={"task": ScopeArg(argv=0), "base": ScopeArg(flag="--base|-B")},
                )
            ],
        ),
        ProcedureSpec(id="sdd:plain", title="Plain", kind="skill"),
    ]


def test_index_atomic_and_generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Publish goes through a temp file + os.replace; generation is stable for equal input."""
    source = _source(tmp_path)
    doc = compile_index(_specs(), [source], root=tmp_path, probe_costs=COSTS)
    again = compile_index(_specs(), [source], root=tmp_path, probe_costs=COSTS)
    assert doc["generation"] == again["generation"]

    calls: list[tuple[str, str]] = []
    real_replace = os.replace

    def wrapper(src: str, dst: str) -> None:
        calls.append((str(src), str(dst)))
        real_replace(src, dst)

    monkeypatch.setattr(index_mod.os, "replace", wrapper)
    plane_dir = tmp_path / PLANE_DIR
    target = publish_index(plane_dir, doc)

    assert len(calls) == 1
    src, dst = calls[0]
    assert Path(src).parent == plane_dir and src != dst and Path(dst) == target
    assert [p.name for p in plane_dir.iterdir()] == [target.name]
    assert read_index(plane_dir) == doc


def test_is_stale_on_source_change(tmp_path: Path) -> None:
    """Editing a manifest, deleting it, or adding an unlisted one makes the index stale."""
    source = _source(tmp_path)
    doc = compile_index(_specs(), [source], root=tmp_path, probe_costs=COSTS)
    assert not is_stale(doc, root=tmp_path)
    assert is_stale(None, root=tmp_path)

    extra = _source(tmp_path, "other.yaml")
    assert is_stale(doc, root=tmp_path)
    extra.unlink()
    assert not is_stale(doc, root=tmp_path)

    source.write_text("graph: changed\n", encoding="utf-8")
    assert is_stale(doc, root=tmp_path)
    source.unlink()
    assert is_stale(doc, root=tmp_path)


def test_read_index_rejects_other_versions(tmp_path: Path) -> None:
    """A missing, unparsable or wrong-version file reads as None."""
    assert read_index(tmp_path) is None
    (tmp_path / index_mod.INDEX_FILE).write_text("{not json", encoding="utf-8")
    assert read_index(tmp_path) is None
    (tmp_path / index_mod.INDEX_FILE).write_text('{"schema_version": 99}', encoding="utf-8")
    assert read_index(tmp_path) is None
    (tmp_path / index_mod.INDEX_FILE).write_text(f'{{"schema_version": {INDEX_SCHEMA_VERSION}}}', encoding="utf-8")
    assert read_index(tmp_path) == {"schema_version": INDEX_SCHEMA_VERSION}


def test_index_contract(tmp_path: Path) -> None:
    """The stdlib hook reader accepts exactly what publish_index writes."""
    assert procedure_advice.INDEX_SCHEMA_VERSION == INDEX_SCHEMA_VERSION
    assert procedure_advice.PLANE_DIR == PLANE_DIR and procedure_advice.INDEX_FILE == index_mod.INDEX_FILE
    source = _source(tmp_path)
    doc = compile_index(_specs(), [source], root=tmp_path, probe_costs=COSTS)
    publish_index(tmp_path / PLANE_DIR, doc)

    loaded = procedure_advice.load_index(tmp_path)
    assert loaded == doc
    assert loaded is not None
    assert loaded["guards"], "expected at least one guard"
    for guard in loaded["guards"]:
        assert {"procedure", "kind", "executable", "argv_prefix", "path_globs", "scope"} <= set(guard)
    assert loaded["guards"][0]["scope"] == {"task": {"argv": 0}, "base": {"flag": "--base|-B"}}
    pre = loaded["procedures"]["sdd:close-task"]["preconditions"]
    for check in pre:
        assert {"probe", "expect", "args", "cost"} <= set(check)
    assert [c["cost"] for c in pre] == ["local", "remote"]


async def test_plane_build_idempotent(tmp_path: Path) -> None:
    """Two builds preserve pages and edges; a dropped source loses its page."""
    (tmp_path / ".git").mkdir()
    first_source = _source(tmp_path, "first.yaml")
    second_source = _source(tmp_path, "second.yaml")
    first, second = _specs()
    first = first.model_copy(
        update={
            "origin_path": first_source.relative_to(tmp_path).as_posix(),
            "requires_procedures": [second.id],
        }
    )
    second = second.model_copy(update={"origin_path": second_source.relative_to(tmp_path).as_posix()})
    plane = ProcedurePlane(tmp_path / PLANE_DIR)

    assert await plane.build([first, second], [first_source, second_source], root=tmp_path, probe_costs=COSTS) == {
        "pages": 2,
        "edges": 1,
        "sources": 2,
    }
    store = SQLiteWikiStore(plane.plane_dir / "wiki.db", wiki_name="procedure")
    page_ids = [page["concept_id"] for page in await store.dump_pages()]
    edges = await store.dump_edges()
    assert (await store.neighbors(first.id, rel="requires", direction="out"))[0]["provenance"] == "sdd"

    await plane.build([first, second], [first_source, second_source], root=tmp_path, probe_costs=COSTS)
    assert [page["concept_id"] for page in await store.dump_pages()] == page_ids
    assert await store.dump_edges() == edges

    await plane.build([first], [first_source], root=tmp_path, probe_costs=COSTS)
    assert [page["concept_id"] for page in await store.dump_pages()] == [first.id]


async def test_plane_specs_round_trip(tmp_path: Path) -> None:
    """The stored JSON round-trips every procedure spec sorted by id."""
    source = _source(tmp_path)
    specs = [
        spec.model_copy(update={"origin_path": source.relative_to(tmp_path).as_posix()})
        for spec in reversed(_specs())
    ]
    plane = ProcedurePlane(tmp_path / PLANE_DIR)

    assert await plane.specs() == []
    await plane.build(specs, [source], root=tmp_path, probe_costs=COSTS)
    assert await plane.specs() == sorted(specs, key=lambda spec: spec.id)


async def test_plane_publishes_index_last(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A store-write failure prevents publication of a new procedure index."""
    source = _source(tmp_path)
    spec = _specs()[0].model_copy(update={"origin_path": source.relative_to(tmp_path).as_posix()})
    plane = ProcedurePlane(tmp_path / PLANE_DIR)

    async def fail_add_edges(self: SQLiteWikiStore, edges: list[tuple]) -> int:
        raise OSError("injected edge write failure")

    monkeypatch.setattr(SQLiteWikiStore, "add_edges", fail_add_edges)
    with pytest.raises(OSError, match="injected edge write failure"):
        await plane.build([spec], [source], root=tmp_path, probe_costs=COSTS)
    assert read_index(plane.plane_dir) is None


def test_for_root_uses_shared_root(tmp_path: Path) -> None:
    """for_root resolves a repository's shared procedure-plane directory."""
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)

    plane = ProcedurePlane.for_root(repo / "sub")
    assert plane is not None
    assert plane.plane_dir == repo / PLANE_DIR
