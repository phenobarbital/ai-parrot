"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers.

Exercises the wiring TASK-3565 adds on top of `BackgroundRegistry`/
`ValidationSupervisor` (TASK-3563/TASK-3564): `coder_bg_status`/
`coder_run_validation` MCP discovery, `run_chunk`/`prepare_native` issuing
real registered handles, and `end_execution`/`cleanup` refusing to close
while an admitted validation has not settled.

`ValidationSupervisor.start()` is spec-mandatory in its use of
`worktree_environment.protected_argv` (bwrap sandboxing) -- never an
unsandboxed fallback. This module's dev/CI shell already runs nested inside
its own Bubblewrap sandbox, where a SECOND, nested `bwrap` cannot create the
namespaces it needs, independent of anything under test here (same
constraint `test_background_validation.py` documents). Every scenario that
admits a validation therefore monkeypatches `background_module.protected_argv`
to an identity pass-through so the *synthetic* child process (a real
`python -c ...` subprocess with a precisely controlled exit code/timing)
runs directly.
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from parrot.flows.dev_loop.sdd_coder import background as background_module
from parrot.flows.dev_loop.sdd_coder.background import BackgroundRegistry
from parrot.flows.dev_loop.sdd_coder.engine import CoderFailure, SddCoderEngine
from parrot.flows.dev_loop.sdd_coder.models import RosterConfig, RosterSeat
from parrot.flows.dev_loop.sdd_coder.optimization_models import BackgroundRegistration
from parrot.flows.dev_loop.sdd_coder.roster import RosterProbe
from parrot.flows.dev_loop.sdd_coder.toolkit import SddCoderToolkit
from parrot.flows.dev_loop.test_scope.datatypes import PytestInvocation, ScopePlan
from parrot.flows.dev_loop.models import DevelopmentOutput, LLMCodeDispatchProfile


