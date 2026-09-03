"""Host-side handle to one per-session REPL worker process (FEAT-380 Module 3).

``WorkerHandle`` owns the async, host-side half of the control protocol
(``protocol.py``) and the child process spawned via
``python -m parrot.tools.repl_worker.worker`` (``worker.py``, TASK-1940).
This is where the feature's core guarantee lives: **the host enforces
``deadline_ms`` — if the worker does not answer in time, SIGKILL** (G2/AC2).

The handle also maintains a cheap, names-only shadow of the worker's
namespace (refreshed from ``ExecResult.new_vars`` and ``list_ns``) so that
after a kill it can tell the LLM exactly which variables were just lost
(AC11), with the cause differentiated as ``"timeout"`` / ``"memory"`` /
``"crash"``.

Prewarming, the worker pool, TTL eviction and the concurrency ceiling are
TASK-1942 (``WorkerPool``) — this module only owns ONE worker's lifecycle.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from typing import Any, BinaryIO, Optional

from .observer import ProcessObserver, read_proc_cpu_seconds, read_proc_status, read_proc_wchan
from .protocol import (
    ExecRequest,
    ExecResult,
    GetVarRequest,
    InjectDfRequest,
    ListNsRequest,
    ListNsResponse,
    MemoryVerdict,
    NamespaceLossError,
    PingRequest,
    PongResponse,
    ReadyResponse,
    ResetRequest,
    SetVarRequest,
    SnapshotRequest,
    SnapshotResponse,
    ValueResponse,
    WorkerConfig,
    decode_value,
    encode_value,
    read_frame,
    write_frame,
)

logger = logging.getLogger(__name__)


def probe_process_state(pid: int | None) -> str:
    """Best-effort one-line snapshot of a live process from ``/proc`` (Linux).

    Bootstrap diagnostics (post-FEAT-500): quoted in ``WorkerBootstrapError``
    when a worker never sends its ready frame, so the error says whether the
    child was stopped (``T``: SIGSTOP/SIGTTOU/debugger), sleeping on a
    kernel wait channel (``S`` + ``wchan``), starved of CPU (``R`` with a
    tiny ``cpu=``), or thrashing (huge ``VmPeak``). Never raises.

    The ``/proc`` parsing itself moved to ``observer.py`` (FEAT-521 TASK-2775,
    reused by ``ProcessObserver``'s continuous sampling); this function is now
    a thin compatibility wrapper preserving its original signature and
    return-value contract for existing callers.

    Args:
        pid: The process to inspect; ``None`` or a non-Linux host yields
            ``""``.

    Returns:
        ``"state=... threads=... vmpeak=... wchan=... cpu=...s"`` or ``""``
        when unavailable.
    """
    if pid is None or sys.platform != "linux":
        return ""
    try:
        fields = read_proc_status(pid)
    except OSError:
        return ""
    wchan = read_proc_wchan(pid) or "?"
    try:
        cpu = f"{read_proc_cpu_seconds(pid):.2f}s"
    except (OSError, ValueError, IndexError):
        cpu = "?"
    return (
        f"state={fields.get('State', '?')} threads={fields.get('Threads', '?')} "
        f"vmpeak={fields.get('VmPeak', '?')} wchan={wchan} cpu={cpu}"
    )


class WorkerBootstrapError(RuntimeError):
    """The worker never sent its :class:`ReadyResponse` in time (FEAT-500).

    Raised by :meth:`WorkerHandle.wait_ready` (and therefore by the first
    :meth:`WorkerHandle._send`) when a worker fails to finish bootstrapping
    within ``WorkerConfig.bootstrap_timeout_ms``, or dies / speaks
    out-of-protocol while doing so. The process has already been killed by
    the time this is raised: a child that cannot boot is not a live worker
    (spec §2, Q1). The message always names the pid, the budget, the
    observed cause and the tail of the worker's stderr.
    """


class NamespaceTimeoutError(TimeoutError):
    """A non-``exec`` request timed out; the worker is still ALIVE (FEAT-500).

    Only the ``execute()`` deadline kills a worker (spec G2/U2). Every other
    request — ``get_var``/``set_var``/``list_vars``/``snapshot``/``reset``/
    ``inject_dataframe``/``ping`` — raises this instead: the process keeps
    running, its namespace is preserved, and the late reply is parked and
    drained before the next request is written. Subclasses ``TimeoutError``
    so existing broad ``except TimeoutError`` callers keep working, but
    unlike the bare ``asyncio.TimeoutError`` it always carries a
    human-readable message (spec G3).
    """


#: Extra grace period added to `deadline_ms` before the host gives up and
#: kills the worker, so ordinary clock skew between host and worker doesn't
#: kill a response that finished just under the wire (Key Constraint).
_DEADLINE_GRACE_MS = 250

#: stderr substrings that hint the worker died from memory pressure rather
#: than a generic crash. Best-effort heuristic — OS-level process death
#: alone cannot always distinguish "memory" from "crash" cleanly; this is
#: not a hard contract, just the differentiation signal the spec calls for.
_MEMORY_MARKERS = (
    "MemoryError",
    "Cannot allocate memory",
    "bad_alloc",
    "failed to map segment",
    "Killed",
    "OOM",
)

#: CPU-seconds delta below which a bootstrap progress window is "flat"
#: (FEAT-521 §3 Module 4 bootstrap diagnostics) — same tolerance as
#: `ProcessObserver`'s own verdict derivation.
_BOOT_PROGRESS_EPSILON_S = 1e-3


def _format_bytes(n: int) -> str:
    """Human-readable binary byte size, e.g. ``4.30 GiB`` (FEAT-521 G4).

    Args:
        n: A byte count.

    Returns:
        ``n`` formatted with the largest binary unit that keeps the value
        readable (``B``/``KiB``/``MiB``/``GiB``/``TiB``).
    """
    value = float(n)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024:
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.2f} {unit}"
        value /= 1024
    return f"{value:.2f} TiB"


class WorkerHandle:
    """Host-side handle to one per-session REPL worker process."""

    def __init__(
        self,
        config: Optional[WorkerConfig] = None,
        output_dir: Optional[str] = None,
        repl_kwargs: Optional[dict[str, Any]] = None,
        executor: Optional[concurrent.futures.Executor] = None,
    ):
        """Initialize the handle (does not spawn — call :meth:`start`).

        Args:
            config: Resource-limit / lifecycle configuration for the worker.
                Defaults to ``WorkerConfig()``.
            output_dir: Shared output directory for plots/reports, visible
                to both host and worker.
            repl_kwargs: Extra ``PythonREPLTool`` constructor kwargs to
                mirror on the worker's internal instance (e.g.
                ``return_plot_as_base64``, TASK-1943) — session config
                distinct from ``WorkerConfig``'s resource-limit fields.
            executor: Dedicated executor for this handle's blocking I/O
                (pipe read/write, subprocess spawn/kill, Arrow encode).
                Code-review fix (post-TASK-1945/AC1): every blocking call
                here previously used ``run_in_executor(None, ...)`` — the
                framework's SHARED default executor, exactly what Module 1
                (TASK-1939, ``PythonREPLTool._repl_executor``) exists to
                stop hijacking. Defaults to a small, self-owned
                ``ThreadPoolExecutor`` (shut down in :meth:`kill`) so even
                standalone ``WorkerHandle`` usage never falls back to the
                shared pool; ``PythonREPLTool``/``WorkerPool`` pass their
                own dedicated executor through explicitly.
        """
        self._config = config or WorkerConfig()
        self._output_dir = output_dir
        self._repl_kwargs = repl_kwargs or {}
        self._proc: Optional[subprocess.Popen] = None
        self._to_worker: Optional[BinaryIO] = None
        self._from_worker: Optional[BinaryIO] = None
        self._lock = asyncio.Lock()
        #: Serializes process teardown. `_kill_process()` can be reached from
        #: several independent paths (a lethal `execute()` deadline,
        #: `_await_ready()`'s bootstrap-timeout branch, `_classify_death()`,
        #: and an explicit `kill()`), and its `poll()` guard is not atomic —
        #: two of them could observe `poll() is None` and both dispatch
        #: `Popen.kill()`/`.wait()`, which are not documented as safe to call
        #: concurrently from multiple threads (code-review finding). Kept
        #: separate from `self._lock` on purpose: `kill()` must never wait on
        #: the request lock (see its docstring), and nothing ever acquires
        #: `self._lock` while holding this one, so the two cannot deadlock.
        self._kill_lock = asyncio.Lock()
        self._owns_executor = executor is None
        self._executor: concurrent.futures.Executor = executor or concurrent.futures.ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="repl-worker-handle"
        )
        # Code-review fix: `_drain_stdio()` runs two permanently-blocking
        # `stream.readline()` loops (stdout+stderr) for the ENTIRE lifetime
        # of the worker process — each iteration immediately resubmits
        # another blocking call the instant the previous one returns, so it
        # occupies 2 executor threads continuously, not just transiently.
        # That's incompatible with sharing `self._executor` (AC1's dedicated
        # but BOUNDED pool, e.g. 4 threads) across MULTIPLE `WorkerHandle`s,
        # as `WorkerPool` does for the session worker + prewarmed spares:
        # once enough live workers exist to saturate the shared pool with
        # drain threads alone, every actual `_send()`/`inject_dataframe()`
        # call permanently starves for a free thread — a real deadlock
        # (reproduced with the default `prewarm_pool_size=2`: 3 live workers
        # x 2 drain threads = 6 needed, only 4 available). The drain loop is
        # a passive diagnostics sink, not part of AC1's contract (which is
        # about not hijacking the FRAMEWORK's shared default executor for
        # the actual code-execution I/O path) — give it its own small,
        # always self-owned executor instead, independent of whatever
        # executor was passed in for `self._executor`.
        self._stdio_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="repl-worker-stdio"
        )
        # FEAT-500 (code review): the SIGKILL path must NEVER queue behind the
        # very blocking reads it exists to interrupt. `_kill_process()` used to
        # dispatch `proc.kill`/`proc.wait` to `self._executor` — the same pool
        # that `_roundtrip()` and `_await_ready()` occupy with blocking
        # `read_frame()` calls. Once every thread there is parked on a read,
        # a timed-out `execute()` could never obtain a thread to run the kill,
        # and freeing a thread required that kill to run first: a hard
        # deadlock in which the `deadline_ms` guarantee (AC4) silently stops
        # working and `kill()` itself hangs (reproduced with a 1-thread
        # executor). This tiny, always-self-owned pool keeps process teardown
        # independent of request traffic — the same split, for the same
        # reason, as `_stdio_executor` above.
        self._lifecycle_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="repl-worker-lifecycle"
        )
        self._stdio_task: Optional[asyncio.Task] = None
        #: FEAT-521: continuous host-side process observation, one instance
        #: per live worker. `None` until `start()` spawns the process; the
        #: verdict is `"unavailable"` on a non-POSIX host (see observer.py).
        self.observer: Optional[ProcessObserver] = None
        self._observer_task: Optional[asyncio.Task] = None
        #: FEAT-521: early-fails the bootstrap when the observer sees a
        #: sustained CPU-flat stall before `bootstrap_stall_ms` — a no-op
        #: task when that config field is 0 (disabled, the default).
        self._bootstrap_stall_task: Optional[asyncio.Task] = None
        #: Bounded ring buffer of recent stderr lines, fed by the continuous
        #: drain task (`_drain_stdio`) — `_classify_death()` reads from this
        #: instead of re-reading `self._proc.stderr` directly, which would
        #: race the drain task reading the same stream.
        self._stderr_tail: list[str] = []
        #: Same ring buffer for stdout — navconfig routes the worker's OWN
        #: log records there, so it is the only trace of a worker whose
        #: bootstrap stalled inside the framework import.
        self._stdout_tail: list[str] = []
        #: Cheap, names-only shadow of the worker namespace — feeds
        #: `lost_variables` in the namespace-loss error after a kill.
        self.known_vars: list[str] = []
        #: FEAT-500 readiness handshake. `_ready` is resolved exactly once by
        #: `_await_ready()` (created in `start()`): with the worker's
        #: `ReadyResponse` on success, or with a `WorkerBootstrapError` if the
        #: bootstrap budget expires / the worker dies while booting. It is a
        #: Future rather than an Event because many callers await the SAME
        #: outcome (the pool's prewarm top-up plus every `_send()`), and a
        #: failure must be re-raisable to all of them.
        self._ready: asyncio.Future | None = None
        self._ready_task: asyncio.Task | None = None
        #: A reply that arrived (or will arrive) after its caller already gave
        #: up on a NON-lethal timeout. The control pipe is a strictly ordered
        #: request/response channel, so this straggler MUST be drained before
        #: the next request is written or every later reply would be
        #: mis-attributed by one frame (spec §7 "Drain before write").
        self._pending_reply: asyncio.Future | None = None
        #: FEAT-521: the round-trip future currently in flight inside
        #: `_send()` (set for the duration of one call, cleared in its
        #: `finally`) — lets `interrupt()` await the SAME already-ordered
        #: reply a lethal deadline is waiting on, without dispatching a
        #: second read against the control pipe.
        self._inflight_reply: asyncio.Future | None = None

    @property
    def is_alive(self) -> bool:
        """Whether the child process is still running."""
        return self._proc is not None and self._proc.poll() is None

    async def start(self) -> None:
        """Spawn the worker process (spawn-only — never fork, see spec)."""
        loop = asyncio.get_event_loop()
        to_worker_r, to_worker_w = os.pipe()
        from_worker_r, from_worker_w = os.pipe()

        argv = [
            sys.executable,
            "-m",
            "parrot.tools.repl_worker.worker",
            self._config.model_dump_json(),
            str(to_worker_r),
            str(from_worker_w),
        ]
        if self._output_dir is not None or self._repl_kwargs:
            argv.append(self._output_dir or "")
        if self._repl_kwargs:
            argv.append(json.dumps(self._repl_kwargs))

        def _spawn() -> subprocess.Popen:
            return subprocess.Popen(  # noqa: S603 - trusted, fixed argv; spawn-only per spec
                argv,
                pass_fds=(to_worker_r, from_worker_w),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self._proc = await loop.run_in_executor(self._executor, _spawn)
        # The parent doesn't need the child's ends of either pipe.
        os.close(to_worker_r)
        os.close(from_worker_w)
        self._to_worker = os.fdopen(to_worker_w, "wb", buffering=0)
        self._from_worker = os.fdopen(from_worker_r, "rb", buffering=0)
        logger.debug("WorkerHandle: spawned worker pid=%s", self._proc.pid)

        # Continuously drain stdout/stderr so their OS pipe buffers never
        # fill (code-review fix): nothing else reads these while the worker
        # is alive, and this framework's own logging setup writes to them
        # for every `self.logger.*` call the worker makes. Once the
        # (~64KB) kernel pipe buffer fills, the worker's next log write
        # blocks indefinitely — previously only ever "recovered" by the
        # HOST's deadline SIGKILL on some later, unrelated exec() call,
        # misreported as an ordinary timeout instead of a stdio deadlock.
        self._stdio_task = loop.create_task(self._drain_stdio())

        # FEAT-521 (G1): start continuous host-side observation right after
        # the stdio drain task, spawn until kill. `_on_observer_hard_breach`
        # is awaited exactly once by the observer the first time a sample
        # crosses `memory_hard_limit_bytes`.
        self.observer = ProcessObserver(self._proc.pid, self._config, on_hard_breach=self._on_observer_hard_breach)
        self._observer_task = loop.create_task(self.observer.run())

        # FEAT-500 (G1): arm the readiness handshake. `start()` still returns
        # as soon as the process is spawned — it is `_send()` and
        # `WorkerPool._top_up_prewarmed()` that await `wait_ready()`, so no
        # request is ever written to a still-booting worker and no spare is
        # ever counted as prewarmed before it can serve.
        self._ready = loop.create_future()
        self._ready_task = loop.create_task(self._await_ready())
        # FEAT-521 (G2): optional early bootstrap failure when the observer
        # sees a sustained CPU-flat stall before `bootstrap_stall_ms` — a
        # no-op task (never started) when that budget is 0 (disabled).
        if self._config.bootstrap_stall_ms > 0:
            self._bootstrap_stall_task = loop.create_task(self._watch_bootstrap_stall())

    async def _await_ready(self) -> None:
        """Read the worker's first frame and resolve the readiness future.

        Reads exactly ONE frame — the :class:`ReadyResponse` the worker
        writes after its ``WorkerNamespace`` is built (FEAT-500, TASK-2758) —
        bounded by ``WorkerConfig.bootstrap_timeout_ms``. This is the only
        reader of ``self._from_worker`` before the first ``_send()``; the two
        can never overlap because ``_send()`` awaits :meth:`wait_ready` while
        holding ``self._lock``.

        Never raises: it is a background task, so both outcomes are recorded
        on ``self._ready`` instead. On failure the worker is killed first — a
        process that cannot boot is not a live worker (spec Q1).

        FEAT-521: no longer takes a one-shot ``/proc`` probe at the kill —
        the timeout branch reads ``self.observer``'s sample ring instead
        (:meth:`_describe_bootstrap_progress`), which was already sampling
        continuously since :meth:`start`. A separate task
        (:meth:`_watch_bootstrap_stall`) can resolve ``self._ready`` with a
        failure EARLIER than ``bootstrap_timeout_ms`` when
        ``bootstrap_stall_ms > 0`` and the observer sees a sustained
        CPU-flat stall; :meth:`_fail_ready` being idempotent is what makes
        that race with this method's own outcome safe.
        """
        loop = asyncio.get_event_loop()
        budget_ms = self._config.bootstrap_timeout_ms
        pid = self._proc.pid if self._proc is not None else None
        cause: str | None = None
        # Records whether the executor ever ran the read: a budget that
        # expires with `read_started` still clear is thread starvation on
        # the shared executor, not a slow worker — and the fix is different.
        read_started = threading.Event()

        def _read_first_frame() -> Any:
            read_started.set()
            return read_frame(self._from_worker)

        future = loop.run_in_executor(self._executor, _read_first_frame)
        try:
            frame = await asyncio.wait_for(future, timeout=budget_ms / 1000)
        except asyncio.CancelledError:
            # `kill()` cancelled us; it resolves `_ready` itself.
            future.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
            raise
        except asyncio.TimeoutError:
            if read_started.is_set():
                cause = "no ready frame within the bootstrap budget"
            else:
                threads = getattr(self._executor, "_max_workers", "?")
                cause = (
                    "the readiness read never got an executor thread — all "
                    f"{threads} thread(s) of the shared executor were busy for the whole "
                    "budget (thread starvation; raise executor_max_workers or lower "
                    "prewarm_pool_size)"
                )
            # FEAT-521: observer-derived progress note (was a one-shot
            # `probe_process_state()` snapshot taken right here — the
            # observer has been sampling continuously since `start()`).
            progress_note = self._describe_bootstrap_progress(budget_ms / 1000)
            if progress_note:
                cause = f"{cause}; {progress_note}"
            # The executor thread stays blocked on the pipe until the kill
            # below closes it; retrieve its eventual exception so Python
            # doesn't warn about it at GC time.
            future.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
        except (EOFError, OSError, ValueError) as exc:
            # EOFError: the worker died during bootstrap (its traceback is in
            # the stderr tail). ValueError: an unknown `op` on the wire.
            cause = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
        else:
            if isinstance(frame, ReadyResponse):
                if not self._ready.done():
                    self._ready.set_result(frame)
                if self.observer is not None:
                    # FEAT-521: the observer has no visibility into the
                    # ReadyResponse handshake by design (observation is
                    # host-side/pipe-independent) — this is the one place
                    # that tells it the worker is no longer "booting".
                    self.observer.mark_idle()
                logger.debug(
                    "WorkerHandle: worker pid=%s ready in %d ms",
                    frame.pid,
                    frame.bootstrap_ms,
                )
                return
            cause = f"first frame was {type(frame).__name__}, expected ReadyResponse"

        await self._kill_process()
        tail = " | ".join(self._stderr_tail[-5:]) or "<empty>"
        stdout_tail = ""
        if self._stdout_tail:
            stdout_tail = "; stdout tail: " + " | ".join(self._stdout_tail[-3:])
        self._fail_ready(
            f"REPL worker pid={pid} did not become ready within {budget_ms} ms "
            f"({cause}); stderr tail: {tail}{stdout_tail}"
        )

    def _fail_ready(self, message: str) -> None:
        """Resolve the readiness future with a `WorkerBootstrapError`.

        Args:
            message: Non-empty, human-readable cause (spec G3).
        """
        if self._ready is None or self._ready.done():
            return
        self._ready.set_exception(WorkerBootstrapError(message))
        # Mark the exception as retrieved: `wait_ready()` may legitimately
        # never be called (e.g. the handle is killed straight away), and an
        # unretrieved Future exception logs a spurious warning at GC time.
        self._ready.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)

    def _describe_bootstrap_progress(self, window_s: float) -> str:
        """Observer-derived progress note for a bootstrap timeout (spec §2).

        Args:
            window_s: Trailing window, in seconds, to measure CPU progress
                over (typically the full bootstrap budget or stall budget).

        Returns:
            E.g. ``"booting, cpu advanced 0.40 s in 30.0 s (starved)"`` or
            ``"booting, cpu flat since last sample, state=S
            wchan=futex_wait_queue (stalled)"``, or ``""`` when the observer
            never took a sample (e.g. it is `"unavailable"`).
        """
        if self.observer is None:
            return ""
        last = self.observer.last()
        if last is None:
            return ""
        progress = self.observer.cpu_progress(window_s)
        if progress > _BOOT_PROGRESS_EPSILON_S:
            return f"booting, cpu advanced {progress:.2f} s in {window_s:.1f} s (starved)"
        return f"booting, cpu flat since last sample, state={last.state} wchan={last.wchan or '-'} (stalled)"

    async def _watch_bootstrap_stall(self) -> None:
        """Fail the bootstrap early on a sustained observer-reported CPU-flat stall.

        Background task started by :meth:`start` alongside :meth:`_await_ready`
        only when ``bootstrap_stall_ms > 0`` (spec §2: "0 = never fail
        bootstrap early on a stalled verdict"). A no-op once ``self._ready``
        resolves from either side — :meth:`_fail_ready` is idempotent, so
        this can only resolve the bootstrap EARLIER than
        ``bootstrap_timeout_ms`` would, never later, and never races
        :meth:`_await_ready`'s own outcome unsafely.
        """
        stall_budget_s = self._config.bootstrap_stall_ms / 1000
        poll_s = min(self._config.observer_poll_ms / 1000, 0.5)
        started_at = time.monotonic()
        while self._ready is not None and not self._ready.done():
            await asyncio.sleep(poll_s)
            if self._ready is None or self._ready.done() or self.observer is None:
                continue
            if (time.monotonic() - started_at) < stall_budget_s:
                continue
            if self.observer.last() is None:
                continue
            if self.observer.cpu_progress(stall_budget_s) > _BOOT_PROGRESS_EPSILON_S:
                continue
            pid = self._proc.pid if self._proc is not None else None
            await self._kill_process()
            tail = " | ".join(self._stderr_tail[-5:]) or "<empty>"
            progress_note = self._describe_bootstrap_progress(stall_budget_s)
            self._fail_ready(
                f"REPL worker pid={pid} bootstrap stalled for >= "
                f"{self._config.bootstrap_stall_ms} ms ({progress_note}; failing early: "
                f"bootstrap_stall_ms exceeded); stderr tail: {tail}"
            )
            return

    @property
    def is_ready(self) -> bool:
        """Whether the worker has signalled readiness and can serve requests."""
        return (
            self._ready is not None
            and self._ready.done()
            and not self._ready.cancelled()
            and self._ready.exception() is None
        )

    async def wait_ready(self, timeout_s: float | None = None) -> ReadyResponse:
        """Await the worker's readiness handshake.

        Safe to call from any number of callers and any number of times: they
        all await the same one-shot future, and a bootstrap failure is
        re-raised to every one of them.

        Args:
            timeout_s: Optional extra ceiling on top of the handle's own
                ``bootstrap_timeout_ms`` budget. ``None`` (the default) waits
                for that budget to play out.

        Returns:
            The worker's :class:`ReadyResponse` (pid + measured bootstrap ms).

        Raises:
            WorkerBootstrapError: the worker never became ready (it has
                already been killed), or ``start()`` was never called.
            asyncio.TimeoutError: ``timeout_s`` elapsed while the worker was
                still booting (the worker is left alone — this is the
                caller's own ceiling, not the bootstrap budget).
        """
        if self._ready is None:
            raise WorkerBootstrapError("WorkerHandle.wait_ready() called before start(): no worker has been spawned")
        # Shield: several callers share this one future, so one caller's
        # timeout or cancellation must never cancel it for the others.
        if timeout_s is None:
            return await asyncio.shield(self._ready)
        return await asyncio.wait_for(asyncio.shield(self._ready), timeout=timeout_s)

    async def _drain_stdio(self) -> None:
        """Continuously read stdout/stderr into the logger (bounded per line).

        stderr lines are also appended to `self._stderr_tail` (a bounded
        ring buffer) for `_classify_death()` to consult — it must NOT read
        `self._proc.stderr` directly itself, since that would race this
        task reading the same stream.
        """
        loop = asyncio.get_event_loop()

        async def _pump(stream: Optional[BinaryIO], label: str) -> None:
            if stream is None:
                return
            while True:
                try:
                    line = await loop.run_in_executor(self._stdio_executor, stream.readline)
                except (ValueError, OSError):
                    return  # stream closed out from under us (kill()) — stop draining
                if not line:
                    return  # EOF: worker exited
                text = line.decode("utf-8", errors="replace").rstrip()
                if not text:
                    continue
                pid = self._proc.pid if self._proc is not None else "?"
                logger.debug("repl_worker[pid=%s %s]: %s", pid, label, text[:2000])
                tail = self._stderr_tail if label == "stderr" else self._stdout_tail
                tail.append(text)
                if len(tail) > 200:
                    tail.pop(0)

        await asyncio.gather(
            _pump(self._proc.stdout if self._proc else None, "stdout"),
            _pump(self._proc.stderr if self._proc else None, "stderr"),
            return_exceptions=True,
        )

    def _roundtrip(self, request: Any) -> Any:
        """Blocking write+read of one request/response pair (runs in an executor)."""
        write_frame(self._to_worker, request)
        return read_frame(self._from_worker)

    async def _send(self, request: Any, timeout_s: float, *, lethal: bool = False) -> Any:
        """Send ``request`` and await its reply within ``timeout_s``, serialized.

        Always waits for the worker's readiness handshake first (FEAT-500
        G1), so no frame is ever written to a still-bootstrapping worker,
        and always drains a reply parked by an earlier non-lethal timeout
        before writing, so replies can never shift by one frame.

        Args:
            request: The protocol message to write.
            timeout_s: Budget for this request's reply.
            lethal: Whether a timeout should kill the worker. ``True`` is
                used by :meth:`execute` ONLY (the ``deadline_ms`` contract,
                G2/AC4); every other request is non-lethal (U2) and gets a
                :class:`NamespaceTimeoutError` while the worker — and its
                namespace — survives.

        Returns:
            The worker's parsed reply message.

        Raises:
            WorkerBootstrapError: the worker never became ready.
            EOFError: the worker process is not running.
            asyncio.TimeoutError: ``lethal=True`` and the budget expired
                (the worker has been SIGKILLed).
            NamespaceTimeoutError: ``lethal=False`` and the budget expired
                (the worker is still alive; the reply is parked).
        """
        loop = asyncio.get_event_loop()
        async with self._lock:
            await self.wait_ready()
            await self._drain_pending_reply(timeout_s)
            if not self.is_alive:
                raise EOFError("worker process is not running")
            # FEAT-521: the observer's in-flight flag brackets exactly this
            # round-trip (spec: "set/cleared around `_roundtrip()` in
            # `_send()`") — cleared in `finally` below so it clears on
            # every outcome (success, timeout, cancellation, pipe failure).
            if self.observer is not None:
                self.observer.mark_busy()
            future = loop.run_in_executor(self._executor, self._roundtrip, request)
            # FEAT-521: exposed so `interrupt()` can await this SAME
            # already-ordered reply (never a second read against the pipe).
            self._inflight_reply = future
            try:
                try:
                    # Shielded (FEAT-500): `wait_for` cancels what it waits
                    # on when the budget expires, which would leave
                    # `_pending_reply` holding an already-cancelled future —
                    # undrainable, and the executor thread would still be
                    # reading the pipe behind it. Shielding cancels only the
                    # outer wrapper, so a non-lethally timed-out reply stays
                    # genuinely pending and awaitable.
                    return await asyncio.wait_for(asyncio.shield(future), timeout=timeout_s)
                except asyncio.CancelledError:
                    # The caller gave up (its own outer timeout, or task
                    # cancellation) — but the shielded executor thread still
                    # owns the pipe and WILL consume one reply frame. Park it
                    # exactly as a non-lethal timeout does: otherwise this
                    # method returns with `_pending_reply` empty, the next
                    # `_send()` writes while that thread is still reading,
                    # two threads read the same pipe and every subsequent
                    # reply is off by one frame. Cancellation is not a
                    # deadline breach, so the worker is never killed here
                    # (even when `lethal=True`).
                    future.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
                    self._pending_reply = future
                    raise
                except asyncio.TimeoutError:
                    # The executor thread is still blocked reading the pipe
                    # and will finish in the background; nobody awaits
                    # `future` through the normal path after this point, so
                    # retrieve/discard its eventual exception to avoid an
                    # "exception was never retrieved" warning at GC time.
                    future.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
                    if lethal:
                        # FEAT-521 G3 (two-stage deadline): try SIGINT before
                        # SIGKILL. The worker's service loop converts a
                        # KeyboardInterrupt into a bounded ExecResult and
                        # keeps its namespace (TASK-2776) — `interrupt()`
                        # awaits the SAME `future` up to
                        # `interrupt_grace_ms`; a reply landing there is
                        # returned normally (not a loss error, `known_vars`
                        # untouched). Only the deterministic SIGKILL fallback
                        # follows when the worker never answers the SIGINT.
                        if self._config.interrupt_before_kill and await self.interrupt():
                            return future.result()
                        await self._kill_process()
                        raise
                    # U2: the worker keeps running and keeps its namespace.
                    # Park the straggling reply so the next `_send()` drains
                    # it.
                    self._pending_reply = future
                    pid = self._proc.pid if self._proc is not None else None
                    raise NamespaceTimeoutError(
                        f"repl_worker[pid={pid}]: {request.op!r} request did not answer "
                        f"within {timeout_s:.1f}s; the worker is still alive and the late "
                        f"reply will be drained on the next call"
                    ) from None
            finally:
                self._inflight_reply = None
                if self.observer is not None:
                    self.observer.mark_idle()

    async def _drain_pending_reply(self, timeout_s: float) -> None:
        """Consume a reply left over from an earlier non-lethal timeout.

        Must run before any new frame is written (spec §7 "Drain before
        write"): the control pipe carries one reply per request in order, so
        an undrained straggler would be handed to the NEXT caller as if it
        were its own answer.

        Args:
            timeout_s: Budget for the straggler to land.

        Raises:
            NamespaceTimeoutError: the straggler still has not landed. It
                stays parked and the worker is left alive — draining is
                never a reason to kill.
        """
        pending = self._pending_reply
        if pending is None:
            return
        try:
            # Shielded: a timeout here must leave the future parked and
            # still running, not cancel it.
            await asyncio.wait_for(asyncio.shield(pending), timeout=timeout_s)
        except asyncio.TimeoutError:
            pid = self._proc.pid if self._proc is not None else None
            raise NamespaceTimeoutError(
                f"repl_worker[pid={pid}]: a reply from a previously timed-out request "
                f"has still not arrived after {timeout_s:.1f}s; the worker is still alive "
                f"and the reply stays queued for the next call"
            ) from None
        except (EOFError, OSError, ValueError) as exc:
            # The straggler failed instead of answering (worker died in the
            # meantime). That is not this caller's error: clear it and let
            # the alive-check / round-trip below report the real state.
            logger.debug("WorkerHandle: parked reply failed while draining: %s", exc)
        self._pending_reply = None

    async def interrupt(self) -> bool:
        """Send SIGINT and wait up to ``interrupt_grace_ms`` for the reply (spec G3).

        Namespace-preserving alternative to an immediate SIGKILL on a
        ``deadline_ms`` breach: signals go through ``_lifecycle_executor``,
        never the pipe-reading ``_executor`` (same rule as
        :meth:`_kill_process` — the kill/signal path must never queue
        behind a blocked read). Awaits ``self._inflight_reply`` — the SAME
        round-trip future :meth:`_send` is already waiting on — rather than
        issuing a second read against the control pipe, which the strictly
        ordered protocol does not allow.

        Never sends SIGINT on a non-POSIX host (``send_signal(SIGINT)`` is
        unreliable there without a shared console — spec AC11: "interrupt
        disabled" off-POSIX), when the process is already dead, or when the
        observer's verdict shows the worker is not actually busy
        (``"settled"``/``"booting"``/``"unavailable"``) — a worker that
        isn't mid-request has nothing productive to interrupt.

        Returns:
            ``True`` if a reply frame arrived within ``interrupt_grace_ms``
            (the worker's namespace survives); ``False`` if SIGINT was
            skipped, the grace period elapsed, or the worker died instead
            of answering — the caller should fall back to
            :meth:`_kill_process`.
        """
        if sys.platform == "win32":
            return False
        if self._proc is None or self._proc.poll() is not None:
            return False
        if self.observer is not None and self.observer.verdict() in ("settled", "booting", "unavailable"):
            logger.debug(
                "WorkerHandle: pid=%s skipping SIGINT — observer verdict=%s (not busy)",
                self._proc.pid,
                self.observer.verdict(),
            )
            return False
        future = self._inflight_reply
        if future is None:
            return False
        loop = asyncio.get_event_loop()
        pid = self._proc.pid
        logger.info("WorkerHandle: pid=%s sending SIGINT (interrupt-before-kill)", pid)
        await loop.run_in_executor(self._lifecycle_executor, self._proc.send_signal, signal.SIGINT)
        grace_s = self._config.interrupt_grace_ms / 1000
        try:
            # Shielded: a caller giving up on THIS wait must never cancel
            # the underlying round-trip future — `_send()`'s own `finally`
            # still owns cleaning it up.
            await asyncio.wait_for(asyncio.shield(future), timeout=grace_s)
        except asyncio.TimeoutError:
            logger.warning(
                "WorkerHandle: pid=%s SIGINT did not produce a reply within interrupt_grace_ms=%d",
                pid,
                self._config.interrupt_grace_ms,
            )
            return False
        except (EOFError, OSError, ValueError):
            # The worker died instead of answering the interrupt — not a
            # reply; the caller falls back to the deterministic kill path.
            return False
        return True

    async def _kill_process(self) -> None:
        """SIGKILL the worker (POSIX) / TerminateProcess (Windows, AC16).

        Idempotent and safe to call after the process is already reaped —
        deliberately touches its executor ONLY when there's actually
        something to kill/wait for (code-review fix): the executor is shut
        down at the end of :meth:`kill`, so an unconditional post-kill
        ``wait()`` dispatch here would raise ``RuntimeError: cannot schedule
        new futures after shutdown`` on a second call (e.g.
        `_classify_death()` reached after an external `kill()`, or `kill()`
        called twice).

        Runs on ``self._lifecycle_executor``, never on ``self._executor``
        (FEAT-500 code review): dispatching the kill to the same pool whose
        threads are parked on blocking pipe reads deadlocks — see the comment
        on that attribute in :meth:`__init__`.
        """
        if self._proc is None or self._proc.poll() is not None:
            return  # nothing alive to kill, or already reaped
        async with self._kill_lock:
            # Re-check under the lock: another path may have killed and reaped
            # the process while we waited for it.
            if self._proc is None or self._proc.poll() is not None:
                return
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(self._lifecycle_executor, self._proc.kill)
            await loop.run_in_executor(self._lifecycle_executor, self._proc.wait)

    async def _on_observer_hard_breach(self, verdict: MemoryVerdict) -> None:
        """Kill the worker deterministically on a hard RSS breach (spec G4).

        Wired as ``ProcessObserver``'s ``on_hard_breach`` callback in
        :meth:`start`; the observer has already recorded ``verdict`` on
        ``self.observer.memory_verdict`` by the time this runs —
        :meth:`_classify_death` consults it before falling back to the
        stderr-marker heuristic. Routes through :meth:`_kill_process` (on
        ``self._lifecycle_executor``), never a direct ``Popen`` call, so it
        never races the SIGKILL path already owned by that method.

        Args:
            verdict: The measured RSS and the limit it crossed.
        """
        pid = self._proc.pid if self._proc is not None else None
        logger.warning(
            "WorkerHandle: pid=%s hard RSS limit breached (rss=%d limit=%d) — killing",
            pid,
            verdict.rss,
            verdict.limit,
        )
        await self._kill_process()

    def death_summary(self) -> tuple[int | None, str]:
        """Why this worker is (or might be) dead, for logs and diagnostics.

        Public accessor added so callers — notably ``WorkerPool``'s
        restart-loop warning — do not have to reach into ``_proc`` /
        ``_stderr_tail`` across the module boundary (code-review finding).

        Returns:
            ``(exit_code, stderr_tail)``: the process' exit code (``None`` if
            it was never spawned or is still running) and the most recent
            stderr line the drain task captured (``""`` if there is none).
        """
        exit_code = self._proc.returncode if self._proc is not None else None
        stderr_tail = self._stderr_tail[-1] if self._stderr_tail else ""
        return exit_code, stderr_tail

    async def _classify_death(self) -> str:
        """Best-effort classification of an unexpected worker death.

        Code-review fix: this used to unconditionally *wait* for the
        process to exit on its own if it was still alive — but a death
        classification can be triggered by a protocol-level failure (e.g.
        `ValueError` from `read_frame()` on a framing desync) that doesn't
        necessarily mean the process died. If the worker was actually still
        alive and healthy, that `wait()` could block forever, hanging the
        caller indefinitely instead of returning the bounded G5 error
        contract the feature is supposed to guarantee everywhere. We can no
        longer trust the pipe's framing state after a desync regardless, so
        if the process is still alive at this point, kill it deterministically
        instead of waiting for it.

        Returns:
            ``"memory"`` when the observer recorded a hard-limit breach
            (checked first — FEAT-521, deterministic, no stderr heuristics
            needed) or stderr hints at memory pressure, else ``"crash"``
            (the generic fallback — segfault, uncaught native abort,
            protocol desync, etc.).
        """
        # `_kill_process()` is idempotent/safe here whether the process is
        # still alive (kills it) or already reaped (no-op, no executor use).
        await self._kill_process()
        # FEAT-521: the observer's own recorded verdict is authoritative —
        # consult it BEFORE the stderr-marker heuristic.
        if self.observer is not None and self.observer.memory_verdict is not None:
            return "memory"
        # Read from the drain task's accumulated buffer, never the stream
        # directly — `_drain_stdio()` owns reading `self._proc.stderr`.
        stderr_text = "\n".join(self._stderr_tail)
        if any(marker in stderr_text for marker in _MEMORY_MARKERS):
            return "memory"
        return "crash"

    def _build_loss_error(self, cause: str, detail: str) -> dict[str, Any]:
        """Build the G5-shaped ``{status, result, error}`` dict for a lost worker.

        Args:
            cause: One of ``"timeout"``, ``"memory"``, ``"crash"`` (AC11).
            detail: A short technical detail appended to the message.

        Returns:
            A dict matching ``PythonREPLTool._execute()``'s error contract.
        """
        # FEAT-521: fold the observer's one-line description into the
        # detail so every namespace-loss error names the verdict and last
        # observation (spec G2/G3 "no blank errors").
        if self.observer is not None:
            detail = f"{detail}; {self.observer.describe()}"
        lost = list(self.known_vars)
        loss = NamespaceLossError(
            cause=cause,
            lost_variables=lost,
            message=(
                f"REPL worker terminated ({cause}: {detail}). ALL variables in this "
                f"session were lost: {', '.join(lost) if lost else '(none)'}. You "
                "must recreate any state you need before retrying."
            ),
        )
        self.known_vars = []  # the namespace is gone with the worker
        return {"status": "error", "result": loss.message, "error": loss.message}

    async def execute(self, code: str, debug: bool = False) -> str | dict:
        """Execute ``code`` in the worker under ``deadline_ms``.

        Args:
            code: Python source to run in the persistent REPL namespace.
            debug: Enable debug mode (mirrors ``PythonREPLTool``'s flag).

        Returns:
            The execution output string on success, or a
            ``{status, result, error}`` dict on error/timeout/crash — the
            same G5 contract ``PythonREPLTool._execute()`` returns today.
        """
        deadline_s = (self._config.deadline_ms + _DEADLINE_GRACE_MS) / 1000
        request = ExecRequest(code=code, debug=debug, deadline_ms=self._config.deadline_ms)
        try:
            # The ONLY lethal caller (G2/AC4): exceeding `deadline_ms` is
            # what SIGKILLs a worker, and nothing else does.
            response: ExecResult = await self._send(request, deadline_s, lethal=True)
        except NamespaceTimeoutError as exc:
            # A reply parked by an EARLIER non-lethal timeout still had not
            # landed when the drain step ran. The worker is alive and its
            # namespace is intact, so this must not be dressed up as a
            # namespace-loss error — that would falsely tell the LLM every
            # variable was lost (and `NamespaceTimeoutError` would otherwise
            # be caught by the clause below, since it subclasses
            # `TimeoutError`, which IS `asyncio.TimeoutError` on 3.11+).
            detail = str(exc)
            return {"status": "error", "result": detail, "error": detail}
        except asyncio.TimeoutError:
            return self._build_loss_error("timeout", f"execution exceeded deadline_ms={self._config.deadline_ms}")
        except (WorkerBootstrapError, EOFError, OSError, ValueError) as exc:
            # `WorkerBootstrapError` (FEAT-500): a fresh worker that never
            # booted. Folded into the same G5 loss dict as any other death so
            # the execute path never raises (AC11) — `_classify_death()` still
            # distinguishes a bootstrap OOM ("memory") from a plain crash.
            cause = await self._classify_death()
            return self._build_loss_error(cause, str(exc))

        if response.new_vars:
            self.known_vars = sorted(set(self.known_vars) | set(response.new_vars))
        # FEAT-521 G4: append exactly one soft-pressure hint line to this
        # result (string or dict `result`), without altering the
        # `{status, result, error}` envelope shape.
        hint = self._soft_memory_hint()
        if response.status:
            result: dict[str, Any] = {"status": response.status, "result": response.result, "error": response.error}
            if hint and isinstance(result["result"], str):
                result["result"] = result["result"] + hint
            return result
        output = response.output
        if hint and isinstance(output, str):
            output = output + hint
        return output

    def _soft_memory_hint(self) -> str:
        """One-line hint appended to the next result on a soft RSS breach (spec G4).

        Returns:
            E.g. ``"\\n[REPL memory] RSS 4.30 GiB exceeds the 4.00 GiB soft
            limit — delete DataFrames you no longer need (del name) before
            continuing."``, or ``""`` when there is no active soft-limit
            pressure.
        """
        if self.observer is None:
            return ""
        pressure = self.observer.memory_pressure
        if pressure is None:
            return ""
        rss, limit = pressure
        return (
            f"\n[REPL memory] RSS {_format_bytes(rss)} exceeds the {_format_bytes(limit)} "
            "soft limit — delete DataFrames you no longer need (del name) before continuing."
        )

    async def inject_dataframe(self, name: str, df: Any) -> None:
        """Inject a DataFrame into the worker namespace via Arrow IPC/shm (TASK-1945).

        Encodes ``df`` (Arrow IPC into a shared-memory block, or pickle as a
        logged fallback for dtypes Arrow can't represent — see
        ``transport.py``), sends it to the worker, and unlinks the shm block
        only after the worker's ACK (the framed response below) — see
        ``transport.py``'s module docstring for the full shm ownership
        contract.

        Args:
            name: Variable name to bind the DataFrame to.
            df: The ``pandas.DataFrame`` to inject.
        """
        # Local import: `transport.py` pulls in `pyarrow` (heavy) — the host
        # process already pays this cost elsewhere via pandas, but keep it
        # off this module's import-time surface for symmetry with the
        # worker side.
        from .transport import encode_dataframe, unlink_shm

        loop = asyncio.get_event_loop()
        # Encoding is CPU/memory-bound (Arrow conversion + a shm copy) — run
        # it off the event loop (Key Constraint).
        encoded = await loop.run_in_executor(self._executor, encode_dataframe, df, name)
        request = InjectDfRequest(
            name=name,
            format=encoded.format,
            shm_name=encoded.shm_name,
            size=encoded.size,
            payload=encoded.payload,
        )
        try:
            await self._send(request, timeout_s=self._namespace_timeout_s)
        finally:
            if encoded.shm_name is not None:
                # Host owns the block's lifecycle: unlink only now that the
                # worker has ack'd (read + closed its handle) via the
                # response awaited above.
                await loop.run_in_executor(self._executor, unlink_shm, encoded.shm_name)
        self.known_vars = sorted(set(self.known_vars) | {name})

    @property
    def _namespace_timeout_s(self) -> float:
        """Budget in seconds for every non-``exec`` request (FEAT-500 G4/AC6).

        Replaces the hard-coded 5 s/10 s/30 s literals that made a cold
        worker unusable: seeding a variable into a worker still importing
        pandas took longer than 5 s under load, and the timeout was lethal.
        """
        return self._config.namespace_timeout_ms / 1000

    async def get_var(self, name: str) -> Any:
        """Read one namespace variable from the worker."""
        response: ValueResponse = await self._send(GetVarRequest(name=name), self._namespace_timeout_s)
        return decode_value(response.value)

    async def set_var(self, name: str, value: Any) -> None:
        """Write one namespace variable in the worker."""
        await self._send(SetVarRequest(name=name, value=encode_value(value)), self._namespace_timeout_s)
        self.known_vars = sorted(set(self.known_vars) | {name})

    async def list_vars(self) -> list[str]:
        """Refresh and return the cheap, names-only namespace shadow."""
        response: ListNsResponse = await self._send(ListNsRequest(), self._namespace_timeout_s)
        self.known_vars = sorted(response.names)
        return self.known_vars

    async def snapshot(self) -> dict[str, Any]:
        """Return a serializable dump of the whole worker namespace."""
        response: SnapshotResponse = await self._send(SnapshotRequest(), self._namespace_timeout_s)
        return {name: decode_value(value) for name, value in response.data.items()}

    async def reset(self) -> None:
        """Reset the worker's REPL environment (equivalent to `reset_environment()`)."""
        await self._send(ResetRequest(), self._namespace_timeout_s)
        self.known_vars = []

    async def ping(self, timeout_s: float = 10.0) -> bool:
        """Health check. Returns True on a live, responsive worker.

        Args:
            timeout_s: How long to wait for a ``pong``. Defaults to 10s
                rather than a tight value — a freshly-``start()``ed worker
                is still importing pandas/numpy/matplotlib and running its
                bootstrap, which can legitimately take several seconds
                under load, and a ping sent right after ``start()`` must
                not be misreported as "unhealthy" just because it raced the
                worker's own bootstrap.
        """
        if not self.is_alive:
            return False
        try:
            response = await self._send(PingRequest(), timeout_s)
        except Exception:  # noqa: BLE001 - any failure means "not healthy"
            return False
        return isinstance(response, PongResponse)

    async def kill(self) -> None:
        """Terminate the worker process, its drain task, and the control pipes.

        Deliberately does NOT take ``self._lock`` before killing: an
        in-flight ``_send()`` holds that lock for the *entire* duration of
        its blocking read (parked in an executor thread, potentially for up
        to ``deadline_ms``) — taking the same lock here would deadlock
        `kill()` against exactly the in-flight call it needs to be able to
        interrupt. Killing the OS process directly (unsynchronized) is safe:
        it makes the worker's end of the pipe close, so a concurrent
        `_send()`'s blocked read observes EOF and resolves via its own
        ``(EOFError, OSError, ValueError)`` handling — a possible
        `ValueError: I/O operation on closed file` from closing the host's
        own stream objects here while another thread reads them is caught
        by that same handler. Only the OS-level kill matters for
        correctness; the stream-close below is opportunistic cleanup.
        """
        await self._kill_process()
        # FEAT-500 (AC12): leave no readiness task and no parked reply behind.
        if self._ready_task is not None:
            self._ready_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._ready_task
            self._ready_task = None
        # FEAT-521: leave no bootstrap-stall-watcher or observer task behind
        # either (spec AC: "killing a handle leaves no observer/readiness/
        # stdio task behind").
        if self._bootstrap_stall_task is not None:
            self._bootstrap_stall_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._bootstrap_stall_task
            self._bootstrap_stall_task = None
        if self._observer_task is not None:
            self._observer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._observer_task
            self._observer_task = None
        # A handle killed before it ever became ready must not leave
        # `wait_ready()` waiting forever — resolve it with a real message.
        self._fail_ready("REPL worker was killed before it signalled readiness")
        if self._pending_reply is not None:
            self._pending_reply.cancel()
            self._pending_reply.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
            self._pending_reply = None
        if self._stdio_task is not None:
            self._stdio_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._stdio_task
            self._stdio_task = None
        for stream in (self._to_worker, self._from_worker):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        self._to_worker = None
        self._from_worker = None
        if self._owns_executor:
            self._executor.shutdown(wait=False, cancel_futures=True)
        # `_stdio_executor` and `_lifecycle_executor` are always self-owned
        # (see `__init__`) — always shut them down here, regardless of
        # `_owns_executor`.
        self._stdio_executor.shutdown(wait=False, cancel_futures=True)
        self._lifecycle_executor.shutdown(wait=False, cancel_futures=True)
