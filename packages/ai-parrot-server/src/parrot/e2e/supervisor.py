"""Own target subprocesses and bounded readiness/teardown (FEAT-581, M3).

Implements the spec §2 "Process Lifecycle and Worktree Isolation" contract for
:class:`E2ESupervisor`, the fixed interface from spec §2 "New Public Interfaces":

    class E2ESupervisor:
        async def start(self, target_id, config) -> RunState: ...
        async def request_stdio(self, run_id, payload) -> dict: ...
        async def stop(self, run_id) -> RunState: ...

Every started target runs in its own process group (``start_new_session=True``,
matching the existing :class:`parrot.mcp.obscura.ObscuraProcessManager`
pattern). Its :class:`parrot.e2e.models.ProcessIdentity` is captured and its
:class:`parrot.e2e.models.RunState` is persisted (spec §2's "registration")
*before* any readiness polling begins — the TASK-3517 research spike measured
this ordering is required, not incidental, for a watchdog to later reconcile a
supervisor crash during startup (``sdd/state/FEAT-581/research/lifecycle.md``
§1.1, §5 item 1).

Scope boundaries this module deliberately keeps:

- **Target adapters** (concrete ``mcp-toolkit``/``mcp-stdio``/``mcp-agent``/
  ``botmanager``/``ui``/``browser`` implementations, M4) are consumed only
  through the already-frozen :class:`parrot.e2e.targets.base.TargetAdapter`
  protocol (``prepare``/``ready``), resolved lazily via
  :func:`parrot.e2e.targets.get_target_adapter` (overridable via
  ``adapter_resolver`` for tests). This module never hardcodes a target kind.
- **stdio protocol readiness.** ``TargetAdapter.ready(state)`` only takes a
  :class:`RunState` — it cannot poll a pipe it has no handle to. Per spec §2's
  target table ("Supervisor retains pipes"), *this* module is the only thing
  holding a stdio target's pipes, so it treats "process alive past one full
  poll interval" as supervisor-level readiness for a ``stdio`` launch and
  leaves *protocol*-level readiness (``initialize``/``tools/list``/...) to the
  caller's own subsequent :meth:`E2ESupervisor.request_stdio` exchange — the
  concrete MCP wire content is an M4/M5 concern this task's Codebase Contract
  does not fix.
- **``RunState.endpoint``.** Neither ``TargetAdapter.prepare()`` (returns a
  :class:`~parrot.e2e.targets.base.LaunchSpec` with no endpoint field) nor
  ``ready()`` (returns only ``bool``) gives this module an HTTP endpoint to
  record. Population of that field is left to future (M4-adjacent) work; it
  is always persisted as ``None`` here, which is one of its two documented
  valid meanings ("None before readiness / for non-networked targets").
- **The watchdog.** Registration/heartbeat *to* a separate watchdog process
  and absolute-lease extension are TASK-3528's job (spec §3 "M3" explicitly
  defers this). What this module does implement is the *handshake surface* a
  future watchdog reconciles against: an atomically-written, mode-0600
  :class:`RunState` per run, updated at every lifecycle transition
  (``starting`` → ``ready``/``failed`` → ``stopping`` → ``stopped``/
  ``failed``), plus a private per-run :class:`parrot.e2e.control.ControlServer`
  exposing ``status``/``stop``/``stdio`` operations so an out-of-process
  caller (the eventual watchdog, or a `down`/`status` CLI) can reach this
  same running supervisor without ever re-deriving pipe/process ownership
  from a bare PID.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import re
import signal
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import IO, Callable, Optional

import psutil
from pydantic import JsonValue

from parrot.e2e import state as e2e_state
from parrot.e2e.control import ControlHandler, ControlServer, DEFAULT_REQUEST_DEADLINE_S, MAX_MESSAGE_BYTES
from parrot.e2e.errors import E2EConfigError, E2ETargetError
from parrot.e2e.models import ProcessIdentity, RunState, TargetConfig
from parrot.e2e.targets import get_target_adapter
from parrot.e2e.targets.base import LaunchSpec, TargetAdapter

__all__ = ["E2ESupervisor", "AdapterResolver"]

logger = logging.getLogger(__name__)

# Resolves one TargetConfig.kind to its concrete TargetAdapter. Defaults to
# the real lazy registry; tests inject a fake resolver instead of monkeypatching
# parrot.e2e.targets (M4 concrete adapters do not exist yet in this checkout).
AdapterResolver = Callable[[str], TargetAdapter]

# Spec §2: "Use SIGTERM, await exit up to 10 seconds, then SIGKILL ...".
_TERM_WAIT_S = 10.0
# Bound for reaping after an escalating SIGKILL (uncatchable, but the kernel
# still needs a scheduler tick to reap a zombie into WIFSIGNALED).
_KILL_WAIT_S = 5.0
# Spec §2: "Detached `up` ... always expires at a default 600-second lease
# (maximum 3600)." Absolute-lease *extension* is TASK-3528's (watchdog's) job;
# this is only the initial default recorded at registration time.
_DEFAULT_LEASE_S = 600.0
_READY_POLL_INTERVAL_S = 0.05
# Linux's AF_UNIX sun_path buffer is 108 bytes including the NUL terminator;
# leave margin below that hard kernel limit (see _resolve_control_socket_path).
_MAX_SOCKET_PATH_BYTES = 100
# A best-effort case-insensitive signature for "the child's own bind failed
# because the chosen port is already in use" — spec §2: "Retry one verified
# EADDRINUSE within the original startup deadline."
_PORT_COLLISION_RE = re.compile(r"address already in use|eaddrinuse", re.IGNORECASE)

# Spec §2: "Model keys are omitted from deterministic targets." This module
# has no visibility into a scenario's tier (that lives on ScenarioSpec, not
# TargetConfig) so it strips every known credential-shaped variable from
# every spawned target's base environment unconditionally — strictly safer
# than the minimum the spec requires. A future live/budgeted adapter (M6, out
# of this task's scope) can still set one explicitly via its own
# LaunchSpec.env, which is merged on top of this stripped base.
_CREDENTIAL_ENV_VARS = frozenset(
    {
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GROQ_API_KEY",
        "HUGGINGFACE_API_KEY",
        "HUGGINGFACEHUB_API_TOKEN",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AZURE_OPENAI_API_KEY",
        "COHERE_API_KEY",
        "MISTRAL_API_KEY",
    }
)

# Same nonempty "safe slug" convention as parrot.e2e.models/parrot.e2e.state's
# own private validators — duplicated intentionally (module-local path/id
# safety checks are not shared across this package, per its own established
# convention; see parrot.e2e.state's module docstring).
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _validate_id(value: str, *, field_name: str) -> str:
    """Validate a nonempty safe slug used as an identifier or path component.

    Args:
        value: The candidate identifier.
        field_name: Name used in the raised error's message/reason code.

    Returns:
        The validated identifier, unchanged.

    Raises:
        E2EConfigError: If ``value`` is empty, contains a path separator, or
            does not match the safe-slug pattern.
    """
    if not value or not _SAFE_ID_RE.match(value) or "/" in value or "\\" in value:
        raise E2EConfigError(
            f"{field_name} must be a nonempty safe slug: {value!r}", reason_code=f"{field_name}_unsafe"
        )
    return value


class _StdioChannel:
    """Mediates one serialized request/response exchange over a stdio target's pipes.

    Spec §2: "For stdio, a private Unix control socket mediates request/
    response exchange; requests are serialized ...". This class is the
    in-process half of that mediation (the piece that actually forwards a
    JSON-RPC-shaped payload to the real child) — the socket half is the
    already-implemented :class:`parrot.e2e.control.ControlServer`, wired by
    :class:`E2ESupervisor` to call into this for its own ``stdio`` operation.
    """

    def __init__(self, process: "asyncio.subprocess.Process") -> None:
        """Initialize the channel over an already-spawned process's pipes.

        Args:
            process: The owned child process; ``stdin``/``stdout`` must be
                pipes (``asyncio.subprocess.PIPE``).
        """
        self._process = process
        self._lock = asyncio.Lock()

    async def request(self, payload: dict[str, JsonValue], *, deadline_s: float) -> dict[str, JsonValue]:
        """Send one JSON line to the child's stdin and read one correlated response line.

        Args:
            payload: The JSON-RPC-shaped request object to forward verbatim.
            deadline_s: Maximum seconds allowed for the write to drain and
                for one response line to arrive.

        Returns:
            The parsed JSON object read from the child's stdout.

        Raises:
            E2ETargetError: If the pipes are unavailable, the payload exceeds
                the control channel's size limit, the deadline elapses, the
                child closes stdout without responding (EOF), or the child's
                stdout line is not a JSON object (a "stdout JSON purity"
                violation, spec §2's ``mcp-stdio`` target requirement).
        """
        if self._process.stdin is None or self._process.stdout is None:
            raise E2ETargetError("stdio target has no open pipes to mediate", reason_code="stdio_unavailable")

        line = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        if len(line) > MAX_MESSAGE_BYTES:
            raise E2ETargetError(
                f"stdio payload exceeds the {MAX_MESSAGE_BYTES}-byte control channel limit",
                reason_code="message_too_large",
            )

        async with self._lock:
            try:
                self._process.stdin.write(line)
                await asyncio.wait_for(self._process.stdin.drain(), timeout=deadline_s)
                raw = await asyncio.wait_for(self._process.stdout.readline(), timeout=deadline_s)
            except asyncio.TimeoutError as exc:
                raise E2ETargetError("stdio request deadline exceeded", reason_code="deadline_exceeded") from exc
            except (ConnectionError, OSError) as exc:
                raise E2ETargetError(f"stdio channel error: {exc}", reason_code="stdio_error") from exc

        if not raw:
            raise E2ETargetError("stdio target closed stdout before responding (EOF)", reason_code="stdio_eof")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise E2ETargetError(
                f"stdio target violated stdout JSON purity: {raw!r}", reason_code="stdio_purity"
            ) from exc
        if not isinstance(parsed, dict):
            raise E2ETargetError(f"stdio target response is not a JSON object: {raw!r}", reason_code="stdio_purity")
        return parsed


@dataclass
class _LiveRun:
    """This process's own live handles for one supervised run.

    Attributes:
        run_id: The run's stable ID.
        target_id: The target key this run started.
        config: The :class:`TargetConfig` this run was started with.
        process: The currently owned child process (replaced in place across
            a single port-collision retry within :meth:`E2ESupervisor.start`).
        control_server: This run's private per-run control channel.
        log_handle: The open log file handle backing the child's captured
            stdout/stderr (or just stderr, for a ``stdio`` target).
        stdio_channel: Set only for a ``stdio``-launched target.
        state: The most recently persisted :class:`RunState` for this run.
    """

    run_id: str
    target_id: str
    config: TargetConfig
    process: "asyncio.subprocess.Process"
    control_server: ControlServer
    log_handle: IO[bytes]
    stdio_channel: Optional[_StdioChannel] = None
    state: Optional[RunState] = None


class E2ESupervisor:
    """Own targets, subprocess probes, leases and bounded teardown for one run (spec §2/§3 "M3").

    One instance may supervise several concurrently started targets (each its
    own :class:`RunState`/``run_id``) within one worktree/owner. Every method
    below only ever acts on a run this same instance started (or, for
    :meth:`stop`, a run whose persisted identity it can independently
    reauthorize) — never on a bare PID.
    """

    def __init__(
        self,
        *,
        worktree: Path,
        owner_id: str,
        feature_id: str,
        adapter_resolver: AdapterResolver = get_target_adapter,
        request_deadline_s: float = DEFAULT_REQUEST_DEADLINE_S,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        """Initialize the supervisor.

        Args:
            worktree: The owning worktree root; must already exist.
            owner_id: This supervisor's own stable identity, recorded on
                every :class:`RunState` it creates and checked before
                signaling any run (including one it did not itself start).
            feature_id: The owning feature's stable ID, recorded on every
                :class:`RunState`.
            adapter_resolver: Resolves a :class:`TargetConfig.kind` to its
                concrete :class:`TargetAdapter`. Defaults to the real lazy
                registry (:func:`parrot.e2e.targets.get_target_adapter`);
                tests inject a fake resolver.
            request_deadline_s: Default per-request deadline for this run's
                private :class:`ControlServer`/stdio exchanges.
            logger: Optional logger; defaults to a module-level logger.

        Raises:
            E2EConfigError: If ``owner_id``/``feature_id`` is not a safe
                nonempty slug, or ``worktree`` does not exist / is not a
                directory.
        """
        _validate_id(owner_id, field_name="owner_id")
        _validate_id(feature_id, field_name="feature_id")
        try:
            resolved_worktree = worktree.resolve(strict=True)
        except OSError as exc:
            raise E2EConfigError(
                f"worktree root does not exist or is unreadable: {worktree}: {exc}", reason_code="worktree_missing"
            ) from exc
        if not resolved_worktree.is_dir():
            raise E2EConfigError(f"worktree root is not a directory: {worktree}", reason_code="worktree_not_directory")

        self._worktree = resolved_worktree
        self._owner_id = owner_id
        self._feature_id = feature_id
        self._adapter_resolver = adapter_resolver
        self._request_deadline_s = request_deadline_s
        self.logger = logger or logging.getLogger(__name__)
        self._runs: dict[str, _LiveRun] = {}

    @property
    def worktree(self) -> Path:
        """The canonical (resolved) worktree root this supervisor operates in."""
        return self._worktree

    # ------------------------------------------------------------------
    # start
    # ------------------------------------------------------------------

    async def start(self, target_id: str, config: TargetConfig) -> RunState:
        """Start the target or raise a typed configuration/readiness error.

        Registers this target's :class:`ProcessIdentity` and persists its
        initial :class:`RunState` (status ``starting``) *before* polling for
        readiness (spec §2). Retries exactly once, within the original
        ``config.startup_timeout_s`` deadline, if the child exits early with
        a verified port-collision signature (spec §2).

        Args:
            target_id: This target's stable key (used to build its run ID).
            config: The target's launch/readiness configuration.

        Returns:
            The final, persisted :class:`RunState` (status ``ready``).

        Raises:
            E2EConfigError: If ``target_id`` is unsafe, or ``config.kind``
                does not resolve to a known adapter.
            E2EPrerequisiteError: If the resolved adapter is unavailable, or
                a required prerequisite for this target is missing.
            E2ETargetError: If the target fails to spawn, exits early
                without a retryable port collision, or never becomes ready
                within its startup deadline.
        """
        _validate_id(target_id, field_name="target_id")
        adapter = self._adapter_resolver(config.kind)

        run_id = self._new_run_id(target_id)
        deadline_monotonic = time.monotonic() + config.startup_timeout_s
        run_directory = e2e_state.run_dir(run_id, worktree=self._worktree)
        control_socket = self._resolve_control_socket_path(run_id, run_directory)
        log_path = self._log_path(run_id, target_id)

        live: Optional[_LiveRun] = None
        for attempt in (1, 2):
            launch_spec = await adapter.prepare(config, run_id=run_id, worktree=self._worktree)
            process, log_handle = await self._spawn_process(
                launch_spec, log_path=log_path, run_id=run_id, target_id=target_id
            )
            identity = e2e_state.capture_process_identity(process.pid, owned=True)
            started_at = datetime.now(timezone.utc)
            own_identity = e2e_state.capture_process_identity(os.getpid(), owned=False)
            state = RunState(
                feature_id=self._feature_id,
                run_id=run_id,
                worktree=str(self._worktree),
                owner_id=self._owner_id,
                controller_identity=own_identity,
                supervisor_identity=own_identity,
                process_identity=identity,
                target_id=target_id,
                status="starting",
                endpoint=None,
                control_socket=str(control_socket),
                started_at=started_at,
                deadline=started_at + timedelta(seconds=_DEFAULT_LEASE_S),
                log_path=str(log_path),
            )
            # Registration before readiness (spec §2 / research spike §1.1).
            with e2e_state.locked_run(run_id, worktree=self._worktree):
                e2e_state.write_state(state, worktree=self._worktree)

            stdio_channel = _StdioChannel(process) if launch_spec.stdio else None
            if live is None:
                operations = self._build_control_operations(run_id)
                control_server = ControlServer(
                    control_socket,
                    run_id=run_id,
                    owner_id=self._owner_id,
                    operations=operations,
                    request_deadline_s=self._request_deadline_s,
                )
                live = _LiveRun(
                    run_id=run_id,
                    target_id=target_id,
                    config=config,
                    process=process,
                    control_server=control_server,
                    log_handle=log_handle,
                    stdio_channel=stdio_channel,
                    state=state,
                )
                self._runs[run_id] = live
                await control_server.start()
            else:
                with contextlib.suppress(Exception):
                    live.log_handle.close()
                live.process = process
                live.log_handle = log_handle
                live.stdio_channel = stdio_channel
                live.state = state

            outcome = await self._await_ready(
                process, adapter, launch_spec, state, deadline_monotonic=deadline_monotonic
            )
            if outcome == "ready":
                ready_state = state.model_copy(update={"status": "ready"})
                with e2e_state.locked_run(run_id, worktree=self._worktree):
                    e2e_state.write_state(ready_state, worktree=self._worktree)
                live.state = ready_state
                return ready_state

            tail = self._read_log_tail(log_path)
            collision = outcome == "exited" and bool(_PORT_COLLISION_RE.search(tail))
            await self._terminate_process_best_effort(process)
            if collision and attempt == 1 and time.monotonic() < deadline_monotonic:
                self.logger.warning("target %r exited with a verified port collision; retrying once", target_id)
                continue

            failure_state = state.model_copy(update={"status": "failed", "cleanup_complete": True})
            with e2e_state.locked_run(run_id, worktree=self._worktree):
                e2e_state.write_state(failure_state, worktree=self._worktree)
            await self._teardown_live_resources(live)
            self._runs.pop(run_id, None)
            reason_code = "target_readiness_timeout" if outcome == "timeout" else "target_exited_early"
            raise E2ETargetError(
                f"target {target_id!r} (run {run_id!r}) failed to become ready: {outcome}", reason_code=reason_code
            )

        raise AssertionError("unreachable: the attempt loop always returns or raises")  # pragma: no cover

    async def _await_ready(
        self,
        process: "asyncio.subprocess.Process",
        adapter: TargetAdapter,
        launch_spec: LaunchSpec,
        state: RunState,
        *,
        deadline_monotonic: float,
    ) -> str:
        """Poll for readiness plus child identity, bounded by ``deadline_monotonic``.

        Args:
            process: The just-spawned child process.
            adapter: This target's adapter (consulted for non-``stdio`` readiness).
            launch_spec: The launch spec that produced ``process``.
            state: This attempt's (not-yet-``ready``) :class:`RunState`.
            deadline_monotonic: ``time.monotonic()`` deadline for this attempt.

        Returns:
            ``"ready"``, ``"exited"`` (the child exited before becoming
            ready) or ``"timeout"`` (the deadline elapsed first).
        """
        iteration = 0
        while True:
            if process.returncode is not None or not self._process_alive(process.pid):
                # `psutil`-observed liveness (an immediate OS-level fact) is
                # checked in addition to `process.returncode`: asyncio's own
                # child-watcher callback that sets `returncode` depends on
                # SIGCHLD delivery to *this* event loop, which is unreliable
                # across the function-scoped event loops pytest-asyncio
                # creates per test (verified flaky without this — a
                # just-exited child could otherwise race past this check as
                # "still alive"). Give asyncio a chance to actually reap it
                # so a later `process.wait()` (e.g. in `stop()`) does not hang.
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(process.wait(), timeout=_READY_POLL_INTERVAL_S)
                return "exited"
            # Require at least one full poll interval of confirmed liveness
            # before ever trusting readiness (from the adapter, or — for a
            # stdio launch, see module docstring — from liveness alone):
            # immediately after spawn, the event loop has not necessarily
            # run the child-exited callback yet, so `returncode is None`
            # on iteration 0 does not yet mean "still alive", only "not
            # observed as dead yet" — an instant crash could otherwise race
            # past this check as a false "ready".
            if iteration >= 1:
                is_ready = True if launch_spec.stdio else await adapter.ready(state)
                if is_ready and process.returncode is None:
                    if e2e_state.process_identity_matches(process.pid, state.process_identity):
                        return "ready"
            if time.monotonic() >= deadline_monotonic:
                return "timeout"
            # Wait on the process's own exit future rather than a passive
            # `asyncio.sleep` — under load, a plain sleep can resume before
            # asyncio's child watcher has actually resolved `returncode`,
            # letting an already-dead child race past the check above as a
            # false "still alive" (verified flaky in this task's own test
            # suite without this). `process.wait()` is safe to await
            # repeatedly and resolves immediately once genuinely known.
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(process.wait(), timeout=_READY_POLL_INTERVAL_S)
            iteration += 1

    @staticmethod
    def _process_alive(pid: int) -> bool:
        """Return whether ``pid`` is a real, non-zombie live process right now.

        A ``psutil``-observed, immediate OS-level fact — independent of
        whether *this* event loop's asyncio child watcher has yet resolved
        the owning :class:`asyncio.subprocess.Process.returncode`.

        Args:
            pid: The OS process ID to check.

        Returns:
            ``True`` if the process exists and is not a zombie; ``False``
            otherwise (including if it cannot be inspected at all).
        """
        try:
            proc = psutil.Process(pid)
            return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
        except psutil.Error:
            return False

    # ------------------------------------------------------------------
    # request_stdio
    # ------------------------------------------------------------------

    async def request_stdio(self, run_id: str, payload: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """Exchange one JSON-RPC request over supervisor-owned stdio pipes.

        Args:
            run_id: The run's stable ID; must be a locally owned, currently
                live ``stdio``-launched run.
            payload: The JSON-RPC-shaped request object to forward verbatim.

        Returns:
            The parsed JSON object read from the target's stdout.

        Raises:
            E2EConfigError: If ``run_id`` is unsafe, unknown to this
                instance, or is not a ``stdio``-launched target.
            E2ETargetError: See :meth:`_StdioChannel.request`.
        """
        _validate_id(run_id, field_name="run_id")
        live = self._runs.get(run_id)
        if live is None:
            raise E2EConfigError(f"unknown or not locally owned run_id: {run_id!r}", reason_code="run_unknown")
        if live.stdio_channel is None:
            raise E2EConfigError(f"run {run_id!r} does not expose a stdio channel", reason_code="not_stdio_target")
        return await live.stdio_channel.request(payload, deadline_s=self._request_deadline_s)

    # ------------------------------------------------------------------
    # stop
    # ------------------------------------------------------------------

    async def stop(self, run_id: str) -> RunState:
        """Idempotently terminate owned processes and persist verified cleanup state.

        TERM, wait up to :data:`_TERM_WAIT_S`, then KILL and bounded reaping
        (spec §2). Revalidates process identity/ownership immediately before
        *every* signal — a foreign, adopted or already-reused-PID run is
        never signaled (spec §2), and an unresolved cleanup is persisted as
        ``failed``, never silently reported as ``stopped``.

        Args:
            run_id: The run's stable ID.

        Returns:
            The final, persisted :class:`RunState`.

        Raises:
            E2EConfigError: If ``run_id`` is unsafe or has no persisted
                :class:`RunState` in this worktree.
        """
        _validate_id(run_id, field_name="run_id")
        current_state = e2e_state.read_state(run_id, worktree=self._worktree)
        if current_state.cleanup_complete:
            return current_state

        with e2e_state.locked_run(run_id, worktree=self._worktree):
            current_state = e2e_state.read_state(run_id, worktree=self._worktree)
            if current_state.cleanup_complete:
                return current_state

            current_state = current_state.model_copy(update={"status": "stopping"})
            e2e_state.write_state(current_state, worktree=self._worktree)

            shutdown_forced = False
            identity = current_state.process_identity
            if e2e_state.is_authorized_to_signal(current_state, worktree=self._worktree, owner_id=self._owner_id):
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(identity.pgid, signal.SIGTERM)
                exited = await self._wait_for_pid_exit(run_id, identity, timeout_s=_TERM_WAIT_S)
                if not exited and e2e_state.is_authorized_to_signal(
                    current_state, worktree=self._worktree, owner_id=self._owner_id
                ):
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(identity.pgid, signal.SIGKILL)
                    shutdown_forced = True
                    exited = await self._wait_for_pid_exit(run_id, identity, timeout_s=_KILL_WAIT_S)
                cleanup_complete = exited
            else:
                # Adopted/foreign/reused-PID/not-ours: never signal. Cleanup
                # only "counts" if the process is independently confirmed gone.
                cleanup_complete = not e2e_state.process_identity_matches(identity.pid, identity)

            live = self._runs.pop(run_id, None)
            if live is not None:
                self._teardown_live_resources_deferred(live)

            final_status = "stopped" if cleanup_complete else "failed"
            final_state = current_state.model_copy(
                update={
                    "status": final_status,
                    "shutdown_forced": shutdown_forced,
                    "cleanup_complete": cleanup_complete,
                }
            )
            e2e_state.write_state(final_state, worktree=self._worktree)
        return final_state

    async def _wait_for_pid_exit(self, run_id: str, identity: ProcessIdentity, *, timeout_s: float) -> bool:
        """Wait up to ``timeout_s`` for ``identity``'s process to exit.

        Uses the locally owned :class:`asyncio.subprocess.Process` handle
        when available (precise, event-driven); otherwise polls
        :func:`parrot.e2e.state.process_identity_matches` (a run known only
        via its persisted state, e.g. a cross-process ``stop``/``down``).

        Args:
            run_id: The run's stable ID.
            identity: The recorded identity to wait on.
            timeout_s: Maximum seconds to wait.

        Returns:
            ``True`` once the process is confirmed gone within the timeout;
            ``False`` otherwise.
        """
        live = self._runs.get(run_id)
        if live is not None:
            try:
                await asyncio.wait_for(live.process.wait(), timeout=timeout_s)
                return True
            except asyncio.TimeoutError:
                return False

        deadline = time.monotonic() + timeout_s
        while True:
            if not e2e_state.process_identity_matches(identity.pid, identity):
                return True
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(_READY_POLL_INTERVAL_S)

    # ------------------------------------------------------------------
    # Control-channel wiring
    # ------------------------------------------------------------------

    def _build_control_operations(self, run_id: str) -> dict[str, ControlHandler]:
        """Build this run's ``status``/``stop``/``stdio`` :class:`ControlServer` operations.

        Every handler looks up ``run_id`` in ``self._runs`` dynamically at
        call time (never captures a specific :class:`_LiveRun` snapshot), so
        it stays correct across a same-run-ID port-collision retry.

        Args:
            run_id: The run these operations are bound to.

        Returns:
            The operations mapping, ready to pass to :class:`ControlServer`.
        """

        async def _op_status(_params: dict[str, JsonValue]) -> dict[str, JsonValue]:
            state = e2e_state.read_state(run_id, worktree=self._worktree)
            return {"state": state.model_dump(mode="json")}

        async def _op_stop(_params: dict[str, JsonValue]) -> dict[str, JsonValue]:
            state = await self.stop(run_id)
            return {"state": state.model_dump(mode="json")}

        async def _op_stdio(params: dict[str, JsonValue]) -> dict[str, JsonValue]:
            payload = params.get("payload")
            if not isinstance(payload, dict):
                raise E2EConfigError("stdio operation requires an object 'payload'", reason_code="invalid_request")
            return await self.request_stdio(run_id, payload)

        return {"status": _op_status, "stop": _op_stop, "stdio": _op_stdio}

    # ------------------------------------------------------------------
    # Process spawn / environment isolation / logging helpers
    # ------------------------------------------------------------------

    async def _spawn_process(
        self, launch_spec: LaunchSpec, *, log_path: Path, run_id: str, target_id: str
    ) -> tuple["asyncio.subprocess.Process", IO[bytes]]:
        """Spawn one target child in its own process group, with an isolated environment.

        Args:
            launch_spec: The validated argv/env/cwd/stdio launch description.
            log_path: This run's log file (spec §2: ``artifacts/logs/e2e/<run-id>/``).
            run_id: The run's stable ID (recorded in the log header).
            target_id: The target's stable key (recorded in the log header).

        Returns:
            ``(process, log_handle)`` — ``log_handle`` stays open for the
            lifetime of this attempt and must be closed by the caller.

        Raises:
            E2ETargetError: If the child process cannot be spawned.
        """
        env = self._build_child_env(launch_spec.env)
        await asyncio.to_thread(
            self._write_log_header, log_path, launch_spec=launch_spec, env=env, run_id=run_id, target_id=target_id
        )
        log_handle = await asyncio.to_thread(open, log_path, "ab", buffering=0)
        try:
            if launch_spec.stdio:
                process = await asyncio.create_subprocess_exec(
                    *launch_spec.argv,
                    cwd=str(launch_spec.cwd),
                    env=env,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=log_handle,
                    start_new_session=True,
                )
            else:
                process = await asyncio.create_subprocess_exec(
                    *launch_spec.argv,
                    cwd=str(launch_spec.cwd),
                    env=env,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=log_handle,
                    stderr=log_handle,
                    start_new_session=True,
                )
        except OSError as exc:
            log_handle.close()
            raise E2ETargetError(f"failed to spawn target {target_id!r}: {exc}", reason_code="spawn_failed") from exc
        return process, log_handle

    def _build_child_env(self, extra_env: dict[str, str]) -> dict[str, str]:
        """Build one target's isolated environment (spec §2 "Child environment ...").

        Strips every known model-credential variable from a copy of this
        process's own environment, disables bytecode writes, prepends this
        worktree's ``packages/*/src`` directories onto ``PYTHONPATH`` (so any
        child that imports ``parrot`` provably uses this checkout), then
        overlays ``extra_env`` (the adapter's own explicit choices win).

        Args:
            extra_env: The :class:`LaunchSpec`'s adapter-specific environment.

        Returns:
            The final environment mapping for the child process.
        """
        base = {key: value for key, value in os.environ.items() if key not in _CREDENTIAL_ENV_VARS}
        base["PYTHONDONTWRITEBYTECODE"] = "1"
        prefixes = self._pythonpath_prefixes()
        if prefixes:
            existing = base.get("PYTHONPATH", "")
            base["PYTHONPATH"] = os.pathsep.join([*prefixes, existing] if existing else prefixes)
        base.update(extra_env)
        return base

    def _pythonpath_prefixes(self) -> list[str]:
        """List this worktree's existing ``packages/*/src`` directories, sorted.

        Returns:
            Sorted absolute directory paths (as strings); empty if this
            worktree has no ``packages`` directory.
        """
        packages_dir = self._worktree / "packages"
        if not packages_dir.is_dir():
            return []
        return sorted(str(path) for path in packages_dir.glob("*/src") if path.is_dir())

    def _resolve_control_socket_path(self, run_id: str, run_directory: Path) -> Path:
        """Choose this run's control-socket path, honoring ``AF_UNIX``'s hard length limit.

        Spec §2 says sockets "reside in a mode-0700 run directory"
        (``run_directory / "control.sock"``, the spec-literal choice) — but
        Linux's ``sun_path`` buffer is only 108 bytes including the NUL
        terminator, and this project's own worktree convention
        (``.claude/worktrees/<feature>--TASK-<id>-<uuid>/``) routinely
        produces a ``run_directory`` alone longer than that, before any
        run/target ID is even appended (verified directly against this
        checkout's own worktree path). When the spec-literal path would not
        fit, this falls back to a short, still mode-0700-protected path
        outside the worktree, named by an opaque hash of ``(worktree,
        run_id)`` — never the (also potentially long) ``run_id`` itself.

        Args:
            run_id: The run's stable ID.
            run_directory: The run's mode-0700 directory (spec-preferred
                socket location when it fits).

        Returns:
            An absolute path short enough to ``bind()`` an ``AF_UNIX``
            socket at.
        """
        preferred = run_directory / "control.sock"
        if len(str(preferred).encode("utf-8")) < _MAX_SOCKET_PATH_BYTES:
            return preferred

        socket_dir = Path(tempfile.gettempdir()) / f"parrot-e2e-{self._owner_id}"
        socket_dir.mkdir(mode=0o700, exist_ok=True)
        os.chmod(socket_dir, 0o700)
        digest = hashlib.sha256(f"{self._worktree}:{run_id}".encode("utf-8")).hexdigest()[:16]
        fallback = socket_dir / f"{digest}.sock"
        self.logger.warning(
            "control socket path %s exceeds the AF_UNIX length limit; using %s instead", preferred, fallback
        )
        return fallback

    def _log_path(self, run_id: str, target_id: str) -> Path:
        """Return (creating parent directories if needed) this run's log file path.

        Spec §2: "Logs go to ``artifacts/logs/e2e/<run-id>/``."

        Args:
            run_id: The run's stable ID.
            target_id: The target's stable key.

        Returns:
            ``<worktree>/artifacts/logs/e2e/<run_id>/<target_id>.log``.
        """
        log_dir = self._worktree / "artifacts" / "logs" / "e2e" / run_id
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir / f"{target_id}.log"

    def _write_log_header(
        self, log_path: Path, *, launch_spec: LaunchSpec, env: dict[str, str], run_id: str, target_id: str
    ) -> None:
        """Record this launch's module origin (argv/cwd/PYTHONPATH) at the top of its log.

        Spec §2: "record module origins and logs." Never writes environment
        *values* (only the fixed ``PYTHONPATH``/``cwd``/``argv`` this module
        itself controls) — no secret can appear here even indirectly.

        Args:
            log_path: This run's log file (opened in append mode).
            launch_spec: The launch spec being spawned.
            env: The final child environment (only ``PYTHONPATH`` is read).
            run_id: The run's stable ID.
            target_id: The target's stable key.
        """
        header = (
            f"# E2E run_id={run_id} target_id={target_id} started_at={datetime.now(timezone.utc).isoformat()} "
            f"argv={launch_spec.argv!r} cwd={launch_spec.cwd} pythonpath={env.get('PYTHONPATH', '')!r}\n"
        ).encode("utf-8")
        with open(log_path, "ab") as handle:
            handle.write(header)

    def _read_log_tail(self, log_path: Path, *, max_bytes: int = 4096) -> str:
        """Best-effort read of the last ``max_bytes`` of ``log_path``.

        Args:
            log_path: The log file to read.
            max_bytes: Maximum number of trailing bytes to decode.

        Returns:
            The decoded tail, or ``""`` if the file cannot be read.
        """
        try:
            data = log_path.read_bytes()
        except OSError:
            return ""
        return data[-max_bytes:].decode("utf-8", errors="replace")

    async def _terminate_process_best_effort(self, process: "asyncio.subprocess.Process") -> None:
        """Force-kill and reap a just-failed spawn attempt (not yet a registered ``stop``).

        Args:
            process: The process to terminate, if still alive.
        """
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(process.wait(), timeout=_KILL_WAIT_S)
        if process.stdin is not None:
            with contextlib.suppress(Exception):
                process.stdin.close()

    async def _teardown_live_resources(self, live: _LiveRun) -> None:
        """Close a run's control server, stdio pipe and log handle.

        Args:
            live: The run's live handles to release. Idempotent/best-effort:
                never raises even if some resource is already closed.

        Note:
            Never call this directly from inside one of ``live``'s own
            :class:`ControlServer` request handlers — see
            :meth:`_teardown_live_resources_deferred`.
        """
        with contextlib.suppress(Exception):
            await live.control_server.stop()
        if live.process.stdin is not None:
            with contextlib.suppress(Exception):
                live.process.stdin.close()
        with contextlib.suppress(Exception):
            live.log_handle.close()

    def _teardown_live_resources_deferred(self, live: _LiveRun) -> None:
        """Schedule :meth:`_teardown_live_resources` without awaiting it here.

        :meth:`stop` may itself be invoked *as* a ``ControlServer`` "stop"
        operation for ``live`` (an out-of-process caller reaching in over
        the socket). On CPython's asyncio, ``Server.wait_closed()`` (called
        by :meth:`ControlServer.stop`) waits for every connection the server
        ever accepted to finish — including the very connection currently
        running this handler. Awaiting the teardown synchronously from
        inside that handler would therefore deadlock (verified directly:
        the "stop" RPC never received a response). Scheduling it as a
        separate task lets this handler return its response first; the
        control socket is then closed shortly after, off this call path.

        Args:
            live: The run's live handles to release.
        """
        stdin = live.process.stdin
        if stdin is not None:
            with contextlib.suppress(Exception):
                stdin.close()
        with contextlib.suppress(Exception):
            live.log_handle.close()
        asyncio.create_task(self._close_control_server(live.control_server))

    async def _close_control_server(self, control_server: ControlServer) -> None:
        """Best-effort, exception-suppressing :meth:`ControlServer.stop`."""
        with contextlib.suppress(Exception):
            await control_server.stop()

    def _new_run_id(self, target_id: str) -> str:
        """Generate a fresh, safe-slug run ID scoped to ``target_id``.

        Args:
            target_id: The target's stable key.

        Returns:
            A run ID of the form ``<target_id>-<12 hex chars>``.
        """
        return f"{target_id}-{uuid.uuid4().hex[:12]}"
