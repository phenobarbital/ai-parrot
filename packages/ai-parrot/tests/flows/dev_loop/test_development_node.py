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
    CriterionResult,
    DevAgentPoolConfig,
    DevAgentSpec,
    DevelopmentOutput,
    FeatureBrief,
    FeedbackDecision,
    FlowtaskCriterion,
    LogSource,
    QAReport,
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
        self.session_hosts = []
        self.labels = []
        self.fail_ids = set(fail_ids)
        self.resolver = None

    def set_event_registry_resolver(self, resolver):
        self.resolver = resolver

    async def dispatch(self, *, brief, profile, output_model, run_id, node_id, cwd, **_kwargs):
        # **_kwargs tolerates ``session_host=``/``labels=``, which BOTH the
        # single-agent path (FEAT-466 TASK-2506 / FEAT-496) and the pool
        # path pass.
        task_id = getattr(brief, "task_id", None)
        self.calls.append((task_id, node_id, cwd))
        self.session_hosts.append(_kwargs.get("session_host"))
        self.labels.append(_kwargs.get("labels"))
        if task_id in self.fail_ids:
            self.fail_ids.discard(task_id)
            raise RuntimeError("boom")
        return DevelopmentOutput(files_changed=[f"{task_id}.py"], commit_shas=[f"sha-{task_id}"], summary=task_id or "")


class AlwaysFailDispatcher:
    def __init__(self):
        self.calls = []

    async def dispatch(self, *, brief, profile, output_model, run_id, node_id, cwd, session_host=None):
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

    async def test_pool_dispatch_carries_the_session_host_and_run_registry(self, tmp_path):
        """Both usage seams the pool path used to drop on the floor.

        Without ``session_host`` the run bundle showed a pooled
        ``development`` node with 0 messages / 0 tool uses; without the
        per-run EventRegistry resolver its seats never reached the run's
        usage ledger, so the whole node was missing from the Usage table
        while planner/synthesis (which use the runner-wired dispatcher)
        reported normally.
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
        d1, d2 = FakeDispatcher(), FakeDispatcher()
        resolver = MagicMock(name="run_id -> EventRegistry")
        shared_dispatcher = MagicMock()
        shared_dispatcher.event_registry_resolver = resolver
        host = object()
        node = DevelopmentNode(
            dispatcher=shared_dispatcher,
            pool_config=DevAgentPoolConfig(agents=[DevAgentSpec(agent="claude-code", count=2)]),
            dispatcher_builder=_dispatcher_builder_factory([d1, d2]),
        )

        await node.execute({"run_id": "r1", "research_output": research, "session_host": host})

        assert d1.session_hosts and all(h is host for h in d1.session_hosts)
        assert d2.session_hosts and all(h is host for h in d2.session_hosts)
        assert d1.resolver is resolver
        assert d2.resolver is resolver

    async def test_pool_wiring_is_optional(self, tmp_path):
        """No host and no wired resolver stays exactly as before."""
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
        shared_dispatcher = MagicMock()
        shared_dispatcher.event_registry_resolver = None
        node = DevelopmentNode(
            dispatcher=shared_dispatcher,
            pool_config=DevAgentPoolConfig(agents=[DevAgentSpec(agent="claude-code", count=2)]),
            dispatcher_builder=_dispatcher_builder_factory([d1, d2]),
        )

        result = await node.execute({"run_id": "r1", "research_output": research})

        assert set(result.files_changed) == {"TASK-1.py", "TASK-2.py"}
        assert d1.resolver is None
        assert d1.session_hosts == [None]

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

    async def test_merge_performed_stamped_only_when_a_merge_ran(self, tmp_path, monkeypatch):
        """DevelopmentOutput must record whether sub-worktrees were merged.

        SynthesisNode reads this to decide whether post-merge
        reconciliation has any subject matter at all — inferring it from
        the worker count alone cannot distinguish "two workers, shared
        tree" (nothing merged) from "two workers, isolated trees".
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
        monkeypatch.setattr(conf, "WORKTREE_BASE_PATH", str(tmp_path))
        monkeypatch.setattr(development_module, "SubWorktreeManager", lambda **kw: FakeManager(**kw))

        def _node(isolation: str) -> DevelopmentNode:
            return DevelopmentNode(
                dispatcher=MagicMock(),
                pool_config=DevAgentPoolConfig(
                    agents=[DevAgentSpec(agent="claude-code", count=2)],
                    isolation_mode=isolation,
                ),
                dispatcher_builder=_dispatcher_builder_factory([FakeDispatcher(), FakeDispatcher()]),
            )

        isolated_out = await _node("isolated").execute({"run_id": "r1", "research_output": research})
        assert isolated_out.merge_performed is True

        shared_out = await _node("shared").execute({"run_id": "r2", "research_output": research})
        assert shared_out.merge_performed is False


