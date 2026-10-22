"""Regression cases for FEAT-627 — transactional SQLite ``page_attrs``."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import parrot.knowledge.wiki.store as subject
from parrot.knowledge.wiki.store import (
    AttrsUnsupportedError,
    BaseWikiStore,
    SQLiteWikiStore,
    WikiPageRecord,
)


def _page(cid: str, attrs: dict[str, str] | None = None, source_id: str | None = None, **kw) -> WikiPageRecord:
    return WikiPageRecord(concept_id=cid, title=cid, attrs=attrs or {}, source_id=source_id, **kw)


def _raw_attrs(db: Path) -> list[tuple[str, str, str]]:
    conn = sqlite3.connect(db)
    try:
        return sorted(conn.execute("SELECT concept_id, key, value FROM page_attrs").fetchall())
    finally:
        conn.close()


def _drop_attrs_table(db: Path) -> None:
    conn = sqlite3.connect(db)
    try:
        conn.execute("DROP TABLE page_attrs")
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep any convention-path lookups inside tmp_path."""
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdgc"))


async def test_attrs_transaction_and_lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Attrs roll back with the page, are replaced/cleared, and die with their page."""
    db = tmp_path / "wiki.db"
    store = SQLiteWikiStore(db)
    await store.upsert_pages([_page("a", {"type": "ticket", "status": "open"})])
    assert await store.get_attrs("a") == {"type": "ticket", "status": "open"}
    assert (await store.get_page("a"))["attrs"] == {"type": "ticket", "status": "open"}

    # Replacement drops stale keys; empty attrs clears.
    await store.upsert_pages([_page("a", {"type": "ticket"})])
    assert await store.get_attrs("a") == {"type": "ticket"}
    await store.upsert_pages([_page("a")])
    assert await store.get_attrs("a") == {}

    # Forced failure after the page insert rolls back page and attrs.
    async def boom(self, conn, pages):
        raise RuntimeError("injected")

    monkeypatch.setattr(SQLiteWikiStore, "_replace_attrs_conn", boom)
    with pytest.raises(RuntimeError):
        await store.upsert_pages([_page("b", {"type": "x"})])
    monkeypatch.undo()
    assert await store.get_page("b") is None
    assert _raw_attrs(db) == []

    # CAS shares the transaction.
    assert await store.compare_and_swap_page(_page("c", {"k": "v"}, content_hash="h1"), None) is True
    assert await store.get_attrs("c") == {"k": "v"}
    assert await store.compare_and_swap_page(_page("c", {"k": "w"}, content_hash="h2"), "h1") is True
    assert await store.get_attrs("c") == {"k": "w"}
    assert await store.compare_and_swap_page(_page("c", {"k": "z"}, content_hash="h3"), "stale") is False
    assert await store.get_attrs("c") == {"k": "w"}

    # replace_source_slice: dropped pages lose attrs, replaced page gets the new set.
    await store.replace_source_slice("s1", [_page("s:1", {"a": "1"}, "s1"), _page("s:2", {"a": "2"}, "s1")])
    await store.replace_source_slice("s1", [_page("s:1", {"a": "9"}, "s1")])
    assert await store.get_attrs("s:1") == {"a": "9"}
    assert await store.get_attrs("s:2") == {}
    # delete_page removes attrs with no orphans.
    assert await store.delete_page("s:1") is True
    assert await store.delete_page("c") is True
    assert _raw_attrs(db) == []


async def test_v3_migration_and_readonly(tmp_path: Path) -> None:
    """A legacy v3 plane gains the table on write; read-only reports unsupported."""
    assert subject.SCHEMA_VERSION == "3"
    db = tmp_path / "wiki.db"
    await SQLiteWikiStore(db).upsert_pages([_page("a")])
    _drop_attrs_table(db)

    ro = SQLiteWikiStore(db, read_only=True)
    assert await ro.get_attrs("a") == {}
    assert await ro.list_by_attrs({"type": "x"}) == []
    assert (await ro.stats())["attrs_pages"] == 0
    assert (await ro.get_page("a"))["attrs"] == {}
    assert ro.supports_attrs is False
    with pytest.raises(PermissionError):
        await ro.upsert_attrs("a", {"k": "v"})
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("SELECT count(*) FROM sqlite_master WHERE name='page_attrs'").fetchone()[0] == 0
    finally:
        conn.close()

    rw = SQLiteWikiStore(db)
    assert await rw.upsert_attrs("a", {"type": "ticket"}) == 1
    assert await rw.get_attrs("a") == {"type": "ticket"}
    assert rw.supports_attrs is True
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "3"
    finally:
        conn.close()
    ro2 = SQLiteWikiStore(db, read_only=True)
    assert await ro2.get_attrs("a") == {"type": "ticket"}
    assert ro2.supports_attrs is True


async def test_filters_merge_and_unsupported(tmp_path: Path) -> None:
    """AND/IN/date filtering, merge/replace, missing pages, stats and base defaults."""
    store = SQLiteWikiStore(tmp_path / "wiki.db")
    await store.upsert_pages(
        [
            _page("t1", {"type": "ticket", "status": "open", "date": "2026-10-01"}),
            _page("t2", {"type": "ticket", "status": "done", "date": "2026-10-03"}),
            _page("n1", {"type": "note", "status": "open", "date": "2026-10-05"}),
            _page("plain"),
        ]
    )

    def ids(rows):
        return sorted(r["concept_id"] for r in rows)

    assert ids(await store.list_by_attrs({"type": "ticket"})) == ["t1", "t2"]
    assert ids(await store.list_by_attrs({"type": "ticket", "status": "open"})) == ["t1"]
    assert ids(await store.list_by_attrs({"status": ["open", "done"]})) == ["n1", "t1", "t2"]
    assert await store.list_by_attrs({"status": []}) == []
    assert ids(await store.list_by_attrs({}, date_key="date", since="2026-10-03", until="2026-10-05")) == ["n1", "t2"]
    assert ids(await store.list_by_attrs({"type": "ticket"}, date_key="date", until="2026-10-01")) == ["t1"]
    # Empty filters, no dates: every attr-bearing page; limit honoured; no body leaked.
    rows = await store.list_by_attrs({}, limit=2)
    assert len(rows) == 2 and "body" not in rows[0]
    assert ids(await store.list_by_attrs({})) == ["n1", "t1", "t2"]
    # Hostile key/value are bound, not interpolated.
    assert await store.list_by_attrs({"type' OR '1'='1": "x"}) == []
    with pytest.raises(ValueError):
        await store.list_by_attrs({}, since="2026-10-01")

    # Merge vs replace; missing page writes nothing.
    assert await store.upsert_attrs("t1", {"owner": "me"}, replace=False) == 1
    assert await store.get_attrs("t1") == {"type": "ticket", "status": "open", "date": "2026-10-01", "owner": "me"}
    assert await store.upsert_attrs("t1", {"owner": "you"}) == 1
    assert await store.get_attrs("t1") == {"owner": "you"}
    assert await store.upsert_attrs("ghost", {"a": "b"}) == 0
    assert await store.get_attrs("ghost") == {}

    # Distinct attr-bearing pages (t1, t2, n1).
    assert (await store.stats())["attrs_pages"] == 3

    # Base defaults: non-abstract, unsupported, no network needed.
    assert BaseWikiStore.supports_attrs is False
    from parrot.knowledge.wiki.arango_store import ArangoDBWikiStore
    from parrot.knowledge.wiki.postgres_store import PostgresWikiStore

    for cls in (ArangoDBWikiStore, PostgresWikiStore):
        assert cls.supports_attrs is False
        assert await cls.get_attrs(object.__new__(cls), "x") == {}
        assert await cls.list_by_attrs(object.__new__(cls), {"a": "b"}) == []
        with pytest.raises(AttrsUnsupportedError):
            await cls.upsert_attrs(object.__new__(cls), "x", {"a": "b"})
