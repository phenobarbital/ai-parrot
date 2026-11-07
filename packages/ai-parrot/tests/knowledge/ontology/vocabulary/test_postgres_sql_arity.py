"""SQL placeholder/argument arity of PostgresOntologyStore reads, checked without a live server (FEAT-824)."""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import pytest

from parrot.knowledge.ontology.vocabulary.postgres_store import PostgresOntologyStore

_ROW = {
    "current_version": 2,
    "iri": "https://x/a",
    "kind": "class",
    "pref_label": "A",
    "definition": None,
    "deprecated": False,
    "replaced_by": None,
    "object_iri": "https://x/b",
    "predicate": "p",
    "is_exact": True,
    "sim": 0.9,
}


class _Conn:
    """Records every statement and answers with one universal row."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any]:
        self.calls.append((sql, args))
        return dict(_ROW)

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        self.calls.append((sql, args))
        return [dict(_ROW)]


class _Pool:
    def __init__(self, conn: _Conn) -> None:
        self.conn = conn

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[_Conn]:
        yield self.conn


def _store() -> tuple[PostgresOntologyStore, _Conn]:
    conn = _Conn()
    return PostgresOntologyStore(_Pool(conn), schema="ontology_store"), conn


def _assert_arity(conn: _Conn) -> None:
    """Every statement uses exactly the placeholders $1..$N for its N bound arguments."""
    assert conn.calls
    for sql, args in conn.calls:
        used = {int(number) for number in re.findall(r"\$(\d+)", sql)}
        assert used == set(range(1, len(args) + 1)), (sql, args)


@pytest.mark.asyncio
async def test_get_arity() -> None:
    store, conn = _store()
    assert (await store.get("o", "https://x/a")) is not None
    _assert_arity(conn)


@pytest.mark.asyncio
@pytest.mark.parametrize("predicate", [None, "p"])
async def test_neighbors_arity(predicate: str | None) -> None:
    store, conn = _store()
    assert await store.neighbors("o", "https://x/a", predicate) == [("p", "https://x/b")]
    _assert_arity(conn)


@pytest.mark.asyncio
async def test_canonical_arity() -> None:
    store, conn = _store()
    assert await store.canonical("o", ["https://x/a"]) == {}
    _assert_arity(conn)


@pytest.mark.asyncio
@pytest.mark.parametrize("lang", [None, "es"])
@pytest.mark.parametrize("kinds", [None, ["class"]])
@pytest.mark.parametrize("embedding", [None, [0.1, 0.2]])
async def test_resolve_arity(lang: str | None, kinds: list[str] | None, embedding: list[float] | None) -> None:
    store, conn = _store()
    results = await store.resolve("o", "A", lang=lang, kinds=kinds, embedding=embedding)
    assert results and results[0].concept.iri == "https://x/a" and results[0].matched_by == "exact"
    _assert_arity(conn)


@pytest.mark.asyncio
@pytest.mark.parametrize("direction", ["down", "up", "both"])
@pytest.mark.parametrize("max_depth", [None, 3])
@pytest.mark.parametrize("include_deprecated", [True, False])
async def test_expand_arity(direction: str, max_depth: int | None, include_deprecated: bool) -> None:
    store, conn = _store()
    found = await store.expand(
        "o", ["https://x/seed"], direction=direction, max_depth=max_depth, include_deprecated=include_deprecated
    )
    assert "https://x/seed" in found
    _assert_arity(conn)
    sql = " ".join(call[0] for call in conn.calls)
    assert sql.count("FROM ontology_store.closure") == (2 if direction == "both" else 1)
