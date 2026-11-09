"""Deterministic regression coverage for Bookstore recovery hardening."""

import asyncio
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.knowledge.bookstore.config import LibraryLocation
from parrot.knowledge.bookstore.library import Bookstore
from parrot.knowledge.pageindex.locks import tree_lock


def _bookstore(tmp_path: Path) -> Bookstore:
    """Create a single-scope bookstore rooted in a temporary directory."""
    return Bookstore([LibraryLocation(scope="project", root=tmp_path)])


@pytest.mark.asyncio
async def test_concurrent_scope_open(tmp_path: Path) -> None:
    """First async callers join one successful recovery."""
    bookstore = _bookstore(tmp_path)
    toolkit = MagicMock()
    sweep_started = asyncio.Event()
    allow_sweep = asyncio.Event()
    sweeps: list[str] = []

    async def sweep(scope: str) -> None:
        sweeps.append(scope)
        sweep_started.set()
        await allow_sweep.wait()

    bookstore._toolkit = MagicMock(return_value=toolkit)
    bookstore._sweep_reserved_trees = sweep
    first = asyncio.create_task(bookstore._ready_toolkit("project"))
    await sweep_started.wait()
    second = asyncio.create_task(bookstore._ready_toolkit("project"))
    await asyncio.sleep(0)
    assert sweeps == ["project"]

    allow_sweep.set()
    assert await first is toolkit
    assert await second is toolkit
    assert sweeps == ["project"]


@pytest.mark.asyncio
async def test_active_old_staging_survives(tmp_path: Path) -> None:
    """Recovery cannot delete an active import just because it is old."""
    bookstore = _bookstore(tmp_path)
    trees_dir = tmp_path / "trees"
    trees_dir.mkdir()
    staging = trees_dir / "alpha--staging-deadbeef.json"
    staging.write_text("{}", encoding="utf-8")
    old = time.time() - 7200
    os.utime(staging, (old, old))

    toolkit = MagicMock()
    toolkit.delete_tree = AsyncMock()
    toolkit.rename_tree = AsyncMock()
    toolkit.vacuum_tree = AsyncMock()
    toolkit._store.exists.return_value = False
    bookstore._toolkits["project"] = toolkit

    async with tree_lock(bookstore._operation_storage_dir("project"), "book-alpha", timeout=0.1):
        await bookstore._sweep_reserved_trees("project")

    assert staging.exists()
    toolkit.delete_tree.assert_not_awaited()
    assert (tmp_path / ".bookstore-operations" / ".locks" / "book-alpha.lock").is_file()


@pytest.mark.asyncio
async def test_cancelled_scope_open_retries(tmp_path: Path) -> None:
    """Cancellation leaves initialization retryable."""
    bookstore = _bookstore(tmp_path)
    toolkit = MagicMock()
    started = asyncio.Event()
    sweeps = 0

    async def sweep(scope: str) -> None:
        nonlocal sweeps
        sweeps += 1
        started.set()
        await asyncio.Event().wait()

    bookstore._toolkit = MagicMock(return_value=toolkit)
    bookstore._sweep_reserved_trees = sweep
    opening = asyncio.create_task(bookstore._ready_toolkit("project"))
    await started.wait()
    opening.cancel()
    with pytest.raises(asyncio.CancelledError):
        await opening

    async def recovered(scope: str) -> None:
        nonlocal sweeps
        sweeps += 1

    bookstore._sweep_reserved_trees = recovered
    assert await bookstore._ready_toolkit("project") is toolkit
    assert sweeps == 2


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), True])
def test_reindex_lock_timeout_must_be_positive_and_finite(tmp_path: Path, timeout: float) -> None:
    """Operation-lock timeout configuration rejects invalid values."""
    with pytest.raises(ValueError, match="positive finite"):
        Bookstore([LibraryLocation(scope="project", root=tmp_path)], reindex_lock_timeout_s=timeout)
