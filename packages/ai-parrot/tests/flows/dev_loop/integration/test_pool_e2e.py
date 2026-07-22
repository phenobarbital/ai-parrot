"""End-to-end integration tests for the FEAT-323 dev-agent pool (TASK-1864).

Covers the COMPOSED scenarios from spec §4 "Integration Tests" that the
unit tests of TASK-1857..1863 do not exercise together: the full
``DevelopmentNode`` pool orchestration in 'shared' and 'isolated' modes,
merge-conflict resolution, partial completion, and the pre-FEAT-323
single-agent path (regression, run through the same node used for pool
mode). No network, no real CLIs, no Redis — everything here is
deterministic and in-process (real git only for the 'isolated' scenarios).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot import conf
from parrot.flows.dev_loop.models import DevAgentPoolConfig, DevAgentSpec, DevelopmentOutput
from parrot.flows.dev_loop.nodes.development import DevelopmentNode

from .conftest import FakeDispatcher, GitCommittingFakeDispatcher, _run_git, research_output, write_index


class DepCheckingGitDispatcher:
    """A ``GitCommittingFakeDispatcher`` that snapshots what a designated
    task can see in its ``cwd`` before committing.

    Used to prove that, in 'isolated' mode across multiple waves, a
    later-wave task is dispatched into a sub-worktree that already contains
    every earlier wave's *merged* output — even output produced by a
    different worker (regression for the stale-sub-worktree bug).
    """

    def __init__(self, *, check_task: str, expect_files: List[str]) -> None:
        self.calls: List[Tuple[Optional[str], str, str]] = []
        self._check_task = check_task
        self._expect_files = expect_files
        self.seen: Optional[dict] = None

    async def dispatch(
        self, *, brief: Any, profile: Any, output_model: Any, run_id: str, node_id: str, cwd: str
    ) -> DevelopmentOutput:
        task_id = getattr(brief, "task_id", None)
        self.calls.append((task_id, node_id, cwd))
        if task_id == self._check_task:
            self.seen = {f: (Path(cwd) / f).exists() for f in self._expect_files}
        filename = f"{task_id}.py"
        (Path(cwd) / filename).write_text(f"content from {task_id} via {node_id}\n")
        await _run_git("add", filename, cwd=Path(cwd))
        await _run_git("commit", "-m", f"{node_id}: implement {task_id}", cwd=Path(cwd))
        return DevelopmentOutput(files_changed=[filename], commit_shas=[node_id], summary=task_id or "")


def _pool_dispatcher_builder(dispatchers: list):
    """Hand out dispatchers in order, one per DevAgentSpec expansion."""
    state = {"i": 0}

    def _builder(spec: DevAgentSpec):
        idx = state["i"]
        state["i"] += 1
        return dispatchers[idx % len(dispatchers)], object()

    return _builder


@pytest.mark.asyncio
class TestSharedMode:
    async def test_pool_shared_mode_end_to_end(self, tmp_path):
        write_index(
            tmp_path,
            "FEAT-323",
            "my-feature",
            [
                {"id": "TASK-1", "status": "pending", "depends_on": []},
                {"id": "TASK-2", "status": "pending", "depends_on": []},
                {"id": "TASK-3", "status": "pending", "depends_on": ["TASK-1"]},
                {"id": "TASK-4", "status": "pending", "depends_on": ["TASK-2"]},
            ],
        )
        research = research_output(str(tmp_path))
        d1, d2 = FakeDispatcher(), FakeDispatcher()
        pool_config = DevAgentPoolConfig(agents=[DevAgentSpec(agent="claude-code", count=2)])
        node = DevelopmentNode(
            dispatcher=MagicMock(),
            pool_config=pool_config,
            dispatcher_builder=_pool_dispatcher_builder([d1, d2]),
        )

        ctx = {"run_id": "run-shared", "research_output": research}
        result: DevelopmentOutput = await node.execute(ctx)

        assert set(result.files_changed) == {
            "TASK-1.py",
            "TASK-2.py",
            "TASK-3.py",
            "TASK-4.py",
        }
        assert result.incomplete_tasks == []
        assert len(result.worker_summaries) == 2
        assert {ws.worker_id for ws in result.worker_summaries} == {
            "development.w1",
            "development.w2",
        }
        # Both workers dispatched against the SAME shared worktree (no
        # sub-worktree creation in 'shared' mode).
        assert all(call[2] == research.worktree_path for call in d1.calls + d2.calls)
        assert ctx["development_output"] is result


@pytest.mark.asyncio
class TestIsolatedMode:
    async def test_pool_isolated_mode_end_to_end(self, git_sandbox, monkeypatch):
        base_worktree, feature_branch, worktree_base_path = git_sandbox
        monkeypatch.setattr(conf, "WORKTREE_BASE_PATH", str(worktree_base_path))
        write_index(
            base_worktree,
            "FEAT-323",
            "my-feature",
            [
                {"id": "TASK-1", "status": "pending", "depends_on": []},
                {"id": "TASK-2", "status": "pending", "depends_on": []},
            ],
        )
        research = research_output(str(base_worktree))
        # Match the sandbox's feature branch name.
        research = research.model_copy(update={"branch_name": feature_branch})

        d1, d2 = GitCommittingFakeDispatcher(), GitCommittingFakeDispatcher()
        pool_config = DevAgentPoolConfig(
            agents=[DevAgentSpec(agent="claude-code", count=2)], isolation_mode="isolated"
        )
        node = DevelopmentNode(
            dispatcher=MagicMock(),
            pool_config=pool_config,
            dispatcher_builder=_pool_dispatcher_builder([d1, d2]),
        )

        ctx = {"run_id": "run-isolated", "research_output": research}
        result: DevelopmentOutput = await node.execute(ctx)

        assert set(result.files_changed) == {"TASK-1.py", "TASK-2.py"}
        assert result.incomplete_tasks == []
        # Disjoint files -> clean sequential merges, nothing to resolve.
        # Both files must now exist in the BASE worktree (merged back).
        assert (base_worktree / "TASK-1.py").exists()
        assert (base_worktree / "TASK-2.py").exists()
        # Dispatches happened against distinct sub-worktree paths, not the base.
        cwds = {call[2] for call in d1.calls + d2.calls}
        assert research.worktree_path not in cwds
        assert len(cwds) == 2

    async def test_isolated_multiwave_dependency_sees_prior_wave(
        self, git_sandbox, monkeypatch
    ):
        """A wave-2 task sees BOTH wave-1 files, even the one another worker made.

        Wave 1 dispatches TASK-A and TASK-B (one per worker). Wave 2
        dispatches TASK-C (``depends_on`` both), which lands on w1. Without
        refreshing sub-worktrees between waves, w1 would only have the
        wave-1 file it produced itself — this asserts it has both, i.e. the
        sub-worktree was fast-forwarded to the merged feature branch.
        """
        base_worktree, feature_branch, worktree_base_path = git_sandbox
        monkeypatch.setattr(conf, "WORKTREE_BASE_PATH", str(worktree_base_path))
        write_index(
            base_worktree,
            "FEAT-323",
            "my-feature",
            [
                {"id": "TASK-A", "status": "pending", "depends_on": []},
                {"id": "TASK-B", "status": "pending", "depends_on": []},
                {"id": "TASK-C", "status": "pending", "depends_on": ["TASK-A", "TASK-B"]},
            ],
        )
        research = research_output(str(base_worktree)).model_copy(
            update={"branch_name": feature_branch}
        )

        # w1 (d1) runs the wave-2 task TASK-C and snapshots what it sees.
        d1 = DepCheckingGitDispatcher(check_task="TASK-C", expect_files=["TASK-A.py", "TASK-B.py"])
        d2 = GitCommittingFakeDispatcher()
        pool_config = DevAgentPoolConfig(
            agents=[DevAgentSpec(agent="claude-code", count=2)], isolation_mode="isolated"
        )
        node = DevelopmentNode(
            dispatcher=MagicMock(),
            pool_config=pool_config,
            dispatcher_builder=_pool_dispatcher_builder([d1, d2]),
        )

        ctx = {"run_id": "run-multiwave", "research_output": research}
        result: DevelopmentOutput = await node.execute(ctx)

        assert result.incomplete_tasks == []
        # The wave-2 worker saw BOTH prior-wave files in its (refreshed) tree.
        assert d1.seen == {"TASK-A.py": True, "TASK-B.py": True}
        # All three files integrated into the base worktree.
        for name in ("TASK-A.py", "TASK-B.py", "TASK-C.py"):
            assert (base_worktree / name).exists()

    async def test_isolated_merge_conflict_resolved(self, git_sandbox, monkeypatch):
        base_worktree, feature_branch, worktree_base_path = git_sandbox
        monkeypatch.setattr(conf, "WORKTREE_BASE_PATH", str(worktree_base_path))
        write_index(
            base_worktree,
            "FEAT-323",
            "my-feature",
            [
                {"id": "TASK-1", "status": "pending", "depends_on": []},
                {"id": "TASK-2", "status": "pending", "depends_on": []},
            ],
        )
        research = research_output(str(base_worktree))
        research = research.model_copy(update={"branch_name": feature_branch})

        # Both workers write the SAME filename -> the second worker's merge
        # conflicts against the first worker's already-merged change.
        conflicting_filename = lambda _task_id: "shared.py"  # noqa: E731
        d1 = GitCommittingFakeDispatcher(filename_for=conflicting_filename)
        d2 = GitCommittingFakeDispatcher(filename_for=conflicting_filename)
        pool_config = DevAgentPoolConfig(
            agents=[DevAgentSpec(agent="claude-code", count=2)], isolation_mode="isolated"
        )
        node = DevelopmentNode(
            dispatcher=MagicMock(),
            pool_config=pool_config,
            dispatcher_builder=_pool_dispatcher_builder([d1, d2]),
        )

        ctx = {"run_id": "run-conflict", "research_output": research}
        result: DevelopmentOutput = await node.execute(ctx)

        # The run completed (no SubWorktreeMergeError) — the resolver (the
        # pool's first worker, d1) fixed the conflict in-place and committed.
        assert result.incomplete_tasks == []
        assert (base_worktree / "shared.py").exists()
        resolver_calls = [c for c in d1.calls if c[0] == "RESOLVE_MERGE_CONFLICT"]
        assert len(resolver_calls) == 1
        # The resolver dispatch's cwd must be the BASE worktree (where the
        # conflict actually lives) — regression for the bug TASK-1864 found
        # in SubWorktreeManager.merge_sequential (see test_worktree_manager.py).
        assert resolver_calls[0][2] == str(base_worktree.resolve())


@pytest.mark.asyncio
class TestPartial:
    async def test_partial_completion_reaches_qa(self, tmp_path):
        write_index(
            tmp_path,
            "FEAT-323",
            "my-feature",
            [
                {"id": "TASK-1", "status": "pending", "depends_on": []},
                {"id": "TASK-2", "status": "pending", "depends_on": []},
                {"id": "TASK-3", "status": "pending", "depends_on": ["TASK-2"]},
            ],
        )
        research = research_output(str(tmp_path))
        # TASK-2 fails twice (initial dispatch + the single retry) -> incomplete.
        d1 = FakeDispatcher(fail_counts={"TASK-2": 2})
        pool_config = DevAgentPoolConfig(agents=[DevAgentSpec(agent="claude-code")])
        node = DevelopmentNode(
            dispatcher=MagicMock(),
            pool_config=pool_config,
            dispatcher_builder=_pool_dispatcher_builder([d1]),
        )

        ctx = {"run_id": "run-partial", "research_output": research}
        result: DevelopmentOutput = await node.execute(ctx)

        assert "TASK-1.py" in result.files_changed
        assert set(result.incomplete_tasks) == {"TASK-2", "TASK-3"}
        # QA reads shared["development_output"] even on partial completion.
        assert ctx["development_output"] is result


@pytest.mark.asyncio
class TestRegression:
    async def test_single_agent_regression_e2e(self, tmp_path):
        """No pool config at all -> exactly 1 dispatch, node_id='development'."""
        research = research_output(str(tmp_path))
        dispatcher = MagicMock()
        dev_out = DevelopmentOutput(files_changed=["a.py"], commit_shas=["sha1"], summary="ok")
        dispatcher.dispatch = AsyncMock(return_value=dev_out)
        node = DevelopmentNode(dispatcher=dispatcher)

        ctx = {"run_id": "run-single", "research_output": research}
        result = await node.execute(ctx)

        assert result is dev_out
        dispatcher.dispatch.assert_awaited_once()
        kwargs = dispatcher.dispatch.await_args.kwargs
        assert kwargs["node_id"] == "development"
        assert kwargs["cwd"] == research.worktree_path
