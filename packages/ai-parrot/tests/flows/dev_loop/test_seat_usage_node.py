"""DevelopmentNode publishes the per-seat usage roll-up (sdd-coder journals or pool seats)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parrot.flows.dev_loop.models import DevelopmentOutput, ResearchOutput, WorkerSummary
from parrot.flows.dev_loop.nodes.development import DevelopmentNode
from parrot.flows.dev_loop.sdd_coder.models import AttemptRecord, CoderJob, TaskResult
from parrot.flows.dev_loop.sdd_coder.summary import JOURNAL_DIR
from parrot.flows.dev_loop.session_state import DispatchCompleted, DispatchQueued, SessionHost


class _Dispatcher:
    def __init__(self, dev_out: DevelopmentOutput):
        self.dev_out = dev_out

    async def dispatch(self, **_kwargs):
        return self.dev_out


def _research(worktree: Path) -> ResearchOutput:
    return ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="s",
        feat_id="FEAT-1",
        branch_name="feat-1",
        worktree_path=str(worktree),
        log_excerpts=[],
        base_branch="dev",
    )


def _journal(worktree: Path) -> None:
    job = CoderJob(
        job_id="job-1",
        feature_id="FEAT-1",
        chunk_task_ids=["TASK-1"],
        state="done",
        started_at="now",
        tasks=[
            TaskResult(
                task_id="TASK-1",
                outcome="merged",
                attempts=[
                    AttemptRecord(
                        attempt=1,
                        seat_label="qwen",
                        backend="nova",
                        model="qwen",
                        started_at="now",
                        duration_s=42.0,
                        usage={"input_tokens": 900, "output_tokens": 100},
                    )
                ],
            )
        ],
    )
    (worktree / JOURNAL_DIR).mkdir(parents=True)
    (worktree / JOURNAL_DIR / "job-1.json").write_text(json.dumps(json.loads(job.model_dump_json()), indent=2))


@pytest.mark.asyncio
async def test_journals_become_seat_usage_in_shared_and_state(tmp_path):
    _journal(tmp_path)
    host = SessionHost("run-1")
    dev_out = DevelopmentOutput(files_changed=["a.py"], commit_shas=["x"], summary="done")
    node = DevelopmentNode(dispatcher=_Dispatcher(dev_out))
    shared = {"run_id": "run-1", "research_output": _research(tmp_path), "session_host": host}

    await node.execute(shared)

    (seat,) = shared["seat_usage"]
    assert seat.seat == "qwen" and seat.tasks_handled == ["TASK-1"] and seat.input_tokens == 900
    assert host.state.seat_usage == [seat]
    finished = host.state.nodes["development"].progress[-1]
    assert finished.phase == "finished" and "1 seat(s)" in finished.headline


@pytest.mark.asyncio
async def test_pool_seats_fall_back_to_worker_summaries_and_seat_state(tmp_path):
    host = SessionHost("run-1")
    host.apply(DispatchQueued(node_id="development", seat="development.w1", agent="codex", model="gpt"))
    host.apply(
        DispatchCompleted(
            node_id="development", seat="development.w1", input_tokens=300, output_tokens=40, duration_ms=5000
        )
    )
    dev_out = DevelopmentOutput(
        files_changed=["a.py"],
        commit_shas=["x"],
        summary="done",
        worker_summaries=[
            WorkerSummary(worker_id="development.w1", agent="codex", model="gpt", tasks_completed=["TASK-1", "TASK-2"]),
            WorkerSummary(worker_id="development.w2", agent="nova", model="q", tasks_failed=["TASK-3"]),
        ],
    )
    node = DevelopmentNode(dispatcher=_Dispatcher(dev_out))
    shared = {"run_id": "run-1", "research_output": _research(tmp_path), "session_host": host}

    await node.execute(shared)

    rows = {s.seat: s for s in shared["seat_usage"]}
    w1 = rows["development.w1"]
    assert w1.tasks_handled == ["TASK-1", "TASK-2"] and w1.tasks_merged == 2
    assert w1.input_tokens == 300 and w1.output_tokens == 40 and w1.usage_known
    assert w1.duration_s == 5.0 and w1.attempts == 1
    w2 = rows["development.w2"]
    assert w2.failures == 1 and w2.usage_known is False and w2.input_tokens is None
    assert [s.seat for s in host.state.seat_usage] == ["development.w1", "development.w2"]


@pytest.mark.asyncio
async def test_no_journals_and_no_workers_records_nothing(tmp_path):
    dev_out = DevelopmentOutput(files_changed=[], commit_shas=[], summary="")
    node = DevelopmentNode(dispatcher=_Dispatcher(dev_out))
    shared = {"run_id": "run-1", "research_output": _research(tmp_path)}
    await node.execute(shared)
    assert "seat_usage" not in shared
