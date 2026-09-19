"""Unit and process-boundary tests for ``parrot.e2e.supervisor`` (TASK-3527, M3).

Every "acceptance"-flavored test below spawns a **real** ``python3 -c``
child process via a real :class:`~parrot.e2e.targets.base.TargetAdapter`
test double (never a mock of the process boundary itself) — per this task's
own Test Specification: "any process-boundary acceptance test must use real
subprocesses." Only the adapter's ``prepare``/``ready`` *decision logic* is
faked; the process it describes is always real, and cleanup/teardown
assertions check real OS-level facts (``psutil.pid_exists`` / a live
:class:`ControlClient` round trip), never a mirrored constant.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psutil
import pytest

from parrot.e2e import state as e2e_state
from parrot.e2e.control import ControlClient
from parrot.e2e.errors import E2EConfigError, E2EPrerequisiteError, E2ETargetError
from parrot.e2e.models import RunState, TargetConfig
from parrot.e2e.targets.base import LaunchSpec
from parrot.e2e import supervisor as supervisor_module
from parrot.e2e.supervisor import E2ESupervisor

_FEATURE_ID = "FEAT-581"
_OWNER_ID = "owner-1"

_MARKER_READY_TEMPLATE = """
import pathlib, time
pathlib.Path({marker!r}).write_text("ready")
time.sleep(60)
"""

_MARKER_IGNORE_SIGTERM_TEMPLATE = """
import pathlib, signal, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
pathlib.Path({marker!r}).write_text("ready")
time.sleep(60)
"""

_PORT_COLLISION_SCRIPT = "import sys; sys.stderr.write('Address already in use\\n'); sys.exit(1)"

_GENERIC_FAILURE_SCRIPT = "import sys; sys.exit(7)"

_STDIO_ECHO_SCRIPT = """
import sys, json
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    obj = json.loads(line)
    sys.stdout.write(json.dumps({"echo": obj}) + chr(10))
    sys.stdout.flush()
