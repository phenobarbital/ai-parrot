"""Deterministic regression coverage for Bookstore recovery hardening."""

import asyncio
import hashlib
import os
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.knowledge.bookstore.config import LibraryLocation
from parrot.knowledge.bookstore.library import Bookstore
from parrot.knowledge.bookstore.models import BookRelation, REL_WEIGHTS
from parrot.knowledge.pageindex.locks import tree_lock


def _bookstore(tmp_path: Path) -> Bookstore:
    """Create a single-scope bookstore rooted in a temporary directory."""
    return Bookstore([LibraryLocation(scope="project", root=tmp_path)])


_MARKDOWN = (
    "# Locking Handbook\n\n"
    "This introduction has enough descriptive material to survive markdown thinning during deterministic tests.\n\n"
    "## Stable Chapter\n\n"
    "This chapter describes serialized publication, graph retention and recovery with sufficient detail.\n"
)


@pytest.mark.asyncio
async def test_concurrent_scope_open(tmp_path: Path) -> None:
    """First async callers join one successful recovery."""
    bookstore = _bookstore(tmp_path)
    toolkit = MagicMock()
    sweep_started = asyncio.Event()
    allow_sweep = asyncio.Event()
    sweeps: list[str] = []

    async def sweep(scope: str) -> None:
        sweeps.append(scope)
        sweep_started.set()
        await allow_sweep.wait()

    bookstore._toolkit = MagicMock(return_value=toolkit)
    bookstore._sweep_reserved_trees = sweep
    first = asyncio.create_task(bookstore._ready_toolkit("project"))
    await sweep_started.wait()
    second = asyncio.create_task(bookstore._ready_toolkit("project"))
    await asyncio.sleep(0)
    assert sweeps == ["project"]

    allow_sweep.set()
    assert await first is toolkit
    assert await second is toolkit
    assert sweeps == ["project"]


@pytest.mark.asyncio
async def test_active_old_staging_survives(tmp_path: Path) -> None:
    """Recovery cannot delete an active import just because it is old."""
    bookstore = _bookstore(tmp_path)
    trees_dir = tmp_path / "trees"
    trees_dir.mkdir()
    staging = trees_dir / "alpha--staging-deadbeef.json"
    staging.write_text("{}", encoding="utf-8")
    old = time.time() - 7200
    os.utime(staging, (old, old))

    toolkit = MagicMock()
    toolkit.delete_tree = AsyncMock()
    toolkit.rename_tree = AsyncMock()
    toolkit.vacuum_tree = AsyncMock()
    toolkit._store.exists.return_value = False
    bookstore._toolkits["project"] = toolkit

    async with tree_lock(bookstore._operation_storage_dir("project"), "book-alpha", timeout=0.1):
        await bookstore._sweep_reserved_trees("project")

    assert staging.exists()
    toolkit.delete_tree.assert_not_awaited()
    assert (tmp_path / ".bookstore-operations" / ".locks" / "book-alpha.lock").is_file()


@pytest.mark.asyncio
async def test_cancelled_scope_open_retries(tmp_path: Path) -> None:
    """Cancellation leaves initialization retryable."""
    bookstore = _bookstore(tmp_path)
    toolkit = MagicMock()
    started = asyncio.Event()
    sweeps = 0

    async def sweep(scope: str) -> None:
        nonlocal sweeps
        sweeps += 1
        started.set()
        await asyncio.Event().wait()

    bookstore._toolkit = MagicMock(return_value=toolkit)
    bookstore._sweep_reserved_trees = sweep
    opening = asyncio.create_task(bookstore._ready_toolkit("project"))
    await started.wait()
    opening.cancel()
    with pytest.raises(asyncio.CancelledError):
        await opening

    async def recovered(scope: str) -> None:
        nonlocal sweeps
        sweeps += 1

    bookstore._sweep_reserved_trees = recovered
    assert await bookstore._ready_toolkit("project") is toolkit
    assert sweeps == 2


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), True])
def test_reindex_lock_timeout_must_be_positive_and_finite(tmp_path: Path, timeout: float) -> None:
    """Operation-lock timeout configuration rejects invalid values."""
    with pytest.raises(ValueError, match="positive finite"):
        Bookstore([LibraryLocation(scope="project", root=tmp_path)], reindex_lock_timeout_s=timeout)


@pytest.mark.asyncio
async def test_same_heading_changed_bytes_invalidates_graph(tmp_path: Path) -> None:
    """A stable TOC cannot justify retaining relations after content changes."""
    bookstore = _bookstore(tmp_path)
    source = tmp_path / "handbook.md"
    other = tmp_path / "other.md"
    source.write_text(_MARKDOWN, encoding="utf-8")
    other.write_text(_MARKDOWN + "\nAdditional distinct material for the second book.\n", encoding="utf-8")
    card, _ = await bookstore.add_book(source)
    other_card, _ = await bookstore.add_book(other)
    catalog = bookstore._catalog("project")
    catalog.upsert_relations(
        [
            BookRelation(
                src_book_id=card.book_id,
                dst_book_id=other_card.book_id,
                rel="parallels",
                origin="deterministic",
                confidence=1.0,
                weight=REL_WEIGHTS["parallels"],
                computed_at="2026-11-09T00:00:00+00:00",
            )
        ]
    )
    source.write_text(_MARKDOWN.replace("serialized publication", "atomic publication"), encoding="utf-8")

    updated, status = await bookstore.add_book(source)

    assert status == "updated"
    assert updated.toc_digest == card.toc_digest
    assert updated.source_sha256 != card.source_sha256
    assert bookstore.related_books(card.book_id) == []


