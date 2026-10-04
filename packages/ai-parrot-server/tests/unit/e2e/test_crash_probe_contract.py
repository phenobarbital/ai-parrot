"""Fast, always-run contract tests for crash cleanup and worktree isolation (TASK-3537, M5).

Complements ``packages/ai-parrot-server/tests/e2e/test_supervisor.py`` (the
frozen-node-ID acceptance scenarios, opt-in via ``PARROT_TEST_E2E=1``): every
test here runs unconditionally (no opt-in required, matching the sibling
``test_supervisor.py``/``test_watchdog.py`` unit suites from TASK-3527/
TASK-3528) and demonstrates the same documented spec §2 contract with
deterministic barriers and bounded deadlines — never a brittle sleep, never a
broad process-name scan.

Every "acceptance"-flavored test below spawns real OS subprocesses for
whatever this test's own scenario requires a real process boundary for; only
adapter *decision logic* (``prepare``/``ready``) is faked, never the process
itself, per this task's own Test Specification.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from string import Template

import psutil
import pytest

from parrot.e2e import state as e2e_state
from parrot.e2e import supervisor as supervisor_module
from parrot.e2e import watchdog as e2e_watchdog
from parrot.e2e.models import RunState, TargetConfig
from parrot.e2e.supervisor import E2ESupervisor
from parrot.e2e.targets.base import LaunchSpec

_FEATURE_ID = "FEAT-581"
_POLL_INTERVAL_S = 0.05


async def _poll_until(predicate, *, timeout_s: float, description: str) -> None:
    """Poll a zero-argument synchronous predicate until true, bounded by ``timeout_s``.

    A deterministic barrier — never a brittle fixed sleep — used throughout
    this module wherever a test must wait for an externally observable,
    file- or state-backed fact (spec §2's own registration/readiness/cleanup
    handshakes) rather than guessing at timing.

    Args:
        predicate: Zero-argument callable returning ``True`` once satisfied.
        timeout_s: Maximum seconds to wait.
        description: Human-readable description used in the timeout message.

    Raises:
        AssertionError: If ``predicate`` never becomes true within ``timeout_s``.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        if predicate():
            return
        if time.monotonic() >= deadline:
            raise AssertionError(f"timed out after {timeout_s}s waiting for: {description}")
        await asyncio.sleep(_POLL_INTERVAL_S)


class _RealAdapter:
    """A real, minimal ``TargetAdapter`` test double (never a ``MagicMock``).

    ``prepare()``/``ready()`` are plain callables the test controls
    directly — every attribute this class exposes is a real method with
    real behavior, never a duck-typed mock that would satisfy every
    ``hasattr`` check a Protocol performs.
    """

    def __init__(self, prepare_fn, ready_fn) -> None:
        self._prepare_fn = prepare_fn
        self._ready_fn = ready_fn

    async def prepare(self, config: TargetConfig, *, run_id: str, worktree: Path) -> LaunchSpec:
        return self._prepare_fn(run_id=run_id, worktree=worktree)

    async def ready(self, state: RunState) -> bool:
        return self._ready_fn(state)


def _marker_launch_spec(worktree: Path, marker: Path) -> LaunchSpec:
    """Build a ``LaunchSpec`` for a target that touches ``marker`` then sleeps."""
    script = f"import pathlib, time; pathlib.Path({str(marker)!r}).write_text('ready'); time.sleep(60)"
    return LaunchSpec(argv=[sys.executable, "-u", "-c", script], cwd=worktree, stdio=False)


def _subprocess_env() -> dict[str, str]:
    """Build a standalone controller subprocess's environment.

    Inherits this test process's own resolved ``sys.path`` as ``PYTHONPATH``
    so the spawned controller can ``import parrot.e2e.supervisor`` from the
    exact same source tree as the current test run, independent of whatever
    (possibly bare) ``worktree`` directory it supervises state under.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(sys.path)
    return env


# ---------------------------------------------------------------------------
# Controller/supervisor death at deterministic registration and readiness
# barriers (spec §2: "SIGKILL of controller and supervisor are tested
# separately.").
# ---------------------------------------------------------------------------

_CONTROLLER_SCRIPT_TEMPLATE = """
import asyncio
import sys
from pathlib import Path

