"""The S2 sqlite prototype must never leave an aiosqlite worker thread behind on failure.

An unclosed ``aiosqlite`` connection owns a non-daemon thread; after an exception the
interpreter (and the Bubblewrap sandbox around it) hangs instead of exiting.
"""

from __future__ import annotations

from pathlib import Path
import threading

import pytest

from .sqlite_prototype import SQLiteEpisodeBackend


def _aiosqlite_threads() -> set[str]:
    return {t.name for t in threading.enumerate() if "_connection_worker_thread" in t.name}


async def test_failed_configure_closes_connection(tmp_path: Path) -> None:
    db_path = tmp_path / "s2.sqlite"
    db_path.write_bytes(b"this is not a sqlite database")  # connect() is lazy; the first PRAGMA raises
    before = _aiosqlite_threads()
    backend = SQLiteEpisodeBackend(db_path)
    with pytest.raises(Exception):
        await backend.configure()
    assert backend._db is None
    assert _aiosqlite_threads() == before