@pytest.mark.asyncio
class TestSingleAgentTaskManifest:
    """A single agent implements the WHOLE spec — every task in it.

    So it needs the same index-resolved artifact paths a pooled seat gets
    via ``TaskScopedBrief.task_file``, once per task. Without them it
    reconstructs `TASK-<NNN>-<slug>.md` and reaches for the FEATURE slug.
    """

    @staticmethod
    def _dispatched_brief(dispatcher) -> ResearchOutput:
        return dispatcher.dispatch.await_args.kwargs["brief"]

    async def test_manifest_carries_the_real_paths(self, tmp_path):
        _write_index(
            tmp_path,
            "FEAT-494",
            "select-model-dev-flow-ideation-model",
            [
                {
                    "id": "TASK-2717",
                    "title": "catalog.py — Add Fable models",
                    "status": "done",
                    "depends_on": [],
                    "file": "sdd/tasks/completed/TASK-2717-catalog-add-fable-and-research-primary-role.md",
                },
                {
                    "id": "TASK-2719",
                    "title": "Tests — Assert Fable in catalog",
                    "status": "pending",
                    "depends_on": ["TASK-2717"],
                    "file": "sdd/tasks/active/TASK-2719-tests-fable-research-primary.md",
                },
            ],
        )
        research = _research(str(tmp_path), feat_id="FEAT-494")
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(return_value=DevelopmentOutput(files_changed=[], commit_shas=[], summary="s"))
        node = DevelopmentNode(dispatcher=dispatcher)

        await node.execute({"run_id": "r1", "research_output": research})

        note = self._dispatched_brief(dispatcher).log_excerpts[0]
        assert "TASK INVENTORY" in note
        assert "sdd/tasks/active/TASK-2719-tests-fable-research-primary.md" in note
        assert "sdd/tasks/completed/TASK-2717-catalog-add-fable-and-research-primary-role.md" in note
        # The status is what lets the agent skip work already banked.
        assert "TASK-2717 [done]" in note
        assert "TASK-2719 [pending]" in note
        assert "depends_on: TASK-2717" in note
        # The feature slug must never appear as a filename.
        assert "TASK-2719-select-model-dev-flow-ideation-model.md" not in note

    async def test_manifest_is_prepended_not_replacing_prior_excerpts(self, tmp_path):
        _write_index(
            tmp_path,
            "FEAT-494",
            "my-feature",
            [{"id": "TASK-1", "status": "pending", "depends_on": [], "file": "sdd/tasks/active/TASK-1-a.md"}],
        )
        research = _research(str(tmp_path), feat_id="FEAT-494").model_copy(
            update={"log_excerpts": ["pre-existing excerpt"]}
        )
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(return_value=DevelopmentOutput(files_changed=[], commit_shas=[], summary="s"))
        node = DevelopmentNode(dispatcher=dispatcher)

        await node.execute({"run_id": "r1", "research_output": research})

        excerpts = self._dispatched_brief(dispatcher).log_excerpts
        assert "TASK INVENTORY" in excerpts[0]
        assert excerpts[1] == "pre-existing excerpt"

    async def test_no_index_dispatches_unchanged(self, tmp_path):
        """A hotfix reserves no ids and has no index — no manifest, no crash."""
        research = _research(str(tmp_path), feat_id="FEAT-494")
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(return_value=DevelopmentOutput(files_changed=[], commit_shas=[], summary="s"))
        node = DevelopmentNode(dispatcher=dispatcher)

        await node.execute({"run_id": "r1", "research_output": research})

        assert self._dispatched_brief(dispatcher).log_excerpts == []

    async def test_task_without_a_file_is_listed_but_not_invented(self, tmp_path):
        _write_index(
            tmp_path,
            "FEAT-494",
            "my-feature",
            [{"id": "TASK-1", "title": "no file recorded", "status": "pending", "depends_on": []}],
        )
        research = _research(str(tmp_path), feat_id="FEAT-494")
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(return_value=DevelopmentOutput(files_changed=[], commit_shas=[], summary="s"))
        node = DevelopmentNode(dispatcher=dispatcher)

        await node.execute({"run_id": "r1", "research_output": research})

        note = self._dispatched_brief(dispatcher).log_excerpts[0]
        assert "TASK-1 [pending]" in note
        assert "not recorded in the index" in note


