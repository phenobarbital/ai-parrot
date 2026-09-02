"""Unit tests for DevAgentPool (FEAT-323 TASK-1860)."""

from __future__ import annotations

import logging

import pytest

from parrot.flows.dev_loop.agent_pool import (
    DevAgentPool,
    aggregate_outputs,
    is_internal_error,
)
from parrot.flows.dev_loop.models import (
    DevAgentPoolConfig,
    DevAgentSpec,
    DevelopmentOutput,
    ResearchOutput,
)
from parrot.flows.dev_loop.task_scheduler import TaskRef


class FakeDispatcher:
    """Fulfils the ``DevLoopCodeDispatcher`` Protocol.

    Records every dispatch call (including the ``profile`` actually used,
    for FEAT-377 TASK-1912's escalation-model assertions) and can be
    programmed to fail (raise) for specific task ids — only on the FIRST
    call for that id, so a retry on a different worker succeeds.
    """

    def __init__(self, fail_ids=()):
        self.calls = []
        self.fail_ids = set(fail_ids)

    async def dispatch(self, *, brief, profile, output_model, run_id, node_id, cwd, session_host=None):
        self.calls.append((brief.task_id, node_id, cwd, profile))
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

    async def dispatch(self, *, brief, profile, output_model, run_id, node_id, cwd, session_host=None):
        self.calls.append((brief.task_id, node_id, cwd))
        raise RuntimeError("always fails")


class SelfDeclaredIncompleteDispatcher:
    """Returns a well-formed output that admits it did not finish.

    This is what a salvaged dispatch looks like when the model ran out of
    turns mid-task: the payload validates, so the pool would otherwise bank
    it as a completed task.
    """

    def __init__(self):
        self.calls = []

    async def dispatch(self, *, brief, profile, output_model, run_id, node_id, cwd, session_host=None):
        self.calls.append((brief.task_id, node_id))
        return DevelopmentOutput(
            files_changed=[f"{brief.task_id}.py"],
            commit_shas=[],
            summary="ran out of turns halfway",
            incomplete_tasks=[brief.task_id],
        )


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


def _build_pool_with_specs(dispatchers, specs, *, pool_max=99):
    """Build a DevAgentPool with explicit ``DevAgentSpec``s (FEAT-377
    TASK-1912) and a real ``model``-bearing dispatch profile per worker
    (``ClaudeCodeDispatchProfile`` — the pool only ever reads/copies its
    ``model`` field via ``model_copy``, never anything Claude-specific)."""
    from parrot.flows.dev_loop.models import ClaudeCodeDispatchProfile

    config = DevAgentPoolConfig(agents=list(specs))

    def _builder(spec):
        idx = len(_builder.built)
        d = dispatchers[idx]
        _builder.built.append(d)
        return d, ClaudeCodeDispatchProfile(model=spec.model or "base-model")

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

    async def test_self_declared_incomplete_output_is_not_a_completion(self):
        """A salvaged dispatch must not buy 'completed' by admitting failure.

        The forced `final_output` salvage turn asks the model to declare
        partial work in `incomplete_tasks`; honouring that declaration is
        what keeps the salvage from turning lost tasks into false successes.
        """
        d1 = SelfDeclaredIncompleteDispatcher()
        pool = _build_pool([d1])  # single worker: retry lands on itself
        tasks = _tasks("TASK-1")

        result = await pool.run_wave(
            tasks, research=_research(), run_id="run-1", cwd_for=_cwd_for
        )

        assert result.completed == {}
        assert result.failed == ["TASK-1"]
        assert len(d1.calls) == 2  # it still gets its retry

    async def test_incomplete_tasks_naming_another_task_is_still_a_completion(self):
        """Only the dispatch's OWN task id disqualifies it."""

        class _OtherTaskIncomplete(SelfDeclaredIncompleteDispatcher):
            async def dispatch(self, *, brief, profile, output_model, run_id, node_id, cwd, session_host=None):
                self.calls.append((brief.task_id, node_id))
                return DevelopmentOutput(
                    files_changed=[],
                    commit_shas=["sha-1"],
                    summary="done; noted a sibling task is not",
                    incomplete_tasks=["TASK-99"],
                )

        d1 = _OtherTaskIncomplete()
        pool = _build_pool([d1])

        result = await pool.run_wave(
            _tasks("TASK-1"), research=_research(), run_id="run-1", cwd_for=_cwd_for
        )

        assert list(result.completed) == ["TASK-1"]
        assert result.failed == []

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


