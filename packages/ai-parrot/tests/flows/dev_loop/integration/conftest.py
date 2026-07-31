"""Fixtures and skip helpers for the dev-loop integration suite.

Two families of fixtures live here:

1. **Live-test fixtures** (pre-existing): exercise the full dispatch +
   flow path against a real ``claude`` CLI, real Redis, and (optionally) a
   real Jira sandbox. Gated behind the ``live`` pytest marker and skipped
   automatically when their prerequisites are missing.
2. **Deterministic FEAT-323 pool fixtures** (TASK-1864): fully in-process
   fakes (``FakeDispatcher``, ``FakeRedis``) plus a real temporary git
   repo (``git_sandbox``) for the 'isolated' mode tests. No network, no
   real CLIs, no ``live`` marker needed — these run in every CI pass.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import pytest

from parrot.flows.dev_loop.models import DevelopmentOutput, ResearchOutput


def _claude_cli_available() -> bool:
    return shutil.which("claude") is not None


def _redis_available() -> bool:
    try:
        import redis  # noqa: F401
        # Heuristic: presence of REDIS_URL env var or default localhost.
        return True
    except ImportError:
        return False


@pytest.fixture
def skip_unless_claude_available():
    """Skip the test when the ``claude`` CLI or API key is missing."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set; live test skipped")
    if not _claude_cli_available():
        pytest.skip("`claude` CLI not on PATH; live test skipped")


@pytest.fixture
def skip_unless_redis_available():
    """Skip when ``redis`` is not installed."""
    if not _redis_available():
        pytest.skip("`redis` package not available; live test skipped")


@pytest.fixture
def temp_worktree_base(tmp_path, monkeypatch) -> Iterator[str]:
    """Override ``WORKTREE_BASE_PATH`` to point at an ephemeral tmp dir."""
    monkeypatch.setattr(
        "parrot.flows.dev_loop.dispatcher.conf.WORKTREE_BASE_PATH",
        str(tmp_path),
    )
    monkeypatch.setattr(
        "parrot.flows.dev_loop.nodes.research.conf.WORKTREE_BASE_PATH",
        str(tmp_path),
    )
    yield str(tmp_path)


# ---------------------------------------------------------------------------
# FEAT-323 (TASK-1864): deterministic pool fixtures — no network, no live CLIs
# ---------------------------------------------------------------------------


def research_output(worktree_path: str, feat_id: str = "FEAT-323") -> ResearchOutput:
    """Build a minimal valid ``ResearchOutput`` for pool integration tests."""
    return ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/x.spec.md",
        feat_id=feat_id,
        branch_name="feat-323-pool-e2e",
        worktree_path=worktree_path,
        log_excerpts=[],
    )


def write_index(worktree_path: Path, feat_id: str, feature_slug: str, tasks: list) -> None:
    """Write a synthetic per-spec task index (FEAT-145 schema) under ``worktree_path``."""
    index_dir = worktree_path / "sdd" / "tasks" / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / f"{feature_slug}.json").write_text(
        json.dumps({"feature": feature_slug, "feature_id": feat_id, "tasks": tasks})
    )


class FakeDispatcher:
    """Fulfils the ``DevLoopCodeDispatcher`` Protocol; purely in-memory.

    Optionally programmed to fail a given ``task_id`` a fixed number of
    times (``fail_counts``) before succeeding — used to exercise the
    pool's single-retry-on-another-worker semantics deterministically.
    """

    def __init__(self, fail_counts: Optional[Dict[str, int]] = None) -> None:
        self.calls: List[Tuple[Optional[str], str, str]] = []
        self._fail_counts: Dict[str, int] = dict(fail_counts or {})

    async def dispatch(
        self, *, brief: Any, profile: Any, output_model: Any, run_id: str, node_id: str, cwd: str
    ) -> DevelopmentOutput:
        task_id = getattr(brief, "task_id", None)
        self.calls.append((task_id, node_id, cwd))
        remaining = self._fail_counts.get(task_id, 0)
        if remaining > 0:
            self._fail_counts[task_id] = remaining - 1
            raise RuntimeError(f"scheduled failure for {task_id}")
        return DevelopmentOutput(
            files_changed=[f"{task_id}.py"],
            commit_shas=[f"sha-{task_id}"],
            summary=task_id or "",
        )