"""

_STDIO_IMPURE_SCRIPT = """
import sys
sys.stdout.write("not-json" + chr(10))
sys.stdout.flush()
import time
time.sleep(60)
"""


class _FakeAdapter:
    """A real, minimal :class:`TargetAdapter` test double.

    ``prepare()``/``ready()`` are plain callables the test controls
    directly — never a ``unittest.mock.MagicMock`` (which would satisfy
    every ``hasattr``/attribute check a duck-typed Protocol performs and
    could mask a real defect); every attribute this class exposes is a real
    method with real behavior.
    """

    def __init__(self, prepare_fn, ready_fn=None) -> None:
        self._prepare_fn = prepare_fn
        self._ready_fn = ready_fn or (lambda state: True)
        self.prepare_calls: list[TargetConfig] = []
        self.ready_calls: list[RunState] = []

    async def prepare(self, config: TargetConfig, *, run_id: str, worktree: Path) -> LaunchSpec:
        self.prepare_calls.append(config)
        return self._prepare_fn(run_id=run_id, worktree=worktree, call_index=len(self.prepare_calls))

    async def ready(self, state: RunState) -> bool:
        self.ready_calls.append(state)
        return self._ready_fn(state)


def _marker_launch_spec(worktree: Path, marker: Path, *, ignore_sigterm: bool = False) -> LaunchSpec:
    template = _MARKER_IGNORE_SIGTERM_TEMPLATE if ignore_sigterm else _MARKER_READY_TEMPLATE
    script = template.format(marker=str(marker))
    return LaunchSpec(argv=[sys.executable, "-u", "-c", script], cwd=worktree, stdio=False)


def _marker_ready(marker: Path):
    def _check(_state: RunState) -> bool:
        return marker.exists()

    return _check


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def make_supervisor(worktree: Path):
    created: list[E2ESupervisor] = []

    def _make(**kwargs) -> E2ESupervisor:
        supervisor = E2ESupervisor(worktree=worktree, owner_id=_OWNER_ID, feature_id=_FEATURE_ID, **kwargs)
        created.append(supervisor)
        return supervisor

    yield _make

    # Best-effort cleanup: reap any run left alive by a failing test so no
    # child process leaks past this test.
    for supervisor in created:
        for _run_id, live in list(supervisor._runs.items()):
            if live.process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(live.process.pid, signal.SIGKILL)


# ----------------------------------------------------------------------
# Construction
# ----------------------------------------------------------------------


def test_construction_rejects_unsafe_owner_id(worktree: Path) -> None:
    with pytest.raises(E2EConfigError, match="owner_id"):
        E2ESupervisor(worktree=worktree, owner_id="../escape", feature_id=_FEATURE_ID)


def test_construction_rejects_missing_worktree(tmp_path: Path) -> None:
    with pytest.raises(E2EConfigError, match="worktree"):
        E2ESupervisor(worktree=tmp_path / "does-not-exist", owner_id=_OWNER_ID, feature_id=_FEATURE_ID)


# ----------------------------------------------------------------------
# start() — success, real subprocess
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_reaches_ready_with_real_subprocess_and_persists_state(
    make_supervisor, worktree: Path, tmp_path: Path
) -> None:
    marker = tmp_path / "ready.marker"
    adapter = _FakeAdapter(
        lambda **kw: _marker_launch_spec(worktree, marker), ready_fn=_marker_ready(marker)
    )
    supervisor = make_supervisor(adapter_resolver=lambda kind: adapter)
    config = TargetConfig(kind="mcp-toolkit", startup_timeout_s=5)

    state = await supervisor.start("toolkit-a", config)

    assert state.status == "ready"
    assert state.target_id == "toolkit-a"
    assert state.process_identity.owned is True
    assert psutil.pid_exists(state.process_identity.pid)

    persisted = e2e_state.read_state(state.run_id, worktree=worktree)
    assert persisted.status == "ready"
    assert persisted.run_id == state.run_id

    log_path = Path(state.log_path)
    assert log_path.is_file()
    header = log_path.read_text(encoding="utf-8")
    assert "toolkit-a" in header
    assert sys.executable in header

    final = await supervisor.stop(state.run_id)
    assert final.status == "stopped"
    assert final.cleanup_complete is True
    assert final.shutdown_forced is False
    assert not psutil.pid_exists(final.process_identity.pid) or not e2e_state.process_identity_matches(
        final.process_identity.pid, final.process_identity
    )


@pytest.mark.asyncio
async def test_start_control_server_status_and_stop_over_real_socket(
    make_supervisor, worktree: Path, tmp_path: Path
) -> None:
    marker = tmp_path / "ready2.marker"
    adapter = _FakeAdapter(lambda **kw: _marker_launch_spec(worktree, marker), ready_fn=_marker_ready(marker))
    supervisor = make_supervisor(adapter_resolver=lambda kind: adapter)
    config = TargetConfig(kind="mcp-toolkit", startup_timeout_s=5)

    state = await supervisor.start("toolkit-b", config)

    client = ControlClient(Path(state.control_socket), run_id=state.run_id, owner_id=_OWNER_ID)
    status_result = await client.request("status", {})
    assert status_result["state"]["run_id"] == state.run_id
    assert status_result["state"]["status"] == "ready"

    stop_result = await client.request("stop", {})
    assert stop_result["state"]["status"] == "stopped"
    assert stop_result["state"]["cleanup_complete"] is True


# ----------------------------------------------------------------------
# start() — stdio target real round trip
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_stdio_round_trip_real_subprocess(make_supervisor, worktree: Path) -> None:
    adapter = _FakeAdapter(
        lambda **kw: LaunchSpec(argv=[sys.executable, "-u", "-c", _STDIO_ECHO_SCRIPT], cwd=worktree, stdio=True)
    )
    supervisor = make_supervisor(adapter_resolver=lambda kind: adapter)
    config = TargetConfig(kind="mcp-stdio", startup_timeout_s=5)

    state = await supervisor.start("stdio-a", config)
    assert state.status == "ready"

    response = await supervisor.request_stdio(state.run_id, {"id": 1, "method": "ping"})
    assert response == {"echo": {"id": 1, "method": "ping"}}

    # requests are serialized: two concurrent requests must not interleave.
    results = await asyncio.gather(
        supervisor.request_stdio(state.run_id, {"n": 1}),
        supervisor.request_stdio(state.run_id, {"n": 2}),
    )
    assert {"echo": {"n": 1}} in results
    assert {"echo": {"n": 2}} in results

    final = await supervisor.stop(state.run_id)
    assert final.status == "stopped"


@pytest.mark.asyncio
async def test_request_stdio_rejects_stdout_purity_violation(make_supervisor, worktree: Path) -> None:
    adapter = _FakeAdapter(
        lambda **kw: LaunchSpec(argv=[sys.executable, "-u", "-c", _STDIO_IMPURE_SCRIPT], cwd=worktree, stdio=True)
    )
    supervisor = make_supervisor(adapter_resolver=lambda kind: adapter)
    config = TargetConfig(kind="mcp-stdio", startup_timeout_s=5)

    state = await supervisor.start("stdio-impure", config)
    with pytest.raises(E2ETargetError, match="purity"):
        await supervisor.request_stdio(state.run_id, {"id": 1})

    await supervisor.stop(state.run_id)


@pytest.mark.asyncio
async def test_request_stdio_unknown_run_id(make_supervisor) -> None:
    supervisor = make_supervisor(adapter_resolver=lambda kind: _FakeAdapter(lambda **kw: None))
    with pytest.raises(E2EConfigError) as excinfo:
        await supervisor.request_stdio("no-such-run", {})
    assert excinfo.value.reason_code == "run_unknown"


@pytest.mark.asyncio
async def test_request_stdio_rejects_non_stdio_target(make_supervisor, worktree: Path, tmp_path: Path) -> None:
    marker = tmp_path / "ready3.marker"
    adapter = _FakeAdapter(lambda **kw: _marker_launch_spec(worktree, marker), ready_fn=_marker_ready(marker))
    supervisor = make_supervisor(adapter_resolver=lambda kind: adapter)
    config = TargetConfig(kind="mcp-toolkit", startup_timeout_s=5)

    state = await supervisor.start("toolkit-non-stdio", config)
    with pytest.raises(E2EConfigError) as excinfo:
        await supervisor.request_stdio(state.run_id, {})
    assert excinfo.value.reason_code == "not_stdio_target"

    await supervisor.stop(state.run_id)


# ----------------------------------------------------------------------
# start() — failure and port-collision retry
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_raises_on_readiness_timeout_and_persists_failed(make_supervisor, worktree: Path) -> None:
    adapter = _FakeAdapter(
        lambda **kw: LaunchSpec(argv=[sys.executable, "-u", "-c", "import time; time.sleep(60)"], cwd=worktree),
        ready_fn=lambda state: False,
    )
    supervisor = make_supervisor(adapter_resolver=lambda kind: adapter)
    config = TargetConfig(kind="mcp-toolkit", startup_timeout_s=0.3)

    with pytest.raises(E2ETargetError) as excinfo:
        await supervisor.start("timeout-target", config)
    assert excinfo.value.reason_code == "target_readiness_timeout"

    # The failed run's state must be persisted as failed/cleanup_complete,
    # never silently dropped, and the run_id must no longer be tracked live.
    run_ids = e2e_state.list_run_ids(worktree=worktree)
    matching = [rid for rid in run_ids if rid.startswith("timeout-target-")]
    assert len(matching) == 1
    persisted = e2e_state.read_state(matching[0], worktree=worktree)
    assert persisted.status == "failed"
    assert persisted.cleanup_complete is True
    assert matching[0] not in supervisor._runs


@pytest.mark.asyncio
async def test_start_raises_on_early_exit_without_port_collision(make_supervisor, worktree: Path) -> None:
    # ready_fn is deliberately always-False: this test isolates "the child
    # exited before ever becoming ready" from readiness itself. A real
    # adapter's ready() polls a real endpoint/marker it would never
    # spuriously satisfy just because an unrelated process happens to be
    # alive at that instant -- an always-True fake would race the trivial
    # `sys.exit(7)` child's own interpreter startup time under load.
    adapter = _FakeAdapter(
        lambda **kw: LaunchSpec(argv=[sys.executable, "-c", _GENERIC_FAILURE_SCRIPT], cwd=worktree),
        ready_fn=lambda state: False,
    )
    supervisor = make_supervisor(adapter_resolver=lambda kind: adapter)
    config = TargetConfig(kind="mcp-toolkit", startup_timeout_s=5)

    with pytest.raises(E2ETargetError) as excinfo:
        await supervisor.start("crash-target", config)
    assert excinfo.value.reason_code == "target_exited_early"

    # No retry for a non-collision exit: prepare() called exactly once.
    assert len(adapter.prepare_calls) == 1


@pytest.mark.asyncio
async def test_start_retries_once_on_verified_port_collision(make_supervisor, worktree: Path, tmp_path: Path) -> None:
    marker = tmp_path / "ready-after-retry.marker"

    def _prepare(*, run_id: str, worktree: Path, call_index: int) -> LaunchSpec:
        if call_index == 1:
            return LaunchSpec(argv=[sys.executable, "-c", _PORT_COLLISION_SCRIPT], cwd=worktree)
        return _marker_launch_spec(worktree, marker)

    adapter = _FakeAdapter(_prepare, ready_fn=_marker_ready(marker))
    supervisor = make_supervisor(adapter_resolver=lambda kind: adapter)
    config = TargetConfig(kind="mcp-toolkit", startup_timeout_s=5)

    state = await supervisor.start("collide-target", config)

    assert state.status == "ready"
    assert len(adapter.prepare_calls) == 2

    await supervisor.stop(state.run_id)


@pytest.mark.asyncio
async def test_start_unknown_target_kind_raises_before_any_side_effect(make_supervisor, worktree: Path) -> None:
    def _resolver(kind: str):
        raise E2EConfigError(f"unknown target kind {kind!r}", reason_code="unknown_target_kind")

    supervisor = make_supervisor(adapter_resolver=_resolver)
    config = TargetConfig(kind="mcp-toolkit", startup_timeout_s=5)

    with pytest.raises(E2EConfigError) as excinfo:
        await supervisor.start("bad-kind", config)
    assert excinfo.value.reason_code == "unknown_target_kind"

    assert e2e_state.list_run_ids(worktree=worktree) == []


@pytest.mark.asyncio
async def test_start_missing_adapter_prerequisite_propagates(make_supervisor, worktree: Path) -> None:
    def _resolver(kind: str):
        raise E2EPrerequisiteError("adapter unavailable", reason_code="target_adapter_unavailable")

    supervisor = make_supervisor(adapter_resolver=_resolver)
    config = TargetConfig(kind="browser", startup_timeout_s=5)

    with pytest.raises(E2EPrerequisiteError):
        await supervisor.start("no-adapter", config)


# ----------------------------------------------------------------------
# stop() — escalation, idempotence, foreign/adopted authorization
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_escalates_to_sigkill_when_target_ignores_sigterm(
    make_supervisor, worktree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(supervisor_module, "_TERM_WAIT_S", 0.3)
    marker = tmp_path / "ignore-term.marker"
    adapter = _FakeAdapter(
        lambda **kw: _marker_launch_spec(worktree, marker, ignore_sigterm=True), ready_fn=_marker_ready(marker)
    )
    supervisor = make_supervisor(adapter_resolver=lambda kind: adapter)
    config = TargetConfig(kind="mcp-toolkit", startup_timeout_s=5)

    state = await supervisor.start("stubborn-target", config)
    final = await supervisor.stop(state.run_id)

    assert final.shutdown_forced is True
    assert final.cleanup_complete is True
    assert final.status == "stopped"
    assert not psutil.pid_exists(final.process_identity.pid)


@pytest.mark.asyncio
async def test_stop_is_idempotent(make_supervisor, worktree: Path, tmp_path: Path) -> None:
    marker = tmp_path / "idempotent.marker"
    adapter = _FakeAdapter(lambda **kw: _marker_launch_spec(worktree, marker), ready_fn=_marker_ready(marker))
    supervisor = make_supervisor(adapter_resolver=lambda kind: adapter)
    config = TargetConfig(kind="mcp-toolkit", startup_timeout_s=5)

    state = await supervisor.start("idempotent-target", config)
    first = await supervisor.stop(state.run_id)
    second = await supervisor.stop(state.run_id)

    assert first.status == second.status == "stopped"
    assert second.cleanup_complete is True


@pytest.mark.asyncio
async def test_stop_unknown_run_id_raises(make_supervisor) -> None:
    supervisor = make_supervisor()
    with pytest.raises(E2EConfigError) as excinfo:
        await supervisor.stop("no-such-run")
    assert excinfo.value.reason_code == "state_missing"


@pytest.mark.asyncio
async def test_stop_never_signals_a_foreign_adopted_process(make_supervisor, worktree: Path) -> None:
    """A process this supervisor never spawned (``owned=False``) must never be signaled."""
    supervisor = make_supervisor()

    foreign_process = await asyncio.create_subprocess_exec(
        sys.executable, "-c", "import time; time.sleep(60)", start_new_session=True
    )
    try:
        run_id = "foreign-run-0001"
        e2e_state.run_dir(run_id, worktree=worktree)
        identity = e2e_state.capture_process_identity(foreign_process.pid, owned=False)
        own_identity = e2e_state.capture_process_identity(os.getpid(), owned=False)
        started_at = datetime.now(timezone.utc)
        state = RunState(
            feature_id=_FEATURE_ID,
            run_id=run_id,
            worktree=str(worktree),
            owner_id=_OWNER_ID,
            controller_identity=own_identity,
            supervisor_identity=own_identity,
            process_identity=identity,
            target_id="foreign-target",
            status="ready",
            endpoint=None,
            control_socket=str(worktree / "sdd" / "state" / "e2e" / run_id / "control.sock"),
            started_at=started_at,
            deadline=started_at + timedelta(seconds=600),
            log_path=str(worktree / "nowhere.log"),
        )
        e2e_state.write_state(state, worktree=worktree)

        result = await supervisor.stop(run_id)

        assert result.status == "failed"
        assert result.cleanup_complete is False
        assert result.shutdown_forced is False
        assert foreign_process.returncode is None
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(foreign_process.pid, signal.SIGKILL)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(foreign_process.wait(), timeout=5.0)


# ----------------------------------------------------------------------
# Environment isolation (pure unit test — no subprocess boundary claimed)
# ----------------------------------------------------------------------


def test_build_child_env_strips_credentials_and_prepends_pythonpath(
    make_supervisor, worktree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "super-secret")
    monkeypatch.setenv("UNRELATED_VAR", "keep-me")
    (worktree / "packages" / "one" / "src").mkdir(parents=True)
    (worktree / "packages" / "two" / "src").mkdir(parents=True)

    supervisor = make_supervisor()
    env = supervisor._build_child_env({"ADAPTER_SPECIFIC": "value"})

    assert "GOOGLE_API_KEY" not in env
    assert env["UNRELATED_VAR"] == "keep-me"
    assert env["ADAPTER_SPECIFIC"] == "value"
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    pythonpath_entries = env["PYTHONPATH"].split(os.pathsep)
    assert str(worktree / "packages" / "one" / "src") in pythonpath_entries
    assert str(worktree / "packages" / "two" / "src") in pythonpath_entries


def test_build_child_env_adapter_env_overrides_base(make_supervisor, worktree: Path) -> None:
    supervisor = make_supervisor()
    env = supervisor._build_child_env({"PYTHONDONTWRITEBYTECODE": "0"})
    assert env["PYTHONDONTWRITEBYTECODE"] == "0"
