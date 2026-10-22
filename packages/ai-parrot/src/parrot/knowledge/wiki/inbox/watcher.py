"""Source-agnostic folder watcher for the wiki inbox (FEAT-715).

This module must stay importable without ``watchdog`` installed: it lives only in
the ``filesystem-transport-full`` extra, so it is imported lazily by
:func:`_require_watchdog`.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, NamedTuple

from pydantic import BaseModel

from parrot.knowledge.wiki.inbox.models import InboxRunReport
from parrot.knowledge.wiki.inbox.processor import InboxLockBusy, InboxProcessor, InboxRuntime
from parrot.knowledge.wiki.project import InboxConfig, validate_inbox_paths

logger = logging.getLogger(__name__)

WATCHDOG_EXTRA = "filesystem-transport-full"


class WatcherUnavailable(RuntimeError):
    """Raised when the optional ``watchdog`` dependency is not installed."""


def _require_watchdog() -> Any:
    """Import and return the ``watchdog.observers`` module, or raise WatcherUnavailable."""
    try:
        from watchdog import observers  # noqa: PLC0415 — lazy by design (spec §8 Q1)
    except ImportError as exc:
        raise WatcherUnavailable(
            "wikitoolkit inbox --watch needs the optional 'watchdog' package: "
            f"install ai-parrot[{WATCHDOG_EXTRA}]"
        ) from exc
    return observers


class WatcherStats(BaseModel):
    """Counters for one watcher lifetime; surfaced by the CLI on shutdown."""

    events_seen: int = 0
    runs_started: int = 0
    documents_processed: int = 0
    lock_busy_retries: int = 0


class FileSample(NamedTuple):
    """One stat observation of a candidate file."""

    size: int
    mtime_ns: int


def is_candidate(path: Path, inbox_dir: Path) -> bool:
    """Whether ``path`` is something InboxProcessor.discover() would pick up."""
    # FILL IN: False when `path` is not under `inbox_dir`, is a directory, or ANY
    #          component of path.relative_to(inbox_dir) starts with "." — bounded by
    #          processor.py:167 and the agent's `.tmp` convention (AC2).
    try:
        relative = path.relative_to(inbox_dir)
    except ValueError:
        # path is not under inbox_dir
        return False
    if path.is_dir():
        return False
    for component in relative.parts:
        if component.startswith("."):
            return False
    return True


class StabilityProbe:
    """Decide whether a file stopped changing, with injectable time and stat."""

    def __init__(
        self,
        window: float,
        poll_interval: float,
        *,
        stat: Callable[[Path], os.stat_result] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Bind the timing policy; ``stat=None`` means os.stat run in a worker thread."""
        self.window = window
        self.poll_interval = poll_interval
        self._stat = stat
        self._sleep = sleep
        self._clock = clock

    @classmethod
    def from_config(cls, config: InboxConfig, **overrides: Any) -> "StabilityProbe":
        """Build from InboxConfig.stability_window / stability_poll_interval."""
        return cls(config.stability_window, config.stability_poll_interval, **overrides)

    async def sample(self, path: Path) -> FileSample | None:
        """Return the current FileSample, or None when the file is gone."""
        # FILL IN: call self._stat(path) directly when injected, else
        #          await asyncio.to_thread(os.stat, path); FileNotFoundError -> None.
        try:
            if self._stat is not None:
                stat_result = self._stat(path)
            else:
                stat_result = await asyncio.to_thread(os.stat, path)
            return FileSample(size=stat_result.st_size, mtime_ns=stat_result.st_mtime_ns)
        except FileNotFoundError:
            return None

    async def is_stable(self, path: Path) -> bool:
        """True iff >=2 samples spanning >= window seconds are all identical."""
        # FILL IN: window == 0 -> return (await self.sample(path)) is not None.
        #          Otherwise sample at start, then loop: await self._sleep(poll_interval),
        #          sample again; any None or any differing sample -> False; stop once
        #          self._clock() - start >= self.window AND >= 2 samples -> True.
        if self.window == 0:
            return (await self.sample(path)) is not None

        start_time = self._clock()
        samples = []
        first_sample = await self.sample(path)
        if first_sample is None:
            return False
        samples.append(first_sample)

        while True:
            await self._sleep(self.poll_interval)
            current_sample = await self.sample(path)
            if current_sample is None:
                return False
            if current_sample != first_sample:
                return False
            samples.append(current_sample)
            if len(samples) >= 2 and (self._clock() - start_time) >= self.window:
                return True


class _Handler:
    """Duck-typed watchdog handler: thread-side, hands paths to the loop only."""

    def __init__(self, loop: asyncio.AbstractEventLoop, enqueue: Callable[[Path], None]) -> None:
        """Bind the event loop callback used to transfer paths safely."""
        self._loop = loop
        self._enqueue = enqueue

    def dispatch(self, event: Any) -> None:
        """Hand the event path to the event loop without touching watcher state."""
        raw = getattr(event, "dest_path", "") or getattr(event, "src_path", "")
        if raw:
            self._loop.call_soon_threadsafe(self._enqueue, Path(raw))


