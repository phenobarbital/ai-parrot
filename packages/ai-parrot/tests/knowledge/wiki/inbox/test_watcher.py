"""Tests for inbox watcher stability probes and lifecycle (FEAT-715)."""

import asyncio
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from parrot.knowledge.wiki.inbox.watcher import (
    InboxWatcher,
    StabilityProbe,
    WatcherUnavailable,
    _require_watchdog,
    is_candidate,
)
from parrot.knowledge.wiki.inbox.processor import InboxLockBusy
from parrot.knowledge.wiki.project import InboxConfig, WikiProjectConfig


class FakeClock:
    """Deterministic clock and sleep for tests."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class FakeStat:
    """Minimal stat_result stand-in for tests."""

    st_size: int
    st_mtime_ns: int


def scripted_stat(samples):  # list[tuple[size, mtime_ns] | None], consumed in order
    it = iter(samples)

    def _stat(path: Path) -> FakeStat:
        s = next(it, None)
        if s is None:
            raise FileNotFoundError(path)
        return FakeStat(*s)

    return _stat


async def test_identical_samples_are_stable(tmp_path: Path) -> None:
    """Stable when all samples are identical and window elapsed."""
    clock = FakeClock()
    probe = StabilityProbe(3.0, 1.5, stat=scripted_stat([(10, 1)] * 3), sleep=clock.sleep, clock=clock)
    assert await probe.is_stable(tmp_path / "a.md") is True


async def test_same_size_changed_mtime_is_unstable(tmp_path: Path) -> None:
    """Unstable when mtime changes even if size stays the same."""
    clock = FakeClock()
    probe = StabilityProbe(3.0, 1.5, stat=scripted_stat([(10, 1), (10, 2), (10, 2)]), sleep=clock.sleep, clock=clock)
    assert await probe.is_stable(tmp_path / "a.md") is False


async def test_missing_file_is_unstable(tmp_path: Path) -> None:
    """Unstable when the file disappears."""
    clock = FakeClock()
    probe = StabilityProbe(3.0, 1.5, stat=scripted_stat([None]), sleep=clock.sleep, clock=clock)
    assert await probe.is_stable(tmp_path / "gone.md") is False


async def test_window_zero_returns_exists(tmp_path: Path) -> None:
    """window == 0 means stable iff the file exists."""
    clock = FakeClock()
    probe = StabilityProbe(0.0, 1.5, stat=scripted_stat([(10, 1)]), sleep=clock.sleep, clock=clock)
    assert await probe.is_stable(tmp_path / "a.md") is True


async def test_window_zero_missing_file_unstable(tmp_path: Path) -> None:
    """window == 0 with missing file is unstable."""
    clock = FakeClock()
    probe = StabilityProbe(0.0, 1.5, stat=scripted_stat([None]), sleep=clock.sleep, clock=clock)
    assert await probe.is_stable(tmp_path / "gone.md") is False


def test_dot_prefixed_temp_is_not_a_candidate(tmp_path: Path) -> None:
    """Dot-prefixed names are skipped by the processor."""
    assert is_candidate(tmp_path / ".meeting.md.tmp", tmp_path) is False
    assert is_candidate(tmp_path / ".hidden" / "x.md", tmp_path) is False


def test_nested_dot_component_is_not_a_candidate(tmp_path: Path) -> None:
    """Any dot-prefixed component in the relative path blocks the candidate."""
    assert is_candidate(tmp_path / "a" / ".b" / "c.md", tmp_path) is False


def test_valid_candidate(tmp_path: Path) -> None:
    """A regular file under the inbox is a candidate."""
    file = tmp_path / "meeting.md"
    file.touch()
    assert is_candidate(file, tmp_path) is True


def test_directory_is_not_a_candidate(tmp_path: Path) -> None:
    """Directories are never candidates."""
    dir_path = tmp_path / "subdir"
    dir_path.mkdir()
    assert is_candidate(dir_path, tmp_path) is False


def test_outside_inbox_is_not_a_candidate(tmp_path: Path) -> None:
    """Paths outside the inbox root are not candidates."""
    outside = tmp_path.parent / "other" / "file.md"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.touch()
    assert is_candidate(outside, tmp_path) is False


def test_watchdog_absent_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """_require_watchdog raises WatcherUnavailable when watchdog is not installed."""
    monkeypatch.setitem(sys.modules, "watchdog", None)
    with pytest.raises(WatcherUnavailable, match="filesystem-transport-full"):
        _require_watchdog()


async def test_size_change_is_unstable(tmp_path: Path) -> None:
    """Unstable when size changes."""
    clock = FakeClock()
    probe = StabilityProbe(3.0, 1.5, stat=scripted_stat([(10, 1), (11, 1), (11, 1)]), sleep=clock.sleep, clock=clock)
    assert await probe.is_stable(tmp_path / "a.md") is False


async def test_insufficient_samples_unstable(tmp_path: Path) -> None:
    """Unstable if window elapses with only one sample."""
    clock = FakeClock()
    probe = StabilityProbe(3.0, 1.5, stat=scripted_stat([(10, 1)]), sleep=clock.sleep, clock=clock)
    assert await probe.is_stable(tmp_path / "a.md") is False


class FakeObserver:
    """Observer stand-in that retains the registered handler."""

    def __init__(self) -> None:
        self.handler = None
        self.started = False
        self.stopped = False
        self.joined = False

    def schedule(self, handler, path: str, recursive: bool = True) -> None:
        """Retain the loop-safe handler supplied by the watcher."""
        self.handler = handler

    def start(self) -> None:
        """Record observer startup."""
        self.started = True

    def stop(self) -> None:
        """Record observer shutdown."""
        self.stopped = True

    def join(self) -> None:
        """Record observer join."""
        self.joined = True


class CountingProcessor:
    """Processor fake with a configurable first lock failure."""

    runs = 0
    fail_first_with_lock = False

    def __init__(self, runtime) -> None:
        """Accept the unchanged runtime passed by the watcher."""

    async def run(self, **kwargs) -> SimpleNamespace:
        """Count a run and optionally simulate a busy writer lock."""
        type(self).runs += 1
        if type(self).fail_first_with_lock and type(self).runs == 1:
            raise InboxLockBusy("busy")
        return SimpleNamespace(documents=[], counts={})


class AlwaysStable(StabilityProbe):
    """Probe fake that accepts every existing candidate immediately."""

    def __init__(self) -> None:
        super().__init__(0.0, 0.1)

    async def is_stable(self, path: Path) -> bool:
        """Return stability without sampling the filesystem."""
        return True


class StableAfterFirstProbe(AlwaysStable):
    """Probe fake that defers its first candidate check."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def is_stable(self, path: Path) -> bool:
        """Return false once, then permit the deferred run."""
        self.calls += 1
        return self.calls > 1


