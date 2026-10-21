"""Tests for the inbox watcher stability probe and candidate filter (FEAT-715)."""

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from parrot.knowledge.wiki.inbox.watcher import (
    StabilityProbe,
    WatcherUnavailable,
    _require_watchdog,
    is_candidate,
)


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
        s = next(it)
        if s is None:
            raise FileNotFoundError(path)
        return FakeStat(*s)

    return _stat


async def test_identical_samples_are_stable(tmp_path: Path) -> None:
    """Stable when all samples are identical and window elapsed."""
    clock = FakeClock()
    probe = StabilityProbe(
        3.0, 1.5, stat=scripted_stat([(10, 1)] * 3), sleep=clock.sleep, clock=clock
    )
    assert await probe.is_stable(tmp_path / "a.md") is True


async def test_same_size_changed_mtime_is_unstable(tmp_path: Path) -> None:
    """Unstable when mtime changes even if size stays the same."""
    clock = FakeClock()
    probe = StabilityProbe(
        3.0, 1.5, stat=scripted_stat([(10, 1), (10, 2), (10, 2)]), sleep=clock.sleep, clock=clock
    )
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
    probe = StabilityProbe(
        3.0, 1.5, stat=scripted_stat([(10, 1), (11, 1), (11, 1)]), sleep=clock.sleep, clock=clock
    )
    assert await probe.is_stable(tmp_path / "a.md") is False


async def test_insufficient_samples_unstable(tmp_path: Path) -> None:
    """Unstable if window elapses with only one sample."""
    clock = FakeClock()
    probe = StabilityProbe(
        3.0, 1.5, stat=scripted_stat([(10, 1)]), sleep=clock.sleep, clock=clock
    )
    assert await probe.is_stable(tmp_path / "a.md") is False
