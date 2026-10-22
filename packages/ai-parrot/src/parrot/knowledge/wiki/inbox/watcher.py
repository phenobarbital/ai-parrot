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

from parrot.knowledge.wiki.project import InboxConfig

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
