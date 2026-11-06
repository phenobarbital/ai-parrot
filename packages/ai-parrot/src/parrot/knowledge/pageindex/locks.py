"""Cross-process, per-tree writer lock for PageIndex generation publication (FEAT-831)."""

from __future__ import annotations

import asyncio
import logging
import time
import weakref
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

try:  # POSIX only.
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX platform
    fcntl = None  # type: ignore[assignment]

from parrot.knowledge.pageindex.store import JSONTreeStore

logger = logging.getLogger("parrot.knowledge.pageindex.locks")

_LOCK_POLL_SECONDS: float = 0.05
_LOCAL_LOCKS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]]" = (
    weakref.WeakKeyDictionary()
)


class TreeLockTimeout(TimeoutError):
    """Raised when the per-tree lock is not acquired within ``timeout`` seconds."""


def lock_path(storage_dir: Path, tree_name: str) -> Path:
    """Return ``<storage_dir>/.locks/<tree_name>.lock`` after validating ``tree_name``."""
    JSONTreeStore._validate_name(tree_name)
    return Path(storage_dir) / ".locks" / f"{tree_name}.lock"


def _local_lock(path: Path) -> asyncio.Lock:
    """Return the running loop's in-process lock for ``path``."""
    loop = asyncio.get_running_loop()
    locks = _LOCAL_LOCKS.setdefault(loop, {})
    return locks.setdefault(str(path.resolve()), asyncio.Lock())


@asynccontextmanager
async def tree_lock(storage_dir: Path, tree_name: str, *, timeout: float) -> AsyncIterator[None]:
    """Hold an exclusive lock on ``tree_name`` for the duration of the block.

    Raises:
        TreeLockTimeout: The lock was not acquired within ``timeout`` seconds.
        RuntimeError: ``fcntl`` is unavailable on this platform.
    """
    if fcntl is None:
        raise RuntimeError("tree_lock requires fcntl (POSIX)")

    path = lock_path(storage_dir, tree_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + max(timeout, 0.0)
    local = _local_lock(path)
    local_acquired = False
    handle = None
    try:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            if local.locked():
                raise TreeLockTimeout(tree_name)
            await local.acquire()
        else:
            try:
                await asyncio.wait_for(local.acquire(), remaining)
            except asyncio.TimeoutError as exc:
                raise TreeLockTimeout(tree_name) from exc
        local_acquired = True

        handle = open(path, "a+")  # noqa: SIM115,ASYNC230 - closed in finally
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TreeLockTimeout(tree_name)
                await asyncio.sleep(_LOCK_POLL_SECONDS)

        yield
    finally:
        if handle is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:  # pragma: no cover - descriptor already invalid
                pass
            handle.close()
        if local_acquired:
            local.release()
