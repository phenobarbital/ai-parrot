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
import subprocess
import sys
from typing import Any, BinaryIO, Optional

from .protocol import (
    ExecRequest,
    ExecResult,
    GetVarRequest,
    InjectDfRequest,
    ListNsRequest,
    ListNsResponse,
    NamespaceLossError,
    PingRequest,
    PongResponse,
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
        self._stdio_task: Optional[asyncio.Task] = None
        #: Bounded ring buffer of recent stderr lines, fed by the continuous
        #: drain task (`_drain_stdio`) — `_classify_death()` reads from this
        #: instead of re-reading `self._proc.stderr` directly, which would
        #: race the drain task reading the same stream.
        self._stderr_tail: list[str] = []
        #: Cheap, names-only shadow of the worker namespace — feeds
        #: `lost_variables` in the namespace-loss error after a kill.
        self.known_vars: list[str] = []

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
                if label == "stderr":
                    self._stderr_tail.append(text)
                    if len(self._stderr_tail) > 200:
                        self._stderr_tail.pop(0)

        await asyncio.gather(
            _pump(self._proc.stdout if self._proc else None, "stdout"),
            _pump(self._proc.stderr if self._proc else None, "stderr"),
            return_exceptions=True,
        )

    def _roundtrip(self, request: Any) -> Any:
        """Blocking write+read of one request/response pair (runs in an executor)."""
        write_frame(self._to_worker, request)
        return read_frame(self._from_worker)

    async def _send(self, request: Any, timeout_s: float) -> Any:
        """Send ``request`` and await its reply within ``timeout_s``, serialized.

        On a timeout, SIGKILLs the worker (G2/AC2) and raises
        ``asyncio.TimeoutError``. On any protocol/process failure (worker
        died on its own), raises the underlying exception. Callers build the
        namespace-loss error from these two failure modes.
        """
        loop = asyncio.get_event_loop()
        async with self._lock:
            if not self.is_alive:
                raise EOFError("worker process is not running")
            future = loop.run_in_executor(self._executor, self._roundtrip, request)
            try:
                return await asyncio.wait_for(future, timeout=timeout_s)
            except asyncio.TimeoutError:
                await self._kill_process()
                # The executor thread is still blocked reading from the (now
                # closed) pipe and will finish in the background once it
                # observes EOF; nobody awaits `future` after this point, so
                # retrieve/discard its eventual exception to avoid an
                # "exception was never retrieved" warning at GC time.
                future.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
                raise

    async def _kill_process(self) -> None:
        """SIGKILL the worker (POSIX) / TerminateProcess (Windows, AC16).

        Idempotent and safe to call after the process is already reaped —
        deliberately touches ``self._executor`` ONLY when there's actually
        something to kill/wait for (code-review fix): a self-owned executor
        is shut down at the end of :meth:`kill`, so an unconditional
        post-kill ``wait()`` dispatch here would raise
        ``RuntimeError: cannot schedule new futures after shutdown`` on a
        second call (e.g. `_classify_death()` reached after an external
        `kill()`, or `kill()` called twice).
        """
        if self._proc is None or self._proc.poll() is not None:
            return  # nothing alive to kill, or already reaped
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self._executor, self._proc.kill)
        await loop.run_in_executor(self._executor, self._proc.wait)

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
            ``"memory"`` when stderr hints at memory pressure, else
            ``"crash"`` (the generic fallback — segfault, uncaught native
            abort, protocol desync, etc.).
        """
        # `_kill_process()` is idempotent/safe here whether the process is
        # still alive (kills it) or already reaped (no-op, no executor use).
        await self._kill_process()
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
            response: ExecResult = await self._send(request, deadline_s)
        except asyncio.TimeoutError:
            return self._build_loss_error("timeout", f"execution exceeded deadline_ms={self._config.deadline_ms}")
        except (EOFError, OSError, ValueError) as exc:
            cause = await self._classify_death()
            return self._build_loss_error(cause, str(exc))

        if response.new_vars:
            self.known_vars = sorted(set(self.known_vars) | set(response.new_vars))
        if response.status:
            return {"status": response.status, "result": response.result, "error": response.error}
        return response.output

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
            await self._send(request, timeout_s=30.0)
        finally:
            if encoded.shm_name is not None:
                # Host owns the block's lifecycle: unlink only now that the
                # worker has ack'd (read + closed its handle) via the
                # response awaited above.
                await loop.run_in_executor(self._executor, unlink_shm, encoded.shm_name)
        self.known_vars = sorted(set(self.known_vars) | {name})

    async def get_var(self, name: str) -> Any:
        """Read one namespace variable from the worker."""
        response: ValueResponse = await self._send(GetVarRequest(name=name), 5.0)
        return decode_value(response.value)

    async def set_var(self, name: str, value: Any) -> None:
        """Write one namespace variable in the worker."""
        await self._send(SetVarRequest(name=name, value=encode_value(value)), 5.0)
        self.known_vars = sorted(set(self.known_vars) | {name})

    async def list_vars(self) -> list[str]:
        """Refresh and return the cheap, names-only namespace shadow."""
        response: ListNsResponse = await self._send(ListNsRequest(), 5.0)
        self.known_vars = sorted(response.names)
        return self.known_vars

    async def snapshot(self) -> dict[str, Any]:
        """Return a serializable dump of the whole worker namespace."""
        response: SnapshotResponse = await self._send(SnapshotRequest(), 10.0)
        return {name: decode_value(value) for name, value in response.data.items()}

    async def reset(self) -> None:
        """Reset the worker's REPL environment (equivalent to `reset_environment()`)."""
        await self._send(ResetRequest(), 30.0)
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
        # `_stdio_executor` is always self-owned (see `__init__`) — always
        # shut it down here, regardless of `_owns_executor`.
        self._stdio_executor.shutdown(wait=False, cancel_futures=True)
