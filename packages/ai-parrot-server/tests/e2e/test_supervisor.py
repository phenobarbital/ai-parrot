"""Real crash-isolation and concurrent-worktree acceptance scenarios (TASK-3537, M5).

These are the spec §3 "Integration Tests" scenarios this task owns; every
node ID below is frozen (referenced by the generated feature plan) and must
not be renamed without updating that plan. Opt-in via ``PARROT_TEST_E2E=1``
(``tests/e2e/conftest.py``'s own ``pytest_runtest_setup`` hook), exactly like
every other scenario in this directory.

Complements ``packages/ai-parrot-server/tests/unit/e2e/test_crash_probe_contract.py``
(the always-run, fast contract tests exercising the same documented spec §2
crash-cleanup/worktree-isolation behavior against synthetic worktrees). This
file instead runs against this suite's real checkout (``e2e_worktree``) and,
for the two-worktree/module-origin scenarios, a second synthetic checkout
alongside it — proving isolation between two *real*, independently rooted
source trees, not just two bare directories.

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
import uuid
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
    file- or state-backed fact rather than guessing at timing.

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
    """A real, minimal ``TargetAdapter`` test double (never a ``MagicMock``)."""

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
    exact same source tree as the current test run, independent of the
    (real or synthetic) worktree it supervises state under.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(sys.path)
    return env


# ---------------------------------------------------------------------------
# test_controller_and_supervisor_death
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


async def _run_controller_death_scenario(
    e2e_worktree: Path, tmp_path: Path, *, target_id: str, never_ready: bool
) -> None:
    """Spawn a standalone controller, kill it at a deterministic barrier, verify watchdog cleanup.

    "Controller" and "supervisor" are, as documented in
    ``parrot.e2e.watchdog``'s own module docstring, the same OS process in
    this checkout (no separate foreground controller process exists yet) --
    killing this standalone process exercises both halves of spec §2's
    "SIGKILL of controller and supervisor are tested separately" at the two
    distinct barriers this Scope names: right after registration, and again
    after readiness.
    """
    run_id_file = tmp_path / f"{target_id}-run-id.txt"
    ready_marker = tmp_path / f"{target_id}-ready.marker"
    script = Template(_CONTROLLER_SCRIPT_TEMPLATE).substitute(
        worktree=repr(str(e2e_worktree)),
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
        # begins) -- an externally observable fact, not a guessed delay.
        registered_marker = e2e_state.run_dir(run_id, worktree=e2e_worktree) / e2e_watchdog.REGISTERED_FILENAME
        await _poll_until(
            registered_marker.is_file, timeout_s=15.0, description="watchdog acknowledges target registration"
        )

        if not never_ready:

            def _is_ready() -> bool:
                try:
                    return e2e_state.read_state(run_id, worktree=e2e_worktree).status == "ready"
                except Exception:
                    return False

            await _poll_until(_is_ready, timeout_s=15.0, description="target reaches ready")

        target_pid = e2e_state.read_state(run_id, worktree=e2e_worktree).process_identity.pid

        # Kill the controller/supervisor. Fully reap it (not just signal
        # it): a zombie still satisfies psutil's own identity checks, so
        # the watchdog (a genuinely different OS process) would not
        # otherwise observe it as gone until this, its real parent, reaps it.
        controller.kill()
        await asyncio.wait_for(controller.wait(), timeout=10.0)

        def _cleaned_up() -> bool:
            try:
                return e2e_state.read_state(run_id, worktree=e2e_worktree).cleanup_complete
            except Exception:
                return False

        await _poll_until(_cleaned_up, timeout_s=20.0, description="watchdog tears down the owned target")

        final = e2e_state.read_state(run_id, worktree=e2e_worktree)
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


@pytest.mark.e2e
async def test_controller_and_supervisor_death(e2e_worktree: Path, tmp_path: Path) -> None:
    """Kill controller/supervisor separately during startup and readiness; watchdog cleans verified owned processes."""
    await _run_controller_death_scenario(e2e_worktree, tmp_path, target_id="ctrl-death-startup", never_ready=True)
    await _run_controller_death_scenario(e2e_worktree, tmp_path, target_id="ctrl-death-ready", never_ready=False)


# ---------------------------------------------------------------------------
# test_timeout_and_grandchild_teardown
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


async def _run_stale_reused_pid_scenario(e2e_worktree: Path) -> None:
    """A real, currently-alive foreign process is never signaled; cleanup is retained as unresolved.

    Stands in for a reused/foreign PID (spec §2: "Revalidate boot ID/process
    creation time and ownership before every signal ... Persist unresolved
    cleanup as failure; never remove its state as if successful.").
    """
    foreign = await asyncio.create_subprocess_exec(
        sys.executable, "-u", "-c", "import time; time.sleep(60)", start_new_session=True
    )
    owner_id = f"stale-owner-{uuid.uuid4().hex}"
    supervisor = E2ESupervisor(worktree=e2e_worktree, owner_id=owner_id, feature_id=_FEATURE_ID)
    run_id = f"stale-reused-{uuid.uuid4().hex[:12]}"
    try:
        e2e_state.run_dir(run_id, worktree=e2e_worktree)
        foreign_identity = e2e_state.capture_process_identity(foreign.pid, owned=False)
        own_identity = e2e_state.capture_process_identity(os.getpid(), owned=False)
        started_at = datetime.now(timezone.utc)
        state = RunState(
            feature_id=_FEATURE_ID,
            run_id=run_id,
            worktree=str(e2e_worktree.resolve()),
            owner_id=owner_id,
            controller_identity=own_identity,
            supervisor_identity=own_identity,
            process_identity=foreign_identity,
            target_id="stale-target",
            status="ready",
            endpoint=None,
            control_socket=str(e2e_state.run_dir(run_id, worktree=e2e_worktree) / "control.sock"),
            started_at=started_at,
            deadline=started_at + timedelta(seconds=600),
            log_path=str(e2e_worktree / "artifacts" / "logs" / "e2e" / run_id / "stale-target.log"),
        )
        e2e_state.write_state(state, worktree=e2e_worktree)

        result = await supervisor.stop(run_id)

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
        with contextlib.suppress(Exception):
            e2e_state.delete_state(run_id, worktree=e2e_worktree)


@pytest.mark.e2e
async def test_timeout_and_grandchild_teardown(
    e2e_supervisor_factory, e2e_worktree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hung process tree forces bounded group cleanup and records forced stop.

    Also exercises this Scope's stale/reused-PID requirement: a real,
    currently-alive foreign process must never be signaled, and its
    unresolved cleanup must be retained as a recorded failure.
    """
    monkeypatch.setattr(supervisor_module, "_TERM_WAIT_S", 0.3)
    marker = tmp_path / "hung-tree.marker"
    grandchild_marker = tmp_path / "hung-tree-grandchild.marker"
    script = Template(_HUNG_TREE_SCRIPT_TEMPLATE).substitute(
        marker=repr(str(marker)), grandchild_marker=repr(str(grandchild_marker))
    )
    adapter = _RealAdapter(
        lambda **kw: LaunchSpec(argv=[sys.executable, "-u", "-c", script], cwd=e2e_worktree),
        lambda _state: marker.exists() and grandchild_marker.exists(),
    )
    supervisor: E2ESupervisor = e2e_supervisor_factory(lambda _kind: adapter)
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

    await _run_stale_reused_pid_scenario(e2e_worktree)


# ---------------------------------------------------------------------------
# test_two_worktrees_independent
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_two_worktrees_independent(tmp_path: Path) -> None:
    """Concurrent worktrees use distinct ports/state/data; down cannot kill a sibling run."""
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
        # Distinct worktree-local state, socket and log paths (spec §2:
        # concurrent state/data isolation), and distinct owned processes.
        assert state_a.worktree != state_b.worktree
        assert state_a.control_socket != state_b.control_socket
        assert Path(state_a.log_path).is_relative_to(worktree_a.resolve())
        assert Path(state_b.log_path).is_relative_to(worktree_b.resolve())
        assert state_a.process_identity.pid != state_b.process_identity.pid

        # One owner's down must never touch the sibling run.
        final_a = await supervisor_a.stop(state_a.run_id)
        assert final_a.status == "stopped"
        assert final_a.cleanup_complete is True

        assert psutil.pid_exists(state_b.process_identity.pid)
        still_b = e2e_state.read_state(state_b.run_id, worktree=worktree_b)
        assert still_b.status == "ready"
        assert still_b.cleanup_complete is False
    finally:
        with contextlib.suppress(Exception):
            await supervisor_b.stop(state_b.run_id)


# ---------------------------------------------------------------------------
# test_wrong_checkout_cannot_pass
# ---------------------------------------------------------------------------

_MODULE_ORIGIN_PROBE_TEMPLATE = """
import e2e_probe_marker, pathlib, time
pathlib.Path($marker).write_text(e2e_probe_marker.SENTINEL + chr(10) + e2e_probe_marker.__file__)
time.sleep(60)
"""


def _make_synthetic_worktree(root: Path, name: str, sentinel: str) -> Path:
    """Build a minimal synthetic worktree with one uniquely-sentineled ``packages/*/src`` module."""
    worktree = root / name
    module_dir = worktree / "packages" / f"probe-{name}" / "src"
    module_dir.mkdir(parents=True)
    (module_dir / "e2e_probe_marker.py").write_text(f"SENTINEL = {sentinel!r}\n", encoding="utf-8")
    return worktree


@pytest.mark.e2e
async def test_wrong_checkout_cannot_pass(tmp_path: Path) -> None:
    """Imported target module origins are checked against the feature worktree, never a sibling checkout.

    Two synthetic worktrees each declare a same-named ``e2e_probe_marker``
    module with different content. A target launched from one worktree must
    only ever import its own worktree's copy, even though both are
    simultaneously present on disk and importable by name alone.
    """
    worktree_a = _make_synthetic_worktree(tmp_path, "worktree-a", "WORKTREE_A")
    worktree_b = _make_synthetic_worktree(tmp_path, "worktree-b", "WORKTREE_B")

    async def _probe(worktree: Path, expected_sentinel: str) -> None:
        marker = tmp_path / f"{worktree.name}-origin.marker"
        script = Template(_MODULE_ORIGIN_PROBE_TEMPLATE).substitute(marker=repr(str(marker)))
        adapter = _RealAdapter(
            lambda **kw: LaunchSpec(argv=[sys.executable, "-u", "-c", script], cwd=worktree),
            lambda _state: marker.exists(),
        )
        supervisor = E2ESupervisor(
            worktree=worktree,
            owner_id=f"origin-{worktree.name}",
            feature_id=_FEATURE_ID,
            adapter_resolver=lambda kind: adapter,
        )
        config = TargetConfig(kind="mcp-toolkit", startup_timeout_s=15)
        state = await supervisor.start("origin-probe", config)
        try:
            sentinel_line, module_path = marker.read_text(encoding="utf-8").splitlines()
            assert sentinel_line == expected_sentinel
            assert Path(module_path).is_relative_to(worktree.resolve())
        finally:
            await supervisor.stop(state.run_id)

    await _probe(worktree_a, "WORKTREE_A")
    await _probe(worktree_b, "WORKTREE_B")