def _failing_qa_report() -> QAReport:
    """The shape QANode publishes when the deterministic gate goes red."""
    return QAReport(
        passed=False,
        lint_passed=False,
        lint_output="catalog.py:1:1: I001 un-sorted-imports",
        criterion_results=[
            CriterionResult(
                name="pytest (derived: changed scopes)",
                kind="shell",
                exit_code=4,
                passed=False,
            )
        ],
        code_review_passed=False,
        code_review_findings=["catalog.py: 28 UP-series violations"],
    )


class TestRepairFeedbackBrief:
    """`_with_repair_feedback` must carry BOTH halves of the re-entry
    context: the condensed QA failure AND the feedback router's dev_brief.
    """

    def test_dev_brief_is_appended_after_the_condensed_report(self, tmp_path):
        node = DevelopmentNode(dispatcher=MagicMock())
        shared = {
            "qa_report": _failing_qa_report(),
            "feedback_decision": FeedbackDecision(
                decision="retry",
                dev_brief="  Fix the I001 import order in catalog.py.  ",
            ),
        }

        out = node._with_repair_feedback(shared, _research(str(tmp_path)))

        assert shared["qa_attempt"] == 2
        assert len(out.log_excerpts) == 2
        # Evidence first, then the instruction derived from it.
        assert out.log_excerpts[0].startswith("[QA repair-loop feedback — attempt 2]")
        assert out.log_excerpts[1] == (
            "[Feedback router — required fixes for attempt 2]\n" "Fix the I001 import order in catalog.py."
        )

    def test_bug_mode_without_a_feedback_decision_is_unchanged(self, tmp_path):
        """Bug-mode topology has no feedback_router — one note, as before."""
        node = DevelopmentNode(dispatcher=MagicMock())
        shared = {"qa_report": _failing_qa_report()}

        out = node._with_repair_feedback(shared, _research(str(tmp_path)))

        assert len(out.log_excerpts) == 1
        assert out.log_excerpts[0].startswith("[QA repair-loop feedback — attempt 2]")

    def test_blank_dev_brief_appends_nothing(self, tmp_path):
        node = DevelopmentNode(dispatcher=MagicMock())
        shared = {
            "qa_report": _failing_qa_report(),
            "feedback_decision": FeedbackDecision(decision="retry", dev_brief="   "),
        }

        out = node._with_repair_feedback(shared, _research(str(tmp_path)))

        assert len(out.log_excerpts) == 1

    def test_first_pass_never_stamps_a_brief(self, tmp_path):
        node = DevelopmentNode(dispatcher=MagicMock())
        shared = {
            "feedback_decision": FeedbackDecision(decision="retry", dev_brief="never read"),
        }

        research = _research(str(tmp_path))
        out = node._with_repair_feedback(shared, research)

        assert out is research
        assert "qa_attempt" not in shared


