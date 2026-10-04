"""Separate watchdog process: heartbeat/lease enforcement and crash recovery (FEAT-581, M3).

Implements the spec §2 "Process Lifecycle and Worktree Isolation" contract this
task (TASK-3528) owns:

    A separate watchdog monitors supervisor identity and a 5-second heartbeat;
    15 seconds without a heartbeat, controller death for a foreground `run`, or
    absolute deadline expiry starts teardown. Detached `up` intentionally
    survives launcher exit but always expires at a default 600-second lease
    (maximum 3600). The watchdog inherits the run manifest/control information
    before target spawn.

    Startup registration uses a watchdog acknowledgement handshake: target
    identity must be acknowledged before readiness can be reported. An
    interrupted startup is reconciled by scanning only the recorded
    supervisor's descendants/group; no global process-name matching.
    Simultaneous watchdog/host destruction cannot guarantee cleanup;
    next-invocation stale reconciliation is the recovery path and must be
    documented.

The fixed entry point (spec §3 "M3") is::

    python -m parrot.e2e.watchdog --state-dir PATH --run-id ID

``--state-dir`` is the *worktree root* -- the same value every other
``parrot.e2e`` module accepts as ``worktree=``, not the leaf
``sdd/state/e2e`` directory. Every helper this module reuses
(:mod:`parrot.e2e.state`) is keyed off the worktree root (it is also
:class:`~parrot.e2e.models.RunState.worktree`'s own recorded value); accepting
the leaf directory here would force this module to re-derive the worktree
root by hardcoding the ``sdd/state/e2e`` suffix a second time, for no benefit.

This module runs in its own OS process (spawned by
:class:`parrot.e2e.supervisor.E2ESupervisor`, never the reverse -- this module
never imports ``parrot.e2e.supervisor``, to keep the two sides of the
handshake decoupled and importable independently) and communicates with the
supervisor only through:

1. Three small marker files inside the run's private, mode-0700 run
   directory (:func:`parrot.e2e.state.run_dir`) -- never a bare PID file
   (spec §2: "Never expose raw stdio through a PID file", generalized here
   to "never a bare, unverified PID file for anything"):

   - :data:`ACK_FILENAME` -- written once, immediately on watchdog startup.
     Its mere existence is this watchdog's own startup acknowledgement
     ("inherits the run manifest/control information before target spawn").
   - :data:`REGISTERED_FILENAME` -- written with the currently-registered
     target's ``ProcessIdentity.pid`` as soon as (and every time) this
     watchdog observes a (new) persisted :class:`~parrot.e2e.models.RunState`.
     This is the "target identity must be acknowledged before readiness can
     be reported" handshake the supervisor blocks on
     (:meth:`WatchdogHandle.wait_for_registration_ack`) before it ever polls
     target readiness.
   - :data:`HEARTBEAT_FILENAME` -- an empty file this watchdog only ever
     reads the *mtime* of; the supervisor "touches" it every
     :data:`HEARTBEAT_INTERVAL_S` seconds (:func:`record_heartbeat`).

2. The run's own persisted :class:`~parrot.e2e.models.RunState`
   (:mod:`parrot.e2e.state`) -- the only source of truth this watchdog ever
   signals against. It never accepts an arbitrary PID from its own CLI
   arguments, and it never matches a process by name: every kill this
   module ever issues is preceded by an immediate, live re-verification via
   :func:`parrot.e2e.state.is_authorized_to_signal` /
   :func:`parrot.e2e.state.process_identity_matches` (the same discipline
   :meth:`parrot.e2e.supervisor.E2ESupervisor.stop` already applies,
   duplicated here on purpose -- this module runs in a different OS process
   and cannot share that method's in-process state).

Unavoidable limit, documented per spec §2's own requirement: if the
supervisor is killed simultaneously with (or strictly before registering)
this watchdog, there is nothing signed, verified or even persisted yet for
this process to safely act on -- it is not a "kill the process tree blindly"
situation, it is "there is nothing here yet". :func:`reconcile_stale_run` is
the documented next-invocation recovery path for exactly that case, once a
:class:`~parrot.e2e.models.RunState` does exist to reconcile against.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from parrot.e2e import state as e2e_state
from parrot.e2e.errors import E2EConfigError, E2ETargetError
from parrot.e2e.models import ProcessIdentity, RunState

__all__ = [
    "HEARTBEAT_INTERVAL_S",
    "HEARTBEAT_EXPIRY_S",
    "ACK_FILENAME",
    "REGISTERED_FILENAME",
    "HEARTBEAT_FILENAME",
    "WatchdogSpawnError",
    "WatchdogHandle",
    "spawn_watchdog",
    "record_heartbeat",
    "run_watchdog",
    "reconcile_stale_run",
    "main",
]

logger = logging.getLogger(__name__)

# Spec §2: "A separate watchdog monitors supervisor identity and a 5-second
# heartbeat; 15 seconds without a heartbeat ... starts teardown."
HEARTBEAT_INTERVAL_S = 5.0
HEARTBEAT_EXPIRY_S = 15.0

# Same TERM-then-KILL bounds as parrot.e2e.supervisor's own teardown (spec §2:
# "Use SIGTERM, await exit up to 10 seconds, then SIGKILL ..."). Duplicated
# rather than imported: this module never imports parrot.e2e.supervisor (see
# the module docstring) -- these two small floats are not worth a shared
# import that would otherwise couple the two processes' modules together.
_TERM_WAIT_S = 10.0
_KILL_WAIT_S = 5.0

# Marker file names inside the run's private, mode-0700 run directory
# (parrot.e2e.state.run_dir) -- siblings of its control socket, never inside
# the state file itself.
ACK_FILENAME = "watchdog.ack"
REGISTERED_FILENAME = "watchdog.registered"
HEARTBEAT_FILENAME = "watchdog.heartbeat"

_ACK_POLL_INTERVAL_S = 0.02
_DEFAULT_ACK_TIMEOUT_S = 10.0
_DEFAULT_BOOTSTRAP_TIMEOUT_S = 30.0
_DEFAULT_MONITOR_POLL_INTERVAL_S = 1.0
_IDENTITY_GONE_POLL_INTERVAL_S = 0.05


class WatchdogSpawnError(E2ETargetError):
    """The watchdog subprocess failed to start or acknowledge registration.

    Maps to exit code 1 (inherited from :class:`E2ETargetError`) -- the same
    class of failure as any other target that never became ready.
    """


class WatchdogHandle:
    """The supervisor's own handle onto one run's spawned, ack'd watchdog process.

    Every method here only ever touches this run's own private marker
    files/subprocess handle -- never another run's, and never a bare PID.

    Attributes:
        run_id: The run this watchdog instance monitors.
        worktree: The owning worktree root.
    """

    def __init__(self, process: "asyncio.subprocess.Process", *, run_id: str, worktree: Path) -> None:
        """Initialize the handle around an already-spawned, already-ack'd watchdog process.

        Args:
            process: The spawned watchdog subprocess.
            run_id: The run this watchdog instance monitors.
            worktree: The owning worktree root.
        """
        self._process = process
        self.run_id = run_id
        self.worktree = worktree

    @property
    def pid(self) -> int:
        """This watchdog subprocess's own OS process ID."""
        return self._process.pid

    async def send_heartbeat(self) -> None:
        """Record a fresh heartbeat for this handle's run (spec §2: every 5 seconds)."""
        await asyncio.to_thread(record_heartbeat, self.run_id, worktree=self.worktree)

    async def wait_for_registration_ack(self, expected_pid: int, *, timeout_s: float) -> None:
        """Block until the watchdog acknowledges ``expected_pid`` as the current target identity.

        Spec §2: "target identity must be acknowledged before readiness can
        be reported." Called once per
        :meth:`parrot.e2e.supervisor.E2ESupervisor.start` attempt,
        immediately after that attempt's target identity is registered
        (persisted), and always before that attempt's own readiness polling
        begins.

        Args:
            expected_pid: The just-registered target's ``ProcessIdentity.pid``.
            timeout_s: Maximum seconds to wait for the acknowledgement.

        Raises:
            WatchdogSpawnError: If the watchdog process has already exited,
                or the acknowledgement does not arrive within ``timeout_s``.
        """
        registered_path = e2e_state.run_dir(self.run_id, worktree=self.worktree) / REGISTERED_FILENAME
        deadline = time.monotonic() + timeout_s
        while True:
            if self._process.returncode is not None:
                raise WatchdogSpawnError(
                    f"watchdog for run {self.run_id!r} exited (code {self._process.returncode}) "
                    f"before acknowledging target pid {expected_pid}",
                    reason_code="watchdog_exited",
                )
            content = await asyncio.to_thread(_read_text_if_exists, registered_path)
            if content is not None and content.strip() == str(expected_pid):
                return
            if time.monotonic() >= deadline:
                raise WatchdogSpawnError(
                    f"watchdog for run {self.run_id!r} did not acknowledge target pid {expected_pid} "
                    f"within {timeout_s}s",
                    reason_code="watchdog_ack_timeout",
                )
            await asyncio.sleep(_ACK_POLL_INTERVAL_S)

    async def stop(self) -> None:
        """Best-effort, idempotent TERM-then-KILL of the watchdog subprocess itself.

        Called once this run no longer needs monitoring (a normal
        ``stop()``, or a ``start()`` failure that has already torn down
        everything else). Never raises.
        """
        if self._process.returncode is not None:
            return
        with contextlib.suppress(ProcessLookupError):
            self._process.terminate()
        try:
            await asyncio.wait_for(self._process.wait(), timeout=_TERM_WAIT_S)
            return
        except asyncio.TimeoutError:
            pass
        with contextlib.suppress(ProcessLookupError):
            self._process.kill()
        with contextlib.suppress(Exception):
            await self._process.wait()