@pytest.mark.asyncio
async def test_equal_hash_and_toc_preserves_graph_and_community(tmp_path: Path) -> None:
    """Forced identical imports retain graph state only when both identities still match."""
    bookstore = _bookstore(tmp_path)
    source = tmp_path / "handbook.md"
    other = tmp_path / "other.md"
    source.write_text(_MARKDOWN, encoding="utf-8")
    other.write_text(_MARKDOWN + "\nA distinct second book for relation state.\n", encoding="utf-8")
    card, _ = await bookstore.add_book(source)
    other_card, _ = await bookstore.add_book(other)
    catalog = bookstore._catalog("project")
    catalog.upsert_relations(
        [
            BookRelation(
                src_book_id=card.book_id,
                dst_book_id=other_card.book_id,
                rel="parallels",
                origin="deterministic",
                confidence=1.0,
                weight=REL_WEIGHTS["parallels"],
                computed_at="2026-11-09T00:00:00+00:00",
            )
        ]
    )
    catalog.set_card_community(card.book_id, "c1", "Stable community")

    updated, status = await bookstore.add_book(source, force=True)

    assert status == "updated"
    assert updated.community_id == "c1"
    assert updated.community_label == "Stable community"
    assert bookstore.related_books(card.book_id)


@pytest.mark.asyncio
async def test_new_slug_collision_serializes_without_overwrite(tmp_path: Path) -> None:
    """Different sources requesting one title obtain distinct stable slugs."""
    bookstore = _bookstore(tmp_path)
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text(_MARKDOWN + "\nFirst source content.\n", encoding="utf-8")
    second.write_text(_MARKDOWN + "\nSecond source content.\n", encoding="utf-8")

    left, right = await asyncio.gather(
        bookstore.add_book(first, title="Shared Title"),
        bookstore.add_book(second, title="Shared Title"),
    )

    assert {left[0].book_id, right[0].book_id} == {"shared-title", "shared-title-2"}
    assert len(bookstore.list_books()) == 2


@pytest.mark.asyncio
async def test_two_process_import_lock(tmp_path: Path) -> None:
    """A competing process holding a source lock produces a bounded import timeout."""
    source = tmp_path / "handbook.md"
    source.write_text(_MARKDOWN, encoding="utf-8")
    bookstore = Bookstore([LibraryLocation(scope="project", root=tmp_path)], reindex_lock_timeout_s=0.1)
    canonical = str(source.resolve()).encode()
    lock_name = f"path-{hashlib.sha256(canonical).hexdigest()}.lock"
    lock_path = tmp_path / ".bookstore-operations" / ".locks" / lock_name
    locker = (
        "import fcntl, pathlib, sys, time; "
        "path = pathlib.Path(sys.argv[1]); path.parent.mkdir(parents=True, exist_ok=True); "
        "handle = path.open('a+'); fcntl.flock(handle.fileno(), fcntl.LOCK_EX); "
        "print('locked', flush=True); time.sleep(5)"
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        locker,
        str(lock_path),
        stdout=asyncio.subprocess.PIPE,
    )
    assert await asyncio.wait_for(process.stdout.readline(), timeout=1) == b"locked\n"
    try:
        with pytest.raises(Exception, match="Re-index already in progress"):
            await bookstore.add_book(source)
    finally:
        process.terminate()
        await process.wait()


@pytest.mark.asyncio
async def test_cancelled_import_cleans_staging_without_catalog_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancellation leaves no staged tree or partial card behind."""
    bookstore = _bookstore(tmp_path)
    source = tmp_path / "handbook.md"
    source.write_text(_MARKDOWN, encoding="utf-8")
    toolkit = bookstore._toolkit("project")

    async def cancelled(*args: object, **kwargs: object) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(toolkit, "insert_markdown", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await bookstore.add_book(source)

    assert bookstore.list_books() == []
    assert not list((tmp_path / "trees").glob("*--staging-*.json"))


@pytest.mark.asyncio
async def test_catalog_failure_keeps_successfully_published_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A post-rename catalog failure leaves the live content available for repair."""
    bookstore = _bookstore(tmp_path)
    source = tmp_path / "handbook.md"
    source.write_text(_MARKDOWN, encoding="utf-8")
    catalog = bookstore._catalog("project")

    def failed_upsert(*args: object, **kwargs: object) -> None:
        raise RuntimeError("catalog unavailable")

    monkeypatch.setattr(catalog, "upsert", failed_upsert)
    with pytest.raises(RuntimeError, match="catalog unavailable"):
        await bookstore.add_book(source)

    assert (tmp_path / "trees" / "handbook.json").is_file()
    assert not list((tmp_path / "trees").glob("*--staging-*.json"))
