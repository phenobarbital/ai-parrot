"""Unit tests for DevAgentPool (FEAT-323 TASK-1860)."""

from __future__ import annotations

import pytest

from parrot.flows.dev_loop.agent_pool import DevAgentPool, aggregate_outputs
from parrot.flows.dev_loop.models import (
    DevAgentPoolConfig,
    DevAgentSpec,
    DevelopmentOutput,
    ResearchOutput,
)
from parrot.flows.dev_loop.task_scheduler import TaskRef


class FakeDispatcher:
    """Fulfils the ``DevLoopCodeDispatcher`` Protocol.

    Records every dispatch call and can be programmed to fail (raise) for
    specific task ids — only on the FIRST call for that id, so a retry on
    a different worker succeeds.
    """

    def __init__(self, fail_ids=()):
        self.calls = []
        self.fail_ids = set(fail_ids)

    async def dispatch(self, *, brief, profile, output_model, run_id, node_id, cwd):
        self.calls.append((brief.task_id, node_id, cwd))
        if brief.task_id in self.fail_ids:
            self.fail_ids.discard(brief.task_id)
            raise RuntimeError("boom")
        return DevelopmentOutput(
            files_changed=[f"{brief.task_id}.py"],
            commit_shas=[f"sha-{brief.task_id}"],
            summary=brief.task_id,
        )


class AlwaysFailDispatcher:
    """Fails every dispatch, unconditionally."""

    def __init__(self):
        self.calls = []

    async def dispatch(self, *, brief, profile, output_model, run_id, node_id, cwd):
        self.calls.append((brief.task_id, node_id, cwd))
        raise RuntimeError("always fails")


def _research() -> ResearchOutput:
    return ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-323",
        branch_name="feat-323-x",
        worktree_path="/tmp/wt",
    )


def _tasks(*ids):
    return [TaskRef(id=i, status="pending", depends_on=[]) for i in ids]


def _cwd_for(worker_id: str) -> str:
    return f"/tmp/wt/{worker_id}"


def _build_pool(dispatchers, *, pool_max=99):
    """Build a DevAgentPool with one worker per fake dispatcher."""
    config = DevAgentPoolConfig(
        agents=[DevAgentSpec(agent="claude-code") for _ in dispatchers]
    )

    def _builder(spec):
        idx = len(_builder.built)
        d = dispatchers[idx]
        _builder.built.append(d)
        return d, object()

    _builder.built = []
    return DevAgentPool.build(config, _builder, pool_max)


@pytest.mark.asyncio
class TestPool:
    async def test_round_robin_and_stream_ids(self):
        d1, d2 = FakeDispatcher(), FakeDispatcher()
        pool = _build_pool([d1, d2])
        tasks = _tasks("TASK-1", "TASK-2", "TASK-3", "TASK-4")

        result = await pool.run_wave(
            tasks, research=_research(), run_id="run-1", cwd_for=_cwd_for
        )

        assert set(result.completed) == {"TASK-1", "TASK-2", "TASK-3", "TASK-4"}
        assert result.failed == []
        # d1 gets TASK-1/TASK-3, d2 gets TASK-2/TASK-4 (round robin).
        assert [c[0] for c in d1.calls] == ["TASK-1", "TASK-3"]
        assert [c[0] for c in d2.calls] == ["TASK-2", "TASK-4"]
        assert d1.calls[0][1] == "development.w1"
        assert d2.calls[0][1] == "development.w2"

    async def test_retry_on_other_worker_then_partial(self):
        d1, d2 = FakeDispatcher(fail_ids={"TASK-1"}), FakeDispatcher()
        pool = _build_pool([d1, d2])
        tasks = _tasks("TASK-1", "TASK-2")

        result = await pool.run_wave(
            tasks, research=_research(), run_id="run-1", cwd_for=_cwd_for
        )

        # TASK-1 assigned to w1 (fails), retried on w2 (succeeds).
        assert "TASK-1" in result.completed
        assert result.failed == []
        assert [c[0] for c in d2.calls] == ["TASK-2", "TASK-1"]

    async def test_second_failure_marks_task_failed(self):
        d1 = AlwaysFailDispatcher()
        pool = _build_pool([d1])  # single worker: retry lands on itself
        tasks = _tasks("TASK-1")

        result = await pool.run_wave(
            tasks, research=_research(), run_id="run-1", cwd_for=_cwd_for
        )

        assert result.completed == {}
        assert result.failed == ["TASK-1"]
        assert len(d1.calls) == 2  # original + retry, both on the same worker

    async def test_pool_max_truncates(self):
        config = DevAgentPoolConfig(agents=[DevAgentSpec(agent="claude-code", count=5)])

        def _builder(spec):
            return FakeDispatcher(), object()

        pool = DevAgentPool.build(config, _builder, pool_max=2)
        assert len(pool.workers) == 2
        assert [w.worker_id for w in pool.workers] == ["development.w1", "development.w2"]

    async def test_empty_tasks_returns_empty_result(self):
        pool = _build_pool([FakeDispatcher()])
        result = await pool.run_wave(
            [], research=_research(), run_id="run-1", cwd_for=_cwd_for
        )
        assert result.completed == {} and result.failed == [] and result.worker_summaries == []

    async def test_no_workers_raises(self):
        config = DevAgentPoolConfig(agents=[DevAgentSpec(agent="claude-code")])
        pool = DevAgentPool.build(config, lambda spec: (FakeDispatcher(), object()), pool_max=0)
        with pytest.raises(ValueError):
            await pool.run_wave(
                _tasks("TASK-1"), research=_research(), run_id="run-1", cwd_for=_cwd_for
            )


