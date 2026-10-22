"""Hermetic git-repo tests for the baseline-aware verdict (FEAT-699, TASK-4448)."""

import subprocess
from pathlib import Path

import pytest

from parrot.flows.dev_loop.test_scope import baseline
from parrot.flows.dev_loop.test_scope.baseline import classify_failures, gate_failed, summarize

PASS = "def test_x():\n    assert True\n"
FAIL = "def test_x():\n    assert False\n"


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


@pytest.fixture
def hermetic_repo(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    _git(repo, "init", "-q")
    (repo / "tests" / "test_a.py").write_text(PASS)
    (repo / "tests" / "test_b.py").write_text(FAIL)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "branch")
    (repo / "tests" / "test_a.py").write_text(FAIL)
    (repo / "tests" / "test_c.py").write_text(FAIL)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "branch")
    return repo, base


def _worktrees(repo: Path) -> list[str]:
    return [ln for ln in _git(repo, "worktree", "list").splitlines() if "baseline-" in ln]


def test_new_red_vs_baseline_red(hermetic_repo, tmp_path):
    repo, base = hermetic_repo
    ids = ["tests/test_a.py::test_x", "tests/test_b.py::test_x"]
    verdicts = classify_failures(
        worktree=repo, base_ref=base, failed_nodeids=ids, timeout_s=120, scratch=tmp_path / "s"
    )
    assert [v.status for v in verdicts] == ["new_red", "baseline_red"]
    assert gate_failed(verdicts)
    assert summarize(verdicts) == {"new_red": 1, "baseline_red": 1}


def test_branch_only_file_is_new_red(hermetic_repo, tmp_path):
    repo, base = hermetic_repo
    (tmp_path / "s").mkdir()
    verdicts = classify_failures(
        worktree=repo, base_ref=base, failed_nodeids=["tests/test_c.py::test_x"], timeout_s=120, scratch=tmp_path / "s"
    )
    assert verdicts[0].status == "new_red"
    assert verdicts[0].detail == "test only on branch"


def test_unbuildable_base_is_unknown(hermetic_repo, tmp_path):
    repo, _ = hermetic_repo
    verdicts = classify_failures(
        worktree=repo, base_ref="no-such-ref", failed_nodeids=["tests/test_a.py::test_x"], timeout_s=60
    )
    assert [v.status for v in verdicts] == ["unknown"]
    assert gate_failed(verdicts)


def test_empty_input(hermetic_repo):
    repo, base = hermetic_repo
    assert classify_failures(worktree=repo, base_ref=base, failed_nodeids=[], timeout_s=1) == ()
    assert not gate_failed(())


def test_non_pytest_failure_is_unknown_without_checkout(hermetic_repo, monkeypatch):
    repo, base = hermetic_repo

    def fail_if_called(**kwargs):
        raise AssertionError("baseline checkout must not be created")

    monkeypatch.setattr(baseline, "prepare_baseline_checkout", fail_if_called)
    verdicts = classify_failures(
        worktree=repo,
        base_ref=base,
        failed_nodeids=["src/example.test.ts::runs"],
        timeout_s=60,
        runner_of={"src/example.test.ts::runs": "vitest"},
    )
    assert [(verdict.status, verdict.detail) for verdict in verdicts] == [("unknown", "baseline only supports pytest")]


def test_checkout_always_removed(hermetic_repo, tmp_path):
    repo, base = hermetic_repo
    classify_failures(
        worktree=repo, base_ref=base, failed_nodeids=["tests/test_b.py::test_x"], timeout_s=120, scratch=tmp_path / "s"
    )
    assert _worktrees(repo) == []
    classify_failures(worktree=repo, base_ref="bad", failed_nodeids=["tests/test_b.py::test_x"], timeout_s=5)
    assert _worktrees(repo) == []


def test_baseline_checkout_still_refuses_unbuilt_extension(hermetic_repo, tmp_path, monkeypatch):
    """An unpaired source in the main checkout is still fatal and the checkout is removed."""
    from parrot.flows.dev_loop.native_artifacts import MissingArtifact, NativeSyncReport

    repo, base = hermetic_repo
    seen = {}

    def fake_sync(*, main_root, target, autobuild=True, **kwargs):
        seen["autobuild"] = autobuild
        return NativeSyncReport(
            enabled=True,
            missing=[MissingArtifact(group="core", reason="unpaired_source", detail="pkg/ext.pyx")],
        )

    monkeypatch.setattr(baseline, "sync_native_artifacts", fake_sync)
    scratch = tmp_path / "s"
    scratch.mkdir()
    with pytest.raises(baseline.BaselineUnavailable, match="no compiled extension for pkg/ext.pyx"):
        baseline.prepare_baseline_checkout(worktree=repo, base_ref=base, scratch=scratch)
    assert seen["autobuild"] is False
    assert _worktrees(repo) == []
    assert not any(scratch.iterdir())


def test_baseline_checkout_tolerates_non_source_missing_artifacts(hermetic_repo, tmp_path, monkeypatch):
    """`no_match` / `abi_mismatch` were invisible to the pre-FEAT-722 check and stay non-fatal.

    A main checkout that never built navrules, or one whose `.so` files target another
    interpreter, must still produce a usable baseline checkout — otherwise every
    baseline-classified failure silently becomes `unknown`.
    """
    from parrot.flows.dev_loop.native_artifacts import MissingArtifact, NativeSyncReport

    repo, base = hermetic_repo

    def fake_sync(*, main_root, target, autobuild=True, **kwargs):
        return NativeSyncReport(
            enabled=True,
            missing=[
                MissingArtifact(group="navrules-pyo3", reason="no_match", detail="packages/navrules/**/*.so"),
                MissingArtifact(group="cython-core", reason="abi_mismatch", detail="pkg/ext.cpython-399.so"),
            ],
        )

    monkeypatch.setattr(baseline, "sync_native_artifacts", fake_sync)
    scratch = tmp_path / "s"
    scratch.mkdir()
    target = baseline.prepare_baseline_checkout(worktree=repo, base_ref=base, scratch=scratch)
    assert target.is_dir()
    baseline.remove_baseline_checkout(repo, target)
