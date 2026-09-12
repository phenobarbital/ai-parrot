"""End-to-end: toolkit/engine + fake dispatchers + real git sandbox (FEAT-549 AC-1, AC-13, AC-14, AC-15)."""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Dict

from parrot.flows.dev_loop.dispatchers import DispatchExecutionError
from parrot.flows.dev_loop.models import DevelopmentOutput, LLMCodeDispatchProfile
from parrot.flows.dev_loop.sdd_coder import SddCoderEngine
from parrot.flows.dev_loop.sdd_coder.models import PlannedTask


async def _git(*args: str, cwd) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "git", *args, cwd=str(cwd), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    return proc.returncode or 0, out.decode(), err.decode()


async def _write_and_commit(worktree: Path, filename: str, content: str, message: str) -> None:
    path = worktree / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    rc, _out, err = await _git("add", filename, cwd=worktree)
    assert rc == 0, err
    rc, _out, err = await _git("commit", "-m", message, cwd=worktree)
    assert rc == 0, err


class CommittingFakeDispatcher:
    """Writes the task's listed file in `cwd`, commits, returns DevelopmentOutput.

    Records timing + cwd per call so tests can assert real concurrency and
    cwd isolation. `mode` drives the scenario:
      - "ok": commit exactly the listed file (`pkg/t<n>.py`, per the
        `git_sandbox_feature` fixture's own task templates — TASK-3120).
      - "fail": raise `DispatchExecutionError` before writing anything.
      - "extra": also commit an UNLISTED file (fidelity violation).
      - "dirty": leave an uncommitted, untracked file behind.
    """

    def __init__(self, label: str, mode: str = "ok") -> None:
        self.label, self.mode = label, mode
        self.calls: list[dict] = []

    async def dispatch(self, *, brief, profile, output_model, run_id, node_id, cwd, session_host=None, labels=None):
        start = time.monotonic()
        await asyncio.sleep(0.05)
        if self.mode == "fail":
            self.calls.append({"cwd": cwd, "start": start, "end": time.monotonic(), "subagent": profile.subagent})
            raise DispatchExecutionError(f"{self.label} down")

        n = int(brief.task_id.rsplit("-", 1)[-1])
        target = f"pkg/t{n}.py"
        await _write_and_commit(Path(cwd), target, f"# {brief.task_id}\n", f"impl {brief.task_id}")

        if self.mode == "extra":
            await _write_and_commit(Path(cwd), "pkg/extra.py", "# extra\n", "extra unlisted file")
        if self.mode == "dirty":
            (Path(cwd) / "pkg" / "untracked.py").write_text("# untracked\n")

        self.calls.append({"cwd": cwd, "start": start, "end": time.monotonic(), "subagent": profile.subagent})
        return DevelopmentOutput(files_changed=[target], commit_shas=["deadbeef"], summary=f"{self.label} done")


def make_builder(modes: Dict[str, str]):
    fakes: Dict[str, CommittingFakeDispatcher] = {}

    def builder(spec, *, redis_url, max_concurrent, stream_ttl_seconds, **_kwargs):
        fake = fakes.setdefault(spec.agent, CommittingFakeDispatcher(spec.agent, modes.get(spec.agent, "ok")))
        return fake, LLMCodeDispatchProfile()

    return builder, fakes


