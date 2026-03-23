"""ActivityFeed — global append-only JSONL event log."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import aiofiles

from .config import FilesystemTransportConfig

logger = logging.getLogger(__name__)


class ActivityFeed:
    """Global append-only JSONL event log for the FilesystemTransport.

    Every system event (agent join/leave, message delivery, broadcast,
    reservation) is recorded as a single JSON line. The feed auto-rotates
    when it exceeds ``feed_retention`` lines, keeping only the most recent
    entries.

    All writes are serialized via an ``asyncio.Lock`` to prevent
    interleaved output from concurrent coroutines.

    Args:
        feed_path: Path to the JSONL feed file.
        config: Transport configuration.
    """

    def __init__(self, feed_path: Path, config: FilesystemTransportConfig) -> None:
        self._path = feed_path
        self._config = config
        self._lock = asyncio.Lock()

    async def emit(self, event: str, data: Dict[str, Any] | None = None) -> None:
        """Append an event to the activity feed.

        Args:
            event: Event type string (e.g. "agent_joined", "message_sent").
            data: Optional dict of event-specific data merged into the entry.
        """
        entry: Dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
        }
        if data:
            entry.update(data)

        line = json.dumps(entry, separators=(",", ":")) + "\n"

        async with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(self._path, "a") as f:
                await f.write(line)
            await self._maybe_rotate()

    async def tail(self, n: int = 50) -> List[Dict[str, Any]]:
        """Read the last *n* events from the feed.

        Args:
            n: Maximum number of events to return.

        Returns:
            List of event dicts, oldest first. Empty list if the feed
            file does not exist.
        """
        if not self._path.exists():
            return []
        try:
            async with aiofiles.open(self._path, "r") as f:
                content = await f.read()
        except FileNotFoundError:
            return []

        lines = content.strip().splitlines()
        entries: List[Dict[str, Any]] = []
        for raw in lines[-n:]:
            try:
                entries.append(json.loads(raw))
            except json.JSONDecodeError:
                logger.debug("Skipping malformed feed line: %s", raw[:80])
        return entries

    async def _maybe_rotate(self) -> None:
        """Rotate the feed file if it exceeds ``feed_retention`` lines.

        Keeps only the most recent ``feed_retention`` lines. Uses
        write-then-rename for atomicity.
        """
        retention = self._config.feed_retention
        if retention <= 0:
            return

        try:
            async with aiofiles.open(self._path, "r") as f:
                content = await f.read()
        except FileNotFoundError:
            return

        lines = content.splitlines(keepends=True)
        if len(lines) <= retention:
            return

        keep = lines[-retention:]
        tmp_path = self._path.with_suffix(".tmp")
        async with aiofiles.open(tmp_path, "w") as f:
            await f.writelines(keep)
        tmp_path.rename(self._path)
        logger.debug(
            "Feed rotated: %d → %d lines",
            len(lines),
            len(keep),
        )