from parrot.e2e.models import TargetConfig
from parrot.e2e.supervisor import E2ESupervisor
from parrot.e2e.targets.base import LaunchSpec

worktree = Path($worktree)
target_id = $target_id
run_id_file = Path($run_id_file)
ready_marker = Path($ready_marker)
never_ready = $never_ready


class _Adapter:
    async def prepare(self, config, *, run_id, worktree):
        run_id_file.write_text(run_id)
        if never_ready:
            argv = [sys.executable, "-u", "-c", "import time; time.sleep(120)"]
        else:
            script = "import pathlib, time; pathlib.Path(" + repr(str(ready_marker)) + ").touch(); time.sleep(120)"
            argv = [sys.executable, "-u", "-c", script]
        return LaunchSpec(argv=argv, cwd=worktree, stdio=False)

    async def ready(self, state):
        return ready_marker.exists()


async def _main():
    supervisor = E2ESupervisor(
        worktree=worktree,
        owner_id="controller",
        feature_id=$feature_id,
        adapter_resolver=lambda kind: _Adapter(),
    )
    config = TargetConfig(kind="mcp-toolkit", startup_timeout_s=90)
    await supervisor.start(target_id, config)
    while True:
        await asyncio.sleep(3600)


asyncio.run(_main())
"""


@pytest.mark.asyncio
@pytest.mark.parametrize("never_ready", [True, False], ids=["registration-barrier", "after-readiness"])
async def test_controller_death_barrier_triggers_watchdog_cleanup(tmp_path: Path, never_ready: bool) -> None:
    """Kill controller/supervisor separately at registration and after readiness; watchdog cleans up.

    "Controller" and "supervisor" are, as documented in
    ``parrot.e2e.watchdog``'s own module docstring, the same OS process in
    this checkout (no separate foreground controller process exists yet) —
    killing this standalone process therefore exercises both halves of the
    spec's "SIGKILL of controller and supervisor are tested separately"
    requirement at once, at two distinct, deterministically observed
    barriers.
    """
    worktree = tmp_path
    target_id = "ctrl-death-target"
    run_id_file = tmp_path / "run-id.txt"
    ready_marker = tmp_path / "ready.marker"

    script = Template(_CONTROLLER_SCRIPT_TEMPLATE).substitute(
        worktree=repr(str(worktree)),
        target_id=repr(target_id),
        run_id_file=repr(str(run_id_file)),
        ready_marker=repr(str(ready_marker)),
        never_ready=repr(never_ready),
        feature_id=repr(_FEATURE_ID),
    )
    controller = await asyncio.create_subprocess_exec(
        sys.executable, "-u", "-c", script, env=_subprocess_env(), start_new_session=True
    )
    try:
        await _poll_until(run_id_file.is_file, timeout_s=15.0, description="controller records its run_id")
        run_id = run_id_file.read_text(encoding="utf-8").strip()

        # Deterministic registration barrier: the separately spawned
        # watchdog only ever writes this marker once it has observed the
        # target's first persisted RunState (before any readiness polling
        # begins) — an externally observable fact, not a guessed delay.
        registered_marker = e2e_state.run_dir(run_id, worktree=worktree) / e2e_watchdog.REGISTERED_FILENAME
        await _poll_until(
            registered_marker.is_file, timeout_s=15.0, description="watchdog acknowledges target registration"
        )

        if not never_ready:

            def _is_ready() -> bool:
                try:
                    return e2e_state.read_state(run_id, worktree=worktree).status == "ready"
                except Exception:
                    return False

            await _poll_until(_is_ready, timeout_s=15.0, description="target reaches ready")

        target_pid = e2e_state.read_state(run_id, worktree=worktree).process_identity.pid

        # Kill the controller/supervisor. Fully reap it (not just signal
        # it): a zombie still satisfies psutil's own identity checks, so the
        # watchdog (a genuinely different OS process) would not otherwise
        # observe it as gone until this, its real parent, reaps it.
        controller.kill()
        await asyncio.wait_for(controller.wait(), timeout=10.0)

        def _cleaned_up() -> bool:
            try:
                return e2e_state.read_state(run_id, worktree=worktree).cleanup_complete
            except Exception:
                return False

        await _poll_until(_cleaned_up, timeout_s=20.0, description="watchdog tears down the owned target")

        final = e2e_state.read_state(run_id, worktree=worktree)
        assert final.status == "stopped"
        assert final.cleanup_complete is True

        await _poll_until(
            lambda: not psutil.pid_exists(target_pid), timeout_s=10.0, description="target process is fully reaped"
        )
    finally:
        if controller.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                controller.kill()
            with contextlib.suppress(Exception):
                await controller.wait()


# ---------------------------------------------------------------------------
# Hung grandchild tree -> bounded group cleanup, forced stop
# ---------------------------------------------------------------------------

_HUNG_TREE_SCRIPT_TEMPLATE = """
import pathlib, signal, subprocess, sys, time

