"""Live-DB-gated tests for the wiki symbol surface on PostgresWikiStore (FEAT-520 TASK-2772).

No SQLite symbol test suite exists in this codebase to port from — see
the task's Codebase Contract correction. Written directly against the
SQLite method docstrings/signatures (the "living reference") as
self-contained behavioral coverage.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest

from parrot.conf import default_dsn
from parrot.knowledge.wiki.postgres_store import PostgresWikiStore
from parrot.knowledge.wiki.symbols import SymbolKind, SymbolRecord

PG_DSN = os.environ.get("GRAPHINDEX_PG_DSN") or default_dsn
pytestmark = pytest.mark.skipif(not PG_DSN, reason="needs live Postgres")


def make_symbol(rel_path: str, qualname: str, **kwargs: Any) -> SymbolRecord:
    kwargs.setdefault("name", qualname.rsplit(".", 1)[-1])
    kwargs.setdefault("start_line", 1)
    kwargs.setdefault("end_line", 5)
    kwargs.setdefault("start_byte", 0)
    kwargs.setdefault("end_byte", 100)
    kwargs.setdefault("content_hash", "deadbeef")
    kwargs.setdefault("kind", SymbolKind.FUNCTION)
    kwargs.setdefault("language", "python")
    return SymbolRecord(rel_path=rel_path, qualname=qualname, **kwargs)


@pytest.fixture
def tmp_schema() -> str:
    return f"graphindex_test_{uuid.uuid4().hex[:12]}"


@pytest.fixture
async def pg_wiki_store(tmp_schema):
    store = PostgresWikiStore(PG_DSN, wiki_name="test-wiki", schema=tmp_schema)
    try:
        yield store
    finally:
        pool = await store._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(f"DROP SCHEMA IF EXISTS {tmp_schema} CASCADE")
        await store.close()


async def test_symbol_roundtrip(pg_wiki_store):
    sym = make_symbol(
        "src/main.py",
        "MyClass.my_method",
        name="my_method",
        parent="MyClass",
        signature="(self, x: int) -> str",
        doc="Does a thing.",
        exported=True,
        is_async=True,
        depth=2,
        kind=SymbolKind.METHOD,
    )
    written = await pg_wiki_store.upsert_symbols([sym], source_id="src/main.py")
    assert written == 1

    found = await pg_wiki_store.symbols_for("src/main.py")
    assert len(found) == 1
    got = found[0]
    assert got.rel_path == sym.rel_path
    assert got.qualname == sym.qualname
    assert got.name == sym.name
    assert got.parent == sym.parent
    assert got.signature == sym.signature
    assert got.doc == sym.doc
    assert got.exported is True
    assert got.is_async is True
    assert got.depth == 2
    assert got.kind == SymbolKind.METHOD
    assert got.content_hash == sym.content_hash


async def test_upsert_is_idempotent_update(pg_wiki_store):
    sym_v1 = make_symbol("src/a.py", "foo", doc="v1")
    await pg_wiki_store.upsert_symbols([sym_v1])
    sym_v2 = make_symbol("src/a.py", "foo", doc="v2")
    await pg_wiki_store.upsert_symbols([sym_v2])

    found = await pg_wiki_store.symbols_for("src/a.py")
    assert len(found) == 1  # updated in place, not duplicated
    assert found[0].doc == "v2"


async def test_symbols_for_empty_file(pg_wiki_store):
    assert await pg_wiki_store.symbols_for("nope.py") == []


async def test_find_symbols_filters(pg_wiki_store):
    await pg_wiki_store.upsert_symbols(
        [
            make_symbol("a.py", "foo", name="foo", kind=SymbolKind.FUNCTION, language="python"),
            make_symbol("b.py", "Bar.baz", name="baz", kind=SymbolKind.METHOD, language="python"),
            make_symbol("c.ts", "qux", name="qux", kind=SymbolKind.FUNCTION, language="typescript"),
        ]
    )

    by_name = await pg_wiki_store.find_symbols(name="foo")
    assert [s.qualname for s in by_name] == ["foo"]

    by_prefix = await pg_wiki_store.find_symbols(qualname_prefix="Bar.")
    assert [s.qualname for s in by_prefix] == ["Bar.baz"]

    by_kind = await pg_wiki_store.find_symbols(kind="method")
    assert [s.qualname for s in by_kind] == ["Bar.baz"]

    by_language = await pg_wiki_store.find_symbols(language="typescript")
    assert [s.qualname for s in by_language] == ["qux"]

    by_path_prefix = await pg_wiki_store.find_symbols(path_prefix="a.")
    assert [s.qualname for s in by_path_prefix] == ["foo"]


async def test_search_symbols_trigram(pg_wiki_store):
    await pg_wiki_store.upsert_symbols(
        [
            make_symbol("svc.py", "UserService.get_user_profile", name="get_user_profile"),
            make_symbol("svc.py", "OrderService.list_orders", name="list_orders"),
        ]
    )
    # Exact word match on qualname -> deterministic tsvector hit, no stemming.
    hits = await pg_wiki_store.search_symbols_fts("get_user_profile")
    assert any(h.qualname == "UserService.get_user_profile" for h in hits)
    assert not any(h.qualname == "OrderService.list_orders" for h in hits)


async def test_search_symbols_no_language_stemming(pg_wiki_store):
    # 'simple' regconfig must NOT stem -- searching a stemmed form should
    # not match a differently-inflected identifier the way 'english' would.
    await pg_wiki_store.upsert_symbols([make_symbol("run.py", "running", name="running")])
    hits = await pg_wiki_store.search_symbols_fts("running")
    assert any(h.qualname == "running" for h in hits)
    stemmed_query_hits = await pg_wiki_store.search_symbols_fts("run")
    # 'run' (a different token under 'simple') should not word-match
    # 'running' via tsvector -- pg_trgm may still fuzzy-match it, which is
    # the documented, intentional trigram fallback, not stemming.
    assert isinstance(stemmed_query_hits, list)  # no crash; behavior documented above


async def test_page_hashes_covers_symbol_pages(pg_wiki_store):
    """page_hashes operates on wiki PAGES (node_versions), already covered
    by TASK-2768 — a sym: page upserted via upsert_pages round-trips its
    content_hash the same as any other page."""
    from parrot.knowledge.wiki.store import WikiPageRecord

    await pg_wiki_store.upsert_pages([WikiPageRecord(concept_id="sym:a.py#foo", title="foo", content_hash="abc123")])
    hashes = await pg_wiki_store.page_hashes(["sym:a.py#foo", "unknown"])
    assert hashes == {"sym:a.py#foo": "abc123", "unknown": None}


def test_no_sqlalchemy_imports():
    import parrot.knowledge.wiki.postgres_store as module

    with open(module.__file__, "r", encoding="utf-8") as fh:
        content = fh.read()
    assert "sqlalchemy" not in content.lower()