async def test_full_chunk_merges_and_runs_concurrently(git_sandbox_feature, three_seat_roster, noop_probe, caplog):
    worktree, feature_branch, base_path, _index_path = git_sandbox_feature
    builder, fakes = make_builder({})
    engine = SddCoderEngine(
        roster=three_seat_roster,
        probe=noop_probe,
        redis_url="redis://127.0.0.1:1/0",
        worktree_base_path=str(base_path),
        dispatcher_builder=builder,
    )
    plan = await engine.plan("FEAT-549", str(worktree))
    ids = [t.task_id for t in plan.chunks[0].tasks if not t.native]
    assert len(ids) == 3

    with caplog.at_level(logging.WARNING):
        job = await engine.run_chunk("FEAT-549", str(worktree), ids)
        done = await engine.wait(job.job_id, 30)

    assert done.state == "done"
    assert {t.outcome for t in done.tasks} == {"merged"}

    all_calls = [c for fake in fakes.values() for c in fake.calls]
    assert len(all_calls) == 3
    for call in all_calls:
        assert call["cwd"].startswith(str(base_path))
        assert "-a1" in call["cwd"]
        assert call["subagent"] == "sdd-coder"

    # AC-1: at least one pair of attempts genuinely overlapped in wall-clock time.
    overlaps = any(
        a["start"] < b["end"] and b["start"] < a["end"]
        for i, a in enumerate(all_calls)
        for b in all_calls[i + 1 :]
    )
    assert overlaps

    _rc, log, _err = await _git("log", "--oneline", feature_branch, cwd=worktree)
    for task_id in ids:
        assert f"impl {task_id}" in log

    journal = worktree / ".sdd-coder" / "jobs" / f"{job.job_id}.json"
    assert journal.is_file()

    # AC-15: Redis is unreachable (bogus URL) — at most one warning about it, not one per event.
    redis_warnings = sum(
        1 for r in caplog.records if r.levelname == "WARNING" and "redis" in r.getMessage().lower()
    )
    assert redis_warnings <= 1


async def test_partial_completion_and_orphans(git_sandbox_feature, three_seat_roster, noop_probe):
    worktree, feature_branch, base_path, _index_path = git_sandbox_feature
    builder, _fakes = make_builder({"nova": "fail", "codex": "extra"})
    engine = SddCoderEngine(
        roster=three_seat_roster,
        probe=noop_probe,
        redis_url="redis://127.0.0.1:1/0",
        worktree_base_path=str(base_path),
        dispatcher_builder=builder,
    )
    plan = await engine.plan("FEAT-549", str(worktree))
    ids = [t.task_id for t in plan.chunks[0].tasks if not t.native]
    job = await engine.run_chunk("FEAT-549", str(worktree), ids)
    done = await engine.wait(job.job_id, 30)

    retried = [t for t in done.tasks if len(t.attempts) == 2]
    assert retried, "the nova-seat task should have failed once and retried on a different seat"
    assert retried[0].attempts[0].seat_label != retried[0].attempts[1].seat_label
    assert retried[0].outcome == "merged"

    violated = [t for t in done.tasks if t.outcome == "fidelity_violation"]
    assert violated, "the codex-seat task wrote an unlisted file"
    assert "pkg/extra.py" in violated[0].unexpected_files

    plan2 = await engine.plan("FEAT-549", str(worktree))
    orphan_ids = {o.task_id for o in plan2.orphan_branches}
    assert violated[0].task_id in orphan_ids
    assert violated[0].task_id in plan2.pending


async def test_merge_conflict_leaves_feature_clean(git_sandbox_feature, three_seat_roster, noop_probe):
    worktree, feature_branch, base_path, _index_path = git_sandbox_feature
    engine = SddCoderEngine(
        roster=three_seat_roster, probe=noop_probe, redis_url="redis://127.0.0.1:1/0", worktree_base_path=str(base_path)
    )
    ctx = await engine._resolve_feature("FEAT-549", str(worktree))

    manager1 = engine._manager_for(ctx, "TASK-0001", 1)
    path1 = Path(await manager1.create("TASK-0001.a1"))
    manager2 = engine._manager_for(ctx, "TASK-0001", 2)
    path2 = Path(await manager2.create("TASK-0001.a2"))

    await _write_and_commit(path1, "pkg/t1.py", "print('A')\n", "attempt 1")
    await _write_and_commit(path2, "pkg/t1.py", "print('B')\n", "attempt 2")

    planned = PlannedTask(
        task_id="TASK-0001", task_file="sdd/tasks/active/TASK-0001-demo.md", seat_label="a", native=False
    )
    first = await engine._consolidate(ctx, manager1, planned, branch=f"{feature_branch}--TASK-0001-a1", path=str(path1))
    assert first.outcome == "merged"

    second = await engine.merge("FEAT-549", str(worktree), "TASK-0001")
    assert second.outcome == "merge_conflict"

    _rc, status, _err = await _git("status", "--porcelain", cwd=worktree)
    assert status.strip() == ""