signal.signal(signal.SIGTERM, signal.SIG_IGN)
grandchild_marker = $grandchild_marker
grandchild_script = (
    "import os, signal, pathlib, time; "
    "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
    "pathlib.Path(" + repr(grandchild_marker) + ").write_text(str(os.getpid())); "
    "time.sleep(120)"
)
grandchild = subprocess.Popen([sys.executable, "-u", "-c", grandchild_script])
pathlib.Path($marker).touch()
time.sleep(120)
"""


@pytest.mark.asyncio
async def test_hung_grandchild_tree_forces_sigkill_and_marks_shutdown_forced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hung tree (target + a same-pgid grandchild, both ignoring SIGTERM) is force-killed as a group.

    The grandchild is spawned by the target itself (``subprocess.Popen``,
    no new session), so it inherits the target's own process group — the
    same ``killpg`` this task's supervisor already issues on ``stop()``
    must therefore reach it too, without this test ever tracking its PID
    through any channel but the group itself.
    """
    monkeypatch.setattr(supervisor_module, "_TERM_WAIT_S", 0.3)
    worktree = tmp_path
    marker = tmp_path / "hung-tree.marker"
    grandchild_marker = tmp_path / "hung-tree-grandchild.marker"
    script = Template(_HUNG_TREE_SCRIPT_TEMPLATE).substitute(
        marker=repr(str(marker)), grandchild_marker=repr(str(grandchild_marker))
    )
    adapter = _RealAdapter(
        lambda **kw: LaunchSpec(argv=[sys.executable, "-u", "-c", script], cwd=worktree),
        lambda _state: marker.exists() and grandchild_marker.exists(),
    )
    supervisor = E2ESupervisor(
        worktree=worktree, owner_id="owner-hung", feature_id=_FEATURE_ID, adapter_resolver=lambda kind: adapter
    )
    config = TargetConfig(kind="mcp-toolkit", startup_timeout_s=30)

    state = await supervisor.start("hung-tree", config)
    target_pid = state.process_identity.pid
    grandchild_pid = int(grandchild_marker.read_text(encoding="utf-8").strip())

    final = await supervisor.stop(state.run_id)

    assert final.shutdown_forced is True
    assert final.cleanup_complete is True
    assert final.status == "stopped"

    await _poll_until(lambda: not psutil.pid_exists(target_pid), timeout_s=10.0, description="target process reaped")
    await _poll_until(
        lambda: not psutil.pid_exists(grandchild_pid), timeout_s=10.0, description="grandchild process reaped"
    )


