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
    FeatureBrief,
    FlowtaskCriterion,
    LogSource,
    ResearchOutput,
    WorkBrief,
)
from parrot.flows.dev_loop.nodes import development as development_module
from parrot.flows.dev_loop.nodes.development import DevelopmentNode, should_fan_out
from parrot.flows.dev_loop.task_scheduler import TaskRef
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


def _feature_brief(tmp_path: Path, **overrides) -> FeatureBrief:
    """dev-flow's brief shape — the one this node never used to look for.

    ``FeatureBrief`` validates that ``document_path`` exists, so the spec
    file is materialised under ``tmp_path``.
    """
    document = tmp_path / "x.spec.md"
    if not document.exists():
        document.write_text("# spec\n", encoding="utf-8")
    defaults = dict(document_path=str(document), document_kind="spec")
    defaults.update(overrides)
    return FeatureBrief(**defaults)


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

    async def dispatch(self, *, brief, profile, output_model, run_id, node_id, cwd, **_kwargs):
        # **_kwargs tolerates the single-agent path's ``session_host=``
        # (FEAT-466 TASK-2506); the pool path never passes it.
        task_id = getattr(brief, "task_id", None)
        self.calls.append((task_id, node_id, cwd))
        if task_id in self.fail_ids:
            self.fail_ids.discard(task_id)
            raise RuntimeError("boom")
        return DevelopmentOutput(files_changed=[f"{task_id}.py"], commit_shas=[f"sha-{task_id}"], summary=task_id or "")


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
        self.refresh_calls = 0
        self.cleanup_calls: list[bool] = []

    async def create(self, worker_id: str) -> str:
        self.created.append(worker_id)
        return f"{self.base_worktree}/subwt/{worker_id}"

    async def merge_sequential(self, *, resolver=None) -> MergeReport:
        self.merge_calls += 1
        return MergeReport()

    async def refresh_all(self) -> None:
        self.refresh_calls += 1

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


def _task_ref(task_id: str) -> TaskRef:
    return TaskRef(id=task_id, status="pending", depends_on=[])


class TestShouldFanOut:
    """FEAT-377 TASK-1913: should_fan_out — pure, no-LLM stop rule."""

    def test_two_independent_tasks_and_multi_slot_pool_fans_out(self):
        wave = [_task_ref("TASK-1"), _task_ref("TASK-2")]
        pool_cfg = DevAgentPoolConfig(agents=[DevAgentSpec(agent="claude-code", count=2)])
        assert should_fan_out(wave, pool_cfg) is True

    def test_single_task_wave_never_fans_out(self):
        wave = [_task_ref("TASK-1")]
        pool_cfg = DevAgentPoolConfig(agents=[DevAgentSpec(agent="claude-code", count=4)])
        assert should_fan_out(wave, pool_cfg) is False

    def test_empty_wave_never_fans_out(self):
        pool_cfg = DevAgentPoolConfig(agents=[DevAgentSpec(agent="claude-code", count=4)])
        assert should_fan_out([], pool_cfg) is False

    def test_single_effective_slot_never_fans_out(self):
        wave = [_task_ref("TASK-1"), _task_ref("TASK-2")]
        pool_cfg = DevAgentPoolConfig(agents=[DevAgentSpec(agent="claude-code", count=1)])
        assert should_fan_out(wave, pool_cfg) is False

    def test_effective_slots_sum_across_multiple_specs(self):
        """Two specs with count=1 each still sum to 2 effective slots."""
        wave = [_task_ref("TASK-1"), _task_ref("TASK-2")]
        pool_cfg = DevAgentPoolConfig(agents=[DevAgentSpec(agent="claude-code"), DevAgentSpec(agent="codex")])
        assert should_fan_out(wave, pool_cfg) is True


