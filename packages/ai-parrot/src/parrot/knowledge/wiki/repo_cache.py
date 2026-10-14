"""Repository cache data contracts and asynchronous process locking."""
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from pydantic import BaseModel

try:  # POSIX only; degrade to a no-op lock elsewhere.
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX platform
    fcntl = None  # type: ignore[assignment]

#: Poll interval while waiting for a contended lock.
_LOCK_POLL_SECONDS = 0.05


class RepoCachePaths(BaseModel):
    """Resolved layout for one canonical repository."""

    slug: str
    repository: str
    clone_dir: Path
    plane_dir: Path
    lock_path: Path


class BuildOutcome(BaseModel):
    """Outcome of one bounded wiki build subprocess."""

    ok: bool
    returncode: int
    timed_out: bool
    duration_s: float
    stderr_tail: str


@asynccontextmanager
async def repo_lock(lock_path: Path, *, timeout: float) -> AsyncIterator[bool]:
    """Acquire an advisory process lock without blocking the event loop.

    The lock is held through an open descriptor via nonblocking ``flock``
    and released in ``finally`` (also on exception or cancellation), so the
    kernel frees it if the holder crashes. Contended acquisition polls with
    :func:`asyncio.sleep`. Without :mod:`fcntl` it is a no-op yielding
    ``True``.

    Args:
        lock_path: Lock file path; parent directories are created.
        timeout: Seconds to keep retrying. ``0`` tries exactly once.

    Yields:
        ``True`` when the lock is held by this caller, ``False`` on timeout.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+")  # noqa: SIM115 - closed in finally
    acquired = False
    try:
        if fcntl is None:  # pragma: no cover - non-POSIX platform
            acquired = True
        else:
            deadline = time.monotonic() + max(timeout, 0.0)
            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        break
                    await asyncio.sleep(_LOCK_POLL_SECONDS)
        yield acquired
    finally:
        if acquired and fcntl is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:  # pragma: no cover - descriptor already invalid
                pass
        handle.close()