# ---------------------------------------------------------------------------
# Stale/reused (foreign) PID -> never signaled, failure retained
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_foreign_identity_is_never_signaled_and_failure_is_retained(tmp_path: Path) -> None:
    """A foreign/reused-PID identity is never signaled; the unresolved failure is retained across repeat calls.

    A real, currently-alive process this supervisor never spawned stands in
    for a reused/foreign PID (spec §2: "Revalidate boot ID/process creation
    time and ownership before every signal ... Persist unresolved cleanup as
    failure; never remove its state as if successful."). Calling ``stop()``
    twice demonstrates that the recorded failure is *retained*, never
    silently self-healed into a false "stopped".
    """
    worktree = tmp_path
    foreign = await asyncio.create_subprocess_exec(
        sys.executable, "-u", "-c", "import time; time.sleep(60)", start_new_session=True
    )
    supervisor = E2ESupervisor(worktree=worktree, owner_id="stale-owner", feature_id=_FEATURE_ID)
    run_id = "stale-reused-target-0001"
    try:
        e2e_state.run_dir(run_id, worktree=worktree)
        foreign_identity = e2e_state.capture_process_identity(foreign.pid, owned=False)
        own_identity = e2e_state.capture_process_identity(os.getpid(), owned=False)
        started_at = datetime.now(timezone.utc)
        state = RunState(
            feature_id=_FEATURE_ID,
            run_id=run_id,
            worktree=str(worktree.resolve()),
            owner_id="stale-owner",
            controller_identity=own_identity,
            supervisor_identity=own_identity,
            process_identity=foreign_identity,
            target_id="stale-target",
            status="ready",
            endpoint=None,
            control_socket=str(e2e_state.run_dir(run_id, worktree=worktree) / "control.sock"),
            started_at=started_at,
            deadline=started_at + timedelta(seconds=600),
            log_path=str(worktree / "stale-target.log"),
        )
        e2e_state.write_state(state, worktree=worktree)

        first = await supervisor.stop(run_id)
        second = await supervisor.stop(run_id)

        for result in (first, second):
            assert result.status == "failed"
            assert result.cleanup_complete is False
            assert result.shutdown_forced is False

        assert foreign.returncode is None
        assert psutil.pid_exists(foreign.pid)
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(foreign.pid, signal.SIGKILL)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(foreign.wait(), timeout=5.0)


# ---------------------------------------------------------------------------
# Concurrent worktree isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_concurrent_worktrees_stop_is_isolated_to_its_owner(tmp_path: Path) -> None:
    """Two concurrently supervised worktrees keep distinct state; stopping one never touches the other."""
    worktree_a = tmp_path / "worktree-a"
    worktree_b = tmp_path / "worktree-b"
    worktree_a.mkdir()
    worktree_b.mkdir()
    marker_a = tmp_path / "concurrent-a.marker"
    marker_b = tmp_path / "concurrent-b.marker"

    adapter_a = _RealAdapter(lambda **kw: _marker_launch_spec(worktree_a, marker_a), lambda _s: marker_a.exists())
    adapter_b = _RealAdapter(lambda **kw: _marker_launch_spec(worktree_b, marker_b), lambda _s: marker_b.exists())
    supervisor_a = E2ESupervisor(
        worktree=worktree_a, owner_id="owner-a", feature_id=_FEATURE_ID, adapter_resolver=lambda kind: adapter_a
    )
    supervisor_b = E2ESupervisor(
        worktree=worktree_b, owner_id="owner-b", feature_id=_FEATURE_ID, adapter_resolver=lambda kind: adapter_b
    )
    config = TargetConfig(kind="mcp-toolkit", startup_timeout_s=15)

    state_a = await supervisor_a.start("concurrent-target", config)
    state_b = await supervisor_b.start("concurrent-target", config)
    try:
        assert state_a.worktree != state_b.worktree
        assert state_a.control_socket != state_b.control_socket
        assert state_a.process_identity.pid != state_b.process_identity.pid

        final_a = await supervisor_a.stop(state_a.run_id)
        assert final_a.status == "stopped"
        assert final_a.cleanup_complete is True

        # The sibling run, owned by a different worktree/owner, is left
        # entirely untouched by the other owner's down.
        assert psutil.pid_exists(state_b.process_identity.pid)
        still_b = e2e_state.read_state(state_b.run_id, worktree=worktree_b)
        assert still_b.status == "ready"
        assert still_b.cleanup_complete is False
    finally:
        with contextlib.suppress(Exception):
            await supervisor_b.stop(state_b.run_id)
