"""Worker pool lifecycle: prewarm, TTL eviction, ceiling, crash restart (FEAT-380 Module 4).

``WorkerPool`` sits on top of ``WorkerHandle`` (TASK-1941) and owns
everything about *which* worker serves *which* session, and for how long:

- **Session mapping** (G7): one worker per ``session_id``.
- **Prewarm pool (v1, G4/AC10)**: ``WorkerConfig.prewarm_pool_size`` workers
  started in the background with pandas/numpy/matplotlib already imported,
  assigned on demand instead of paying the 1-3s import cost on a session's
  first call.
- **Concurrency ceiling** (AC12): ``max_workers`` if set, else
  ``max(4, cpu_count())`` capped at 16. At the ceiling, :meth:`acquire`
  raises :class:`WorkerPoolExhaustedError` immediately — no queueing.
- **Idle TTL** (AC12): a session's worker idle longer than
  ``idle_ttl_seconds`` is killed and unmapped; a later ``acquire`` for that
  session spawns fresh (the namespace is intentionally gone).
- **Crash restart**: a session whose worker died gets a fresh one on its
  next ``acquire`` — the *interrupted* call's namespace-loss error was
  already reported by ``WorkerHandle.execute()`` at the time of the crash;
  this class's job is to make the session usable again, not to resurface
  that error a second time.
- **Orphan reaping** (AC12): :meth:`shutdown` kills every worker (bound and
  prewarmed) — zero live workers survive a clean host shutdown on any
  platform. `PR_SET_PDEATHSIG` (Linux-only, applied worker-side in
  ``worker.py``) is the portable backstop for an UNCLEAN host death.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import logging
import os
import time
from typing import Any, Optional

from .handle import WorkerBootstrapError, WorkerHandle
from .protocol import WorkerConfig

logger = logging.getLogger(__name__)

#: Absolute cap on the effective ceiling, regardless of `cpu_count()`.
_CEILING_CAP = 16
#: Sliding window (seconds) over which session worker restarts are counted
#: before the pool calls it a restart loop (FEAT-500 G5/AC8).
_RESTART_WINDOW_S = 60.0
#: Restarts within `_RESTART_WINDOW_S` that trigger the restart-loop warning.
_RESTART_LOOP_THRESHOLD = 3
#: Floor on the effective ceiling when `max_workers` is left at its
#: auto-detect default (0).
_CEILING_FLOOR = 4


class WorkerPoolExhaustedError(RuntimeError):
    """Raised by :meth:`WorkerPool.acquire` when the worker ceiling is reached.

    Per spec (AC12): the pool never queues past the ceiling — it rejects
    immediately with a clear, catchable error naming the current limit.
    """


class WorkerPool:
    """Prewarmed pool + lifecycle (TTL eviction, ceiling, orphan reaping)."""

    def __init__(
        self,
        config: Optional[WorkerConfig] = None,
        output_dir: Optional[str] = None,
        repl_kwargs: Optional[dict[str, Any]] = None,
        executor: Optional[concurrent.futures.Executor] = None,
    ):
        """Initialize the pool (does not spawn anything until first use).

        Args:
            config: Resource-limit / lifecycle configuration shared by every
                worker this pool spawns. Defaults to ``WorkerConfig()``.
            output_dir: Shared output directory for plots/reports, passed to
                every spawned :class:`WorkerHandle`.
            repl_kwargs: Extra ``PythonREPLTool`` constructor kwargs mirrored
                on every worker's internal instance (e.g.
                ``return_plot_as_base64``, TASK-1943).
            executor: Dedicated executor passed through to every
                :class:`WorkerHandle` this pool spawns (code-review fix,
                AC1). When ``None`` (default), each spawned handle creates
                its own small self-owned executor instead — either way, no
                worker's blocking I/O ever touches the event loop's shared
                default executor. Pass ``PythonREPLTool._repl_executor``
                here to route an entire session's worker I/O through one
                specific dedicated pool.
        """
        self._config = config or WorkerConfig()
        self._output_dir = output_dir
        self._repl_kwargs = repl_kwargs or {}
        self._executor = executor
        self._ceiling = self._effective_ceiling(self._config)

        self._sessions: dict[str, WorkerHandle] = {}
        self._last_active: dict[str, float] = {}
        self._prewarmed: list[WorkerHandle] = []

        self._lock = asyncio.Lock()
        #: Serializes `_top_up_prewarmed()` so at most one "spawn up to
        #: prewarm_pool_size" loop runs at a time (code-review fix): without
        #: this, concurrent invocations (one per `acquire()` call) could each
        #: observe "under ceiling" before any of them recorded its spawn,
        #: transiently overshooting `max_workers`.
        self._topup_lock = asyncio.Lock()
        #: Background tasks this pool has fired (currently just top-up
        #: sweeps) — tracked so `shutdown()` can cancel/await them instead
        #: of leaving them to finish (and possibly append a freshly-spawned,
        #: now-orphaned worker) after shutdown already cleared everything.
        self._background_tasks: set[asyncio.Task] = set()
        self._maintenance_task: Optional[asyncio.Task] = None
        self._started = False
        #: Monotonic timestamps of recent worker restarts per session
        #: (FEAT-500 G5): a session that keeps burning workers is logged as
        #: such instead of silently consuming spares on a 5 s grid. Pruned to
        #: `_RESTART_WINDOW_S` on every read/write.
        self._restarts: dict[str, list[float]] = {}

    @staticmethod
    def _effective_ceiling(config: WorkerConfig) -> int:
        """Resolve `max_workers` per spec: explicit value, else auto-detected."""
        if config.max_workers > 0:
            return config.max_workers
        return min(max(_CEILING_FLOOR, os.cpu_count() or _CEILING_FLOOR), _CEILING_CAP)

    async def _ensure_started(self) -> None:
        """Lazily kick off the maintenance loop and background prewarming.

        Deliberately non-blocking: prewarming runs as a background task so
        the FIRST caller into the pool is never made to wait for it. Later
        callers benefit once the background task has had time to finish.
        """
        if self._started:
            return
        self._started = True
        loop = asyncio.get_event_loop()
        self._maintenance_task = loop.create_task(self._maintenance_loop())
        self._track_background(self._top_up_prewarmed())

    def _track_background(self, coro) -> asyncio.Task:
        """Fire ``coro`` as a background task, tracked for `shutdown()`."""
        task = asyncio.get_event_loop().create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    async def _spawn_handle(self) -> WorkerHandle:
        handle = WorkerHandle(
            self._config, output_dir=self._output_dir, repl_kwargs=self._repl_kwargs, executor=self._executor
        )
        await handle.start()
        return handle

    async def _top_up_prewarmed(self) -> None:
        """Spawn prewarmed spares up to `prewarm_pool_size`, respecting the ceiling.

        Single-flight (guarded by `self._topup_lock`): if another top-up is
        already running, this call is a no-op — the running one will keep
        going until full anyway. Without this, concurrent invocations could
        each observe "under ceiling" before any of them recorded its own
        spawn, transiently overshooting `max_workers` (code-review fix).
        """
        if self._topup_lock.locked():
            return
        async with self._topup_lock:
            while True:
                async with self._lock:
                    if not self._started:
                        return  # shutdown() ran — stop topping up
                    total = len(self._sessions) + len(self._prewarmed)
                    if len(self._prewarmed) >= self._config.prewarm_pool_size or total >= self._ceiling:
                        return
                handle = None
                try:
                    handle = await self._spawn_handle()
                    # FEAT-500 (G1/AC1): "prewarmed" now means READY. Awaited
                    # deliberately OUTSIDE `self._lock` — it can take up to
                    # `bootstrap_timeout_ms`, and holding the lock that long
                    # would stall every other session's `acquire()`.
                    ready = await handle.wait_ready()
                except asyncio.CancelledError:
                    # `shutdown()` cancels in-flight top-ups, and this handle
                    # has NOT been appended to `_prewarmed` yet — so the
                    # shutdown sweep (which only walks `_sessions` +
                    # `_prewarmed`) can never see it. Kill it here or the
                    # worker process and its readiness task outlive the pool
                    # (AC12). The window is real: `wait_ready()` above can be
                    # awaiting for up to `bootstrap_timeout_ms`.
                    if handle is not None:
                        with contextlib.suppress(Exception):
                            await handle.kill()
                    raise
                except WorkerBootstrapError:
                    logger.exception("WorkerPool: prewarmed worker failed to become ready")
                    # `_await_ready()` already killed it; idempotent, and it
                    # also reaps the pipes/executors.
                    await handle.kill()
                    return
                except Exception:
                    logger.exception("WorkerPool: failed to spawn a prewarmed worker")
                    return
                async with self._lock:
                    # FEAT-500 (code review): the ceiling must be re-checked
                    # HERE, not only before the spawn. The lock was released
                    # for `_spawn_handle()` + `wait_ready()` — a window this
                    # feature widened from a sub-second spawn to up to
                    # `bootstrap_timeout_ms` — and a concurrent `acquire()`
                    # can spawn its own fresh worker off the same stale count
                    # during it. Appending unconditionally then pushes the
                    # pool past `max_workers` (reproduced 3/3 with
                    # `max_workers=1, prewarm_pool_size=1`), breaking the
                    # "never queues past the ceiling" contract that
                    # `WorkerPoolExhaustedError` documents.
                    over_ceiling = len(self._sessions) + len(self._prewarmed) >= self._ceiling
                    if not self._started or over_ceiling:
                        # Either shutdown() ran while we were spawning — this
                        # worker would otherwise be appended into a pool that
                        # already believes it holds zero live workers (an
                        # orphan `shutdown()` never sees) — or the spare
                        # became surplus to the ceiling while it booted.
                        # Either way, kill it instead of adopting it
                        # (code-review fix, AC12).
                        if over_ceiling and self._started:
                            logger.debug(
                                "WorkerPool: discarding a now-ready spare — the ceiling "
                                "(%d) was reached while it was bootstrapping",
                                self._ceiling,
                            )
                        stale_handle = handle
                        handle = None
                    else:
                        self._prewarmed.append(handle)
                if handle is None:
                    await stale_handle.kill()
                    return
                logger.debug(
                    "WorkerPool: prewarmed worker ready (pid=%s, bootstrap_ms=%d, pool size=%d)",
                    ready.pid,
                    ready.bootstrap_ms,
                    len(self._prewarmed),
                )

    async def _maintenance_loop(self) -> None:
        """Background TTL-eviction sweep. Cancelled deterministically by shutdown()."""
        interval = min(5.0, max(1.0, self._config.idle_ttl_seconds / 10))
        try:
            while True:
                await asyncio.sleep(interval)
                await self._evict_idle()
        except asyncio.CancelledError:
            raise

    async def _evict_idle(self) -> None:
        """Kill and unmap any session worker idle longer than `idle_ttl_seconds`."""
        now = time.monotonic()
        to_evict: list[tuple[str, WorkerHandle]] = []
        async with self._lock:
            for session_id, last in list(self._last_active.items()):
                if now - last > self._config.idle_ttl_seconds:
                    handle = self._sessions.pop(session_id, None)
                    self._last_active.pop(session_id, None)
                    # The session is gone; its restart history goes with it
                    # (FEAT-500) so a later session reusing the same id
                    # starts from a clean slate.
                    self._restarts.pop(session_id, None)
                    if handle is not None:
                        to_evict.append((session_id, handle))
        for session_id, handle in to_evict:
            logger.info("WorkerPool: evicting idle session %r (TTL exceeded)", session_id)
            await handle.kill()

    def _record_restart(self, session_id: str, dead: WorkerHandle) -> None:
        """Count one worker restart for ``session_id`` and warn on a loop.

        A session whose worker keeps dying used to burn one spare every few
        seconds in complete silence (FEAT-500 G5). Restarts are kept in a
        `_RESTART_WINDOW_S` sliding window; crossing
        `_RESTART_LOOP_THRESHOLD` logs one warning naming the session and the
        dead worker's exit code / stderr tail so the real cause is visible.

        Called under ``self._lock``.

        Args:
            session_id: The session whose worker just died.
            dead: The dead handle, read for its exit code and stderr tail.
        """
        now = time.monotonic()
        recent = [t for t in self._restarts.get(session_id, []) if now - t <= _RESTART_WINDOW_S]
        recent.append(now)
        self._restarts[session_id] = recent
        if len(recent) < _RESTART_LOOP_THRESHOLD:
            return
        exit_code = dead._proc.returncode if dead._proc is not None else None
        stderr_tail = dead._stderr_tail[-1] if dead._stderr_tail else ""
        logger.warning(
            "WorkerPool: session %r restarted %d times in the last %ds — possible "
            "restart loop (last worker exit code=%s, stderr tail=%r)",
            session_id,
            len(recent),
            int(_RESTART_WINDOW_S),
            exit_code,
            stderr_tail,
        )

    def restart_count(self, session_id: str) -> int:
        """How many times ``session_id``'s worker restarted recently.

        Observability only — nothing in the pool branches on this value.

        Args:
            session_id: The session to report on.

        Returns:
            Restarts within the last `_RESTART_WINDOW_S` seconds (0 if the
            session is unknown or has never restarted).
        """
        now = time.monotonic()
        recent = [t for t in self._restarts.get(session_id, []) if now - t <= _RESTART_WINDOW_S]
        if recent:
            self._restarts[session_id] = recent
        else:
            self._restarts.pop(session_id, None)
        return len(recent)

    async def acquire(self, session_id: str) -> WorkerHandle:
        """Return the live worker for ``session_id``, binding/spawning one if needed.

        Args:
            session_id: Caller-provided session key. One worker per session
                (G7) — the namespace of one session is never reachable from
                another.

        Returns:
            A live :class:`WorkerHandle` bound to ``session_id``.

        Raises:
            WorkerPoolExhaustedError: The concurrency ceiling is reached and
                ``session_id`` doesn't already have a live worker.
        """
        await self._ensure_started()

        async with self._lock:
            existing = self._sessions.get(session_id)
            if existing is not None:
                if existing.is_alive:
                    self._last_active[session_id] = time.monotonic()
                    return existing
                # Worker died since last use (crash/OOM/kill). The interrupted
                # call already got its namespace-loss error from
                # WorkerHandle.execute() at the time of death — our job here
                # is just to make the session usable again.
                logger.warning("WorkerPool: session %r worker is dead, restarting", session_id)
                self._record_restart(session_id, existing)
                self._sessions.pop(session_id, None)
                self._last_active.pop(session_id, None)

            # Ceiling check (code-review fix): only reject when there's
            # neither a prewarmed spare to consume NOR room to spawn a new
            # one. Consuming a prewarmed spare converts it into a session
            # slot — total worker count doesn't change — so it must never
            # be blocked by the ceiling check; only spawning an ADDITIONAL
            # worker can push past the ceiling. The old `total >= ceiling`
            # check (regardless of `self._prewarmed`) rejected sessions
            # even with spares sitting ready to be assigned — e.g.
            # `max_workers=2, prewarm_pool_size=2` rejected the very first
            # session ever acquired.
            if not self._prewarmed:
                total = len(self._sessions) + len(self._prewarmed)
                if total >= self._ceiling:
                    raise WorkerPoolExhaustedError(
                        f"WorkerPool ceiling reached ({self._ceiling} workers); raise "
                        "WorkerConfig.max_workers to allow more concurrent sessions."
                    )

            if self._prewarmed:
                handle = self._prewarmed.pop(0)
                logger.debug("WorkerPool: session %r bound to a prewarmed worker", session_id)
            else:
                handle = await self._spawn_handle()
                logger.debug("WorkerPool: session %r spawned a fresh worker", session_id)

            self._sessions[session_id] = handle
            self._last_active[session_id] = time.monotonic()

        # Top up the prewarmed spares in the background — never block the
        # caller who just successfully acquired a worker.
        self._track_background(self._top_up_prewarmed())
        return handle

    async def release(self, session_id: str) -> None:
        """Mark ``session_id``'s worker as freshly active (resets its TTL clock).

        Args:
            session_id: The session releasing its worker back to idle.
        """
        async with self._lock:
            if session_id in self._sessions:
                self._last_active[session_id] = time.monotonic()

    async def shutdown(self) -> None:
        """Kill every worker (bound and prewarmed) and stop the maintenance loop.

        Leaves zero live workers behind, on any platform (AC12).

        Code-review fix: previously, a `_top_up_prewarmed()` background task
        that was mid-spawn when `shutdown()` ran could finish afterward and
        append its freshly-spawned worker into `self._prewarmed` — a
        process this method had already "finished" cleaning up and would
        never kill. `self._started = False` is now set FIRST (before
        anything else), so any in-flight top-up observes it (under the
        lock, both before AND after its own spawn) and kills its own worker
        instead of resurrecting it into a pool that already reported zero
        live workers. Tracked background tasks are also cancelled/awaited
        as a best-effort head start (cancellation can't interrupt a spawn
        already in flight, hence the belt-and-suspenders `_started` check).
        """
        self._started = False

        if self._maintenance_task is not None:
            self._maintenance_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._maintenance_task
            self._maintenance_task = None

        tasks = list(self._background_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        async with self._lock:
            handles = list(self._sessions.values()) + list(self._prewarmed)
            self._sessions.clear()
            self._last_active.clear()
            self._prewarmed.clear()
            self._restarts.clear()

        for handle in handles:
            await handle.kill()
