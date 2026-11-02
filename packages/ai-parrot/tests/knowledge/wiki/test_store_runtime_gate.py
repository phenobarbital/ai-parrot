"""FEAT-633 M7 — wiki store version gate (TASK-4092): schema number only."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from parrot.knowledge.wiki import store as store_mod
from parrot.knowledge.wiki.store import MIN_RUNTIME_KEY, SQLiteWikiStore, WikiStoreVersionError


async def _built_plane(tmp_path: Path) -> Path:
    db = tmp_path / "wiki.db"
    await SQLiteWikiStore(db, "t").set_meta("k", "v")  # builds the schema (and stamps min_runtime_version)
    return db


def _stamp(db: Path, key: str, value: str) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def _meta(db: Path, key: str) -> str | None:
    with sqlite3.connect(db) as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return None if row is None else row[0]


async def test_unstamped_plane_opens(tmp_path: Path) -> None:
    """A pre-FEAT-633 plane (no min_runtime_version row) opens normally."""
    db = await _built_plane(tmp_path)
    with sqlite3.connect(db) as conn:  # creation now stamps; drop the row to mimic a pre-FEAT-633 plane
        conn.execute("DELETE FROM meta WHERE key = ?", (MIN_RUNTIME_KEY,))
    assert await SQLiteWikiStore(db, "t").get_meta("k") == "v"


async def test_newer_schema_version_refused(tmp_path: Path) -> None:
    """issue:f249c19e8a4d — a newer schema_version is refused, not re-stamped downward."""
    db = await _built_plane(tmp_path)
    newer = str(int(store_mod.SCHEMA_VERSION) + 7)  # "10" sorts below "3" as text — proves integer comparison
    _stamp(db, "schema_version", newer)
    with pytest.raises(WikiStoreVersionError, match=f"schema version {newer}, newer than this runtime's"):
        await SQLiteWikiStore(db, "t").get_meta("k")
    with pytest.raises(WikiStoreVersionError, match=f"schema version {newer}, newer than this runtime's"):
        await SQLiteWikiStore(db, "t", read_only=True).get_meta("k")
    assert _meta(db, "schema_version") == newer


async def test_fresh_plane_stamped_at_creation(tmp_path: Path) -> None:
    """_ensure_schema stamps min_runtime_version on a brand-new plane."""
    db = await _built_plane(tmp_path)
    assert await SQLiteWikiStore(db, "t").get_meta(MIN_RUNTIME_KEY) == store_mod._running_version()


async def test_gate_blocks_older_runtime(tmp_path: Path) -> None:
    """Spec §4 — a higher schema_version raises; the message has both schemas, the stamp and the fix."""
    db = await _built_plane(tmp_path)
    _stamp(db, MIN_RUNTIME_KEY, "9.9.9")
    _stamp(db, "schema_version", "99")
    with pytest.raises(WikiStoreVersionError) as info:
        await SQLiteWikiStore(db, "t").get_meta("k")
    message = str(info.value)
    assert "schema version 99" in message and f"runtime's {store_mod.SCHEMA_VERSION}" in message
    assert "9.9.9" in message and store_mod._running_version() in message and "parrot self update" in message


async def test_gate_blocks_read_only_store(tmp_path: Path) -> None:
    """Spec §5 "read-only paths included" — _connect_immutable / _connect_readonly refuse too."""
    db = await _built_plane(tmp_path)
    _stamp(db, "schema_version", "99")
    with pytest.raises(WikiStoreVersionError) as info:
        await SQLiteWikiStore(db, "t", read_only=True).get_meta("k")
    assert info.value.store_schema == "99"


async def test_gate_blocks_writes_before_any_write(tmp_path: Path) -> None:
    """Spec §3 M7 (d) — nothing is written: no migrate restamp, no rebuild_index restamp."""
    db = await _built_plane(tmp_path)
    _stamp(db, "schema_version", "99")
    with pytest.raises(WikiStoreVersionError) as set_info:
        await SQLiteWikiStore(db, "t").set_meta("k", "w")
    assert set_info.value.store_schema == "99"
    with pytest.raises(WikiStoreVersionError) as rebuild_info:
        await SQLiteWikiStore(db, "t").rebuild_index()
    assert rebuild_info.value.store_schema == "99"
    assert _meta(db, "schema_version") == "99"
    assert _meta(db, "k") == "v"


async def test_newer_release_same_schema_opens(tmp_path: Path) -> None:
    """min_runtime_version is never compared: a same-schema plane opens."""
    db = await _built_plane(tmp_path)
    _stamp(db, MIN_RUNTIME_KEY, "99.0.0")
    assert await SQLiteWikiStore(db, "t").get_meta("k") == "v"
    assert await SQLiteWikiStore(db, "t", read_only=True).get_meta("k") == "v"
    await SQLiteWikiStore(db, "t").set_meta("k", "w")
    assert await SQLiteWikiStore(db, "t").get_meta(MIN_RUNTIME_KEY) == "99.0.0"  # an open never restamps


async def test_migration_stamps_running_version(tmp_path: Path) -> None:
    """A stale schema_version migrates and stamps min_runtime_version = running version."""
    db = await _built_plane(tmp_path)
    _stamp(db, MIN_RUNTIME_KEY, "0.0.1")  # older stamp, so only `_migrate`'s upsert can produce the running version
    _stamp(db, "schema_version", "2")
    await SQLiteWikiStore(db, "t").get_meta("k")  # first open migrates
    assert await SQLiteWikiStore(db, "t").get_meta(MIN_RUNTIME_KEY) == store_mod._running_version()


async def test_non_integer_schema_still_migrates(tmp_path: Path) -> None:
    """A non-integer stored schema_version is not refused: it is stale and migrates, as today."""
    db = await _built_plane(tmp_path)
    _stamp(db, "schema_version", "garbage")
    await SQLiteWikiStore(db, "t").get_meta("k")  # first open migrates
    assert await SQLiteWikiStore(db, "t").get_meta("schema_version") == store_mod.SCHEMA_VERSION
