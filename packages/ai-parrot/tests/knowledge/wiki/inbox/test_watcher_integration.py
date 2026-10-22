"""Integration: real watchdog observer -> InboxWatcher -> recording processor (FEAT-715)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("watchdog")

from parrot.knowledge.wiki.inbox import InboxWatcher  # noqa: E402
from parrot.knowledge.wiki.project import InboxConfig, WikiProjectConfig  # noqa: E402

# Shared event used by RecordingProcessor to signal that a run completed.
_run_completed: asyncio.Event | None = None


class RecordingProcessor:
    """Records which inbox files existed at each run."""

    seen: list[list[str]] = []

    def __init__(self, runtime) -> None:
        self.inbox = runtime.config.inbox_path(runtime.root)

    async def run(self, **kwargs):
        """Snapshot visible filenames and clear the inbox to emulate archiving."""
        names = sorted(p.name for p in self.inbox.iterdir() if p.is_file() and not p.name.startswith("."))
        type(self).seen.append(names)
        for p in self.inbox.iterdir():
            if p.is_file() and not p.name.startswith("."):
                p.unlink()
        if _run_completed is not None:
            _run_completed.set()
        return SimpleNamespace(documents=[object()] * len(names), counts={})


@pytest.fixture
def runtime(tmp_path: Path):
    """Build a lightweight runtime stand-in with a real inbox directory."""
    (tmp_path / "inbox").mkdir()
    cfg = WikiProjectConfig(inbox=InboxConfig(stability_window=0.2, stability_poll_interval=0.1))
    return SimpleNamespace(root=tmp_path, config=cfg)


@pytest.mark.asyncio
async def test_atomic_drop_is_processed_once(runtime) -> None:
    """An atomic rename into the inbox is picked up exactly once (AC2/AC4)."""
    global _run_completed  # noqa: PLW0603
    _run_completed = asyncio.Event()
    RecordingProcessor.seen = []
    watcher = InboxWatcher(runtime, debounce=0.1, processor_factory=RecordingProcessor)
    await watcher.start()

    inbox = runtime.root / "inbox"
    tmp = inbox / ".meeting.md.tmp"
    tmp.write_text("# meeting\nfireflies_id: abc123\n")
    os.replace(tmp, inbox / "meeting.md")

    await asyncio.wait_for(_run_completed.wait(), timeout=10)
    await watcher.stop(drain=True)

    assert len(RecordingProcessor.seen) == 1
    assert RecordingProcessor.seen[0] == ["meeting.md"]
    assert watcher.stats.documents_processed == 1


@pytest.mark.asyncio
async def test_dot_prefixed_temp_never_processed(runtime) -> None:
    """A lingering dot-prefixed temp file never appears in a processor run."""
    global _run_completed  # noqa: PLW0603
    _run_completed = asyncio.Event()
    RecordingProcessor.seen = []
    watcher = InboxWatcher(runtime, debounce=0.1, processor_factory=RecordingProcessor)
    await watcher.start()

    inbox = runtime.root / "inbox"
    # Drop a dot-prefixed temp that stays in place (never renamed)
    (inbox / ".upload.tmp").write_text("partial data")
    # Also drop a real file so the processor actually runs
    (inbox / "real.md").write_text("# real meeting\n")

    await asyncio.wait_for(_run_completed.wait(), timeout=10)
    await watcher.stop(drain=True)

    # The processor must have run but only seen the real file
    assert len(RecordingProcessor.seen) >= 1
    for run_files in RecordingProcessor.seen:
        assert ".upload.tmp" not in run_files, "dot-prefixed temp must never reach the processor"
    # The real file must have been seen in exactly one run
    all_files = [f for run in RecordingProcessor.seen for f in run]
    assert all_files.count("real.md") == 1


@pytest.mark.asyncio
async def test_two_files_coalesce_into_one_run(runtime) -> None:
    """Two files dropped back to back are coalesced into a single processor run."""
    global _run_completed  # noqa: PLW0603
    _run_completed = asyncio.Event()
    RecordingProcessor.seen = []
    watcher = InboxWatcher(runtime, debounce=0.3, processor_factory=RecordingProcessor)
    await watcher.start()

    inbox = runtime.root / "inbox"
    (inbox / "first.md").write_text("# first meeting\n")
    (inbox / "second.md").write_text("# second meeting\n")

    await asyncio.wait_for(_run_completed.wait(), timeout=10)
    # Give a brief pause to ensure no second run fires
    await asyncio.sleep(0.5)
    await watcher.stop(drain=True)

    # Both files should appear in a single run
    assert len(RecordingProcessor.seen) == 1
    assert sorted(RecordingProcessor.seen[0]) == ["first.md", "second.md"]
    assert watcher.stats.documents_processed == 2
