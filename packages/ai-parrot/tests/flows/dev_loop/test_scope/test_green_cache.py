"""Tests for the content-addressed green cache (FEAT-699 Module 4)."""

import multiprocessing
import subprocess
from pathlib import Path

import pytest

from parrot.flows.dev_loop.test_scope import green_cache as gc
from parrot.flows.dev_loop.test_scope.datatypes import TestTarget
from parrot.flows.dev_loop.test_scope.impact import ImportIndex
from parrot.flows.dev_loop.test_scope.planner import build_plan
from parrot.flows.dev_loop.test_scope.policy import ScopePolicy

TEST = "packages/a/tests/test_x.py"
NS = gc.cache_namespace(feature_id="FEAT-1", base_ref="origin/dev", contract_digest="d")


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "packages/a/src/amod").mkdir(parents=True)
    (root / "packages/a/tests").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[tool.x]\n")
    (root / "packages/a/pyproject.toml").write_text("[project]\nname='a'\n")
    (root / "packages/a/src/amod/__init__.py").write_text("")
    (root / "packages/a/src/amod/core.py").write_text("V = 1\n")
    (root / "packages/a/tests/conftest.py").write_text("")
    (root / TEST).write_text("from amod.core import V\n\ndef test_v():\n    assert V\n")
    (root / "packages/a/tests/test_y.py").write_text("def test_y():\n    pass\n")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init")
    return root


def _plan(root: Path, *paths: str):
    targets = [TestTarget(path=p, distribution="a", reason="declared") for p in paths]
    return build_plan(targets, tier="merge", worktree=root, policy=ScopePolicy())


def _green(root: Path, plan, paths=(TEST,), **kw):
    nodes = [(f"{p}::t", "passed") for p in paths]
    gc.record_green(root, namespace=NS, plan=plan, nodes=nodes, **kw)


def test_second_run_is_cached(git_repo):
    plan = _plan(git_repo, TEST, "packages/a/tests/test_y.py")
    _green(git_repo, plan, (TEST, "packages/a/tests/test_y.py"))
    again = gc.filter_cached(git_repo, _plan(git_repo, TEST), namespace=NS)
    assert again.cached == (TEST,)
    assert all(TEST not in a for inv in again.invocations for a in inv.argv)
    assert any("green cache: skipped 1" in n for n in again.notes)


@pytest.mark.parametrize(
    "edit",
    [TEST, "packages/a/tests/conftest.py", "packages/a/pyproject.toml", "pyproject.toml", "packages/a/src/amod/core.py"],
)
def test_input_change_invalidates(git_repo, edit):
    _green(git_repo, _plan(git_repo, TEST))
    with (git_repo / edit).open("a") as fh:
        fh.write("\n# edit\n")
    assert gc.filter_cached(git_repo, _plan(git_repo, TEST), namespace=NS).cached == ()


def test_marker_change_invalidates(git_repo):
    _green(git_repo, _plan(git_repo, TEST))
    plan = build_plan(
        [TestTarget(path=TEST, distribution="a", reason="declared")],
        tier="merge",
        worktree=git_repo,
        policy=ScopePolicy(marker_expression="other"),
    )
    assert gc.filter_cached(git_repo, plan, namespace=NS).cached == ()


def test_unmapped_nodes_never_recorded(git_repo):
    _green(git_repo, _plan(git_repo, TEST), unmapped=1)
    assert gc.filter_cached(git_repo, _plan(git_repo, TEST), namespace=NS).cached == ()


def test_red_removes_entry_and_baseline_red_allowed(git_repo):
    plan = _plan(git_repo, TEST)
    _green(git_repo, plan)
    gc.record_green(git_repo, namespace=NS, plan=plan, nodes=[(f"{TEST}::t", "failed")])
    assert gc.filter_cached(git_repo, plan, namespace=NS).cached == ()
    gc.record_green(git_repo, namespace=NS, plan=plan, nodes=[(f"{TEST}::t", "failed")], baseline_reds=[f"{TEST}::t"])
    assert gc.filter_cached(git_repo, plan, namespace=NS).cached == (TEST,)


def test_no_nodes_not_recorded(git_repo):
    gc.record_green(git_repo, namespace=NS, plan=_plan(git_repo, TEST), nodes=[])
    assert gc.filter_cached(git_repo, _plan(git_repo, TEST), namespace=NS).cached == ()


def test_namespace_change_resets(git_repo):
    _green(git_repo, _plan(git_repo, TEST))
    other = gc.cache_namespace(feature_id="FEAT-2", base_ref="origin/dev", contract_digest="d")
    assert gc.filter_cached(git_repo, _plan(git_repo, TEST), namespace=other).cached == ()
    gc.record_green(git_repo, namespace=other, plan=_plan(git_repo, "packages/a/tests/test_y.py"),
                    nodes=[("packages/a/tests/test_y.py::t", "passed")])
    assert gc.filter_cached(git_repo, _plan(git_repo, TEST), namespace=NS).cached == ()


def test_directory_never_cached(git_repo):
    plan = _plan(git_repo, "packages/a/tests")
    gc.record_green(git_repo, namespace=NS, plan=plan, nodes=[(f"{TEST}::t", "passed")])
    assert gc.filter_cached(git_repo, plan, namespace=NS).cached == ()


def test_invalidate_and_corrupt_store(git_repo):
    _green(git_repo, _plan(git_repo, TEST))
    gc.invalidate(git_repo)
    assert gc.filter_cached(git_repo, _plan(git_repo, TEST), namespace=NS).cached == ()
    git_dir = Path(subprocess.run(["git", "rev-parse", "--absolute-git-dir"], cwd=git_repo, capture_output=True,
                                  text=True).stdout.strip())
    (git_dir / gc.CACHE_FILENAME).write_text("{not json")
    assert gc.filter_cached(git_repo, _plan(git_repo, TEST), namespace=NS).cached == ()


def test_manifest_unresolvable_is_none(git_repo):
    index = ImportIndex.build(git_repo)
    assert gc.execution_manifest(git_repo, "packages/a/tests/missing.py", marker_expression="m", index=index) is None


def _worker(root: str, path: str) -> None:
    r = Path(root)
    gc.record_green(r, namespace=NS, plan=_plan(r, path), nodes=[(f"{path}::t", "passed")])


def test_concurrent_record_green(git_repo):
    paths = []
    for i in range(6):
        p = f"packages/a/tests/test_c{i}.py"
        (git_repo / p).write_text("def test_c():\n    pass\n")
        paths.append(p)
    ctx = multiprocessing.get_context("fork")
    procs = [ctx.Process(target=_worker, args=(str(git_repo), p)) for p in paths]
    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join()
    cached = gc.filter_cached(git_repo, _plan(git_repo, *paths), namespace=NS).cached
    assert set(cached) == set(paths)
