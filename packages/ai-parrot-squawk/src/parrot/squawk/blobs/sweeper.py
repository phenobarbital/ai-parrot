"""Periodic TTL garbage collection for any Squawk blob store."""

from __future__ import annotations

import asyncio
import logging

from parrot.squawk.blobs.store import SquawkBlobStore


class BlobSweeper:
    """Run a blob store's TTL sweep periodically in a background task."""

    def __init__(self, store: SquawkBlobStore, *, interval_s: int = 300) -> None:
        """Initialize the periodic sweeper.

        Args:
            store: Blob store whose expired objects are removed.
            interval_s: Delay between sweep attempts in seconds.
        """
        self._store = store
        self._interval = interval_s
        self._task: asyncio.Task[None] | None = None
        self.logger = logging.getLogger(__name__)

    async def _run(self) -> None:
        """Sweep forever until the task is cancelled."""
        while True:
            try:
                removed = await self._store.sweep()
                if removed:
                    self.logger.info("BlobSweeper: removed %d expired blobs", removed)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - a failed sweep never kills the loop
                self.logger.exception("BlobSweeper: sweep failed")
            await asyncio.sleep(self._interval)

    async def start(self) -> None:
        """Start the loop unless it is already running."""
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Cancel and await the running loop, if any."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
