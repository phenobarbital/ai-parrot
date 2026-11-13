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
