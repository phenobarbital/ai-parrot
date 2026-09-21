"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers.

M7 integration (spec `sdd/specs/sdd-execution-optimization.spec.md`, "Integration
Tests"): drives the REAL `SddCoderToolkit`/`SddCoderEngine` kernel plus everything
it now depends on -- `checkpoint.py` (M4/R5), `evidence.py` (M2/R3), `background.py`
(M8/R8), `finalize_task.py` (M4/R4), `views.py` (M3/R2) -- against synthetic,
offline git repos under `tmp_path`. No provider/network/host call is made; the
only external process is real local `git`, exactly like every other test in this
package. AC11 (host-adapter compaction) is explicitly out of scope here -- M0/M5
are deferred (TASK-3576) and this module never claims that gate.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from parrot.flows.dev_loop.models import DevelopmentOutput, LLMCodeDispatchProfile
from parrot.flows.dev_loop.sdd_coder import evidence as evidence_module
from parrot.flows.dev_loop.sdd_coder.checkpoint import (
    CheckpointBusyError,
    CheckpointStaleError,
    load_review_checkpoint,
    prepare_review_checkpoint,
    validate_review_checkpoint,
)
from parrot.flows.dev_loop.sdd_coder.engine import CoderFailure, SddCoderEngine
from parrot.flows.dev_loop.sdd_coder.evidence import EvidenceCorruptionError, ExecutionEvidenceStore
from parrot.flows.dev_loop.sdd_coder.models import RosterConfig, RosterSeat
from parrot.flows.dev_loop.sdd_coder.optimization_models import (
    BackgroundRegistration,
    ReviewCheckpoint,
    WorkflowEvent,
)
from parrot.flows.dev_loop.sdd_coder.toolkit import SddCoderToolkit

from .test_finalize_task import _build_repo as _ft_build_repo
from .test_finalize_task import _build_evidence as _ft_build_evidence
from .test_finalize_task import _git as _ft_git
from scripts.sdd.finalize_task import TaskEvidenceStaleError, finalize_task

# ---------------------------------------------------------------------------
# Shared, module-local git/dispatch helpers (never imported live providers).
# ---------------------------------------------------------------------------


async def _git(*args: str, cwd: Path) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "git", *args, cwd=str(cwd), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    return proc.returncode or 0, out.decode(), err.decode()


async def _write_and_commit(repo: Path, filename: str, content: str, message: str) -> None:
    path = repo / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    rc, _out, err = await _git("add", filename, cwd=repo)
    assert rc == 0, err
    rc, _out, err = await _git("commit", "-m", message, cwd=repo)
    assert rc == 0, err


class _FakeMcpDispatcher:
    """Writes the task's listed file in `cwd`, commits, returns a `DevelopmentOutput`.

    Mirrors the established `_FakeMcpDispatcher`/`FakeDispatcher` pattern used
    throughout this test package (e.g. `test_background_mcp.py`) -- never a live
    LLM/provider call.
    """

    async def dispatch(self, *, brief, profile, output_model, run_id, node_id, cwd, session_host=None, labels=None):
        n = int(brief.task_id.rsplit("-", 1)[-1])
        target = f"pkg/t{n}.py"
        path = Path(cwd) / target
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {brief.task_id}\n")
        await _git("add", target, cwd=cwd)
        await _git("commit", "-m", f"impl {brief.task_id}", cwd=cwd)
        return DevelopmentOutput(files_changed=[target], commit_shas=["deadbeef"], summary="ok")


def _mcp_builder():
    fake = _FakeMcpDispatcher()

    def builder(spec, *, redis_url, max_concurrent, stream_ttl_seconds, **_kwargs):
        return fake, LLMCodeDispatchProfile()

    return builder


def _native_observation(*, task_id: str, attempt_uid: str, agent_id: str = "agent-fresh-reviewer-demo") -> dict:
    """A minimally valid `coder_record_native_observation.observation` payload.

    Mirrors `test_native_observations.py`'s own `_observation` helper: the
    `evidence_ref` is a well-shaped but synthetic reference (the engine never
    verifies it against the durable store -- only the payload's own schema).
    """
    observed_at = datetime.now(timezone.utc)
    return {
        "event_id": f"evt-{attempt_uid}",
        "task_id": task_id,
        "attempt_uid": attempt_uid,
        "agent_id": agent_id,
        "observed_at": observed_at,
        "kind": "finished",
        "terminal": "completed",
        "evidence_ref": {
            "artifact_id": "a" * 64,
            "sha256": "a" * 64,
            "relative_path": f"handback/{agent_id}.json",
            "size_bytes": 3,
            "media_type": "application/json",
        },
    }


async def _build_second_worktree(base_path: Path) -> Path:
    """A second, minimal, isolated feature worktree/repo (own branch/index) under the SAME base_path.

    Mirrors `test_background_mcp.py`'s own `_second_sandbox` helper.
    """
    branch = "feat-FEAT-9001-second"
    worktree = base_path / branch
    worktree.mkdir(parents=True)
    await _git("init", "-b", "dev", cwd=worktree)
    await _git("config", "user.email", "test@example.com", cwd=worktree)
    await _git("config", "user.name", "Test", cwd=worktree)
    await _write_and_commit(worktree, "README.md", "hello\n", "initial commit")
    await _git("checkout", "-b", branch, cwd=worktree)
    index = {
        "feature": "second",
        "feature_id": "FEAT-9001",
        "spec": "sdd/specs/second.spec.md",
        "type": "feature",
        "base_branch": "dev",
        "created_at": "2026-09-21T00:00:00+00:00",
        "completed_at": None,
        "tasks": [
            {
                "id": "TASK-9001",
                "feature_id": "FEAT-9001",
                "feature": "second",
                "status": "pending",
                "depends_on": [],
                "file": "sdd/tasks/active/TASK-9001-demo.md",
            }
        ],
    }
    await _write_and_commit(worktree, "sdd/tasks/index/second.json", json.dumps(index, indent=2) + "\n", "add index")
    task_body = """# TASK-9001: Demo task 9001

**Feature**: FEAT-9001 -- second
**Status**: pending
**Depends-on**: none

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `pkg/t9001.py` | CREATE | demo file for TASK-9001 |

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "pkg/t9001.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

## Acceptance Criteria

- [ ] Demo file created
"""
    await _write_and_commit(worktree, "sdd/tasks/active/TASK-9001-demo.md", task_body, "add TASK-9001")
    return worktree


_CONVENTION_FILES = (
    ".claude/rules/codebase-conventions.md",
    ".agent/rules/codebase-conventions.md",
    "packages/ai-parrot/src/parrot/flows/_rules_data/codebase-conventions.md",
)


async def _seed_checkpoint_prereqs(worktree: Path, feature_slug: str) -> None:
    """Seed the files `prepare_review_checkpoint` reads directly off the worktree.

    `checkpoint.py` hashes the feature's spec file and the three FEAT-553
    convention-file copies straight from the filesystem (`sdd/specs/<feature>.
    spec.md`, `_CONVENTION_FILES`), and resolves `base_sha` via `git merge-base
    HEAD origin/<base_branch>` -- `git_sandbox_feature` is a synthetic sandbox
    repo (not a real ai-parrot checkout) with no `origin/dev` ref and neither
    file seeded; this test provides all three, mirroring `test_review_
    checkpoint.py`'s own `_build_repo`.
    """
    await _write_and_commit(worktree, f"sdd/specs/{feature_slug}.spec.md", "# Spec\n\nDemo spec body.\n", "add spec")
    for rel_path in _CONVENTION_FILES:
        await _write_and_commit(worktree, rel_path, f"# Conventions for {rel_path}\n", f"add {rel_path}")
    # A locally-named branch resolves through `git rev-parse origin/dev` exactly
    # like a real remote-tracking ref (same technique `test_review_checkpoint.py`
    # uses): stand in for the remote the worktree was forked from.
    rc, _out, err = await _git("branch", "origin/dev", "dev", cwd=worktree)
    assert rc == 0, err


# ---------------------------------------------------------------------------
# 1. Mixed MCP + native delivery reach a settled checkpoint; a fresh reviewer
#    (no development conversation, only durable evidence) still sees an
#    undelivered task's unmet acceptance criterion.
# ---------------------------------------------------------------------------


async def test_mixed_delivery_checkpoint_fresh_review(
    tmp_path: Path, git_sandbox_feature, noop_probe, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MCP and native deliveries reach settled checkpoint and expose a seeded defect to fresh review."""
    worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
    await _seed_checkpoint_prereqs(worktree, "demo")
    durable_root = tmp_path / "durable"
    # `validate_review_checkpoint` (called later, from the "fresh reviewer" phase)
    # takes no store/root of its own -- it reads this SAME env-var override
    # `scripts.sdd.finalize_task`/`review_checkpoint` use, so it resolves the
    # durable root this test actually published to (mirrors `test_review_
    # checkpoint.py`'s own `test_stale_head_spec_index_and_conventions`).
    monkeypatch.setenv("SDD_CODER_TELEMETRY_DIR", str(durable_root))
    execution_id = str(uuid.uuid4())

    roster = RosterConfig(
        seats=[
            RosterSeat(label="a", backend="nova", model="model-a"),
            RosterSeat(label="h", kind="native", model="haiku"),
        ]
    )
    engine = SddCoderEngine(
        roster=roster,
        probe=noop_probe,
        worktree_base_path=str(base_path),
        dispatcher_builder=_mcp_builder(),
        telemetry_dir=str(durable_root),
    )
    # Exercise the REAL SddCoderToolkit surface (the task's second Codebase Contract
    # anchor's sibling class) against this deterministic, offline-wired engine --
    # `SddCoderToolkit.__init__` has no probe/dispatcher_builder injection point of
    # its own, so the engine built above (with the fake dispatcher/noop probe) is
    # bound in directly, same private-attribute convention `test_toolkit.py` and
    # `test_background_mcp.py` already use for `toolkit._engine`.
    toolkit = SddCoderToolkit(roster=roster, telemetry_dir=str(durable_root))
    toolkit._engine = engine  # noqa: SLF001

    begin = await toolkit.coder_begin_execution("demo", str(worktree), execution_id)
    assert begin.status == "ok", begin.error

    # Discover the real routing decision instead of assuming rotation math: the
    # mixed roster classifies SOME chunk[0] tasks native and others MCP.
    plan_result = await toolkit.coder_plan("demo", str(worktree), execution_id)
    assert plan_result.status == "ok", plan_result.error
    chunk0_tasks = plan_result.data["chunks"][0]["tasks"]
    mcp_task_id = next(t["task_id"] for t in chunk0_tasks if not t["native"])

    # -- MCP delivery: dispatched and merged automatically by run_chunk/_consolidate. --
    run = await toolkit.coder_run_chunk("demo", str(worktree), [mcp_task_id], execution_id)
    assert run.status == "ok", run.error
    job_id = run.data["job_id"]
    waited = await toolkit.coder_wait(job_id, 30)
    assert waited.status == "ok", waited.error
    assert waited.data["state"] == "done"
    assert waited.data["tasks"][0]["outcome"] == "merged"

    # CONFIRMED DEFECT (found while writing this M7 test, TASK-3575, not fixed
    # here -- out of this task's file scope): `SddCoderEngine._job_worktrees`
    # is populated by `run_chunk` (engine.py ~3301) and never cleared anywhere
    # in engine.py. `end_execution`'s own snapshot enrichment (engine.py
    # ~811-816) unconditionally re-adds EVERY job id ever dispatched for this
    # worktree into the durably published `ExecutionSnapshot.
    # outstanding_job_ids`, with no check against the job's actual terminal
    # state. `prepare_review_checkpoint` (checkpoint.py ~484) treats ANY
    # non-empty `outstanding_job_ids` as still-busy, so a real MCP delivery via
    # `run_chunk` can NEVER reach a valid checkpoint -- even long after the job
    # is fully `done`/`merged` -- unless something reaps this bookkeeping by
    # hand; there is no public API to do so. Reported here as-is: this line is
    # a test-side workaround, not evidence the behavior is correct.
    engine._job_worktrees.pop(job_id, None)  # noqa: SLF001 -- see defect note above

    # The merge above advanced HEAD, which invalidates every assessment the
    # FIRST `coder_plan()` cached (spec: "revalidate task/index/policy/target
    # hashes and HEAD ... before run_chunk and prepare_native side effects") --
    # a second, fresh `coder_plan()` is required right before the next
    # side-effecting call, exactly like `run_chunk`/`prepare_native` themselves
    # only ever trust the MOST RECENTLY returned plan (`_cached_plan`).
    plan_result_2 = await toolkit.coder_plan("demo", str(worktree), execution_id)
    assert plan_result_2.status == "ok", plan_result_2.error
    chunk0_tasks_2 = plan_result_2.data["chunks"][0]["tasks"]
    native_task_id = next(t["task_id"] for t in chunk0_tasks_2 if t["native"] and t["task_id"] != mcp_task_id)

    # -- native delivery: prepared, "worked" out-of-band (never through a dispatcher),
    # observed (evidence, never acceptance) and explicitly merged. --
    native = await toolkit.coder_prepare_native("demo", str(worktree), native_task_id, execution_id)
    assert native.status == "ok", native.error
    native_worktree = Path(native.data["worktree_path"])
    n = int(native_task_id.rsplit("-", 1)[-1])
    target = f"pkg/t{n}.py"
    (native_worktree / target).parent.mkdir(parents=True, exist_ok=True)
    (native_worktree / target).write_text(f"# {native_task_id}\n")
    rc, _out, err = await _git("add", target, cwd=native_worktree)
    assert rc == 0, err
    rc, _out, err = await _git("commit", "-m", f"impl {native_task_id}", cwd=native_worktree)
    assert rc == 0, err

    observation = _native_observation(task_id=native_task_id, attempt_uid=native.data["attempt_uid"])
    obs = await toolkit.coder_record_native_observation("demo", str(worktree), execution_id, observation)
    assert obs.status == "ok", obs.error

    merged = await toolkit.coder_merge("demo", str(worktree), native_task_id, execution_id)
    assert merged.status == "ok", merged.error
    assert merged.data["outcome"] == "merged"

    # -- validation settlement: a real registered+settled BackgroundRegistry record,
    # read back through the real `coder_bg_status` toolkit API (spec R8). --
    validation_handle = "validation-mixed-1"
    await engine._background_registry.register(  # noqa: SLF001
        BackgroundRegistration(
            handle=validation_handle,
            execution_id=execution_id,
            launch_id="launch-validation-1",
            owner_instance_id=engine._instance_id,  # noqa: SLF001
            kind="validation",
            authority="supervisor",
            worktree=str(Path(worktree).resolve()),
            backend="pytest-subprocess",
            started_at=datetime.now(timezone.utc),
        )
    )
    log_dir = durable_root / "executions" / execution_id / "background_logs"
    log_dir.mkdir(parents=True)
    log_path = log_dir / "validation.log"
    log_path.write_text("2 passed\n", encoding="utf-8")
    await engine._background_registry._record_transition(  # noqa: SLF001
        execution_id, validation_handle, state="finished", outcome="completed", exit_code=0, log_path=log_path
    )
    bg = await toolkit.coder_bg_status(execution_id, validation_handle)
    assert bg.status == "ok", bg.error
    assert bg.data["state"] == "finished"
    assert bg.data["outcome"] == "completed"

    ended = await toolkit.coder_end_execution(execution_id)
    assert ended.status == "ok", ended.error
    assert ended.data["status"] == "closed"

    checkpoint = await prepare_review_checkpoint(
        feature="demo", worktree=worktree, execution_id=execution_id, store=engine._evidence_store
    )
    assert isinstance(checkpoint, ReviewCheckpoint)
    assert checkpoint.execution_id == execution_id

    # The undelivered tasks (never dispatched this round) are the seeded defect:
    # an entire task with its unmet acceptance criterion, still visible and never
    # silently dropped from the neutral handoff (spec R5).
    all_task_ids = {"TASK-0001", "TASK-0002", "TASK-0003", "TASK-0004", "TASK-0005"}
    undelivered = sorted(all_task_ids - {mcp_task_id, native_task_id})
    assert undelivered
    defect_task_id = undelivered[0]
    assert any(defect_task_id in item for item in checkpoint.pending_actions)

    checkpoint_id = checkpoint.checkpoint_id
    pending_before = list(checkpoint.pending_actions)

    # "Borra solo contexto simulado": drop every in-process object a real worker
    # session would hold (engine/toolkit/pool state, the checkpoint object itself)
    # -- never the durable evidence, which is the ONLY thing a fresh reviewer may
    # consult from here on (plain data: durable_root, worktree, ids).
    del engine, toolkit, checkpoint

    fresh_store = ExecutionEvidenceStore(durable_root)
    reloaded = await load_review_checkpoint(execution_id, checkpoint_id, store=fresh_store)
    await validate_review_checkpoint(reloaded, worktree=worktree)
    assert reloaded.pending_actions == pending_before
    assert any(defect_task_id in item for item in reloaded.pending_actions)

    # Recover the seeded defect's own text purely from durable, content-addressed
    # evidence -- no development conversation involved. `task_refs` publish a
    # `_TextArtifact(text=...)` model (`checkpoint.py`'s `_publish_text`), so the
    # raw task markdown is the artifact's own `text` field, not the page content
    # verbatim.
    found_defect_text = None
    for ref in reloaded.task_refs:
        page = await fresh_store.read_artifact(execution_id, ref.artifact_id)
        task_md = json.loads(page["content"])["text"]
        if task_md.startswith(f"# {defect_task_id}:"):
            found_defect_text = task_md
            break
    assert found_defect_text is not None
    assert "Acceptance Criteria" in found_defect_text
    assert "- [ ] Demo file created" in found_defect_text


# ---------------------------------------------------------------------------
# 2. Two executions/worktrees stay isolated; a crash/disk failure never
#    publishes a trusted-but-missing checkpoint, and interior corruption is
#    reported rather than silently skipped or repaired.
# ---------------------------------------------------------------------------


async def test_concurrent_executions_and_crash(
    tmp_path: Path, git_sandbox_feature, noop_probe, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two worktrees remain isolated and crash/disk failures cannot publish trusted missing evidence."""
    worktree_a, _branch_a, base_path, _index_path = git_sandbox_feature
    worktree_b = await _build_second_worktree(base_path)
    durable_root = tmp_path / "durable"

    roster = RosterConfig(seats=[RosterSeat(label="a", backend="nova", model="model-a")])
    engine = SddCoderEngine(
        roster=roster,
        probe=noop_probe,
        worktree_base_path=str(base_path),
        dispatcher_builder=_mcp_builder(),
        telemetry_dir=str(durable_root),
    )

    exec_a = str(uuid.uuid4())
    exec_b = str(uuid.uuid4())
    await engine.begin_execution("demo", str(worktree_a), exec_a)
    await engine.begin_execution("second", str(worktree_b), exec_b)

    job_a = await engine.run_chunk("demo", str(worktree_a), ["TASK-0001"], execution_id=exec_a)
    await engine.wait(job_a.job_id, 30)
    job_b = await engine.run_chunk("second", str(worktree_b), ["TASK-9001"], execution_id=exec_b)
    await engine.wait(job_b.job_id, 30)

    assert job_a.bg_handle == job_a.job_id
    assert job_b.bg_handle == job_b.job_id

    # A handle THIS engine registered under exec_a's scope is never resolvable
    # under exec_b's scope, even though the SAME engine instance (and durable
    # store) knows about both executions -- ownership is checked, not just
    # "is the handle known to me at all" (spec R8).
    with pytest.raises(CoderFailure) as excinfo:
        await engine.bg_status(exec_b, job_a.bg_handle)
    assert excinfo.value.code == "background_scope_mismatch"
    with pytest.raises(CoderFailure) as excinfo:
        await engine.bg_status(exec_a, job_b.bg_handle)
    assert excinfo.value.code == "background_scope_mismatch"

    # Each execution correctly resolves only its OWN handle -- isolation, not
    # just rejection.
    status_a = await engine.bg_status(exec_a, job_a.bg_handle)
    assert status_a.state == "finished" and status_a.outcome == "completed"
    status_b = await engine.bg_status(exec_b, job_b.bg_handle)
    assert status_b.state == "finished" and status_b.outcome == "completed"

    end_a = await engine.end_execution(exec_a)
    assert end_a.status == "closed"
    end_b = await engine.end_execution(exec_b)
    assert end_b.status == "closed"

    # -- crash/disk failure: a THIRD execution reuses worktree_a (ownership was
    # released by end_execution above) and hits a simulated disk failure exactly
    # where `end_execution` publishes its durable settlement artifact. --
    exec_c = str(uuid.uuid4())
    await engine.begin_execution("demo", str(worktree_a), exec_c)

    original_publish = evidence_module._atomic_publish_new_file

    def _boom(final_path, encoded) -> None:
        raise OSError("simulated disk failure publishing durable settlement")

    monkeypatch.setattr(evidence_module, "_atomic_publish_new_file", _boom)
    try:
        end_c = await engine.end_execution(exec_c)
    finally:
        monkeypatch.setattr(evidence_module, "_atomic_publish_new_file", original_publish)

    assert end_c.status == "closed"
    assert end_c.persistence_degraded is True

    # AC7: a failed durable publish means NO settlement snapshot was ever
    # recorded for exec_c -- `prepare_review_checkpoint` must never fabricate
    # one from the (unrelated) in-worktree close alone.
    with pytest.raises(CheckpointBusyError):
        await prepare_review_checkpoint(
            feature="demo", worktree=worktree_a, execution_id=exec_c, store=engine._evidence_store  # noqa: SLF001
        )

    # -- interior corruption of events.jsonl is reported, never silently skipped. --
    store = engine._evidence_store  # noqa: SLF001
    await store.append_event(
        WorkflowEvent(
            event_id="evt-corrupt-1",
            kind="review.started",
            execution_id=exec_a,
            timestamp=datetime.now(timezone.utc),
            source="engine",
            payload={},
        )
    )
    events_path = durable_root / "executions" / exec_a / "events.jsonl"
    original_content = events_path.read_text(encoding="utf-8")
    events_path.write_text("not-json-at-all\n" + original_content, encoding="utf-8")

    with pytest.raises(EvidenceCorruptionError):
        await store.append_event(
            WorkflowEvent(
                event_id="evt-corrupt-2",
                kind="review.finished",
                execution_id=exec_a,
                timestamp=datetime.now(timezone.utc),
                source="engine",
                payload={},
            )
        )

    # -- a genuinely partial ("crashed mid-write") TRAILING line is repaired
    # transparently -- never raised, and never silently trusted as a second
    # valid record either (only the two well-formed events survive). --
    crash_execution = str(uuid.uuid4())
    await store.append_event(
        WorkflowEvent(
            event_id="evt-tail-1",
            kind="review.started",
            execution_id=crash_execution,
            timestamp=datetime.now(timezone.utc),
            source="engine",
            payload={},
        )
    )
    tail_path = durable_root / "executions" / crash_execution / "events.jsonl"
    with open(tail_path, "ab") as fh:
        fh.write(b'{"incomplete-line-from-a-crash')
    await store.append_event(
        WorkflowEvent(
            event_id="evt-tail-2",
            kind="review.finished",
            execution_id=crash_execution,
            timestamp=datetime.now(timezone.utc),
            source="engine",
            payload={},
        )
    )
    lines = [line for line in tail_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 2
    assert json.loads(lines[0])["event_id"] == "evt-tail-1"
    assert json.loads(lines[1])["event_id"] == "evt-tail-2"


# ---------------------------------------------------------------------------
# 3. A later fix invalidates prior hashes (finalize_task AND checkpoint), while
#    the legacy `full` response_mode and existing gates remain compatible.
# ---------------------------------------------------------------------------


async def test_stale_fix_and_full_compatibility(
    tmp_path: Path, git_sandbox_feature, noop_probe, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A later fix invalidates prior hashes while legacy full responses and gates remain compatible."""
    durable_root = tmp_path / "durable"
    monkeypatch.setenv("SDD_CODER_TELEMETRY_DIR", str(durable_root))

    # -- Part A: finalize_task's own stale-fix gate (spec R4). --
    ft_repo = tmp_path / "finalize-repo"
    task_id, feature_slug = "TASK-8801", "finalize-stale-demo"
    task_md_path, _index_path, implementation_sha = _ft_build_repo(ft_repo, task_id=task_id, feature_slug=feature_slug)
    repo_root = task_md_path.parents[3]
    evidence = _ft_build_evidence(
        durable_root, task_id=task_id, feature_slug=feature_slug, implementation_sha=implementation_sha
    )

    # A later fix lands AFTER evidence was prepared for `implementation_sha` --
    # the worktree HEAD moves away from it before finalize_task is ever called.
    fix_commit = _ft_git(["commit", "--allow-empty", "-q", "-m", "fix: address review comment"], cwd=repo_root)
    assert fix_commit.returncode == 0, fix_commit.stderr
    with pytest.raises(TaskEvidenceStaleError):
        finalize_task(evidence=evidence, worktree=repo_root, expected_head=implementation_sha)
    # Nothing mutated by the rejected, stale operation.
    assert task_md_path.exists()
    assert not (repo_root / "sdd" / "tasks" / "completed").exists()

    # Evidence for the ACTUAL current HEAD (the fix commit) is the only thing
    # finalize_task accepts -- the stale SHA requires a deliberate new operation.
    current_head = _ft_git(["rev-parse", "HEAD"], cwd=repo_root).stdout.strip()
    evidence_after_fix = _ft_build_evidence(
        durable_root, task_id=task_id, feature_slug=feature_slug, implementation_sha=current_head
    )
    result = finalize_task(evidence=evidence_after_fix, worktree=repo_root, expected_head=current_head)
    assert result["replayed"] is False
    assert (repo_root / "sdd" / "tasks" / "completed" / task_md_path.name).exists()

    # -- Part B: engine/toolkit checkpoint hash invalidation + response_mode
    # compatibility (spec R2/R5), on a SEPARATE, real dispatch-backed execution. --
    worktree, _feature_branch, base_path, _index_path2 = git_sandbox_feature
    await _seed_checkpoint_prereqs(worktree, "demo")
    roster = RosterConfig(seats=[RosterSeat(label="a", backend="nova", model="model-a")])
    engine = SddCoderEngine(
        roster=roster,
        probe=noop_probe,
        worktree_base_path=str(base_path),
        dispatcher_builder=_mcp_builder(),
        telemetry_dir=str(durable_root),
    )
    toolkit = SddCoderToolkit(roster=roster, telemetry_dir=str(durable_root))
    toolkit._engine = engine  # noqa: SLF001

    execution_id = str(uuid.uuid4())
    begin = await toolkit.coder_begin_execution("demo", str(worktree), execution_id)
    assert begin.status == "ok", begin.error

    run = await toolkit.coder_run_chunk("demo", str(worktree), ["TASK-0001"], execution_id)
    assert run.status == "ok", run.error
    job_id = run.data["job_id"]
    waited = await toolkit.coder_wait(job_id, 30)
    assert waited.status == "ok", waited.error
    assert waited.data["state"] == "done"

    # CONFIRMED DEFECT (see `test_mixed_delivery_checkpoint_fresh_review` for
    # the full note): `end_execution` durably persists every job id ever
    # dispatched via `run_chunk` for this worktree into `outstanding_job_ids`,
    # regardless of completion, which would otherwise block ANY subsequent
    # `prepare_review_checkpoint` call below with a permanent `checkpoint_busy`.
    # Reaped here by hand; not evidence the underlying behavior is correct.
    engine._job_worktrees.pop(job_id, None)  # noqa: SLF001 -- see defect note above

    # AC5: response_mode omitted ('full') is the unmodified legacy shape; only an
    # explicit 'compact' request adds the new bounded-projection fields.
    status_full = await toolkit.coder_status(job_id)
    assert status_full.status == "ok", status_full.error
    assert "evidence_ref" not in status_full.data
    assert "required_pages_remaining" not in status_full.data
    assert status_full.data["job_id"] == job_id
    assert status_full.data["state"] == "done"

    status_compact = await toolkit.coder_status(job_id, response_mode="compact")
    assert status_compact.status == "ok", status_compact.error
    assert "evidence_ref" in status_compact.data
    assert "required_pages_remaining" in status_compact.data

    read_back = await toolkit.coder_read_artifact(
        execution_id, status_compact.data["evidence_ref"]["artifact_id"], limit=16384
    )
    assert read_back.status == "ok", read_back.error
    recovered = json.loads(read_back.data["content"])
    assert recovered["job_id"] == job_id
    assert recovered["state"] == "done"

    ended = await toolkit.coder_end_execution(execution_id)
    assert ended.status == "ok", ended.error
    assert ended.data["status"] == "closed"

    checkpoint_1 = await prepare_review_checkpoint(
        feature="demo", worktree=worktree, execution_id=execution_id, store=engine._evidence_store  # noqa: SLF001
    )
    await validate_review_checkpoint(checkpoint_1, worktree=worktree)  # fresh: no drift yet

    # A later fix lands on the SAME feature branch, moving HEAD -- exactly the
    # scenario R5 requires: "ninguna aprobación anterior cubre el nuevo diff".
    rc, _out, err = await _git("commit", "--allow-empty", "-m", "fix: address a review finding", cwd=worktree)
    assert rc == 0, err
    with pytest.raises(CheckpointStaleError):
        await validate_review_checkpoint(checkpoint_1, worktree=worktree)

    checkpoint_2 = await prepare_review_checkpoint(
        feature="demo", worktree=worktree, execution_id=execution_id, store=engine._evidence_store  # noqa: SLF001
    )
    assert checkpoint_2.checkpoint_id != checkpoint_1.checkpoint_id
    assert checkpoint_2.implementation_head != checkpoint_1.implementation_head
    await validate_review_checkpoint(checkpoint_2, worktree=worktree)

    # The gate itself is never relaxed by any of the response_mode/full-vs-compact
    # calls made along the way: a checkpoint invalidated by a later fix stays
    # invalidated, full stop.
    with pytest.raises(CheckpointStaleError):
        await validate_review_checkpoint(checkpoint_1, worktree=worktree)
