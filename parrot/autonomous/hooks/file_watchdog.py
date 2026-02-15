"""File watchdog hook — reacts to filesystem changes."""
import asyncio
import os
import time
from collections import defaultdict
from typing import Any

from watchdog.events import PatternMatchingEventHandler
from watchdog.observers import Observer

from .base import BaseHook
from .models import FileWatchdogHookConfig, HookType


class _EventHandler(PatternMatchingEventHandler):
    """Internal watchdog handler that forwards events to the hook."""

    def __init__(self, hook: "FileWatchdogHook", patterns: list, not_empty: bool = False) -> None:
        super().__init__(patterns=patterns)
        self._hook = hook
        self._not_empty = not_empty
        self._debounce: dict[str, float] = defaultdict(float)
        self._recently_created: set[str] = set()

    def _is_debounced(self, path: str) -> bool:
        now = time.time()
        if now - self._debounce[path] < 0.5:
            return True
        self._debounce[path] = now
        return False

    def _zero_size(self, path: str) -> bool:
        try:
            return os.path.getsize(path) == 0
        except (OSError, FileNotFoundError):
            return True

    def on_created(self, event: Any) -> None:
        if event.is_directory:
            return
        if "created" not in self._hook.events:
            return
        if self._not_empty and self._zero_size(event.src_path):
            return
        if self._is_debounced(event.src_path):
            return
        self._recently_created.add(event.src_path)
        self._hook.dispatch_event("file.created", event.src_path, event)

    def on_modified(self, event: Any) -> None:
        if event.is_directory:
            return
        if "modified" not in self._hook.events:
            return
        if event.src_path in self._recently_created:
            self._recently_created.discard(event.src_path)
            return
        if self._not_empty and self._zero_size(event.src_path):
            return
        if self._is_debounced(event.src_path):
            return
        self._hook.dispatch_event("file.modified", event.src_path, event)

    def on_moved(self, event: Any) -> None:
        if event.is_directory:
            return
        if "moved" not in self._hook.events:
            return
        if self._not_empty and self._zero_size(event.dest_path):
            return
        if self._is_debounced(event.dest_path):
            return
        self._hook.dispatch_event("file.moved", event.dest_path, event)

    def on_deleted(self, event: Any) -> None:
        if event.is_directory:
            return
        if "deleted" not in self._hook.events:
            return
        self._hook.dispatch_event("file.deleted", event.src_path, event)


class FileWatchdogHook(BaseHook):
    """Monitors a directory for file changes and emits HookEvents."""

    hook_type = HookType.FILE_WATCHDOG

    def __init__(self, config: FileWatchdogHookConfig, **kwargs) -> None:
        super().__init__(
            name=config.name,
            enabled=config.enabled,
            target_type=config.target_type,
            target_id=config.target_id,
            metadata=config.metadata,
            **kwargs,
        )
        self._config = config
        self.events = config.events
        self._observer = Observer()
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        directory = self._config.directory
        if not os.access(directory, os.R_OK | os.X_OK):
            raise PermissionError(
                f"Cannot access directory '{directory}'. "
                "Read and execute permissions required."
            )
        self._loop = asyncio.get_running_loop()
        handler = _EventHandler(
            hook=self,
            patterns=self._config.patterns,
            not_empty=self._config.not_empty,
        )
        self._observer.schedule(
            handler,
            directory,
            recursive=self._config.recursive,
        )
        self._observer.start()
        self.logger.info(
            f"FileWatchdogHook '{self.name}' watching '{directory}'"
        )

    async def stop(self) -> None:
        try:
            self._observer.stop()
        except Exception:
            pass
        self._observer.join(timeout=5)
        self.logger.info(f"FileWatchdogHook '{self.name}' stopped")

    def dispatch_event(self, event_type: str, filename: str, raw_event: Any) -> None:
        """Called from the watchdog thread — schedules async callback."""
        event = self._make_event(
            event_type=event_type,
            payload={
                "directory": self._config.directory,
                "filename": filename,
                "event_kind": raw_event.event_type,
            },
            task=f"File event: {event_type} on {filename}",
        )
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self.on_event(event), self._loop)
