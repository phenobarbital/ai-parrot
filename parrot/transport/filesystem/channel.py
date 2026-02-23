"""ChannelManager — broadcast channels via JSONL files."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

import aiofiles

from .config import FilesystemTransportConfig

logger = logging.getLogger(__name__)

_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")


class ChannelManager:
    """Broadcast channels using JSONL append-only files.

    Each channel is a separate ``.jsonl`` file in the channels directory.
    Agents publish messages (append) and poll from a caller-managed offset.
    No subscription state is maintained server-side.

    All writes are serialized via an ``asyncio.Lock`` to prevent
    interleaved output from concurrent coroutines.

    Args:
        channels_dir: Path to the channels directory.
        config: Transport configuration.
    """

    def __init__(
        self,
        channels_dir: Path,
        config: FilesystemTransportConfig,
    ) -> None:
        self._dir = channels_dir
        self._config = config
        self._lock = asyncio.Lock()

    def _channel_path(self, channel: str) -> Path:
        """Return the file path for a channel, with name sanitization.

        Args:
            channel: Channel name.

        Returns:
            Absolute path to the channel JSONL file.

        Raises:
            ValueError: If the channel name contains unsafe characters.
        """
        if not _SAFE_NAME_RE.match(channel):
            raise ValueError(
                f"Invalid channel name {channel!r}: "
                "only alphanumeric, underscore, and hyphen are allowed"
            )
        return self._dir / f"{channel}.jsonl"

    async def publish(
        self,
        channel: str,
        from_agent: str,
        from_name: str,
        content: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Publish a message to a broadcast channel.

        Appends a single JSON line to the channel's JSONL file.

        Args:
            channel: Channel name.
            from_agent: Sender agent ID.
            from_name: Sender human-readable name.
            content: Message content.
            payload: Optional structured payload.
        """
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "from_agent": from_agent,
            "from_name": from_name,
            "content": content,
            "payload": payload or {},
        }
        line = json.dumps(entry, separators=(",", ":")) + "\n"

        async with self._lock:
            self._dir.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(self._channel_path(channel), "a") as f:
                await f.write(line)
        logger.debug("Published to channel %s from %s", channel, from_agent)

    async def poll(
        self,
        channel: str,
        since_offset: int = 0,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Poll messages from a channel starting at a given offset.

        Yields messages from line ``since_offset`` onwards. The offset
        is 0-based (line number in the JSONL file). Callers track the
        offset themselves.

        Args:
            channel: Channel name.
            since_offset: 0-based line number to start reading from.

        Yields:
            Message dicts with an added ``offset`` field.
        """
        path = self._channel_path(channel)
        if not path.exists():
            return
        try:
            async with aiofiles.open(path, "r") as f:
                content = await f.read()
        except FileNotFoundError:
            return

        lines = content.strip().splitlines()
        for idx, raw in enumerate(lines):
            if idx < since_offset:
                continue
            try:
                entry = json.loads(raw)
                entry["offset"] = idx
                yield entry
            except json.JSONDecodeError:
                logger.debug("Skipping malformed channel line %d in %s", idx, channel)

    async def list_channels(self) -> List[str]:
        """List available channel names.

        Returns:
            Sorted list of channel names (without ``.jsonl`` extension).
        """
        if not self._dir.exists():
            return []
        return sorted(
            p.stem
            for p in self._dir.iterdir()
            if p.suffix == ".jsonl" and not p.name.startswith(".")
        )