def _read_text_if_exists(path: Path) -> Optional[str]:
    """Best-effort read of a small marker file.

    Args:
        path: The marker file to read.

    Returns:
        The file's text content, or ``None`` if it does not exist yet or
        cannot currently be read.
    """
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _build_watchdog_env(worktree: Path) -> dict[str, str]:
    """Build the watchdog subprocess's environment.

    Prepends this worktree's ``packages/*/src`` directories onto
    ``PYTHONPATH`` -- the same prepending
    :meth:`parrot.e2e.supervisor.E2ESupervisor._build_child_env` applies to
    every *target* it spawns, duplicated here (not imported, see the module
    docstring) so a worktree-local watchdog subprocess always imports its
    own worktree's ``parrot.e2e.watchdog``, never a stale editable-installed
    copy of a different checkout.

    Args:
        worktree: The owning worktree root.

    Returns:
        The environment mapping to spawn the watchdog subprocess with.
    """
    env = dict(os.environ)
    packages_dir = worktree / "packages"
    if packages_dir.is_dir():
        prefixes = sorted(str(path) for path in packages_dir.glob("*/src") if path.is_dir())
        if prefixes:
            existing = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = os.pathsep.join([*prefixes, existing] if existing else prefixes)
    return env


async def spawn_watchdog(
    run_id: str,
    *,
    worktree: Path,
    ack_timeout_s: float = _DEFAULT_ACK_TIMEOUT_S,
    heartbeat_expiry_s: Optional[float] = None,
    poll_interval_s: Optional[float] = None,
    bootstrap_timeout_s: Optional[float] = None,
) -> WatchdogHandle:
    """Spawn this run's separate watchdog process and wait for its startup acknowledgement.

    Spec §2: "The watchdog inherits the run manifest/control information
    before target spawn." Called by
    :meth:`parrot.e2e.supervisor.E2ESupervisor.start` before its own target
    adapter ever runs -- the watchdog exists and is already watching
    ``run_id`` before the target it will one day need to reconcile is even
    spawned.

    Args:
        run_id: The run's stable ID (the watchdog's own ``--run-id``).
        worktree: The owning worktree root (the watchdog's own ``--state-dir``).
        ack_timeout_s: Maximum seconds to wait for the watchdog's own
            startup acknowledgement (:data:`ACK_FILENAME`) -- distinct from
            the later, per-attempt target-identity acknowledgement
            (:meth:`WatchdogHandle.wait_for_registration_ack`).
        heartbeat_expiry_s: Optional override of :data:`HEARTBEAT_EXPIRY_S`,
            forwarded to the spawned process. Test-only knob; production
            callers leave this unset.
        poll_interval_s: Optional override of the watchdog's own monitor
            poll interval, forwarded to the spawned process. Test-only knob.
        bootstrap_timeout_s: Optional override of the watchdog's own
            registration-wait bound, forwarded to the spawned process.
            Test-only knob.

    Returns:
        A live :class:`WatchdogHandle` for this run.

    Raises:
        WatchdogSpawnError: If the watchdog process cannot be spawned, exits
            before acknowledging, or does not acknowledge within
            ``ack_timeout_s``.
    """
    run_directory = e2e_state.run_dir(run_id, worktree=worktree)
    ack_path = run_directory / ACK_FILENAME
    registered_path = run_directory / REGISTERED_FILENAME
    heartbeat_path = run_directory / HEARTBEAT_FILENAME
    for stale_path in (ack_path, registered_path, heartbeat_path):
        with contextlib.suppress(OSError):
            stale_path.unlink()

    argv = [sys.executable, "-m", "parrot.e2e.watchdog", "--state-dir", str(worktree), "--run-id", run_id]
    if heartbeat_expiry_s is not None:
        argv += ["--heartbeat-expiry-s", str(heartbeat_expiry_s)]
    if poll_interval_s is not None:
        argv += ["--poll-interval-s", str(poll_interval_s)]
    if bootstrap_timeout_s is not None:
        argv += ["--bootstrap-timeout-s", str(bootstrap_timeout_s)]

    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            env=_build_watchdog_env(worktree),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise WatchdogSpawnError(
            f"failed to spawn watchdog for run {run_id!r}: {exc}", reason_code="watchdog_spawn_failed"
        ) from exc

    deadline = time.monotonic() + ack_timeout_s
    while True:
        if ack_path.is_file():
            break
        if process.returncode is not None:
            raise WatchdogSpawnError(
                f"watchdog for run {run_id!r} exited (code {process.returncode}) before acknowledging startup",
                reason_code="watchdog_exited_before_ack",
            )
        if time.monotonic() >= deadline:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            with contextlib.suppress(Exception):
                await process.wait()
            raise WatchdogSpawnError(
                f"watchdog for run {run_id!r} did not acknowledge startup within {ack_timeout_s}s",
                reason_code="watchdog_ack_timeout",
            )
        await asyncio.sleep(_ACK_POLL_INTERVAL_S)

    handle = WatchdogHandle(process, run_id=run_id, worktree=worktree)
    await handle.send_heartbeat()
    return handle


