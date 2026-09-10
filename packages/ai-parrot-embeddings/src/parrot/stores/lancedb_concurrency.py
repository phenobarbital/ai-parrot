"""Process-shared mutation coordination for one local LanceDB directory.

The asyncio lock here is an in-process optimization only. Cross-process
correctness comes from the coordinator interface TASK-3057's gate proved
sufficient (recorded in ``sdd/state/FEAT-542/lancedb-sdk-contract.md``): a
POSIX ``fcntl.flock`` guarding a critical section, since the pinned SDK
(lancedb==0.38.0) raises NO distinguishable conflict exception for a
colliding-insert race between two independent processes — an in-process
lock and/or catching an exception is not sufficient by itself. The bounded
retry in :meth:`MutationCoordinator.run_mutation` is defense-in-depth for
genuine ``CommitConflict``-raising failures (e.g. lock acquisition
contention), not the primary correctness mechanism.
"""
from __future__ import annotations

import asyncio
import contextlib
import fcntl
import os
import random
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Callable, TypeVar

from pydantic import BaseModel, model_validator  # verified: packages/ai-parrot/src/parrot/stores/models.py:13

T = TypeVar("T")

_LOCK_SUBDIR = ".parrot_lancedb_locks"

# Process-local registry of shared asyncio.Lock instances, keyed by dataset
# key, so that multiple MutationCoordinator/LanceDBStore instances in ONE
# process that reference the same directory+collection serialize against
# each other too (not just across processes).
_LOCAL_LOCKS: dict[str, asyncio.Lock] = {}
_LOCAL_LOCKS_GUARD = threading.Lock()


def _shared_local_lock(dataset_key: str) -> asyncio.Lock:
    with _LOCAL_LOCKS_GUARD:
        lock = _LOCAL_LOCKS.get(dataset_key)
        if lock is None:
            lock = asyncio.Lock()
            _LOCAL_LOCKS[dataset_key] = lock
        return lock


class CommitConflict(RuntimeError):
    """A concurrent writer won the commit race; the caller may retry."""


class CoordinationConfig(BaseModel):
    """Bounded-contention settings. Values come from TASK-3057's evidence doc."""

    max_attempts: int = 5
    base_backoff_seconds: float = 0.05
    max_backoff_seconds: float = 2.0
    acquire_timeout_seconds: float = 30.0

    model_config = {"frozen": True}

    @model_validator(mode="after")
    def _validate_positive(self) -> "CoordinationConfig":
        if self.max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if self.base_backoff_seconds <= 0:
            raise ValueError("base_backoff_seconds must be positive")
        if self.max_backoff_seconds <= 0:
            raise ValueError("max_backoff_seconds must be positive")
        if self.max_backoff_seconds < self.base_backoff_seconds:
            raise ValueError("max_backoff_seconds must be >= base_backoff_seconds")
        if self.acquire_timeout_seconds <= 0:
            raise ValueError("acquire_timeout_seconds must be positive")
        return self


def _acquire_blocking(lock_path: Path, timeout: float) -> int:
    """Blocking, timeout-bounded acquire of an OS-level exclusive lock.

    Runs off the event loop via ``asyncio.to_thread``. Uses non-blocking
    ``flock`` polling (never a plain blocking ``LOCK_EX``) so the bound is
    enforced from inside this function itself — no external cancellation of
    the underlying thread is required or relied upon, and no lock path is
    ever unlinked or "stolen" on a PID/age heuristic. Process death (including
    SIGKILL) releases the OS lock automatically when the kernel closes the
    dead process's file descriptors — this is the built-in POSIX guarantee
    this design deliberately relies on instead of inventing one.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except BlockingIOError:
            if time.monotonic() >= deadline:
                os.close(fd)
                raise TimeoutError(f"Timed out acquiring LanceDB mutation lock at {lock_path}")
            time.sleep(0.01)


def _release_blocking(fd: int) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


@dataclass
class MutationCoordinator:
    """Serializes mutations in-process and mediates cross-process conflicts.

    Covers collection/FTS-index creation as well as upsert and count/delete
    transactions — every mutating operation the gate identified as unsafe to
    race goes through :meth:`exclusive` (directly, for a multi-step critical
    section like "count under the same lock as delete") or :meth:`run_mutation`
    (for a single retryable operation).
    """

    dataset_key: str
    config: CoordinationConfig = field(default_factory=CoordinationConfig)
    _local_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def __post_init__(self) -> None:
        # Replace the per-instance lock with the process-shared one for this
        # dataset_key so independently constructed coordinators (e.g. two
        # LanceDBStore instances in one process) still serialize together.
        self._local_lock = _shared_local_lock(self.dataset_key)

    @classmethod
    def for_directory(cls, uri: str | Path, collection: str, **kwargs: Any) -> "MutationCoordinator":
        """Build a coordinator keyed by canonical directory + collection identity."""
        resolved = str(Path(uri).expanduser().resolve())
        dataset_key = f"{resolved}::{collection}"
        config = kwargs.pop("config", None) or (CoordinationConfig(**kwargs) if kwargs else CoordinationConfig())
        return cls(dataset_key=dataset_key, config=config)

    def _lock_file_path(self) -> Path:
        resolved_uri, collection = self.dataset_key.rsplit("::", 1)
        # Percent-free, filesystem-safe: collection names are already
        # validated against [A-Za-z_][A-Za-z0-9_]{0,127} by LanceDBConfig.
        return Path(resolved_uri) / _LOCK_SUBDIR / f"{collection}.lock"

    @contextlib.asynccontextmanager
    async def exclusive(self, *, description: str) -> AsyncIterator[None]:
        """Cross-process exclusion for operations the gate proved unsafe to race.

        Acquires an OS-level lock off the event loop, honours
        ``acquire_timeout_seconds``, and releases on every exit path
        (including cancellation raised inside the ``async with`` body). A
        write already committed by the SDK before cancellation is NOT
        undone by releasing this lock — release only relinquishes future
        mutation ownership.
        """
        fd = await asyncio.to_thread(_acquire_blocking, self._lock_file_path(), self.config.acquire_timeout_seconds)
        try:
            yield
        finally:
            await asyncio.to_thread(_release_blocking, fd)

    async def run_mutation(self, operation: Callable[[], Any], *, description: str) -> Any:
        """Run one mutation with in-process serialization and bounded retry.

        Raises:
            CommitConflict: retries exhausted; the caller decides whether to
                surface or escalate. Never swallowed into a silent no-op.
        """
        async with self._local_lock:
            last_exc: CommitConflict | None = None
            for attempt in range(1, self.config.max_attempts + 1):
                try:
                    async with self.exclusive(description=description):
                        result = operation()
                        if asyncio.iscoroutine(result):
                            result = await result
                        return result
                except CommitConflict as exc:
                    last_exc = exc
                    if attempt >= self.config.max_attempts:
                        raise
                    backoff = min(
                        self.config.max_backoff_seconds,
                        self.config.base_backoff_seconds * (2 ** (attempt - 1)),
                    )
                    await asyncio.sleep(backoff * (0.5 + random.random() * 0.5))
            raise last_exc  # pragma: no cover — loop above always returns or raises