@pytest.mark.asyncio
class TestFanOutWiring:
    """Pool path is always taken when pool config + dispatcher_builder
    are present, regardless of wave size or slot count."""

    async def test_chain_uses_pool_path_sequentially(self, tmp_path):
        """A straight dependency chain (every wave size 1) still uses
        the pool path — tasks run sequentially through the pool."""
        _write_index(
            tmp_path,
            "FEAT-323",
            "my-feature",
            [
                {"id": "TASK-1", "status": "pending", "depends_on": []},
                {"id": "TASK-2", "status": "pending", "depends_on": ["TASK-1"]},
                {"id": "TASK-3", "status": "pending", "depends_on": ["TASK-2"]},
            ],
        )
        research = _research(str(tmp_path))
        single_dispatcher = MagicMock()
        single_dispatcher.dispatch = AsyncMock(
            return_value=DevelopmentOutput(files_changed=["x.py"], commit_shas=["s"], summary="single")
        )
        pool_dispatcher = FakeDispatcher()
        pool_config = DevAgentPoolConfig(agents=[DevAgentSpec(agent="claude-code", count=4)])
        node = DevelopmentNode(
            dispatcher=single_dispatcher,
            pool_config=pool_config,
            dispatcher_builder=_dispatcher_builder_factory([pool_dispatcher]),
            pool_max=4,
        )

        ctx = {"run_id": "r1", "research_output": research}
        result = await node.execute(ctx)

        # Pool path taken: pool dispatcher handled all three tasks
        # sequentially; the single-agent dispatcher was NOT called.
        single_dispatcher.dispatch.assert_not_awaited()
        dispatched = [c[0] for c in pool_dispatcher.calls]
        assert dispatched == ["TASK-1", "TASK-2", "TASK-3"]
        assert set(result.files_changed) == {"TASK-1.py", "TASK-2.py", "TASK-3.py"}

    async def test_single_slot_pool_uses_pool_path(self, tmp_path):
        """A pool with count=1 dispatches through the pool path
        (sequentially), not the legacy single-agent path."""
        _write_index(
            tmp_path,
            "FEAT-323",
            "my-feature",
            [
                {"id": "TASK-1", "status": "pending", "depends_on": []},
                {"id": "TASK-2", "status": "pending", "depends_on": []},
            ],
        )
        research = _research(str(tmp_path))
        single_dispatcher = MagicMock()
        single_dispatcher.dispatch = AsyncMock(
            return_value=DevelopmentOutput(files_changed=[], commit_shas=[], summary="unused")
        )
        pool_dispatcher = FakeDispatcher()
        pool_config = DevAgentPoolConfig(agents=[DevAgentSpec(agent="claude-code", count=1)])
        node = DevelopmentNode(
            dispatcher=single_dispatcher,
            pool_config=pool_config,
            dispatcher_builder=_dispatcher_builder_factory([pool_dispatcher]),
        )

        ctx = {"run_id": "r1", "research_output": research}
        await node.execute(ctx)

        single_dispatcher.dispatch.assert_not_awaited()
        dispatched_tasks = {c[0] for c in pool_dispatcher.calls}
        assert dispatched_tasks == {"TASK-1", "TASK-2"}

    async def test_development_takes_pool_path_when_wave_has_two_tasks(self, tmp_path):
        """A first wave with 2 independent tasks + a multi-slot pool
        takes the pool path with true parallelism."""
        _write_index(
            tmp_path,
            "FEAT-323",
            "my-feature",
            [
                {"id": "TASK-1", "status": "pending", "depends_on": []},
                {"id": "TASK-2", "status": "pending", "depends_on": []},
            ],
        )
        research = _research(str(tmp_path))
        d1, d2 = FakeDispatcher(), FakeDispatcher()
        pool_config = DevAgentPoolConfig(agents=[DevAgentSpec(agent="claude-code", count=2)])
        node = DevelopmentNode(
            dispatcher=MagicMock(),
            pool_config=pool_config,
            dispatcher_builder=_dispatcher_builder_factory([d1, d2]),
        )

        ctx = {"run_id": "r1", "research_output": research}
        result = await node.execute(ctx)

        assert set(result.files_changed) == {"TASK-1.py", "TASK-2.py"}
        assert d1.calls and d2.calls