def record_heartbeat(run_id: str, *, worktree: Path) -> None:
    """Persist a fresh heartbeat for ``run_id`` (spec §2: every 5 seconds).

    A lightweight liveness signal only -- never a persisted evidence field
    (this task's file scope never modifies
    :class:`parrot.e2e.models.RunState`): a zero-byte marker file inside the
    run's private, mode-0700 run directory, whose *mtime* alone carries the
    signal (``Path.touch()`` updates it even if the file already exists,
    exactly like the POSIX ``touch`` utility).

    Args:
        run_id: The run's stable ID.
        worktree: The owning worktree root.
    """
    heartbeat_path = e2e_state.run_dir(run_id, worktree=worktree) / HEARTBEAT_FILENAME
    heartbeat_path.touch(exist_ok=True)


def _heartbeat_age_s(run_id: str, *, worktree: Path) -> Optional[float]:
    """Seconds elapsed since the last recorded heartbeat.

    Args:
        run_id: The run's stable ID.
        worktree: The owning worktree root.

    Returns:
        The age in seconds, or ``None`` if no heartbeat has ever been recorded.
    """
    heartbeat_path = e2e_state.run_dir(run_id, worktree=worktree) / HEARTBEAT_FILENAME
    try:
        mtime = heartbeat_path.stat().st_mtime
    except OSError:
        return None
    return time.time() - mtime


