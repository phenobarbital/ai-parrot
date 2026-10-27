"""Tests for periodic Squawk blob TTL garbage collection."""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from parrot.squawk.blobs.sweeper import BlobSweeper


class _FlakyStore:
    """Store double whose first sweep raises and second sweep succeeds."""

    def __init__(self) -> None:
        self.calls = 0
        self.succeeded = asyncio.Event()

    async def sweep(self, now: datetime | None = None) -> int:
        """Raise once, then signal that the loop survived."""
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("transient storage failure")
        self.succeeded.set()
        return 1


@pytest.mark.asyncio
async def test_sweeper_survives_failure_repeats_and_stops_cleanly() -> None:
    """Keep looping after a failed sweep and cancel the task on stop."""
    store = _FlakyStore()
    sweeper = BlobSweeper(store, interval_s=0)

    await sweeper.start()
    running_task = sweeper._task
    await asyncio.wait_for(store.succeeded.wait(), timeout=1)
    await sweeper.stop()

    assert store.calls >= 2
    assert running_task is not None
    assert running_task.cancelled()
    assert sweeper._task is None


@pytest.mark.asyncio
async def test_sweeper_start_and_stop_are_idempotent() -> None:
    """Avoid duplicate loop tasks and permit stopping an idle sweeper."""
    store = _FlakyStore()
    sweeper = BlobSweeper(store, interval_s=60)

    await sweeper.start()
    first_task = sweeper._task
    await sweeper.start()

    assert sweeper._task is first_task
    await sweeper.stop()
    await sweeper.stop()