@pytest.mark.asyncio
class TestCascade:
    async def test_injected_pool_used_when_no_brief_pool(self, tmp_path):
        # FEAT-377 TASK-1913: should_fan_out requires >=2 independent
        # first-wave tasks AND >1 effective worker slot to take the pool
        # path — TASK-2 (independent) and count=2 satisfy both.
        _write_index(
            tmp_path,
            "FEAT-323",
            "my-feature",
            [
                {"id": "TASK-1", "status": "pending", "depends_on": []},
                {"id": "TASK-2", "status": "pending", "depends_on": []},
            ],
        )
        research = _research(str(tmp_path))
        d1, d2 = FakeDispatcher(), FakeDispatcher()
        pool_config = DevAgentPoolConfig(agents=[DevAgentSpec(agent="claude-code", count=2)])
        node = DevelopmentNode(
            dispatcher=MagicMock(),
            pool_config=pool_config,
            dispatcher_builder=_dispatcher_builder_factory([d1, d2]),
            pool_max=4,
        )

        ctx = {"run_id": "r1", "research_output": research}
        await node.execute(ctx)

        # next_wave() makes no ordering guarantee, so each worker gets
        # exactly one of the two tasks — which one is unspecified.
        assert len(d1.calls) == 1 and len(d2.calls) == 1
        dispatched_tasks = {d1.calls[0][0], d2.calls[0][0]}
        assert dispatched_tasks == {"TASK-1", "TASK-2"}
        assert d1.calls[0][2] == research.worktree_path
        assert d2.calls[0][2] == research.worktree_path

    async def test_brief_pool_overrides_injected(self, tmp_path):
        # FEAT-377 TASK-1913: same >=2 wave / >1 slot requirement as above.
        _write_index(
            tmp_path,
            "FEAT-323",
            "my-feature",
            [
                {"id": "TASK-1", "status": "pending", "depends_on": []},
                {"id": "TASK-2", "status": "pending", "depends_on": []},
            ],
        )
        research = _research(str(tmp_path))
        injected_dispatcher = FakeDispatcher()
        brief_dispatcher = FakeDispatcher()
        brief = _work_brief(dev_agents=[DevAgentSpec(agent="codex", count=2)])

        # Two different dispatcher_builders would normally be constructed
        # by the same builder, but for this test we key off the spec passed
        # to distinguish which pool config was actually used.
        def _builder(spec: DevAgentSpec):
            if spec.agent == "codex":
                return brief_dispatcher, object()
            return injected_dispatcher, object()

        node = DevelopmentNode(
            dispatcher=MagicMock(),
            pool_config=DevAgentPoolConfig(agents=[DevAgentSpec(agent="claude-code", count=2)]),
            dispatcher_builder=_builder,
            pool_max=4,
        )

        ctx = {"run_id": "r1", "research_output": research, "work_brief": brief}
        await node.execute(ctx)

        assert brief_dispatcher.calls  # brief's codex spec won
        assert not injected_dispatcher.calls

    @pytest.mark.parametrize("brief_key", ["feature_brief", "dev_brief"])
    async def test_dev_flow_brief_pool_overrides_injected(self, tmp_path, brief_key):
        """dev-flow publishes its brief under its OWN keys, never the bug ones.

        Regression: this resolver read only ``work_brief``/``bug_brief``, so
        every dev-flow run silently ignored the console's per-run pool and
        fell back to the build-time ``model_plan`` — while the UI told the
        operator to restart the server to change a seat that was in fact
        meant to be per-run. ``DevFlowRunner.run`` states outright that the
        bug-mode keys stay unset.
        """
        _write_index(
            tmp_path,
            "FEAT-323",
            "my-feature",
            [
                {"id": "TASK-1", "status": "pending", "depends_on": []},
                {"id": "TASK-2", "status": "pending", "depends_on": []},
            ],
        )
        research = _research(str(tmp_path))
        injected_dispatcher = FakeDispatcher()
        brief_dispatcher = FakeDispatcher()
        brief = _feature_brief(tmp_path, dev_agents=[DevAgentSpec(agent="codex", count=2)])

        def _builder(spec: DevAgentSpec):
            if spec.agent == "codex":
                return brief_dispatcher, object()
            return injected_dispatcher, object()

        node = DevelopmentNode(
            dispatcher=MagicMock(),
            pool_config=DevAgentPoolConfig(agents=[DevAgentSpec(agent="claude-code", count=2)]),
            dispatcher_builder=_builder,
            pool_max=4,
        )

        ctx = {"run_id": "r1", "research_output": research, brief_key: brief}
        await node.execute(ctx)

        assert brief_dispatcher.calls  # the per-run pool won
        assert not injected_dispatcher.calls

    async def test_brief_without_a_pool_still_falls_back_to_injected(self, tmp_path):
        """Only a brief that DECLARES a pool displaces the build-time one."""
        _write_index(
            tmp_path,
            "FEAT-323",
            "my-feature",
            [
                {"id": "TASK-1", "status": "pending", "depends_on": []},
                {"id": "TASK-2", "status": "pending", "depends_on": []},
            ],
        )
        research = _research(str(tmp_path))
        d1, d2 = FakeDispatcher(), FakeDispatcher()
        node = DevelopmentNode(
            dispatcher=MagicMock(),
            pool_config=DevAgentPoolConfig(agents=[DevAgentSpec(agent="claude-code", count=2)]),
            dispatcher_builder=_dispatcher_builder_factory([d1, d2]),
            pool_max=4,
        )

        ctx = {
            "run_id": "r1",
            "research_output": research,
            # Present but silent about the pool — dev-flow always seeds this.
            "dev_brief": _feature_brief(tmp_path),
        }
        await node.execute(ctx)

        assert len(d1.calls) == 1 and len(d2.calls) == 1

    async def test_missing_index_degrades_to_single_via_declared_agent(self, tmp_path):
        """FEAT-466 TASK-2506: a missing per-spec index (the normal case for
        a hotfix, which reserves no ids) must still honour the operator's
        declared dev agent via the builder — NOT silently fall back to the
        server's env-configured dispatcher. Supersedes the pre-FEAT-466
        version of this test, which asserted the bug this task fixes."""
        # No sdd/tasks/index/*.json written under tmp_path.
        research = _research(str(tmp_path))
        env_dispatcher = MagicMock()
        env_dispatcher.dispatch = AsyncMock()
        pool_dispatcher = FakeDispatcher()
        pool_config = DevAgentPoolConfig(agents=[DevAgentSpec(agent="codex", model="gpt-5.5")])
        builder_calls = []

        def _builder(spec: DevAgentSpec):
            builder_calls.append(spec)
            return pool_dispatcher, object()

        node = DevelopmentNode(
            dispatcher=env_dispatcher,
            pool_config=pool_config,
            dispatcher_builder=_builder,
        )

        ctx = {"run_id": "r1", "research_output": research}
        result = await node.execute(ctx)

        assert builder_calls == [DevAgentSpec(agent="codex", model="gpt-5.5")]
        assert pool_dispatcher.calls
        env_dispatcher.dispatch.assert_not_awaited()
        assert result.worker_summaries[-1].agent == "codex"
        assert result.worker_summaries[-1].model == "gpt-5.5"

    async def test_no_dispatcher_builder_degrades_to_single(self, tmp_path):
        _write_index(tmp_path, "FEAT-323", "my-feature", [{"id": "TASK-1", "status": "pending", "depends_on": []}])
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
class TestSingleAgentHonoursDeclaredAgent:
    """FEAT-466 TASK-2506 — Problem B: the single-agent path must honour the
    operator's declared dev agent instead of silently substituting the
    server's env-configured default."""

    async def test_uses_pool_spec_when_no_task_index(self, tmp_path):
        """The core FEAT-466 Problem B case: pool declared, no per-spec index
        (as on every hotfix run), selection must still be honoured."""
        research = _research(str(tmp_path))
        env_dispatcher = MagicMock()
        env_dispatcher.dispatch = AsyncMock()
        pool_dispatcher = FakeDispatcher()
        builder_calls = []

        def _builder(spec: DevAgentSpec):
            builder_calls.append(spec)
            return pool_dispatcher, object()

        pool_config = DevAgentPoolConfig(agents=[DevAgentSpec(agent="codex", model="gpt-5.5")])
        node = DevelopmentNode(
            dispatcher=env_dispatcher,
            pool_config=pool_config,
            dispatcher_builder=_builder,
        )

        ctx = {"run_id": "r1", "research_output": research}
        await node.execute(ctx)

        assert builder_calls == [DevAgentSpec(agent="codex", model="gpt-5.5")]
        assert pool_dispatcher.calls
        env_dispatcher.dispatch.assert_not_awaited()

    async def test_no_pool_uses_env_dispatcher(self, tmp_path):
        """Regression guard — the path every existing run takes."""
        research = _research(str(tmp_path))
        dispatcher = MagicMock()
        dev_out = DevelopmentOutput(files_changed=[], commit_shas=[], summary="single")
        dispatcher.dispatch = AsyncMock(return_value=dev_out)
        node = DevelopmentNode(dispatcher=dispatcher)

        ctx = {"run_id": "r1", "research_output": research}
        result = await node.execute(ctx)

        assert result is dev_out
        assert result.worker_summaries == []

    async def test_warns_when_builder_missing(self, tmp_path, caplog):
        _write_index(
            tmp_path,
            "FEAT-323",
            "my-feature",
            [{"id": "TASK-1", "status": "pending", "depends_on": []}],
        )
        research = _research(str(tmp_path))
        dispatcher = MagicMock()
        dev_out = DevelopmentOutput(files_changed=[], commit_shas=[], summary="single")
        dispatcher.dispatch = AsyncMock(return_value=dev_out)
        pool_config = DevAgentPoolConfig(agents=[DevAgentSpec(agent="codex")])
        node = DevelopmentNode(dispatcher=dispatcher, pool_config=pool_config)

        ctx = {"run_id": "r1", "research_output": research}
        with caplog.at_level("WARNING"):
            await node.execute(ctx)

        assert "NOT being honoured" in caplog.text

    async def test_warns_on_multi_spec_pool(self, tmp_path, caplog):
        research = _research(str(tmp_path))
        env_dispatcher = MagicMock()
        env_dispatcher.dispatch = AsyncMock()
        pool_dispatcher = FakeDispatcher()

        def _builder(spec: DevAgentSpec):
            return pool_dispatcher, object()

        pool_config = DevAgentPoolConfig(
            agents=[
                DevAgentSpec(agent="codex", model="gpt-5.5"),
                DevAgentSpec(agent="claude-code"),
            ]
        )
        node = DevelopmentNode(
            dispatcher=env_dispatcher,
            pool_config=pool_config,
            dispatcher_builder=_builder,
        )

        ctx = {"run_id": "r1", "research_output": research}
        with caplog.at_level("WARNING"):
            await node.execute(ctx)

        assert "single-agent; using only" in caplog.text

    async def test_worker_summary_records_actual_backend(self, tmp_path):
        research = _research(str(tmp_path))
        env_dispatcher = MagicMock()
        env_dispatcher.dispatch = AsyncMock()
        pool_dispatcher = FakeDispatcher()

        def _builder(spec: DevAgentSpec):
            return pool_dispatcher, object()

        pool_config = DevAgentPoolConfig(agents=[DevAgentSpec(agent="codex", model="gpt-5.5")])
        node = DevelopmentNode(
            dispatcher=env_dispatcher,
            pool_config=pool_config,
            dispatcher_builder=_builder,
        )

        ctx = {"run_id": "r1", "research_output": research}
        out = await node.execute(ctx)

        assert out.worker_summaries[-1].agent == "codex"
        assert out.worker_summaries[-1].model == "gpt-5.5"

    async def test_worker_summary_failure_does_not_fail_dispatch(self, tmp_path, monkeypatch):
        """A labelling failure while building WorkerSummary must not fail an
        otherwise-successful dispatch."""
        research = _research(str(tmp_path))
        env_dispatcher = MagicMock()
        env_dispatcher.dispatch = AsyncMock()
        pool_dispatcher = FakeDispatcher()

        def _builder(spec: DevAgentSpec):
            return pool_dispatcher, object()

        pool_config = DevAgentPoolConfig(agents=[DevAgentSpec(agent="codex", model="gpt-5.5")])
        node = DevelopmentNode(
            dispatcher=env_dispatcher,
            pool_config=pool_config,
            dispatcher_builder=_builder,
        )

        def _boom(*a, **kw):
            raise RuntimeError("boom")

        monkeypatch.setattr(development_module, "WorkerSummary", _boom)

        ctx = {"run_id": "r1", "research_output": research}
        result = await node.execute(ctx)

        assert result is not None
        assert pool_dispatcher.calls