class TestAggregate:
    def test_single_worker_single_task_equals_worker_output(self):
        from parrot.flows.dev_loop.agent_pool import WaveResult
        from parrot.flows.dev_loop.models import WorkerSummary

        output = DevelopmentOutput(
            files_changed=["a.py"], commit_shas=["sha1"], summary="TASK-1"
        )
        wave = WaveResult(
            completed={"TASK-1": output},
            failed=[],
            worker_summaries=[
                WorkerSummary(
                    worker_id="development.w1",
                    agent="claude-code",
                    model="claude-sonnet-4-6",
                    tasks_completed=["TASK-1"],
                    tasks_failed=[],
                    summary="completed=1 failed=0",
                )
            ],
        )

        agg = aggregate_outputs([wave], incomplete=[])

        assert agg.files_changed == ["a.py"]
        assert agg.commit_shas == ["sha1"]
        assert agg.incomplete_tasks == []
        assert len(agg.worker_summaries) == 1
        assert agg.worker_summaries[0].worker_id == "development.w1"

    def test_dedup_and_metadata(self):
        from parrot.flows.dev_loop.agent_pool import WaveResult
        from parrot.flows.dev_loop.models import WorkerSummary

        wave1 = WaveResult(
            completed={
                "TASK-1": DevelopmentOutput(
                    files_changed=["shared.py", "a.py"],
                    commit_shas=["sha1"],
                    summary="TASK-1",
                )
            },
            failed=[],
            worker_summaries=[
                WorkerSummary(
                    worker_id="development.w1",
                    agent="claude-code",
                    model="m",
                    tasks_completed=["TASK-1"],
                    summary="wave1",
                )
            ],
        )
        wave2 = WaveResult(
            completed={
                "TASK-2": DevelopmentOutput(
                    files_changed=["shared.py", "b.py"],
                    commit_shas=["sha2"],
                    summary="TASK-2",
                )
            },
            failed=[],
            worker_summaries=[
                WorkerSummary(
                    worker_id="development.w1",
                    agent="claude-code",
                    model="m",
                    tasks_completed=["TASK-2"],
                    summary="wave2",
                )
            ],
        )

        agg = aggregate_outputs([wave1, wave2], incomplete=["TASK-3"])

        # shared.py deduplicated, first-seen order preserved.
        assert agg.files_changed == ["shared.py", "a.py", "b.py"]
        assert agg.commit_shas == ["sha1", "sha2"]
        assert agg.incomplete_tasks == ["TASK-3"]
        # Same worker across waves merges into ONE WorkerSummary.
        assert len(agg.worker_summaries) == 1
        merged = agg.worker_summaries[0]
        assert merged.tasks_completed == ["TASK-1", "TASK-2"]
        assert "wave1" in merged.summary and "wave2" in merged.summary