@pytest.fixture
def runtime(tmp_path: Path) -> SimpleNamespace:
    """Build the limited runtime surface the watcher is permitted to read."""
    (tmp_path / "inbox").mkdir()
    return SimpleNamespace(root=tmp_path, config=WikiProjectConfig(inbox=InboxConfig()))


def reset_processor() -> None:
    """Reset mutable fake processor state for each lifecycle test."""
    CountingProcessor.runs = 0
    CountingProcessor.fail_first_with_lock = False


async def test_burst_coalesces_into_one_run(runtime: SimpleNamespace) -> None:
    """Thread-side event bursts are coalesced into one loop-side processor run."""
    reset_processor()
    observer = FakeObserver()
    (runtime.root / "inbox" / "a.md").write_text("a", encoding="utf-8")
    watcher = InboxWatcher(
        runtime,
        probe=AlwaysStable(),
        debounce=0.05,
        observer_factory=lambda: observer,
        processor_factory=CountingProcessor,
    )
    await watcher.start()
    threads = [
        threading.Thread(
            target=observer.handler.dispatch,
            args=(SimpleNamespace(src_path=str(runtime.root / "inbox" / name)),),
        )
        for name in ("a.md", "b.md", "c.md")
    ]
    for thread in threads:
        thread.start()
    await asyncio.gather(*(asyncio.to_thread(thread.join) for thread in threads))
    await asyncio.sleep(0.15)
    await watcher.stop(drain=True)
    assert CountingProcessor.runs == 1
    assert watcher.stats.events_seen == 3
    assert observer.joined is True


async def test_unstable_candidate_defers_run(runtime: SimpleNamespace) -> None:
    """An unstable candidate defers the entire inbox until it becomes stable."""
    reset_processor()
    observer = FakeObserver()
    probe = StableAfterFirstProbe()
    (runtime.root / "inbox" / "a.md").write_text("a", encoding="utf-8")
    watcher = InboxWatcher(
        runtime,
        probe=probe,
        debounce=0.01,
        observer_factory=lambda: observer,
        processor_factory=CountingProcessor,
    )
    await watcher.start()
    await asyncio.sleep(0.08)
    await watcher.stop(drain=True)
    assert probe.calls >= 2
    assert CountingProcessor.runs == 1


async def test_lock_busy_is_retried(runtime: SimpleNamespace) -> None:
    """A busy processor lock is retried without losing the pending work."""
    reset_processor()
    CountingProcessor.fail_first_with_lock = True
    observer = FakeObserver()
    (runtime.root / "inbox" / "a.md").write_text("a", encoding="utf-8")
    watcher = InboxWatcher(
        runtime,
        probe=AlwaysStable(),
        debounce=0.01,
        lock_retry_delay=0.01,
        observer_factory=lambda: observer,
        processor_factory=CountingProcessor,
    )
    await watcher.start()
    await asyncio.sleep(0.08)
    await watcher.stop(drain=True)
    assert CountingProcessor.runs == 2
    assert watcher.stats.lock_busy_retries == 1


async def test_startup_scan_processes_preexisting_file(runtime: SimpleNamespace) -> None:
    """Startup processing does not require a filesystem event."""
    reset_processor()
    observer = FakeObserver()
    (runtime.root / "inbox" / "a.md").write_text("a", encoding="utf-8")
    watcher = InboxWatcher(
        runtime,
        probe=AlwaysStable(),
        debounce=0.01,
        observer_factory=lambda: observer,
        processor_factory=CountingProcessor,
    )
    await watcher.start()
    await asyncio.sleep(0.05)
    await watcher.stop(drain=True)
    assert CountingProcessor.runs == 1
    assert watcher.stats.events_seen == 0


async def test_start_twice_raises(runtime: SimpleNamespace) -> None:
    """A second start while active raises the fixed lifecycle error."""
    reset_processor()
    observer = FakeObserver()
    watcher = InboxWatcher(
        runtime,
        probe=AlwaysStable(),
        observer_factory=lambda: observer,
        processor_factory=CountingProcessor,
    )
    await watcher.start()
    with pytest.raises(RuntimeError, match="InboxWatcher already started"):
        await watcher.start()
    await watcher.stop(drain=True)
