from __future__ import annotations

import pytest

from parrot.knowledge.wiki.arango_store import SYMBOLS_COLLECTION, ArangoDBWikiStore, document_key
from parrot.knowledge.wiki.symbols import SymbolKind, SymbolRecord, sym_concept_id


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> ArangoDBWikiStore:
    """Return a store whose AQL layer records calls without a live database."""
    instance = ArangoDBWikiStore(arango_params={}, database="db", wiki_name="w", text_analyzer="text_en")
    calls: list[tuple[str, dict[str, object]]] = []

    async def fake_query(aql: str, bind_vars: dict[str, object]) -> list[object]:
        calls.append((aql, bind_vars))
        return fake_query.rows

    fake_query.rows: list[object] = []

    async def noop() -> None:
        return None

    monkeypatch.setattr(instance, "_query", fake_query)
    monkeypatch.setattr(instance, "_ensure_init", noop)
    instance._calls = calls
    instance._fake_query = fake_query
    return instance


def _rec(name: str = "f", path: str = "x.py") -> SymbolRecord:
    """Build a complete symbol fixture."""
    return SymbolRecord(
        rel_path=path,
        language="python",
        kind=SymbolKind.FUNCTION,
        name=name,
        qualname=name,
        start_line=1,
        end_line=2,
        start_byte=0,
        end_byte=9,
        content_hash="hash",
    )


@pytest.mark.asyncio
async def test_upsert_symbols_slice_semantics(store: ArangoDBWikiStore) -> None:
    """Source-scoped upserts remove stale rows and write keyed documents."""
    written = await store.upsert_symbols([_rec("a"), _rec("b")], source_id="file:x.py")

    assert written == 2
    remove, upsert = store._calls
    assert "REMOVE" in remove[0]
    assert remove[1]["@c"] == SYMBOLS_COLLECTION
    assert remove[1]["sid"] == "file:x.py"
    assert len(remove[1]["keep"]) == 2
    assert upsert[1]["docs"][0]["_key"] == document_key(sym_concept_id("x.py", "a"))
    assert upsert[1]["docs"][0]["kind"] == "function"


@pytest.mark.asyncio
async def test_symbols_for_roundtrip(store: ArangoDBWikiStore) -> None:
    """Stored symbol documents decode without losing byte offsets."""
    store._fake_query.rows = [store._symbol_doc(_rec(), "file:x.py", "2026-01-01T00:00:00Z")]

    records = await store.symbols_for("x.py")

    assert records[0].qualname == "f"
    assert records[0].start_byte == 0
    assert records[0].end_byte == 9


@pytest.mark.asyncio
async def test_find_symbols_builds_filters_and_limit(store: ArangoDBWikiStore) -> None:
    """Filtered lookups include exact filters and a bounded result set."""
    await store.find_symbols(name="f", kind="function", language="python", path_prefix="src/")

    aql, bind_vars = store._calls[0]
    assert "s.name == @name" in aql
    assert "s.kind == @kind" in aql
    assert "s.language == @language" in aql
    assert "STARTS_WITH(s.rel_path, @path_prefix)" in aql
    assert "LIMIT @limit" in aql
    assert bind_vars["name"] == "f"


@pytest.mark.asyncio
async def test_search_symbols_fts_targets_symbols_view(store: ArangoDBWikiStore) -> None:
    """Full-text symbol search uses the dedicated symbols view."""
    await store.search_symbols_fts("parse")

    aql, _ = store._calls[0]
    assert "w_symbols_view" in aql
    assert "BM25(s) DESC" in aql


@pytest.mark.asyncio
async def test_replace_source_slice_removes_symbols(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replacing a source slice removes its native symbol rows."""
    instance = ArangoDBWikiStore(arango_params={}, database="db", wiki_name="w")
    calls: list[tuple[str, dict[str, object]]] = []

    async def fake_query(aql: str, bind_vars: dict[str, object]) -> list[object]:
        calls.append((aql, bind_vars))
        return []

    async def fake_execute(aql: str, bind_vars: dict[str, object]) -> list[object]:
        calls.append((aql, bind_vars))
        return []

    async def noop() -> None:
        return None

    monkeypatch.setattr(instance, "_query", fake_query)
    monkeypatch.setattr(instance, "_execute", fake_execute)
    monkeypatch.setattr(instance, "_ensure_init", noop)
    monkeypatch.setattr(instance, "upsert_pages", lambda pages: _completed(0))

    await instance.replace_source_slice("file:x.py", [])

    assert any(
        SYMBOLS_COLLECTION in aql and "s.source_id == @sid" in aql and "REMOVE" in aql
        for aql, _ in calls
    )


async def _completed(value: int) -> int:
    """Return an awaitable result for the page-upsert stub."""
    return value