async def _wait_for_identity_gone(identity: ProcessIdentity, *, timeout_s: float) -> bool:
    """Poll until ``identity``'s live process is confirmed gone, bounded by ``timeout_s``.

    Args:
        identity: The recorded identity to wait on.
        timeout_s: Maximum seconds to wait.

    Returns:
        ``True`` once confirmed gone within the timeout; ``False`` otherwise.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        if not e2e_state.process_identity_matches(identity.pid, identity):
            return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(_IDENTITY_GONE_POLL_INTERVAL_S)


async def _teardown_owned_target(run_id: str, *, worktree: Path, reason: str) -> RunState:
    """Verify authorization, then TERM/KILL the owned target group; persist the verified outcome.

    Never signals a foreign, adopted or already-mismatched process (spec
    §2: "Adopted browser processes are never signaled"): the same
    revalidate-immediately-before-every-signal discipline
    :meth:`parrot.e2e.supervisor.E2ESupervisor.stop` applies, duplicated
    here because this module runs in its own OS process and never imports
    the supervisor module (see the module docstring).

    Args:
        run_id: The run's stable ID.
        worktree: The owning worktree root.
        reason: Machine-readable trigger reason, logged only (never
            persisted -- this task's file scope never modifies
            :class:`~parrot.e2e.models.RunState`'s schema).

    Returns:
        The final, persisted :class:`~parrot.e2e.models.RunState`.
    """
    with e2e_state.locked_run(run_id, worktree=worktree):
        current = e2e_state.read_state(run_id, worktree=worktree)
        if current.cleanup_complete:
            return current

        logger.warning("watchdog tearing down run %r: %s", run_id, reason)
        current = current.model_copy(update={"status": "stopping"})
        e2e_state.write_state(current, worktree=worktree)

        identity = current.process_identity
        shutdown_forced = False
        if e2e_state.is_authorized_to_signal(current, worktree=worktree):
            with contextlib.suppress(ProcessLookupError):
                os.killpg(identity.pgid, signal.SIGTERM)
            exited = await _wait_for_identity_gone(identity, timeout_s=_TERM_WAIT_S)
            if not exited and e2e_state.is_authorized_to_signal(current, worktree=worktree):
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(identity.pgid, signal.SIGKILL)
                shutdown_forced = True
                exited = await _wait_for_identity_gone(identity, timeout_s=_KILL_WAIT_S)
            cleanup_complete = exited
        else:
            # Adopted/foreign/reused-PID/not-ours: never signal. Cleanup
            # only "counts" if the process is independently confirmed gone.
            cleanup_complete = not e2e_state.process_identity_matches(identity.pid, identity)

        final_status = "stopped" if cleanup_complete else "failed"
        final = current.model_copy(
            update={"status": final_status, "shutdown_forced": shutdown_forced, "cleanup_complete": cleanup_complete}
        )
        e2e_state.write_state(final, worktree=worktree)
    return final


async def reconcile_stale_run(run_id: str, *, worktree: Path) -> RunState:
    """Reconcile one run's possibly stale/orphaned state when no watchdog is monitoring it.

    Spec §2: "Simultaneous watchdog/host destruction cannot guarantee
    cleanup; next-invocation stale reconciliation is the recovery path and
    must be documented." This is that recovery path -- a later invocation
    (e.g. a future CLI ``down --stale``, out of this task's own file scope)
    can call this directly against a run's persisted
    :class:`~parrot.e2e.models.RunState` with no watchdog process required
    to be alive at all.

    Idempotent and never speculative: a run that is not stale
    (:func:`parrot.e2e.state.is_stale`), or is already ``cleanup_complete``,
    is returned unchanged -- this never signals a process it has not first
    independently confirmed is stale.

    Args:
        run_id: The run's stable ID.
        worktree: The owning worktree root.

    Returns:
        The current (if not stale) or newly reconciled
        :class:`~parrot.e2e.models.RunState`.
    """
    current = e2e_state.read_state(run_id, worktree=worktree)
    if current.cleanup_complete or not e2e_state.is_stale(current):
        return current
    return await _teardown_owned_target(run_id, worktree=worktree, reason="stale_reconciled_next_invocation")


async def _wait_for_registration(run_id: str, *, worktree: Path, timeout_s: float) -> Optional[RunState]:
    """Wait for this run's first persisted ``RunState``, acknowledging it once seen.

    Writes :data:`REGISTERED_FILENAME` with the target's current
    ``process_identity.pid`` as soon as the state becomes readable -- the
    per-attempt handshake :meth:`WatchdogHandle.wait_for_registration_ack`
    blocks on.

    Args:
        run_id: The run's stable ID.
        worktree: The owning worktree root.
        timeout_s: Maximum seconds to wait for the first ``RunState``.

    Returns:
        The first read :class:`~parrot.e2e.models.RunState`, or ``None`` if
        it never appeared within ``timeout_s`` (spec §2's documented
        "supervisor died before ever registering this run" limitation --
        nothing was ever persisted, so nothing can be safely reconciled here).
    """
    run_directory = e2e_state.run_dir(run_id, worktree=worktree)
    registered_path = run_directory / REGISTERED_FILENAME
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            state = e2e_state.read_state(run_id, worktree=worktree)
        except E2EConfigError:
            state = None
        if state is not None:
            registered_path.write_text(str(state.process_identity.pid), encoding="utf-8")
            return state
        if time.monotonic() >= deadline:
            return None
        await asyncio.sleep(_ACK_POLL_INTERVAL_S)


async def _monitor_until_trigger(
    run_id: str, *, worktree: Path, heartbeat_expiry_s: float, poll_interval_s: float
) -> Optional[str]:
    """Poll until a fatal trigger fires or the run reaches a terminal, cleaned-up state.

    Checked most-definitive-first each tick: the absolute ``deadline`` (a
    plain timestamp comparison, spec §2's 600s-default/3600s-max lease),
    then the recorded ``controller_identity``'s liveness (a real,
    independently-verifiable OS fact -- covers "controller death for a
    foreground run"; today the same process as the supervisor, since no
    separate foreground controller process exists yet in this checkout),
    then the supervisor's own heartbeat freshness (the softest signal --
    15 seconds of silence, not an instantaneous fact).

    Args:
        run_id: The run's stable ID.
        worktree: The owning worktree root.
        heartbeat_expiry_s: Seconds of heartbeat silence before assuming
            the supervisor is gone.
        poll_interval_s: Seconds between monitor-loop iterations.

    Returns:
        A reason code for the fatal trigger (``"deadline_expired"``,
        ``"controller_died"`` or ``"heartbeat_expired"``), or ``None`` if
        the run reached a terminal, ``cleanup_complete`` state on its own
        (nothing left for this watchdog to do).
    """
    registered_path = e2e_state.run_dir(run_id, worktree=worktree) / REGISTERED_FILENAME
    last_registered_pid: Optional[int] = None
    while True:
        try:
            state = e2e_state.read_state(run_id, worktree=worktree)
        except E2EConfigError:
            # Briefly unreadable mid atomic-replace; retry rather than fail.
            await asyncio.sleep(poll_interval_s)
            continue

        if state.cleanup_complete:
            return None

        if state.process_identity.pid != last_registered_pid:
            registered_path.write_text(str(state.process_identity.pid), encoding="utf-8")
            last_registered_pid = state.process_identity.pid

        if datetime.now(timezone.utc) >= state.deadline:
            return "deadline_expired"
        if not e2e_state.process_identity_matches(state.controller_identity.pid, state.controller_identity):
            return "controller_died"
        heartbeat_age = _heartbeat_age_s(run_id, worktree=worktree)
        if heartbeat_age is not None and heartbeat_age > heartbeat_expiry_s:
            return "heartbeat_expired"

        await asyncio.sleep(poll_interval_s)


async def run_watchdog(
    run_id: str,
    *,
    worktree: Path,
    heartbeat_expiry_s: float = HEARTBEAT_EXPIRY_S,
    poll_interval_s: float = _DEFAULT_MONITOR_POLL_INTERVAL_S,
    bootstrap_timeout_s: float = _DEFAULT_BOOTSTRAP_TIMEOUT_S,
) -> None:
    """Run this run's full watchdog lifecycle: ack, monitor, teardown-on-trigger, exit.

    See the module docstring for the end-to-end spec §2 contract this
    implements. Exits cleanly (without touching anything) once the run's
    own ``RunState`` reports ``cleanup_complete`` -- a normal
    :meth:`parrot.e2e.supervisor.E2ESupervisor.stop` already handled it.

    Args:
        run_id: The run's stable ID.
        worktree: The owning worktree root.
        heartbeat_expiry_s: Seconds of heartbeat silence before assuming
            the supervisor is gone (default: :data:`HEARTBEAT_EXPIRY_S`).
        poll_interval_s: Seconds between monitor-loop iterations.
        bootstrap_timeout_s: Seconds to wait for the first ``RunState``
            before giving up (see the module docstring's documented limit).
    """
    run_directory = e2e_state.run_dir(run_id, worktree=worktree)
    ack_path = run_directory / ACK_FILENAME
    ack_path.write_text(str(os.getpid()), encoding="utf-8")

    state = await _wait_for_registration(run_id, worktree=worktree, timeout_s=bootstrap_timeout_s)
    if state is None:
        logger.warning(
            "watchdog for run %r: no RunState registered within %ss; nothing persisted to reconcile, exiting",
            run_id,
            bootstrap_timeout_s,
        )
        return

    reason = await _monitor_until_trigger(
        run_id, worktree=worktree, heartbeat_expiry_s=heartbeat_expiry_s, poll_interval_s=poll_interval_s
    )
    if reason is None:
        return
    await _teardown_owned_target(run_id, worktree=worktree, reason=reason)


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build this module's CLI argument parser (spec §3 "M3" fixed interface)."""
    parser = argparse.ArgumentParser(
        prog="python -m parrot.e2e.watchdog",
        description="Supervisor-owned watchdog: heartbeat/lease enforcement and crash recovery (FEAT-581).",
    )
    parser.add_argument("--state-dir", required=True, help="The owning worktree root (RunState resolves under it).")
    parser.add_argument("--run-id", required=True, help="The run's stable ID to monitor.")
    # Internal test-only tuning knobs: never required, never part of the
    # spec's fixed two-flag interface, defaults match the spec's own values.
    parser.add_argument("--heartbeat-expiry-s", type=float, default=HEARTBEAT_EXPIRY_S, help=argparse.SUPPRESS)
    parser.add_argument(
        "--poll-interval-s", type=float, default=_DEFAULT_MONITOR_POLL_INTERVAL_S, help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--bootstrap-timeout-s", type=float, default=_DEFAULT_BOOTSTRAP_TIMEOUT_S, help=argparse.SUPPRESS
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point: ``python -m parrot.e2e.watchdog --state-dir PATH --run-id ID``.

    Args:
        argv: Argument list to parse; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code: ``0`` on a clean exit, ``1`` if ``--state-dir``
        does not resolve to a valid worktree.
    """
    logging.basicConfig(level=logging.INFO)
    args = _build_arg_parser().parse_args(argv)
    try:
        asyncio.run(
            run_watchdog(
                args.run_id,
                worktree=Path(args.state_dir),
                heartbeat_expiry_s=args.heartbeat_expiry_s,
                poll_interval_s=args.poll_interval_s,
                bootstrap_timeout_s=args.bootstrap_timeout_s,
            )
        )
    except E2EConfigError as exc:
        logger.error("watchdog for run %r failed: %s", args.run_id, exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
