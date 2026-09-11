"""Warm asyncio.subprocess worker pool for tiers 1-2 (FEAT-459 / M9).

Implements parrot.eval.sandbox.base.SandboxProvider — the ONLY real
pooling implementation in the codebase; NoopSandboxProvider (base.py:259)
is a no-op reference, not pooling logic to extend. All sizing knobs are
configurable with defaults from spec §7 (OQ-6).

NOTE on network isolation: this module's job is process lifecycle and
scheduling, not kernel-level sandboxing. "no network namespace" for tiers
1-2 (spec §2) is an infra/deployment property (e.g. a restricted
execution user, seccomp profile, or cgroup) layered UNDER this pool, not
something asyncio.subprocess enforces by itself. Tiers 3-4's actual kernel
isolation is gVisor (TASK-3170) — this pool is deliberately the
CHEAPER, un-containerised path for the two tiers that need no such
isolation.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from parrot.eval.sandbox.base import ExecResult, Sandbox, SandboxProvider, SandboxSpec

if TYPE_CHECKING:
    from parrot_formdesigner.core.snippets import SandboxContext, SandboxOutcome

logger = logging.getLogger(__name__)


class PoolExhaustedError(Exception):
    """Raised by acquire() when no worker becomes available within the queue timeout."""


class ColdStartTimeoutError(Exception):
    """Raised when spawning a fresh worker exceeds cold_start_timeout_ms."""


class WorkerDiedError(Exception):
    """Raised when a worker subprocess exits unexpectedly."""


@dataclass
class _PooledWorker:
    """Internal bookkeeping for a pooled worker subprocess."""

    process: asyncio.subprocess.Process
    spawned_at: float = field(default_factory=time.monotonic)
    invocation_count: int = 0
    healthy: bool = True


class _SubprocessSandbox(Sandbox):
    """Sandbox ABC wrapper around one _PooledWorker."""

    def __init__(self, worker: _PooledWorker, pool: "SubprocessWorkerPool") -> None:
        self._worker = worker
        self._pool = pool

    async def __aenter__(self) -> "Sandbox":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._pool.release(self)

    async def reset(self, seed_state: dict[str, Any] | None) -> None:
        # Tiers 1-2 workers are stateless per invocation (the
        # whole point of a SandboxContext/SandboxOutcome round trip per
        # call) — this is a no-op per the SandboxProvider contract.
        pass

    async def health_check(self) -> bool:
        # Verify the worker process is still alive (returncode is None).
        # A more sophisticated implementation could exchange a lightweight
        # ping frame, but for tiers 1-2 a simple process-alive check suffices.
        if self._worker.process.returncode is not None:
            self._worker.healthy = False
            return False
        return self._worker.healthy

    async def snapshot(self) -> dict[str, Any]:
        # Tiers 1-2 have no persistent state to snapshot.
        return {}

    async def exec(self, cmd: list[str]) -> ExecResult:
        # This ABC method is for the eval-harness use case
        # (running shell commands inside a sandbox). The forms use case
        # instead uses run_snippet() which sends a SandboxContext frame
        # and reads a SandboxOutcome frame via the protocol.
        raise NotImplementedError("Use run_snippet() for forms use case; exec() is for eval harness.")

    async def run_snippet(self, ctx: "SandboxContext") -> "SandboxOutcome":
        """Run a snippet with the given context and return the outcome.

        This is the forms-specific method that uses the protocol to
        communicate with the worker subprocess.
        """
        # Import here to avoid circular imports
        from parrot_formdesigner.core.snippets import SandboxOutcome
        from parrot_formdesigner.services.sandbox.protocol import (
            decode_frame,
            encode_frame,
        )

        worker = self._worker
        process = worker.process

        # process.stdin/stdout are only None if the subprocess was spawned
        # without PIPE for that stream — this pool always requests both
        # (see _create_worker), so a None here means the worker died
        # between creation and use.
        if process.stdin is None or process.stdout is None:
            raise WorkerDiedError(f"worker {worker!r} has no stdin/stdout pipe — process died")

        # Send the context to the worker
        process.stdin.write(encode_frame(ctx))
        await process.stdin.drain()

        # Read the outcome from the worker
        outcome = await decode_frame(process.stdout)
        if not isinstance(outcome, SandboxOutcome):
            raise WorkerDiedError(f"Worker returned unexpected frame type: {type(outcome).__name__}")

        # Note: invocation_count is incremented in release() when the
        # sandbox is returned to the pool, not here.
        return outcome


class SubprocessWorkerPool(SandboxProvider):
    """Warm-pooled asyncio.subprocess workers for CapabilityTier PURE/HELPERS."""

    def __init__(
        self,
        *,
        tier12_pool_size: int = 4,
        recycle_after_invocations: int = 500,
        recycle_after_seconds: int = 3600,
        acquire_queue_timeout_ms: int = 2000,
        max_queue_depth: int = 32,
        health_check_interval_s: int = 30,
        cold_start_timeout_ms: int = 5000,
    ) -> None:
        """All defaults per spec §7 OQ-6 pool sizing table.

        Args:
            tier12_pool_size: Warm workers held per process. Under
                gunicorn -w N the REAL total is N * this value — size
                against that, not this number alone (spec §7 note).
            recycle_after_invocations: Retire a worker after this many
                completed invocations.
            recycle_after_seconds: Retire a worker after this much wall
                time regardless of invocation count.
            acquire_queue_timeout_ms: Maximum time acquire() waits for a
                worker before raising PoolExhaustedError. NEVER unbounded.
            max_queue_depth: Beyond this many queued acquire() callers,
                fail fast instead of growing the queue.
            health_check_interval_s: Interval for the background health
                sweep that detects poisoned idle workers.
            cold_start_timeout_ms: Maximum time to spawn a fresh worker
                when the pool is empty and under `tier12_pool_size`.
        """
        self._tier12_pool_size = tier12_pool_size
        self._recycle_after_invocations = recycle_after_invocations
        self._recycle_after_seconds = recycle_after_seconds
        self._acquire_queue_timeout_ms = acquire_queue_timeout_ms
        self._max_queue_depth = max_queue_depth
        self._health_check_interval_s = health_check_interval_s
        self._cold_start_timeout_ms = cold_start_timeout_ms
        self._idle: asyncio.Queue[_PooledWorker] = asyncio.Queue(maxsize=tier12_pool_size)
        self._waiters = 0
        self._live_count = 0
        self._health_check_task: asyncio.Task | None = None
        self._shutdown = False
        self.logger = logger

    async def _spawn_worker(self) -> _PooledWorker:
        """Start one fresh worker subprocess, bounded by cold_start_timeout_ms.

        Raises:
            ColdStartTimeoutError: spawn exceeded cold_start_timeout_ms.
            WorkerDiedError: worker exited during startup.
        """
        # NOTE: The worker entrypoint script is currently unspecified
        # (see task Scope's noted gap). This implementation uses a
        # placeholder command that will need to be replaced once the
        # worker entrypoint is defined (likely in a follow-up task).
        # For now, we spawn a simple Python interpreter that reads from
        # stdin and writes to stdout using the protocol.
        try:
            process = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    sys.executable,
                    "-c",
                    _WORKER_PLACEHOLDER_SCRIPT,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                ),
                timeout=self._cold_start_timeout_ms / 1000,
            )
        except asyncio.TimeoutError:
            raise ColdStartTimeoutError(f"Worker spawn exceeded cold_start_timeout_ms={self._cold_start_timeout_ms}")

        # Check if the process already died
        if process.returncode is not None:
            raise WorkerDiedError(f"Worker exited during startup with code {process.returncode}")

        self._live_count += 1
        return _PooledWorker(process=process)

    def _needs_recycle(self, worker: _PooledWorker) -> bool:
        """Check if a worker should be recycled."""
        age_s = time.monotonic() - worker.spawned_at
        return worker.invocation_count >= self._recycle_after_invocations or age_s >= self._recycle_after_seconds

    async def _recycle_worker(self, worker: _PooledWorker) -> _PooledWorker:
        """Terminate an old worker and spawn a fresh one."""
        self.logger.debug(
            "Recycling worker (invocations=%d, age=%.1fs)",
            worker.invocation_count,
            time.monotonic() - worker.spawned_at,
        )
        worker.process.terminate()
        try:
            await asyncio.wait_for(worker.process.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            worker.process.kill()
            await worker.process.wait()
        self._live_count -= 1
        return await self._spawn_worker()

    async def acquire(self, spec: SandboxSpec) -> Sandbox:
        """Acquire a healthy worker, spawning fresh if the pool has room.

        Raises:
            PoolExhaustedError: no worker became available within
                acquire_queue_timeout_ms, AND max_queue_depth callers are
                already waiting.
        """
        if self._shutdown:
            raise RuntimeError("Pool is shut down")

        if self._waiters >= self._max_queue_depth:
            raise PoolExhaustedError(
                f"acquire queue depth ({self._waiters}) already at max_queue_depth=" f"{self._max_queue_depth}"
            )

        self._waiters += 1
        try:
            # Fast path: try to get an idle worker immediately
            try:
                worker = self._idle.get_nowait()
            except asyncio.QueueEmpty:
                # Pool is empty - spawn fresh if we have room
                if self._live_count < self._tier12_pool_size:
                    worker = await self._spawn_worker()
                else:
                    # Wait for a worker to become available
                    timeout_s = self._acquire_queue_timeout_ms / 1000
                    try:
                        worker = await asyncio.wait_for(self._idle.get(), timeout=timeout_s)
                    except asyncio.TimeoutError:
                        raise PoolExhaustedError(
                            f"No worker available within " f"acquire_queue_timeout_ms={self._acquire_queue_timeout_ms}"
                        )

            # Check if the worker needs recycling before handing it out
            if self._needs_recycle(worker):
                # Recycle: terminate old and spawn new
                self._live_count -= 1
                worker = await self._recycle_worker(worker)

            # Check worker health
            if not worker.healthy or worker.process.returncode is not None:
                self._live_count -= 1
                worker = await self._recycle_worker(worker)

            return _SubprocessSandbox(worker, self)

        finally:
            self._waiters -= 1

    async def release(self, sandbox: Sandbox) -> None:
        """Return a worker to the idle queue, or recycle/discard it first."""
        if not isinstance(sandbox, _SubprocessSandbox):
            self.logger.warning("release() called with non-_SubprocessSandbox: %s", type(sandbox).__name__)
            return

        worker = sandbox._worker

        # Check if worker is still healthy
        if worker.process.returncode is not None:
            self.logger.warning("Worker died during use (exit code: %s)", worker.process.returncode)
            self._live_count -= 1
            return

        # Increment invocation count for this completed use cycle
        worker.invocation_count += 1

        # Check if worker needs recycling
        if self._needs_recycle(worker):
            self.logger.debug("Worker needs recycling after %d invocations", worker.invocation_count)
            self._live_count -= 1
            # Recycle asynchronously (don't block the release)
            try:
                await self._recycle_worker(worker)
            except Exception as e:
                self.logger.error("Failed to recycle worker: %s", e)
            return

        # Return worker to idle pool
        try:
            self._idle.put_nowait(worker)
        except asyncio.QueueFull:
            # Pool is full - discard this worker
            self.logger.debug("Idle pool full, discarding worker")
            self._live_count -= 1
            worker.process.terminate()
            try:
                await asyncio.wait_for(worker.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                worker.process.kill()
                await worker.process.wait()

    async def _health_check_sweep(self) -> None:
        """Periodic health check sweep for idle workers."""
        while not self._shutdown:
            try:
                await asyncio.sleep(self._health_check_interval_s)
                await self._perform_health_check()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Health check sweep error: %s", e)

    async def _perform_health_check(self) -> None:
        """Check all idle workers and replace unhealthy ones."""
        # Drain the idle queue, check each worker, put back if healthy
        workers = []
        while True:
            try:
                worker = self._idle.get_nowait()
                workers.append(worker)
            except asyncio.QueueEmpty:
                break

        for worker in workers:
            if worker.process.returncode is not None:
                # Worker died
                self.logger.warning("Health check: worker died (exit code: %s)", worker.process.returncode)
                self._live_count -= 1
                # Spawn replacement
                try:
                    new_worker = await self._spawn_worker()
                    self._idle.put_nowait(new_worker)
                except Exception as e:
                    self.logger.error("Failed to spawn replacement worker: %s", e)
            else:
                # Worker is alive - put back in queue
                self._idle.put_nowait(worker)

    async def start_health_checks(self) -> None:
        """Start the background health check task."""
        if self._health_check_task is None:
            self._health_check_task = asyncio.create_task(self._health_check_sweep())

    async def stop_health_checks(self) -> None:
        """Stop the background health check task."""
        if self._health_check_task is not None:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
            self._health_check_task = None

    async def shutdown(self) -> None:
        """Gracefully shut down the pool."""
        self._shutdown = True
        await self.stop_health_checks()

        # Terminate all idle workers
        while True:
            try:
                worker = self._idle.get_nowait()
                worker.process.terminate()
                self._live_count -= 1
            except asyncio.QueueEmpty:
                break

        # Wait for all workers to terminate
        # Note: we don't track in-use workers, so this is best-effort
        await asyncio.sleep(0.5)


# Placeholder worker script - this will be replaced once the actual
# worker entrypoint is defined (see task Scope's noted gap)
_WORKER_PLACEHOLDER_SCRIPT = """
import sys
import json
import struct

# Simple placeholder that echoes back what it receives
# This will be replaced with actual snippet execution logic
LENGTH_HEADER_FORMAT = ">I"
LENGTH_HEADER_SIZE = struct.calcsize(LENGTH_HEADER_FORMAT)

while True:
    try:
        # Read frame length
        header = sys.stdin.buffer.read(LENGTH_HEADER_SIZE)
        if not header:
            break
        (length,) = struct.unpack(LENGTH_HEADER_FORMAT, header)

        # Read frame body
        body = sys.stdin.buffer.read(length)
        if not body:
            break

        # Echo back the same frame (placeholder behavior)
        sys.stdout.buffer.write(header + body)
        sys.stdout.buffer.flush()
    except Exception:
        break
"""