@pytest.mark.asyncio
class TestEscalationModel:
    """FEAT-377 TASK-1912: escalation_model — stronger model on retry."""

    async def test_retry_uses_escalation_model(self):
        d1 = FakeDispatcher(fail_ids={"TASK-1"})  # single worker: retries itself
        spec = DevAgentSpec(
            agent="claude-code", model="claude-sonnet-4-6",
            escalation_model="claude-opus-4-6",
        )
        pool = _build_pool_with_specs([d1], [spec])

        result = await pool.run_wave(
            _tasks("TASK-1"), research=_research(), run_id="run-1", cwd_for=_cwd_for
        )

        assert "TASK-1" in result.completed
        assert len(d1.calls) == 2
        first_profile = d1.calls[0][3]
        retry_profile = d1.calls[1][3]
        assert first_profile.model == "claude-sonnet-4-6"
        assert retry_profile.model == "claude-opus-4-6"

    async def test_retry_same_model_when_unset(self):
        d1 = FakeDispatcher(fail_ids={"TASK-1"})
        spec = DevAgentSpec(agent="claude-code", model="claude-sonnet-4-6")
        pool = _build_pool_with_specs([d1], [spec])

        result = await pool.run_wave(
            _tasks("TASK-1"), research=_research(), run_id="run-1", cwd_for=_cwd_for
        )

        assert "TASK-1" in result.completed
        assert len(d1.calls) == 2
        assert d1.calls[0][3].model == "claude-sonnet-4-6"
        assert d1.calls[1][3].model == "claude-sonnet-4-6"

    async def test_first_attempt_never_escalates(self):
        d1, d2 = FakeDispatcher(), FakeDispatcher()
        specs = [
            DevAgentSpec(
                agent="claude-code", model="claude-sonnet-4-6",
                escalation_model="claude-opus-4-6",
            ),
            DevAgentSpec(
                agent="claude-code", model="claude-sonnet-4-6",
                escalation_model="claude-opus-4-6",
            ),
        ]
        pool = _build_pool_with_specs([d1, d2], specs)

        result = await pool.run_wave(
            _tasks("TASK-1", "TASK-2"), research=_research(), run_id="run-1",
            cwd_for=_cwd_for,
        )

        assert set(result.completed) == {"TASK-1", "TASK-2"}
        assert d1.calls[0][3].model == "claude-sonnet-4-6"
        assert d2.calls[0][3].model == "claude-sonnet-4-6"

    async def test_escalation_on_different_retry_worker_uses_that_workers_spec(self):
        """The retry may land on a DIFFERENT worker (round-robin) — the
        escalation model used must be the RETRY worker's own spec, not the
        originally-failed worker's."""
        d1 = FakeDispatcher(fail_ids={"TASK-1"})
        d2 = FakeDispatcher()
        specs = [
            DevAgentSpec(agent="claude-code", model="m1", escalation_model=""),
            DevAgentSpec(agent="claude-code", model="m2", escalation_model="m2-strong"),
        ]
        pool = _build_pool_with_specs([d1, d2], specs)

        result = await pool.run_wave(
            _tasks("TASK-1", "TASK-2"), research=_research(), run_id="run-1",
            cwd_for=_cwd_for,
        )

        assert "TASK-1" in result.completed
        # TASK-1 originally assigned to w1 (d1, fails), retried on w2 (d2).
        retry_call = next(c for c in d2.calls if c[0] == "TASK-1")
        assert retry_call[3].model == "m2-strong"

    async def test_escalated_profile_handles_llm_field_profile(self):
        """FEAT-377 TASK-1912: the 'nvidia' backend's LLMCodeDispatchProfile
        carries the model in a combined ``llm="nvidia:<model>"`` field, not
        a plain ``model`` field."""
        from parrot.flows.dev_loop.agent_pool import DevAgentPool, PoolWorker
        from parrot.flows.dev_loop.models import LLMCodeDispatchProfile

        spec = DevAgentSpec(
            agent="nvidia", model="kimi-k2", escalation_model="kimi-k3-strong",
        )
        worker = PoolWorker(
            worker_id="development.w1", spec=spec,
            dispatcher=FakeDispatcher(),
            profile=LLMCodeDispatchProfile(llm="nvidia:kimi-k2"),
        )
        escalated = DevAgentPool._escalated_profile(worker)
        assert escalated.llm == "nvidia:kimi-k3-strong"
        # The original worker profile is never mutated.
        assert worker.profile.llm == "nvidia:kimi-k2"


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


