"""Unit tests for the FEAT-323 DevelopmentNode pool rework (TASK-1862).

Complements ``test_development.py`` (the pre-existing single-agent test
file, left untouched as the byte-identical regression baseline).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot import conf
from parrot.flows.dev_loop.models import (
    DevAgentPoolConfig,
    DevAgentSpec,
    DevelopmentOutput,
    FlowtaskCriterion,
    LogSource,
    ResearchOutput,
    WorkBrief,
)
from parrot.flows.dev_loop.nodes import development as development_module
from parrot.flows.dev_loop.nodes.development import DevelopmentNode
from parrot.flows.dev_loop.worktree_manager import MergeReport, SubWorktreeMergeError


def _research(worktree_path: str, feat_id: str = "FEAT-323") -> ResearchOutput:
    return ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/x.spec.md",
        feat_id=feat_id,
        branch_name="feat-323-x",
        worktree_path=worktree_path,
        log_excerpts=[],
    )


def _work_brief(**overrides) -> WorkBrief:
    defaults = dict(
        summary="x" * 20,
        affected_component="etl/x.yaml",
        log_sources=[LogSource(kind="cloudwatch", locator="/etl/x")],
        acceptance_criteria=[FlowtaskCriterion(name="run", task_path="etl/x.yaml")],
        escalation_assignee="acct:abc",
        reporter="acct:def",
    )
    defaults.update(overrides)
    return WorkBrief(**defaults)


def _write_index(worktree_path: Path, feat_id: str, feature_slug: str, tasks: list) -> None:
    index_dir = worktree_path / "sdd" / "tasks" / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / f"{feature_slug}.json").write_text(
        json.dumps({"feature": feature_slug, "feature_id": feat_id, "tasks": tasks})
    )


class FakeDispatcher:
    """Fulfils the DevLoopCodeDispatcher Protocol; records calls."""

    def __init__(self, fail_ids=()):
        self.calls = []
        self.fail_ids = set(fail_ids)

    async def dispatch(self, *, brief, profile, output_model, run_id, node_id, cwd):
        task_id = getattr(brief, "task_id", None)
        self.calls.append((task_id, node_id, cwd))
        if task_id in self.fail_ids:
            self.fail_ids.discard(task_id)
            raise RuntimeError("boom")
        return DevelopmentOutput(
            files_changed=[f"{task_id}.py"], commit_shas=[f"sha-{task_id}"], summary=task_id or ""
        )


class AlwaysFailDispatcher:
    def __init__(self):
        self.calls = []

    async def dispatch(self, *, brief, profile, output_model, run_id, node_id, cwd):
        self.calls.append((getattr(brief, "task_id", None), node_id, cwd))
        raise RuntimeError("always fails")


def _dispatcher_builder_factory(dispatchers: list):
    """Returns a dispatcher_builder that hands out dispatchers in order."""
    state = {"i": 0}

    def _builder(spec: DevAgentSpec):
        idx = state["i"]
        state["i"] += 1
        return dispatchers[idx % len(dispatchers)], object()

    return _builder


class FakeManager:
    """Test double for SubWorktreeManager — no real git involved."""

    def __init__(self, *, base_worktree, feature_branch, worktree_base_path):
        self.base_worktree = base_worktree
        self.feature_branch = feature_branch
        self.worktree_base_path = worktree_base_path
        self.created: list[str] = []
        self.merge_calls = 0
        self.cleanup_calls: list[bool] = []

    async def create(self, worker_id: str) -> str:
        self.created.append(worker_id)
        return f"{self.base_worktree}/subwt/{worker_id}"

    async def merge_sequential(self, *, resolver=None) -> MergeReport:
        self.merge_calls += 1
        return MergeReport()

    async def cleanup(self, *, keep_on_conflict: bool = True) -> None:
        self.cleanup_calls.append(keep_on_conflict)


class FailingMergeManager(FakeManager):
    async def merge_sequential(self, *, resolver=None) -> MergeReport:
        self.merge_calls += 1
        raise SubWorktreeMergeError("conflict", branch="b1", worktree_path="/x")


@pytest.mark.asyncio
class TestSinglePathRegression:
    async def test_no_pool_exact_current_behavior(self, tmp_path):
        research = _research(str(tmp_path))
        dispatcher = MagicMock()
        dev_out = DevelopmentOutput(files_changed=[], commit_shas=[], summary="ok")
        dispatcher.dispatch = AsyncMock(return_value=dev_out)
        node = DevelopmentNode(dispatcher=dispatcher)

        ctx = {"run_id": "r1", "research_output": research}
        result = await node.execute(ctx)

        assert result is dev_out
        kwargs = dispatcher.dispatch.await_args.kwargs
        assert kwargs["node_id"] == "development"
        assert kwargs["cwd"] == research.worktree_path
        assert kwargs["brief"] is research
        profile = kwargs["profile"]
        assert profile.subagent == "sdd-worker"
        assert profile.permission_mode == "acceptEdits"
        assert profile.allowed_tools == ["Read", "Edit", "Write", "Bash", "Grep", "Glob"]


@pytest.mark.asyncio
class TestCascade:
    async def test_injected_pool_used_when_no_brief_pool(self, tmp_path):
        _write_index(
            tmp_path,
            "FEAT-323",
            "my-feature",
            [{"id": "TASK-1", "status": "pending", "depends_on": []}],
        )
        research = _research(str(tmp_path))
        d1 = FakeDispatcher()
        pool_config = DevAgentPoolConfig(agents=[DevAgentSpec(agent="claude-code")])
        node = DevelopmentNode(
            dispatcher=MagicMock(),
            pool_config=pool_config,
            dispatcher_builder=_dispatcher_builder_factory([d1]),
            pool_max=4,
        )

        ctx = {"run_id": "r1", "research_output": research}
        await node.execute(ctx)

        assert d1.calls == [("TASK-1", "development.w1", research.worktree_path)]

    async def test_brief_pool_overrides_injected(self, tmp_path):
        _write_index(
            tmp_path,
            "FEAT-323",
            "my-feature",
            [{"id": "TASK-1", "status": "pending", "depends_on": []}],
        )
        research = _research(str(tmp_path))
        injected_dispatcher = FakeDispatcher()
        brief_dispatcher = FakeDispatcher()
        brief = _work_brief(dev_agents=[DevAgentSpec(agent="codex")])

        # Two different dispatcher_builders would normally be constructed
        # by the same builder, but for this test we key off the spec passed
        # to distinguish which pool config was actually used.
        def _builder(spec: DevAgentSpec):
            if spec.agent == "codex":
                return brief_dispatcher, object()
            return injected_dispatcher, object()

        node = DevelopmentNode(
            dispatcher=MagicMock(),
            pool_config=DevAgentPoolConfig(agents=[DevAgentSpec(agent="claude-code")]),
            dispatcher_builder=_builder,
            pool_max=4,
        )

        ctx = {"run_id": "r1", "research_output": research, "work_brief": brief}
        await node.execute(ctx)

        assert brief_dispatcher.calls  # brief's codex spec won
        assert not injected_dispatcher.calls

    async def test_missing_index_degrades_to_single(self, tmp_path):
        # No sdd/tasks/index/*.json written under tmp_path.
        research = _research(str(tmp_path))
        dispatcher = MagicMock()
        dev_out = DevelopmentOutput(files_changed=[], commit_shas=[], summary="single")
        dispatcher.dispatch = AsyncMock(return_value=dev_out)
        pool_config = DevAgentPoolConfig(agents=[DevAgentSpec(agent="claude-code")])
        node = DevelopmentNode(
            dispatcher=dispatcher,
            pool_config=pool_config,
            dispatcher_builder=_dispatcher_builder_factory([FakeDispatcher()]),
        )

        ctx = {"run_id": "r1", "research_output": research}
        result = await node.execute(ctx)

        assert result is dev_out
        dispatcher.dispatch.assert_awaited_once()

    async def test_no_dispatcher_builder_degrades_to_single(self, tmp_path):
        _write_index(
            tmp_path, "FEAT-323", "my-feature", [{"id": "TASK-1", "status": "pending", "depends_on": []}]
        )
        research = _research(str(tmp_path))
        dispatcher = MagicMock()
        dev_out = DevelopmentOutput(files_changed=[], commit_shas=[], summary="single")
        dispatcher.dispatch = AsyncMock(return_value=dev_out)
        pool_config = DevAgentPoolConfig(agents=[DevAgentSpec(agent="claude-code")])
        node = DevelopmentNode(dispatcher=dispatcher, pool_config=pool_config)  # no builder

        ctx = {"run_id": "r1", "research_output": research}
        result = await node.execute(ctx)

        assert result is dev_out


@pytest.mark.asyncio
class TestPoolPath:
    async def test_waves_and_partial(self, tmp_path):
        _write_index(
            tmp_path,
            "FEAT-323",
            "my-feature",
            [
                {"id": "TASK-1", "status": "pending", "depends_on": []},
                {"id": "TASK-2", "status": "pending", "depends_on": ["TASK-1"]},
            ],
        )
        research = _research(str(tmp_path))
        d1 = FakeDispatcher()
        pool_config = DevAgentPoolConfig(agents=[DevAgentSpec(agent="claude-code")])
        node = DevelopmentNode(
            dispatcher=MagicMock(),
            pool_config=pool_config,
            dispatcher_builder=_dispatcher_builder_factory([d1]),
        )

        ctx = {"run_id": "r1", "research_output": research}
        result = await node.execute(ctx)

        assert set(result.files_changed) == {"TASK-1.py", "TASK-2.py"}
        assert result.incomplete_tasks == []
        assert ctx["development_output"] is result

    async def test_all_incomplete_raises(self, tmp_path):
        _write_index(
            tmp_path, "FEAT-323", "my-feature", [{"id": "TASK-1", "status": "pending", "depends_on": []}]
        )
        research = _research(str(tmp_path))
        pool_config = DevAgentPoolConfig(agents=[DevAgentSpec(agent="claude-code")])
        node = DevelopmentNode(
            dispatcher=MagicMock(),
            pool_config=pool_config,
            dispatcher_builder=_dispatcher_builder_factory([AlwaysFailDispatcher()]),
        )

        ctx = {"run_id": "r1", "research_output": research}
        with pytest.raises(RuntimeError):
            await node.execute(ctx)

    async def test_isolated_uses_manager_and_cleanup(self, tmp_path, monkeypatch):
        _write_index(
            tmp_path, "FEAT-323", "my-feature", [{"id": "TASK-1", "status": "pending", "depends_on": []}]
        )
        research = _research(str(tmp_path))
        monkeypatch.setattr(conf, "WORKTREE_BASE_PATH", str(tmp_path))

        created_managers: list[FakeManager] = []

        def _manager_factory(**kwargs):
            m = FakeManager(**kwargs)
            created_managers.append(m)
            return m

        monkeypatch.setattr(development_module, "SubWorktreeManager", _manager_factory)

        d1 = FakeDispatcher()
        pool_config = DevAgentPoolConfig(
            agents=[DevAgentSpec(agent="claude-code")], isolation_mode="isolated"
        )
        node = DevelopmentNode(
            dispatcher=MagicMock(),
            pool_config=pool_config,
            dispatcher_builder=_dispatcher_builder_factory([d1]),
        )

        ctx = {"run_id": "r1", "research_output": research}
        await node.execute(ctx)

        assert len(created_managers) == 1
        manager = created_managers[0]
        assert manager.created == ["development.w1"]
        assert manager.merge_calls == 1
        assert manager.cleanup_calls == [True]
        # Dispatch happened against the sub-worktree path, not the base worktree.
        assert d1.calls[0][2] == f"{research.worktree_path}/subwt/development.w1"

    async def test_isolated_cleanup_runs_even_on_merge_failure(self, tmp_path, monkeypatch):
        _write_index(
            tmp_path, "FEAT-323", "my-feature", [{"id": "TASK-1", "status": "pending", "depends_on": []}]
        )
        research = _research(str(tmp_path))
        monkeypatch.setattr(conf, "WORKTREE_BASE_PATH", str(tmp_path))

        created_managers: list[FailingMergeManager] = []

        def _manager_factory(**kwargs):
            m = FailingMergeManager(**kwargs)
            created_managers.append(m)
            return m

        monkeypatch.setattr(development_module, "SubWorktreeManager", _manager_factory)

        pool_config = DevAgentPoolConfig(
            agents=[DevAgentSpec(agent="claude-code")], isolation_mode="isolated"
        )
        node = DevelopmentNode(
            dispatcher=MagicMock(),
            pool_config=pool_config,
            dispatcher_builder=_dispatcher_builder_factory([FakeDispatcher()]),
        )

        ctx = {"run_id": "r1", "research_output": research}
        with pytest.raises(SubWorktreeMergeError):
            await node.execute(ctx)

        assert created_managers[0].cleanup_calls == [True]
