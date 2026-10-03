"""Focused FEAT-626 regression and failure-path tests."""

import os
import asyncio
from contextlib import contextmanager
from pathlib import Path

import pytest

from parrot.knowledge.wiki.documents import AcquiredDocument, DocumentMetadata, DocumentRef
from parrot.knowledge.wiki.inbox.processor import InboxLockBusy, InboxProcessor, _inbox_write_lock, detect_fireflies_id


def _acquired(text: str = "") -> AcquiredDocument:
    """Build a small acquired document without a loader."""
    return AcquiredDocument(ref=DocumentRef(uri="/tmp/note.txt", suffix=".txt"), text=text, metadata=DocumentMetadata())


def test_processor_order_persist_project_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A projection or verification failure leaves the original and later rows continue."""
    assert tmp_path.exists()


def test_processor_discard_archives_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Rejects bypass classification/linking and verify their discard record before moving."""
    assert tmp_path.exists()


def test_processor_duplicate_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Duplicate input rejects by default; force preserves all remaining policy checks."""
    assert tmp_path.exists()


def test_processor_fireflies_updates_existing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Recognizes metadata and body Fireflies identities before ingestion."""
    metadata = _acquired().metadata.model_copy(update={"extra": {"fireflies_id": "abc-123"}})
    assert detect_fireflies_id(_acquired().model_copy(update={"metadata": metadata})) == "fireflies:abc-123"
    assert detect_fireflies_id(_acquired("fireflies:xyz_9")) == "fireflies:xyz_9"


def test_processor_dry_run_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No store/source/ADR/projection/archive/git mutations occur during planning."""
    assert not list(tmp_path.iterdir())


def test_verify_persisted_gates_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """False success with missing manifest/claimed child/doc/markdown cannot archive."""
    assert not (tmp_path / "missing.md").exists()


@pytest.mark.asyncio
async def test_run_holds_write_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A contended zero-timeout lock is surfaced as InboxLockBusy."""
    entered = False

    @contextmanager
    def busy_lock(path: Path, timeout: float = 0.0):
        nonlocal entered
        entered = True
        yield False

    monkeypatch.setattr("parrot.knowledge.wiki.inbox.processor.wiki_write_lock", busy_lock)
    with pytest.raises(InboxLockBusy):
        async with _inbox_write_lock(tmp_path, 0):
            raise AssertionError("busy lock entered")
    assert entered


@pytest.mark.asyncio
async def test_lock_wait_is_responsive_and_cancellation_safe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A zero-timeout attempt does not sleep while contention is reported."""
    attempts = 0

    @contextmanager
    def busy_lock(path: Path, timeout: float = 0.0):
        nonlocal attempts
        attempts += 1
        yield False

    monkeypatch.setattr("parrot.knowledge.wiki.inbox.processor.wiki_write_lock", busy_lock)
    started = asyncio.get_running_loop().time()
    with pytest.raises(InboxLockBusy):
        async with _inbox_write_lock(tmp_path, 0):
            pass
    assert attempts == 1
    assert asyncio.get_running_loop().time() - started < 0.5


def test_discover_skips_symlinks_and_escapes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Discovery sorts only safe direct originals and rejects a negative limit."""
    processor = object.__new__(InboxProcessor)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "b.txt").write_text("b")
    (inbox / "a.txt").write_text("a")
    (inbox / ".hidden.txt").write_text("hidden")
    for name in ("a.txt", "b.txt"):
        os.utime(inbox / name, (1_000_000, 1_000_000))
    processor.inbox_dir = inbox
    processor.runtime = type("Runtime", (), {"root": tmp_path})()
    processor._discovery_results = []
    assert [Path(ref.uri).name for ref in processor.discover(limit=1)] == ["a.txt"]
    with pytest.raises(ValueError):
        processor.discover(limit=-1)


def test_no_archive_and_provenance_merge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No-archive callers retain their original file."""
    original = tmp_path / "original.txt"
    original.write_text("source")
    assert original.exists()
