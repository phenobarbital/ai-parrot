"""InboxManager — point-to-point message delivery via filesystem."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, Optional

import aiofiles

from .config import FilesystemTransportConfig

logger = logging.getLogger(__name__)


class InboxManager:
    """Point-to-point message delivery between agents using the filesystem.

    Messages are delivered atomically via write-then-rename. Processing
    uses exactly-once semantics by moving messages to ``.processed/``
    before yielding them. Optional watchdog/inotify integration provides
    sub-50ms notification latency with automatic fallback to polling.

    Args:
        inbox_dir: Path to the inbox root directory.
        agent_id: The agent ID whose inbox this manager owns.
        config: Transport configuration.
    """

    def __init__(
        self,
        inbox_dir: Path,
        agent_id: str,
        config: FilesystemTransportConfig,
    ) -> None:
        self._inbox_dir = inbox_dir
        self._agent_id = agent_id
        self._config = config
        self._agent_inbox: Path = inbox_dir / agent_id
        self._processed_dir: Path = self._agent_inbox / ".processed"
        self._watcher_event: Optional[asyncio.Event] = None
        self._observer: Any = None

    def setup(self) -> None:
        """Create inbox directories for this agent."""
        self._agent_inbox.mkdir(parents=True, exist_ok=True)
        self._processed_dir.mkdir(parents=True, exist_ok=True)

    async def deliver(
        self,
        from_agent: str,
        from_name: str,
        to_agent: str,
        content: str,
        msg_type: str = "message",
        payload: Optional[Dict[str, Any]] = None,
        reply_to: Optional[str] = None,
    ) -> str:
        """Deliver a message to an agent's inbox atomically.

        Uses write-then-rename for POSIX atomicity: the message is first
        written to a temporary file, then renamed to its final path.

        Args:
            from_agent: Sender agent ID.
            from_name: Sender human-readable name.
            to_agent: Recipient agent ID.
            content: Message content.
            msg_type: Message type (e.g. "message", "command").
            payload: Optional structured payload.
            reply_to: Optional message ID this replies to.

        Returns:
            The generated message ID.
        """
        target_dir = self._inbox_dir / to_agent
        target_dir.mkdir(parents=True, exist_ok=True)

        msg_id = f"msg-{uuid.uuid4().hex}"
        now = time.time()
        expires_at = now + self._config.message_ttl if self._config.message_ttl > 0 else 0

        message = {
            "id": msg_id,
            "from": from_agent,
            "from_name": from_name,
            "to": to_agent,
            "type": msg_type,
            "content": content,
            "payload": payload or {},
            "reply_to": reply_to,
            "timestamp": now,
            "expires_at": expires_at,
        }

        tmp_path = target_dir / f".tmp-{msg_id}.json"
        final_path = target_dir / f"{msg_id}.json"

        async with aiofiles.open(tmp_path, "w") as f:
            await f.write(json.dumps(message, indent=2))
        tmp_path.rename(final_path)

        logger.debug("Delivered %s from %s to %s", msg_id, from_agent, to_agent)
        return msg_id

    async def poll(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Poll the inbox for new messages.

        Yields messages in chronological order (by mtime). Each message
        is moved to ``.processed/`` (or deleted if ``keep_processed`` is
        False) before being yielded, ensuring exactly-once delivery.

        If watchdog/inotify is enabled, waits for filesystem events
        instead of sleeping between polls.

        Yields:
            Message dicts in chronological order.
        """
        if self._config.use_inotify and self._observer is None:
            self._start_watcher()

        while True:
            messages = self._list_pending()
            for path in messages:
                msg = await self._read_message(path)
                if msg is None:
                    continue
                # Check TTL expiration.
                expires_at = msg.get("expires_at", 0)
                if expires_at and time.time() > expires_at:
                    logger.debug("Message %s expired, removing", msg.get("id"))
                    try:
                        path.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                # Move to processed before yielding (exactly-once).
                self._move_to_processed(path)
                yield msg

            # Wait for new messages.
            if self._watcher_event is not None:
                try:
                    await asyncio.wait_for(
                        self._watcher_event.wait(),
                        timeout=self._config.poll_interval,
                    )
                    self._watcher_event.clear()
                except asyncio.TimeoutError:
                    pass
            else:
                await asyncio.sleep(self._config.poll_interval)

    def _list_pending(self) -> list[Path]:
        """List pending message files sorted by modification time.

        Returns:
            List of message file paths sorted chronologically.
        """
        if not self._agent_inbox.exists():
            return []
        files = [
            p
            for p in self._agent_inbox.iterdir()
            if p.suffix == ".json" and not p.name.startswith(".")
        ]
        files.sort(key=lambda p: p.stat().st_mtime)
        return files

    async def _read_message(self, path: Path) -> Optional[Dict[str, Any]]:
        """Read and parse a message JSON file.

        Args:
            path: Path to the message file.

        Returns:
            Parsed message dict, or None on error.
        """
        try:
            async with aiofiles.open(path, "r") as f:
                content = await f.read()
            return json.loads(content)
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            logger.debug("Failed to read message %s: %s", path, exc)
            return None

    def _move_to_processed(self, path: Path) -> None:
        """Move a message file to .processed/ or delete it.

        Args:
            path: Path to the message file to process.
        """
        if self._config.keep_processed:
            dest = self._processed_dir / path.name
            try:
                path.rename(dest)
            except FileNotFoundError:
                pass
        else:
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def _start_watcher(self) -> None:
        """Start a watchdog observer for inotify-based notification.

        Falls back silently to polling if watchdog is not available.
        """
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer

            loop = asyncio.get_event_loop()
            self._watcher_event = asyncio.Event()
            event = self._watcher_event

            class _InboxHandler(FileSystemEventHandler):
                def on_created(self, ev: Any) -> None:
                    if ev.src_path.endswith(".json") and not Path(ev.src_path).name.startswith("."):
                        loop.call_soon_threadsafe(event.set)

                def on_moved(self, ev: Any) -> None:
                    if ev.dest_path.endswith(".json") and not Path(ev.dest_path).name.startswith("."):
                        loop.call_soon_threadsafe(event.set)

            observer = Observer()
            observer.schedule(
                _InboxHandler(),
                str(self._agent_inbox),
                recursive=False,
            )
            observer.daemon = True
            observer.start()
            self._observer = observer
            logger.info("Watchdog observer started for %s", self._agent_inbox)
        except ImportError:
            logger.debug("watchdog not available, using polling fallback")
            self._watcher_event = None
        except Exception as exc:
            logger.warning("Failed to start watchdog: %s, falling back to polling", exc)
            self._watcher_event = None

    def stop_watcher(self) -> None:
        """Stop the watchdog observer if running."""
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=2.0)
            self._observer = None
            logger.debug("Watchdog observer stopped")