@pytest.mark.asyncio
class TestPoolPath:
    async def test_waves_and_partial(self, tmp_path):
        # FEAT-377 TASK-1913: TASK-2 is independent (alongside TASK-1) so
        # the FIRST wave has 2 tasks (should_fan_out -> True); TASK-3
        # depends on TASK-1 and lands in a SECOND wave, preserving this
        # test's original multi-wave intent.
        _write_index(
            tmp_path,
            "FEAT-323",
            "my-feature",
            [
                {"id": "TASK-1", "status": "pending", "depends_on": []},
                {"id": "TASK-2", "status": "pending", "depends_on": []},
                {"id": "TASK-3", "status": "pending", "depends_on": ["TASK-1"]},
            ],
        )
        research = _research(str(tmp_path))
        d1, d2 = FakeDispatcher(), FakeDispatcher()
        pool_config = DevAgentPoolConfig(agents=[DevAgentSpec(agent="claude-code", count=2)])
        node = DevelopmentNode(
            dispatcher=MagicMock(),
            pool_config=pool_config,
            dispatcher_builder=_dispatcher_builder_factory([d1, d2]),
        )

        ctx = {"run_id": "r1", "research_output": research}
        result = await node.execute(ctx)

        assert set(result.files_changed) == {"TASK-1.py", "TASK-2.py", "TASK-3.py"}
        assert result.incomplete_tasks == []
        assert ctx["development_output"] is result

    async def test_all_incomplete_raises(self, tmp_path):
        # FEAT-377 TASK-1913: 2 independent tasks + count=2 to satisfy
        # should_fan_out and actually reach the pool path.
        _write_index(
            tmp_path,
            "FEAT-323",
            "my-feature",
            [
                {"id": "TASK-1", "status": "pending", "depends_on": []},
                {"id": "TASK-2", "status": "pending", "depends_on": []},
            ],
        )
        research = _research(str(tmp_path))
        pool_config = DevAgentPoolConfig(agents=[DevAgentSpec(agent="claude-code", count=2)])
        node = DevelopmentNode(
            dispatcher=MagicMock(),
            pool_config=pool_config,
            dispatcher_builder=_dispatcher_builder_factory([AlwaysFailDispatcher()]),
        )

        ctx = {"run_id": "r1", "research_output": research}
        with pytest.raises(RuntimeError):
            await node.execute(ctx)

    async def test_isolated_uses_manager_and_cleanup(self, tmp_path, monkeypatch):
        # FEAT-377 TASK-1913: 2 independent tasks + count=2 pool.
        _write_index(
            tmp_path,
            "FEAT-323",
            "my-feature",
            [
                {"id": "TASK-1", "status": "pending", "depends_on": []},
                {"id": "TASK-2", "status": "pending", "depends_on": []},
            ],
        )
        research = _research(str(tmp_path))
        monkeypatch.setattr(conf, "WORKTREE_BASE_PATH", str(tmp_path))

        created_managers: list[FakeManager] = []

        def _manager_factory(**kwargs):
            m = FakeManager(**kwargs)
            created_managers.append(m)
            return m

        monkeypatch.setattr(development_module, "SubWorktreeManager", _manager_factory)

        d1, d2 = FakeDispatcher(), FakeDispatcher()
        pool_config = DevAgentPoolConfig(agents=[DevAgentSpec(agent="claude-code", count=2)], isolation_mode="isolated")
        node = DevelopmentNode(
            dispatcher=MagicMock(),
            pool_config=pool_config,
            dispatcher_builder=_dispatcher_builder_factory([d1, d2]),
        )

        ctx = {"run_id": "r1", "research_output": research}
        await node.execute(ctx)

        assert len(created_managers) == 1
        manager = created_managers[0]
        assert manager.created == ["development.w1", "development.w2"]
        assert manager.merge_calls == 1
        assert manager.cleanup_calls == [True]
        # Dispatch happened against the sub-worktree path, not the base worktree.
        assert d1.calls[0][2] == f"{research.worktree_path}/subwt/development.w1"
        assert d2.calls[0][2] == f"{research.worktree_path}/subwt/development.w2"

    async def test_isolated_cleanup_runs_even_on_merge_failure(self, tmp_path, monkeypatch):
        # FEAT-377 TASK-1913: 2 independent tasks + count=2 pool.
        _write_index(
            tmp_path,
            "FEAT-323",
            "my-feature",
            [
                {"id": "TASK-1", "status": "pending", "depends_on": []},
                {"id": "TASK-2", "status": "pending", "depends_on": []},
            ],
        )
        research = _research(str(tmp_path))
        monkeypatch.setattr(conf, "WORKTREE_BASE_PATH", str(tmp_path))

        created_managers: list[FailingMergeManager] = []

        def _manager_factory(**kwargs):
            m = FailingMergeManager(**kwargs)
            created_managers.append(m)
            return m

        monkeypatch.setattr(development_module, "SubWorktreeManager", _manager_factory)

        pool_config = DevAgentPoolConfig(agents=[DevAgentSpec(agent="claude-code", count=2)], isolation_mode="isolated")
        node = DevelopmentNode(
            dispatcher=MagicMock(),
            pool_config=pool_config,
            dispatcher_builder=_dispatcher_builder_factory([FakeDispatcher(), FakeDispatcher()]),
        )

        ctx = {"run_id": "r1", "research_output": research}
        with pytest.raises(SubWorktreeMergeError):
            await node.execute(ctx)

        assert created_managers[0].cleanup_calls == [True]