class GitCommittingFakeDispatcher:
    """Like :class:`FakeDispatcher`, but really writes + commits into ``cwd``.

    Used by the 'isolated' mode end-to-end tests, where ``cwd`` is a real
    git sub-worktree and the test verifies actual merges/conflicts.

    Args:
        filename_for: ``task_id -> filename`` (default: ``"{task_id}.py"``).
            Pass a constant-returning callable to force two workers onto
            the SAME file and trigger a real merge conflict.
        fail_counts: Optional ``{task_id: times_to_fail}`` map.
    """

    def __init__(
        self,
        *,
        filename_for: Optional[Any] = None,
        fail_counts: Optional[Dict[str, int]] = None,
    ) -> None:
        self.calls: List[Tuple[Optional[str], str, str]] = []
        self._filename_for = filename_for or (lambda task_id: f"{task_id}.py")
        self._fail_counts: Dict[str, int] = dict(fail_counts or {})

    async def dispatch(
        self, *, brief: Any, profile: Any, output_model: Any, run_id: str, node_id: str, cwd: str
    ) -> DevelopmentOutput:
        task_id = getattr(brief, "task_id", None)
        self.calls.append((task_id, node_id, cwd))
        remaining = self._fail_counts.get(task_id, 0)
        if remaining > 0:
            self._fail_counts[task_id] = remaining - 1
            raise RuntimeError(f"scheduled failure for {task_id}")

        filename = self._filename_for(task_id)
        (Path(cwd) / filename).write_text(f"content from {task_id} via {node_id}\n")
        await _run_git("add", filename, cwd=Path(cwd))
        await _run_git("commit", "-m", f"{node_id}: implement {task_id}", cwd=Path(cwd))
        return DevelopmentOutput(files_changed=[filename], commit_shas=[node_id], summary=task_id or "")


async def _run_git(*args: str, cwd: Path) -> None:
    """Run ``git <args>`` in ``cwd``, asserting success (test helper)."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    assert proc.returncode == 0, (
        f"git {' '.join(args)} failed in {cwd}: {err.decode()}\n{out.decode()}"
    )


async def _write_and_commit(repo: Path, filename: str, content: str, message: str) -> None:
    (repo / filename).write_text(content)
    await _run_git("add", filename, cwd=repo)
    await _run_git("commit", "-m", message, cwd=repo)


@pytest.fixture
async def git_sandbox(tmp_path):
    """Real temp git repo: init, initial commit, feature branch checked out.

    Extracted (unchanged behaviour) from the TASK-1861
    ``test_worktree_manager.py`` fixture of the same name, so the 'isolated'
    mode integration tests share the exact same sandbox semantics.

    Returns ``(base_worktree, feature_branch, worktree_base_path)``.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    await _run_git("init", "-b", "main", cwd=repo)
    await _run_git("config", "user.email", "test@example.com", cwd=repo)
    await _run_git("config", "user.name", "Test", cwd=repo)
    await _write_and_commit(repo, "README.md", "hello\n", "initial commit")

    feature_branch = "feat-323-x"
    await _run_git("checkout", "-b", feature_branch, cwd=repo)

    return repo, feature_branch, tmp_path


class FakeRedis:
    """Minimal async fake supporting the SCAN-based discovery path.

    Only implements what :meth:`FlowStreamMultiplexer._discover_dispatch_streams`
    needs: ``scan(cursor=..., match=..., count=...)`` returning
    ``(next_cursor, keys)`` with ``next_cursor == 0`` terminating the scan.
    """

    def __init__(self, keys: List[str]) -> None:
        self._keys = keys

    async def scan(self, cursor: int = 0, match: Optional[str] = None, count: Optional[int] = None):
        import fnmatch

        pattern = match or "*"
        matched = [k for k in self._keys if fnmatch.fnmatch(k, pattern)]
        return 0, matched