class InboxWatcher:
    """Source-agnostic folder watcher that serializes InboxProcessor runs."""

    def __init__(
        self,
        runtime: InboxRuntime,
        *,
        stats: WatcherStats | None = None,
        probe: StabilityProbe | None = None,
        debounce: float = 0.5,
        lock_retry_delay: float = 2.0,
        force: bool = False,
        archive: bool = True,
        observer_factory: Callable[[], Any] | None = None,
        processor_factory: Callable[[Any], Any] | None = None,
    ) -> None:
        """Bind an already-built runtime and validate its inbox paths."""
        self.runtime = runtime
        self.stats = stats or WatcherStats()
        self.logger = logger
        self.inbox_dir = runtime.config.inbox_path(runtime.root)
        validate_inbox_paths(
            runtime.root,
            self.inbox_dir,
            runtime.config.archive_path(runtime.root),
            runtime.config.inbox_markdown_path(runtime.root),
        )
        self._probe = probe or StabilityProbe.from_config(runtime.config.inbox)
        self._debounce = debounce
        self._lock_retry_delay = lock_retry_delay
        self._run_kwargs = {"force": force, "archive": archive}
        self._observer_factory = observer_factory
        self._processor_factory = processor_factory or InboxProcessor
        self._observer: Any = None
        self._worker_task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._stopping = False
        self._pending = False
        self._running = False

    async def start(self) -> None:
        """Begin observing the inbox and start the sole processor-owning worker."""
        if self._observer is not None:
            raise RuntimeError("InboxWatcher already started")
        loop = asyncio.get_running_loop()
        factory = self._observer_factory or _require_watchdog().Observer
        self._stopping = False
        self._observer = factory()
        self._observer.schedule(_Handler(loop, self._enqueue), str(self.inbox_dir), recursive=True)
        self._observer.start()
        self._worker_task = loop.create_task(self._worker())
        await self._startup_scan()

    def _enqueue(self, path: Path) -> None:
        """Count an event and wake the loop-owned worker."""
        self.stats.events_seen += 1
        self._pending = True
        self._wake.set()

    async def _startup_scan(self) -> None:
        """Wake the worker so files present before startup are processed."""
        self._pending = True
        self._wake.set()

    async def _is_stable(self, path: Path) -> bool:
        """Delegate the stability decision to the injected probe."""
        return await self._probe.is_stable(path)

    async def _worker(self) -> None:
        """Run every InboxProcessor call from one coroutine only."""
        while True:
            await self._wake.wait()
            self._wake.clear()
            if self._stopping:
                return
            if not self._pending:
                continue

            await asyncio.sleep(self._debounce)
            self._pending = False
            candidates = await asyncio.to_thread(
                lambda: [path for path in self.inbox_dir.rglob("*") if is_candidate(path, self.inbox_dir)]
            )
            if not candidates:
                if self._stopping and not self._pending:
                    return
                continue
            if not all([await self._is_stable(path) for path in candidates]):
                self.logger.info("Deferring inbox watcher run because a candidate is still changing")
                self._pending = True
                self._wake.set()
                continue

            self._running = True
            try:
                report = await self._drain_once()
            finally:
                self._running = False
            self.stats.documents_processed += len(report.documents)
            if self._stopping and not self._pending:
                return

    async def _drain_once(self) -> InboxRunReport:
        """Run the processor, retrying an unavailable writer lock without loss."""
        while True:
            self.stats.runs_started += 1
            try:
                return await self._processor_factory(self.runtime).run(**self._run_kwargs)
            except InboxLockBusy:
                self.stats.lock_busy_retries += 1
                await asyncio.sleep(self._lock_retry_delay)

    async def stop(self, *, drain: bool = True) -> WatcherStats:
        """Stop observing and either drain the worker or cancel it."""
        self._stopping = True
        observer = self._observer
        worker = self._worker_task
        if observer is not None:
            observer.stop()
            await asyncio.to_thread(observer.join)
        if worker is not None:
            if drain:
                self._wake.set()
                if not self._running:
                    worker.cancel()
                try:
                    await worker
                except asyncio.CancelledError:
                    pass
            else:
                worker.cancel()
                try:
                    await worker
                except asyncio.CancelledError:
                    pass
        self._worker_task = None
        self._observer = None
        return self.stats

    async def run_forever(self, *, stop_event: asyncio.Event | None = None) -> WatcherStats:
        """Run until stopped by the supplied event or coroutine cancellation."""
        await self.start()
        try:
            if stop_event is None:
                await asyncio.Event().wait()
            else:
                await stop_event.wait()
        finally:
            await self.stop(drain=True)
        return self.stats
