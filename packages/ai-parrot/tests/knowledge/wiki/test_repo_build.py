"""Hermetic behavioral tests for FEAT-672 repository wiki builds."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from parrot.knowledge.wiki.repo_build import LAST_GOOD_FILENAME, WikiBuildRunner
from parrot.knowledge.wiki.repo_cache import BuildOutcome


def _fake_wikitoolkit(tmp_path: Path, body: str) -> Path:
    """Create an executable fake that records the runner's argv."""
    executable = tmp_path / "wikitoolkit"
    executable.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    executable.chmod(0o755)
    return executable


async def test_build_runner_argv(tmp_path: Path) -> None:
    """Exact argv includes path, storage dir, lean-output flags, and quiet."""
    argv_file = tmp_path / "argv.json"
    executable = _fake_wikitoolkit(
        tmp_path,
        f"import json, pathlib, sys\npathlib.Path({str(argv_file)!r}).write_text(json.dumps(sys.argv[1:]))\n",
    )
    clone_dir, plane_dir = tmp_path / "clone", tmp_path / "plane"
    outcome = await WikiBuildRunner(executable=str(executable)).run(clone_dir, plane_dir)
    assert outcome.ok
    assert json.loads(argv_file.read_text()) == [
        "build",
        "--path",
        str(clone_dir),
        "--storage-dir",
        str(plane_dir),
        "--no-export",
        "--no-graph",
        "-q",
        "--force",
    ]


async def test_build_runner_omits_export_and_graph(tmp_path: Path) -> None:
    """A real local CLI build produces neither an OKF bundle nor graph.html."""
    clone_dir, plane_dir = tmp_path / "clone", tmp_path / "plane"
    clone_dir.mkdir()
    (clone_dir / "sample.py").write_text("def sample() -> str:\n    return 'ok'\n", encoding="utf-8")
    outcome = await WikiBuildRunner(timeout=30).run(clone_dir, plane_dir)
    assert outcome.ok, outcome.stderr_tail
    assert not list(plane_dir.rglob("graph.html"))
    assert not list(plane_dir.rglob("index.md"))


async def test_needs_force_after_incomplete_build(tmp_path: Path) -> None:
    """A started marker forces the next argv to include ``--force``."""
    argv_file = tmp_path / "argv.json"
    executable = _fake_wikitoolkit(
        tmp_path,
        f"import json, pathlib, sys\npathlib.Path({str(argv_file)!r}).write_text(json.dumps(sys.argv[1:]))\n",
    )
    runner = WikiBuildRunner(executable=str(executable))
    plane_dir = tmp_path / "plane"
    runner.mark_build_started(plane_dir)
    assert runner.needs_force(plane_dir)
    assert (await runner.run(tmp_path / "clone", plane_dir, quiet=False)).ok
    assert "--force" in json.loads(argv_file.read_text())


async def test_build_runner_never_parses_stdout(tmp_path: Path) -> None:
    """A navconfig-style stdout banner does not affect a successful outcome."""
    executable = _fake_wikitoolkit(tmp_path, "print('navconfig: {not json}')\n")
    outcome = await WikiBuildRunner(executable=str(executable)).run(tmp_path / "clone", tmp_path / "plane")
    assert outcome.ok
    assert outcome.returncode == 0


async def test_build_runner_timeout_kills_child(tmp_path: Path) -> None:
    """A hung child is terminated, reaped, and reported as timed out."""
    pid_file = tmp_path / "pid"
    executable = _fake_wikitoolkit(
        tmp_path,
        f"import os, pathlib, time\npathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()))\ntime.sleep(60)\n",
    )
    outcome = await WikiBuildRunner(executable=str(executable), timeout=0.05).run(
        tmp_path / "clone", tmp_path / "plane"
    )
    assert outcome.timed_out
    child_pid = int(pid_file.read_text())
    for _ in range(50):
        try:
            import os

            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        await asyncio.sleep(0.01)
    else:
        pytest.fail("timed-out wikitoolkit child survived")


def test_last_good_marker_roundtrip(tmp_path: Path) -> None:
    """Only a successful outcome makes a plane usable."""
    runner = WikiBuildRunner()
    assert runner.last_good(tmp_path) is None
    assert runner.needs_force(tmp_path)
    runner.mark_build_started(tmp_path)
    assert runner.last_good(tmp_path) is None
    runner.mark_last_good(
        tmp_path,
        BuildOutcome(ok=True, returncode=0, timed_out=False, duration_s=0.1, stderr_tail=""),
    )
    assert runner.last_good(tmp_path) is not None
    assert json.loads((tmp_path / LAST_GOOD_FILENAME).read_text())["state"] == "complete"