async def _run_git(*args: str, cwd: Path) -> None:
    proc = await asyncio.create_subprocess_exec(
        "git", *args, cwd=str(cwd), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    assert proc.returncode == 0, f"git {' '.join(args)} failed in {cwd}: {err.decode()}\n{out.decode()}"


async def _write_and_commit(repo: Path, filename: str, content: str, message: str) -> None:
    path = repo / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    await _run_git("add", filename, cwd=repo)
    await _run_git("commit", "-m", message, cwd=repo)


async def _second_sandbox(base_path: Path) -> Path:
    """A second, minimal, isolated feature worktree/repo (own branch/index) under the SAME base_path."""
    branch = "feat-FEAT-9001-second"
    worktree = base_path / branch
    worktree.mkdir(parents=True)
    await _run_git("init", "-b", "dev", cwd=worktree)
    await _run_git("config", "user.email", "test@example.com", cwd=worktree)
    await _run_git("config", "user.name", "Test", cwd=worktree)
    await _write_and_commit(worktree, "README.md", "hello\n", "initial commit")
    await _run_git("checkout", "-b", branch, cwd=worktree)
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

**Feature**: FEAT-9001 — second
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


def _fast_plan_tests(argv: tuple[str, ...]):
    def _plan(*, worktree, changed_files, tier, declared=(), policy=None) -> ScopePlan:
        invocation = PytestInvocation(distribution="root", argv=argv, targets=())
        return ScopePlan(
            tier=tier, invocations=(invocation,), escalated=(), core_hits=(), skipped_escalations=(), notes=()
        )

    return _plan


def _identity_protected_argv(cwd: Path, argv: list[str]) -> list[str]:
    return list(argv)


class _FakeMcpDispatcher:
    """Writes the listed file in `cwd`, commits, returns DevelopmentOutput (mirrors test_integration_chunk.py)."""

    async def dispatch(self, *, brief, profile, output_model, run_id, node_id, cwd, session_host=None, labels=None):
        n = int(brief.task_id.rsplit("-", 1)[-1])
        target = f"pkg/t{n}.py"
        path = Path(cwd) / target
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {brief.task_id}\n")
        await _run_git("add", target, cwd=cwd)
        await _run_git("commit", "-m", f"impl {brief.task_id}", cwd=cwd)
        return DevelopmentOutput(files_changed=[target], commit_shas=["deadbeef"], summary="ok")


def _mcp_builder():
    fake = _FakeMcpDispatcher()

    def builder(spec, *, redis_url, max_concurrent, stream_ttl_seconds, **_kwargs):
        return fake, LLMCodeDispatchProfile()

    return builder


async def test_mcp_schema_and_issued_handles(tmp_path: Path, git_sandbox_feature, three_seat_roster, noop_probe) -> None:
    """Both tools are discoverable and handles come only from admitted launches (two executions/worktrees)."""
    toolkit = SddCoderToolkit(roster=three_seat_roster, telemetry_dir=str(tmp_path / "telemetry"))
    tool_names = {t.name for t in toolkit.get_tools()}
    assert {"coder_bg_status", "coder_run_validation"} <= tool_names

    worktree, _branch, base_path, _index_path = git_sandbox_feature
    engine = SddCoderEngine(
        roster=three_seat_roster,
        probe=noop_probe,
        worktree_base_path=str(base_path),
        telemetry_dir=str(tmp_path / "telemetry"),
    )
    execution_id = str(uuid.uuid4())
    await engine.begin_execution("demo", str(worktree), execution_id)

    # A never-registered handle is never invented as a status -- "el handle no
    # se inventa al consultar".
    with pytest.raises(CoderFailure) as excinfo:
        await engine.bg_status(execution_id, "never-registered")
    assert excinfo.value.code == "background_not_found"

    # coder_run_validation rejects a task_id not declared in THIS feature's index.
    with pytest.raises(CoderFailure) as excinfo:
        await engine.run_validation("demo", str(worktree), execution_id, ["TASK-9999"], "merge", 5, "req-scope")
    assert excinfo.value.code == "validation_scope_invalid"

    # A second, independent execution/worktree: registering a handle there
    # never leaks into (or is queryable from) the first execution's scope --
    # possessing the handle string is not enough (ownership is checked).
    worktree2 = await _second_sandbox(base_path)
    engine2 = SddCoderEngine(
        roster=three_seat_roster,
        probe=noop_probe,
        worktree_base_path=str(base_path),
        telemetry_dir=str(tmp_path / "telemetry"),
    )
    execution_id2 = str(uuid.uuid4())
    await engine2.begin_execution("FEAT-9001", str(worktree2), execution_id2)

    fake_registration = BackgroundRegistration(
        handle="cross-scope-handle",
        execution_id=execution_id2,
        launch_id="launch-cross",
        owner_instance_id=engine2._instance_id,  # noqa: SLF001
        kind="validation",
        authority="supervisor",
        worktree=str(worktree2),
        backend="pytest-subprocess",
        started_at=datetime.now(timezone.utc),
    )
    await engine2._background_registry.register(fake_registration)  # noqa: SLF001
    engine2._validation_handles.setdefault(execution_id2, set()).add("cross-scope-handle")  # noqa: SLF001

    # THIS engine (engine, not engine2) never registered that handle under
    # execution_id -- looked up there it is indistinguishable from unknown.
    with pytest.raises(CoderFailure) as excinfo:
        await engine.bg_status(execution_id, "cross-scope-handle")
    assert excinfo.value.code == "background_not_found"

    # engine2's own scope resolves it correctly.
    status2 = await engine2.bg_status(execution_id2, "cross-scope-handle")
    assert status2.state == "pending"


async def test_cleanup_and_end_execution_block_unknown(
    tmp_path: Path, git_sandbox_feature, three_seat_roster, noop_probe, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pending, running and unknown validations block closure and cleanup; settlement unblocks both."""
    worktree, _branch, base_path, _index_path = git_sandbox_feature
    engine = SddCoderEngine(
        roster=three_seat_roster,
        probe=noop_probe,
        worktree_base_path=str(base_path),
        telemetry_dir=str(tmp_path / "telemetry"),
    )
    execution_id = str(uuid.uuid4())
    await engine.begin_execution("demo", str(worktree), execution_id)

    # -- pending: registered, never transitioned --
    pending_handle = "handle-pending"
    await engine._background_registry.register(  # noqa: SLF001
        BackgroundRegistration(
            handle=pending_handle,
            execution_id=execution_id,
            launch_id="launch-pending",
            owner_instance_id=engine._instance_id,  # noqa: SLF001
            kind="validation",
            authority="supervisor",
            worktree=str(worktree),
            backend="pytest-subprocess",
            started_at=datetime.now(timezone.utc),
        )
    )
    engine._validation_handles.setdefault(execution_id, set()).add(pending_handle)  # noqa: SLF001

    with pytest.raises(CoderFailure) as excinfo:
        await engine.end_execution(execution_id)
    assert excinfo.value.code == "execution_busy"
    with pytest.raises(CoderFailure) as excinfo:
        await engine.cleanup("demo", str(worktree), execution_id=execution_id)
    assert excinfo.value.code == "execution_busy"

    # -- running --
    await engine._background_registry._record_transition(  # noqa: SLF001
        execution_id, pending_handle, state="running"
    )
    with pytest.raises(CoderFailure) as excinfo:
        await engine.end_execution(execution_id)
    assert excinfo.value.code == "execution_busy"

    # -- unknown: a handle registered by a DIFFERENT (e.g. crashed/restarted)
    # owner instance sharing the SAME durable store -- THIS engine's own
    # registry must report it unknown, and it still blocks close.
    orphan_handle = "handle-orphaned"
    await engine._background_registry.register(  # noqa: SLF001
        BackgroundRegistration(
            handle=orphan_handle,
            execution_id=execution_id,
            launch_id="launch-orphan",
            owner_instance_id="ghost-owner-instance",
            kind="validation",
            authority="supervisor",
            worktree=str(worktree),
            backend="pytest-subprocess",
            started_at=datetime.now(timezone.utc),
        )
    )
    engine._validation_handles[execution_id] = {orphan_handle}
    orphan_status = await engine.bg_status(execution_id, orphan_handle)
    assert orphan_status.state == "unknown"
    assert orphan_status.exit_code is None
    with pytest.raises(CoderFailure) as excinfo:
        await engine.end_execution(execution_id)
    assert excinfo.value.code == "execution_busy"

    # -- end después de reap: a REAL admitted validation settles only once
    # the supervisor's own terminal receipt (`await process.wait()`) lands;
    # close is refused while it is still genuinely running, and allowed once
    # it is reaped. --
    monkeypatch.setattr(
        background_module,
        "plan_tests",
        _fast_plan_tests((sys.executable, "-c", "import time,sys; time.sleep(0.3); sys.exit(0)")),
    )
    monkeypatch.setattr(background_module, "protected_argv", _identity_protected_argv)

    engine._validation_handles[execution_id] = set()  # isolate this scenario from the synthetic handles above
    registration = await engine.run_validation(
        "demo", str(worktree), execution_id, ["TASK-0001"], "merge", 5, "req-settle"
    )

    # The subprocess is still sleeping -- close is refused, no race between
    # a just-issued launch and a concurrent close.
    with pytest.raises(CoderFailure) as excinfo:
        await engine.end_execution(execution_id)
    assert excinfo.value.code == "execution_busy"

    # Await the SAME background settlement task the supervisor keeps (test-only seam).
    task = engine._validation_supervisor._background_tasks[(execution_id, registration.handle)]  # noqa: SLF001
    await asyncio.wait_for(task, timeout=15)

    settled = await engine.bg_status(execution_id, registration.handle)
    assert settled.state == "finished"
    assert settled.outcome == "completed"
    assert settled.exit_code == 0

    view = await engine.end_execution(execution_id)
    assert view.status == "closed"

    # cleanup also succeeds now that everything has settled (no managers in
    # this scope -> an empty, not a refused, report).
    report = await engine.cleanup("demo", str(worktree), execution_id=execution_id)
    assert report.removed == [] and report.kept == []


async def test_native_and_logical_authorities(
    tmp_path: Path, git_sandbox_feature, three_seat_roster, noop_probe, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Native handback remains observation; logical MCP jobs never invent an exit code."""
    worktree, _branch, base_path, _index_path = git_sandbox_feature

    # -- native: prepare_native registers a pending, host_observation handle;
    # record_native_observation links it WITHOUT settling the reservation. --
    native_roster = RosterConfig(seats=[RosterSeat(label="h", kind="native", model="haiku")])
    native_probe = RosterProbe(config_getter=lambda k, fallback=None: "x", which=lambda b: "/usr/bin/" + b, smoke=None)
    native_engine = SddCoderEngine(
        roster=native_roster,
        probe=native_probe,
        worktree_base_path=str(base_path),
        telemetry_dir=str(tmp_path / "telemetry-native"),
    )
    execution_id = str(uuid.uuid4())
    await native_engine.begin_execution("demo", str(worktree), execution_id)
    prep = await native_engine.prepare_native("demo", str(worktree), "TASK-0001", execution_id)
    assert prep.bg_handle == prep.attempt_uid

    pending = await native_engine.bg_status(execution_id, prep.bg_handle)
    assert pending.state == "pending"
    assert pending.authority == "host_observation"

    observation = {
        "event_id": "evt-native-1",
        "task_id": "TASK-0001",
        "attempt_uid": prep.attempt_uid,
        "agent_id": "agent-native",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "kind": "finished",
        "terminal": "completed",
        "evidence_ref": {
            "artifact_id": "a" * 64,
            "sha256": "a" * 64,
            "relative_path": "handback/agent-native.json",
            "size_bytes": 3,
            "media_type": "application/json",
        },
    }
    await native_engine.record_native_observation("demo", str(worktree), execution_id, observation)

    settled = await native_engine.bg_status(execution_id, prep.bg_handle)
    assert settled.state == "finished"
    assert settled.outcome == "completed"
    assert settled.exit_code is None  # host_observation authority never yields a POSIX exit code
    assert settled.authority == "host_observation"

    # Observation is evidence, never acceptance: the reservation is untouched.
    pool = native_engine._executions[execution_id]  # noqa: SLF001
    assert prep.attempt_uid in pool._admitted  # noqa: SLF001

    # -- logical MCP job: coder_run_chunk registers a bg_handle == job_id and
    # settles with a real outcome, never a fabricated POSIX exit_code -- on
    # its OWN second worktree, isolated from the native reservation above. --
    worktree2 = await _second_sandbox(base_path)
    mcp_engine = SddCoderEngine(
        roster=three_seat_roster,
        probe=noop_probe,
        worktree_base_path=str(base_path),
        dispatcher_builder=_mcp_builder(),
        telemetry_dir=str(tmp_path / "telemetry-mcp"),
    )
    mcp_execution_id = str(uuid.uuid4())
    await mcp_engine.begin_execution("FEAT-9001", str(worktree2), mcp_execution_id)
    job = await mcp_engine.run_chunk("FEAT-9001", str(worktree2), ["TASK-9001"], execution_id=mcp_execution_id)
    assert job.bg_handle == job.job_id
    await mcp_engine.wait(job.job_id, 30)

    finished = await mcp_engine.bg_status(mcp_execution_id, job.bg_handle)
    assert finished.state == "finished"
    assert finished.outcome == "completed"
    assert finished.exit_code is None  # a logical MCP job never carries a POSIX exit_code
    assert finished.source.endswith(":mcp_job")
    assert finished.authority == "engine"

    # background.py itself rejects an exit_code for kind='mcp_job' -- the
    # constraint is enforced at the data layer, not merely by omission above.
    with pytest.raises(ValueError):
        await mcp_engine._background_registry._record_transition(  # noqa: SLF001
            mcp_execution_id, job.bg_handle, state="finished", outcome="failed", exit_code=1
        )

    # -- external unsupported: a host_bridge source is never probed by PID;
    # coder_bg_status reports it unsupported instead. --
    await mcp_engine._background_registry.register(  # noqa: SLF001
        BackgroundRegistration(
            handle="bridge-1",
            execution_id=mcp_execution_id,
            launch_id="bridge-launch-1",
            owner_instance_id=mcp_engine._instance_id,  # noqa: SLF001
            kind="host_bridge",
            authority="host_observation",
            worktree=str(worktree2),
            backend="external-bash",
            started_at=datetime.now(timezone.utc),
        )
    )
    with pytest.raises(CoderFailure) as excinfo:
        await mcp_engine.bg_status(mcp_execution_id, "bridge-1")
    assert excinfo.value.code == "background_source_unsupported"

    # -- budgets por wire: the response stays within the spec's 8 KiB envelope. --
    assert len(finished.model_dump_json().encode("utf-8")) <= 8192
