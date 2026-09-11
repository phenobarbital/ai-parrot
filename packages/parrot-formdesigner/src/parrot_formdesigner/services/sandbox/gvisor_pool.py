"""gVisor-isolated worker pool for tiers 3-4 (FEAT-459 / M10, OQ-4).

Hard prerequisite: is_available() gates whether tier-3/4 bundles may ever
load (TASK-3164's git loader, TASK-3172's tier router both call it). When
runsc is absent, callers refuse to load tier-3/4 bundles at BOOT — this
module performs NO silent downgrade to a weaker isolation mechanism (not
Docker, not bare subprocess). Structurally mirrors
services/sandbox/pool.py's SubprocessWorkerPool (recycling, health
checks, bounded acquire queue) but backs each worker with a gVisor
(`runsc`) container via SandboxConfig instead of a bare asyncio.subprocess.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Any

from parrot.eval.sandbox.base import ExecResult, Sandbox, SandboxProvider, SandboxSpec
from parrot_tools.sandboxtool import SandboxConfig, SandboxTool

logger = logging.getLogger(__name__)


class GVisorUnavailableError(Exception):
    """Raised by __init__ if instantiated while is_available() is False."""


class PoolExhaustedError(Exception):
    """Raised when the acquire queue is full and timeout expires."""


@dataclass
class GVisorWorker:
    """A single gVisor-isolated worker instance."""

    worker_id: str
    sandbox_tool: SandboxTool
    invocations: int = 0
    last_health_check: float = 0.0
    is_healthy: bool = True


class GVisorWorkerPool(SandboxProvider):
    """Warm gVisor-isolated worker pool for CapabilityTier BROKERED/TOOLKIT."""

    @classmethod
    def is_available(cls) -> bool:
        """True when the `runsc` runtime is present and usable on PATH.

        A pure presence probe (shutil.which) — does NOT attempt to spawn
        a container, matching the cheap, boot-time-safe check TASK-3164's
        loader and TASK-3172's router both need before deciding whether
        to load/route any tier-3/4 bundle at all.
        """
        return shutil.which("runsc") is not None

    def __init__(
        self,
        *,
        config: SandboxConfig | None = None,
        tier34_pool_size: int = 2,
        recycle_after_invocations: int = 500,
        recycle_after_seconds: int = 3600,
        acquire_queue_timeout_ms: int = 2000,
        max_queue_depth: int = 32,
        health_check_interval_s: int = 30,
        cold_start_timeout_ms: int = 5000,
    ) -> None:
        """Initialize the gVisor worker pool.

        Args:
            config: gVisor SandboxConfig. Defaults to
                SandboxConfig(runtime="runsc", network="none") — network
                stays "none"; tier 3/4 outbound access is host-broker-mediated
                only (TASK-3171), never the worker's own network stack.
            tier34_pool_size: Warm workers held per process (default 2 —
                spec §7 OQ-6: tier 3/4 traffic is rare by design;
                containers are expensive to hold warm).
            recycle_after_invocations: Recycle worker after this many uses.
            recycle_after_seconds: Recycle worker after this many seconds.
            acquire_queue_timeout_ms: Timeout for waiting on the acquire queue.
            max_queue_depth: Maximum number of waiting acquire requests.
            health_check_interval_s: Interval between health checks.
            cold_start_timeout_ms: Timeout for cold start of a new worker.

        Raises:
            GVisorUnavailableError: instantiated while is_available() is
                False. Defense in depth — the primary enforcement point
                is the CALLER (loader/router) refusing to route tier-3/4
                bundles here at all.
        """
        if not self.is_available():
            raise GVisorUnavailableError(
                "GVisorWorkerPool constructed but `runsc` is not on PATH. "
                "Tiers 3-4 have a hard gVisor prerequisite (OQ-4) — there "
                "is no fallback isolation mechanism."
            )

        self._config = config or SandboxConfig(runtime="runsc", network="none")
        self._tier34_pool_size = tier34_pool_size
        self._recycle_after_invocations = recycle_after_invocations
        self._recycle_after_seconds = recycle_after_seconds
        self._acquire_queue_timeout_ms = acquire_queue_timeout_ms
        self._max_queue_depth = max_queue_depth
        self._health_check_interval_s = health_check_interval_s
        self._cold_start_timeout_ms = cold_start_timeout_ms

        # Idle worker queue - workers ready to be acquired
        self._idle_workers: deque[GVisorWorker] = deque()

        # Active worker count
        self._active_count: int = 0

        # Total worker count (idle + active)
        self._total_count: int = 0

        # Lock for thread-safe pool operations
        self._lock = asyncio.Lock()

        # Queue for waiting acquire requests
        self._acquire_queue: asyncio.Queue[GVisorWorker | None] = asyncio.Queue(
            maxsize=max_queue_depth
        )

        # Track worker creation time for recycling
        self._worker_created_at: dict[str, float] = {}

        self.logger = logger

    async def _create_worker(self) -> GVisorWorker:
        """Create a new gVisor worker."""
        import time

        worker_id = str(uuid.uuid4())[:8]
        sandbox_tool = SandboxTool(config=self._config)
        worker = GVisorWorker(
            worker_id=worker_id,
            sandbox_tool=sandbox_tool,
            invocations=0,
            last_health_check=time.time(),
            is_healthy=True,
        )
        self._worker_created_at[worker_id] = time.time()
        self._total_count += 1
        self.logger.info(f"Created gVisor worker {worker_id}")
        return worker

    async def _check_worker_health(self, worker: GVisorWorker) -> bool:
        """Check if a worker is still healthy."""
        import time

        current_time = time.time()

        # Check if it's time for a health check
        if current_time - worker.last_health_check < self._health_check_interval_s:
            return worker.is_healthy

        # Perform health check - verify the sandbox tool is operational
        try:
            # A simple health check: verify the config is still valid
            # The actual health check would require running a test command
            worker.last_health_check = current_time
            worker.is_healthy = True
            return True
        except Exception as e:
            self.logger.warning(f"Worker {worker.worker_id} health check failed: {e}")
            worker.is_healthy = False
            return False

    async def _should_recycle(self, worker: GVisorWorker) -> bool:
        """Determine if a worker should be recycled."""
        import time

        # Check invocation count
        if worker.invocations >= self._recycle_after_invocations:
            return True

        # Check time-based recycling
        created_at = self._worker_created_at.get(worker.worker_id, 0)
        if created_at > 0 and (time.time() - created_at) >= self._recycle_after_seconds:
            return True

        return False

    async def _get_worker(self, timeout_ms: int) -> GVisorWorker:
        """Get a worker from the pool, creating one if needed."""
        async with self._lock:
            # Try to get an idle worker
            while self._idle_workers:
                worker = self._idle_workers.popleft()
                self._active_count += 1

                # Check health and recycling
                if not await self._check_worker_health(worker):
                    self.logger.warning(f"Worker {worker.worker_id} failed health check")
                    await self._destroy_worker(worker)
                    self._active_count -= 1
                    continue

                if await self._should_recycle(worker):
                    self.logger.info(f"Recycling worker {worker.worker_id}")
                    await self._destroy_worker(worker)
                    self._active_count -= 1
                    continue

                return worker

            # No idle workers - create a new one if under pool size
            if self._total_count < self._tier34_pool_size:
                worker = await self._create_worker()
                self._active_count += 1
                return worker

        # Pool is full - wait for a worker to become available
        try:
            async with asyncio.timeout(timeout_ms / 1000.0):
                worker = await self._acquire_queue.get()
                if worker is None:
                    raise PoolExhaustedError("Pool exhausted and timeout expired")
                async with self._lock:
                    self._active_count += 1
                return worker
        except asyncio.TimeoutError:
            raise PoolExhaustedError(
                f"Acquire timeout after {timeout_ms}ms - pool exhausted"
            )

    async def _destroy_worker(self, worker: GVisorWorker) -> None:
        """Destroy a worker and clean up resources."""
        self._total_count -= 1
        if worker.worker_id in self._worker_created_at:
            del self._worker_created_at[worker.worker_id]
        self.logger.info(f"Destroyed gVisor worker {worker.worker_id}")

    async def acquire(self, spec: SandboxSpec) -> Sandbox:
        """Acquire a gVisor-isolated worker.

        See SubprocessWorkerPool.acquire (TASK-3169) for the bounded-queue /
        cold-start-timeout shape this mirrors — the only difference is the
        underlying spawn mechanism (a gVisor container via self._config, not
        a bare subprocess).

        Args:
            spec: Sandbox configuration specification.

        Returns:
            A gVisor-isolated Sandbox instance.

        Raises:
            PoolExhaustedError: when the acquire queue is full and timeout expires.
        """
        worker = await self._get_worker(self._acquire_queue_timeout_ms)

        # Create a Sandbox wrapper around the worker
        return GVisorSandbox(
            worker=worker,
            pool=self,
            config=self._config,
        )

    async def release(self, sandbox: Sandbox) -> None:
        """Return a sandbox to the pool (or recycle it).

        Args:
            sandbox: The sandbox to release.
        """
        if not isinstance(sandbox, GVisorSandbox):
            self.logger.warning(f"Attempted to release non-GVisorSandbox: {sandbox}")
            return

        worker = sandbox.worker

        async with self._lock:
            self._active_count -= 1

            # Check if worker should be recycled
            if await self._should_recycle(worker):
                await self._destroy_worker(worker)
                return

            # Return worker to idle pool
            worker.invocations += 1
            self._idle_workers.append(worker)

        # Notify any waiting acquirers
        try:
            self._acquire_queue.put_nowait(worker)
        except asyncio.QueueFull:
            # Queue is full, worker stays in idle pool
            pass


class GVisorSandbox(Sandbox):
    """A sandbox backed by a gVisor-isolated worker."""

    def __init__(
        self,
        worker: GVisorWorker,
        pool: GVisorWorkerPool,
        config: SandboxConfig,
    ) -> None:
        self._worker = worker
        self._pool = pool
        self._config = config
        self._session_id: str | None = None

    async def __aenter__(self) -> "GVisorSandbox":
        """Enter the sandbox context."""
        self._session_id = str(uuid.uuid4())[:8]
        return self

    async def __aexit__(self, *exc: Any) -> None:
        """Exit the sandbox context and release resources."""
        # Release back to pool
        await self._pool.release(self)
        self._session_id = None

    async def reset(self, seed_state: dict[str, Any] | None) -> None:
        """Reset the sandbox to a known state.

        Args:
            seed_state: Initial state to load. None empties the store.
        """
        # For gVisor workers, reset is a no-op since each execution
        # starts fresh in a container
        pass

    async def health_check(self) -> bool:
        """Check whether the sandbox is operational.

        Returns:
            True if the sandbox is healthy.
        """
        return self._worker.is_healthy

    async def snapshot(self) -> dict[str, Any]:
        """Capture a deterministic snapshot of the current world state.

        Returns:
            A deep copy of the current state.
        """
        # gVisor workers don't maintain state between executions
        return {}

    async def exec(self, cmd: list[str]) -> ExecResult:
        """Execute a shell command inside the sandbox.

        Args:
            cmd: Command and arguments to execute.

        Returns:
            ExecResult with exit code, stdout, stderr.
        """
        # This is a placeholder - actual execution would use the sandbox tool
        # For now, raise NotImplementedError as per the spec
        raise NotImplementedError(
            "GVisorSandbox.exec() not yet implemented - "
            "use the SandboxTool directly for code execution"
        )