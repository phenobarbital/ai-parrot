"""Tests for test_scope.impact (FEAT-563 TASK-3307)."""

from __future__ import annotations

from pathlib import Path

from parrot.flows.dev_loop.test_scope.impact import (
    ImportIndex,
    detect_core,
    impacted_tests,
    module_name_for,
    source_fanin,
)
from parrot.flows.dev_loop.test_scope.policy import ScopePolicy


def _write(root: Path, rel: str, text: str = "") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def _tree(tmp_path: Path) -> Path:
    """dist a: pa/base.py imported by pa/impl.py; dist b: pb/use.py imports pa.base."""
    _write(tmp_path, "packages/a/src/pa/__init__.py")
    _write(tmp_path, "packages/a/src/pa/base.py", "X = 1\n")
    _write(tmp_path, "packages/a/src/pa/impl.py", "from .base import X\n")
    _write(tmp_path, "packages/b/src/pb/use.py", "from pa.base import X\n")
    _write(tmp_path, "packages/a/tests/test_impl.py", "import pa.impl\n")
    _write(tmp_path, "packages/b/tests/test_use.py", "from pb import use\n")
    _write(tmp_path, "tests/test_root.py", "import pa.base\n")
    return tmp_path


def test_module_name_for_src_layout_and_tools_redirect():
    assert module_name_for("packages/a/src/pa/base.py") == "pa.base"
    assert module_name_for("packages/a/src/pa/__init__.py") == "pa"
    assert module_name_for("docs/x.py") is None


def test_impacted_tests_direct_and_one_hop(tmp_path):
    root = _tree(tmp_path)
    index = ImportIndex.build(root)
    direct = impacted_tests(index, ["packages/a/src/pa/base.py"], worktree=root, depth=0)
    assert "tests/test_root.py" in direct
    one_hop = impacted_tests(index, ["packages/a/src/pa/base.py"], worktree=root, depth=1)
    assert {"packages/a/tests/test_impl.py", "packages/b/tests/test_use.py"} <= set(one_hop)


def test_core_detected_by_source_fanin_not_test_count(tmp_path):
    root = _tree(tmp_path)
    hits = detect_core(
        ImportIndex.build(root),
        ["packages/a/src/pa/base.py"],
        policy=ScopePolicy(core_fanin_threshold=2, core_paths=()),
    )
    assert hits and hits[0].distributions == ("a", "b")


def test_core_paths_force_escalation(tmp_path):
    root = _tree(tmp_path)
    hits = detect_core(
        ImportIndex.build(root),
        ["packages/a/src/pa/impl.py"],
        policy=ScopePolicy(core_fanin_threshold=999, core_paths=("packages/a/src/pa/impl.py",)),
    )
    assert hits[0].forced is True


def test_source_fanin_is_cycle_safe(tmp_path):
    """Two modules importing each other: source_fanin must terminate with a finite count."""
    _write(tmp_path, "packages/c/src/pc/__init__.py")
    _write(tmp_path, "packages/c/src/pc/m1.py", "from .m2 import y\n")
    _write(tmp_path, "packages/c/src/pc/m2.py", "from .m1 import x\n")
    index = ImportIndex.build(tmp_path)
    fanin, dists = source_fanin(index, "pc.m1")
    assert fanin == 1
    assert dists == frozenset({"c"})


def test_index_skips_syntax_errors(tmp_path):
    root = _tree(tmp_path)
    _write(root, "tests/test_broken.py", "def (\n")
    index = ImportIndex.build(root)
    assert "tests/test_broken.py" in index.skipped