# ---------------------------------------------------------------------------
# An internal error is OUR bug, not a failed dispatch. Swallowed as "task
# failed" it fails every task on every worker, each burning a retry, and the
# wave reports PARTIAL half an hour later instead of saying what broke.
# ---------------------------------------------------------------------------


class BrokenSignatureDispatcher:
    """A dispatcher whose call signature drifted from the pool's call.

    Models the real incident: the pool started passing ``session_host=``
    and this side had not caught up, so every dispatch raised TypeError.
    """

    def __init__(self):
        self.calls = []

    async def dispatch(self, *, brief, profile, output_model, run_id, node_id, cwd, **_kw):
        self.calls.append((brief.task_id, node_id))
        raise TypeError(
            "dispatch() got an unexpected keyword argument 'session_host'"
        )


@pytest.mark.asyncio
async def test_internal_error_is_not_retried_on_another_worker():
    d1, d2 = BrokenSignatureDispatcher(), BrokenSignatureDispatcher()
    pool = _build_pool([d1, d2])

    result = await pool.run_wave(
        _tasks("TASK-1"), research=_research(), run_id="run-1", cwd_for=_cwd_for
    )

    assert result.failed == ["TASK-1"]
    # ONE attempt in total: a retry would re-run the same bad call.
    assert len(d1.calls) + len(d2.calls) == 1


@pytest.mark.asyncio
async def test_internal_error_is_logged_at_error_with_a_traceback(caplog):
    pool = _build_pool([BrokenSignatureDispatcher()])

    with caplog.at_level(logging.ERROR):
        await pool.run_wave(
            _tasks("TASK-1"), research=_research(), run_id="run-1", cwd_for=_cwd_for
        )

    records = [r for r in caplog.records if "internal error" in r.getMessage()]
    assert records, "the internal error must be logged at ERROR"
    assert records[0].exc_info is not None, "a traceback is the whole point"


@pytest.mark.asyncio
async def test_internal_error_is_marked_in_the_returned_reason():
    dispatcher = BrokenSignatureDispatcher()
    pool = _build_pool([dispatcher])

    _task_id, _worker_id, output, error = await pool._dispatch_one(
        _tasks("TASK-1")[0],
        pool.workers[0],
        research=_research(),
        run_id="run-1",
        cwd_for=_cwd_for,
    )

    assert output is None
    assert is_internal_error(error)
    assert "TypeError" in error


@pytest.mark.asyncio
async def test_a_failed_dispatch_is_still_retried():
    """Contrast: a dispatch that merely FAILED keeps its second chance."""
    d1, d2 = AlwaysFailDispatcher(), AlwaysFailDispatcher()
    pool = _build_pool([d1, d2])

    result = await pool.run_wave(
        _tasks("TASK-1"), research=_research(), run_id="run-1", cwd_for=_cwd_for
    )

    assert result.failed == ["TASK-1"]
    assert len(d1.calls) + len(d2.calls) == 2


@pytest.mark.asyncio
async def test_brief_carries_the_task_file_from_the_index():
    """Without it the seat guesses the slug — and it guesses the FEATURE slug.

    Regression: a worker's first turn was `read_file
    sdd/tasks/active/TASK-2719-<feature-slug>.md`, which does not exist;
    the real artifact is `TASK-2719-tests-fable-research-primary.md`.
    """
    briefs = []

    class RecordingDispatcher:
        async def dispatch(self, *, brief, profile, output_model, run_id, node_id, cwd, session_host=None):
            briefs.append(brief)
            return DevelopmentOutput(
                files_changed=[], commit_shas=[], summary=brief.task_id
            )

    pool = DevAgentPool.build(
        DevAgentPoolConfig(agents=[DevAgentSpec(agent="codex")]),
        lambda spec: (RecordingDispatcher(), object()),
        4,
    )
    task = TaskRef(
        id="TASK-2719",
        status="pending",
        depends_on=[],
        file="sdd/tasks/active/TASK-2719-tests-fable-research-primary.md",
    )

    await pool.run_wave([task], research=_research(), run_id="r1", cwd_for=lambda _w: "/tmp/wt")

    assert briefs[0].task_file == "sdd/tasks/active/TASK-2719-tests-fable-research-primary.md"
    # The prompt is built from the serialized brief, so the path must
    # survive `model_dump_json()` — that is what the seat actually reads.
    assert "TASK-2719-tests-fable-research-primary.md" in briefs[0].model_dump_json()