@pytest.mark.asyncio
class TestRepairReentryDispatch:
    """A repair-loop re-entry whose task index holds nothing runnable must
    still dispatch an agent — otherwise QA re-runs on an unchanged tree.
    """

    @staticmethod
    def _done_index(tmp_path):
        _write_index(
            tmp_path,
            "FEAT-323",
            "my-feature",
            [
                {"id": "TASK-1", "status": "done", "depends_on": []},
                {"id": "TASK-2", "status": "done", "depends_on": ["TASK-1"]},
                {"id": "TASK-3", "status": "done", "depends_on": ["TASK-2"]},
            ],
        )

    async def test_repair_reentry_with_every_task_done_dispatches_one_seat(self, tmp_path):
        self._done_index(tmp_path)
        pool_dispatcher = FakeDispatcher()
        node = DevelopmentNode(
            dispatcher=MagicMock(),
            pool_config=DevAgentPoolConfig(agents=[DevAgentSpec(agent="nova", count=2)]),
            dispatcher_builder=_dispatcher_builder_factory([pool_dispatcher]),
        )
        ctx = {
            "run_id": "r1",
            "research_output": _research(str(tmp_path)),
            "qa_report": _failing_qa_report(),
            "feedback_decision": FeedbackDecision(decision="retry", dev_brief="Fix the I001 import order."),
        }

        await node.execute(ctx)

        # Exactly one dispatch, and it is the whole-feature repair seat —
        # not a per-task pool dispatch (which carries a TaskScopedBrief).
        assert len(pool_dispatcher.calls) == 1
        task_id, _node_id, cwd = pool_dispatcher.calls[0]
        assert task_id is None
        assert cwd == str(tmp_path)

    async def test_repair_seat_brief_carries_the_dev_brief(self, tmp_path):
        self._done_index(tmp_path)
        captured = {}

        class CapturingDispatcher(FakeDispatcher):
            async def dispatch(self, *, brief, **kwargs):
                captured["brief"] = brief
                return await super().dispatch(brief=brief, **kwargs)

        node = DevelopmentNode(
            dispatcher=MagicMock(),
            pool_config=DevAgentPoolConfig(agents=[DevAgentSpec(agent="nova", count=2)]),
            dispatcher_builder=_dispatcher_builder_factory([CapturingDispatcher()]),
        )
        ctx = {
            "run_id": "r1",
            "research_output": _research(str(tmp_path)),
            "qa_report": _failing_qa_report(),
            "feedback_decision": FeedbackDecision(decision="retry", dev_brief="Fix the I001 import order."),
        }

        await node.execute(ctx)

        excerpts = "\n".join(captured["brief"].log_excerpts)
        assert "Fix the I001 import order." in excerpts

    async def test_first_pass_with_every_task_done_still_dispatches_nothing(self, tmp_path):
        """Regression guard: a fresh run over a pre-completed index is a
        legitimate no-op and must NOT be mistaken for a repair re-entry."""
        self._done_index(tmp_path)
        pool_dispatcher = FakeDispatcher()
        node = DevelopmentNode(
            dispatcher=MagicMock(),
            pool_config=DevAgentPoolConfig(agents=[DevAgentSpec(agent="nova", count=2)]),
            dispatcher_builder=_dispatcher_builder_factory([pool_dispatcher]),
        )
        ctx = {"run_id": "r1", "research_output": _research(str(tmp_path))}

        await node.execute(ctx)

        assert pool_dispatcher.calls == []

    async def test_repair_reentry_with_pending_tasks_still_uses_the_pool(self, tmp_path):
        """The guard only fires on an EMPTY wave — a retry that still has
        runnable tasks keeps going through the pool, per task."""
        _write_index(
            tmp_path,
            "FEAT-323",
            "my-feature",
            [
                {"id": "TASK-1", "status": "done", "depends_on": []},
                {"id": "TASK-2", "status": "pending", "depends_on": []},
            ],
        )
        pool_dispatcher = FakeDispatcher()
        node = DevelopmentNode(
            dispatcher=MagicMock(),
            pool_config=DevAgentPoolConfig(agents=[DevAgentSpec(agent="nova", count=2)]),
            dispatcher_builder=_dispatcher_builder_factory([pool_dispatcher]),
        )
        ctx = {
            "run_id": "r1",
            "research_output": _research(str(tmp_path)),
            "qa_report": _failing_qa_report(),
        }

        await node.execute(ctx)

        assert [c[0] for c in pool_dispatcher.calls] == ["TASK-2"]


# ---------------------------------------------------------------------------
# FEAT-496 TASK-2730 — resolver seat + single-agent path labels
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestResolverLabels:
    async def test_resolver_dispatch_is_labelled(self, tmp_path):
        from parrot.flows.dev_loop.agent_pool import PoolWorker
        from parrot.flows.dev_loop.models import ClaudeCodeDispatchProfile

        dispatcher = FakeDispatcher()
        worker = PoolWorker(
            worker_id="development.w1",
            spec=DevAgentSpec(agent="claude-code", model="claude-sonnet-4-6"),
            dispatcher=dispatcher,
            profile=ClaudeCodeDispatchProfile(model="claude-sonnet-4-6"),
        )
        pool = MagicMock()
        pool.workers = [worker]

        node = DevelopmentNode(dispatcher=MagicMock())
        research = _research(str(tmp_path))

        ok = await node._resolve_conflict(
            str(tmp_path),
            "conflict in x.py",
            pool=pool,
            research=research,
            run_id="r1",
        )

        assert ok is True
        labels = dispatcher.labels[-1]
        assert labels.task_id == "RESOLVE_MERGE_CONFLICT"
        assert labels.seat == "development.resolver"
        assert labels.agent == "claude-code"
        assert labels.model == "claude-sonnet-4-6"

    async def test_single_agent_path_is_labelled(self, tmp_path):
        research = _research(str(tmp_path))
        dispatcher = FakeDispatcher()
        node = DevelopmentNode(dispatcher=dispatcher)

        ctx = {"run_id": "r1", "research_output": research}
        await node.execute(ctx)

        labels = dispatcher.labels[-1]
        assert labels is not None
        assert labels.seat == "development"
