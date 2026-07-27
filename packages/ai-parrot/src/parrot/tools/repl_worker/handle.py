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
import logging
import os
import subprocess
import sys
from typing import Any, BinaryIO, Optional

from .protocol import (
    ExecRequest,
    ExecResult,
    GetVarRequest,
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

    def __init__(self, config: Optional[WorkerConfig] = None, output_dir: Optional[str] = None):
        """Initialize the handle (does not spawn — call :meth:`start`).

        Args:
            config: Resource-limit / lifecycle configuration for the worker.
                Defaults to ``WorkerConfig()``.
            output_dir: Shared output directory for plots/reports, visible
                to both host and worker.
        """
        self._config = config or WorkerConfig()
        self._output_dir = output_dir
        self._proc: Optional[subprocess.Popen] = None
        self._to_worker: Optional[BinaryIO] = None
        self._from_worker: Optional[BinaryIO] = None
        self._lock = asyncio.Lock()
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
        if self._output_dir is not None:
            argv.append(self._output_dir)

        def _spawn() -> subprocess.Popen:
            return subprocess.Popen(  # noqa: S603 - trusted, fixed argv; spawn-only per spec
                argv,
                pass_fds=(to_worker_r, from_worker_w),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self._proc = await loop.run_in_executor(None, _spawn)
        # The parent doesn't need the child's ends of either pipe.
        os.close(to_worker_r)
        os.close(from_worker_w)
        self._to_worker = os.fdopen(to_worker_w, "wb", buffering=0)
        self._from_worker = os.fdopen(from_worker_r, "rb", buffering=0)
        logger.debug("WorkerHandle: spawned worker pid=%s", self._proc.pid)

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
            future = loop.run_in_executor(None, self._roundtrip, request)
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
        """SIGKILL the worker (POSIX) / TerminateProcess (Windows, AC16)."""
        if self._proc is None:
            return
        loop = asyncio.get_event_loop()
        if self._proc.poll() is None:
            await loop.run_in_executor(None, self._proc.kill)
        await loop.run_in_executor(None, self._proc.wait)

    async def _classify_death(self) -> str:
        """Best-effort classification of an unexpected worker death.

        Returns:
            ``"memory"`` when stderr hints at memory pressure, else
            ``"crash"`` (the generic fallback — segfault, uncaught native
            abort, etc.).
        """
        loop = asyncio.get_event_loop()
        if self._proc is not None and self._proc.poll() is None:
            await loop.run_in_executor(None, self._proc.wait)
        stderr_text = ""
        if self._proc is not None and self._proc.stderr is not None:
            raw = await loop.run_in_executor(None, self._proc.stderr.read)
            stderr_text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else (raw or "")
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
        """Inject a DataFrame into the worker namespace.

        Raises:
            NotImplementedError: Arrow IPC / shared-memory transport lands
                in TASK-1945 — not in scope for this task.
        """
        raise NotImplementedError("inject_dataframe: Arrow IPC transport is TASK-1945")

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
        """Terminate the worker process and close the control pipes."""
        await self._kill_process()
        for stream in (self._to_worker, self._from_worker):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        self._to_worker = None
        self._from_worker = None
