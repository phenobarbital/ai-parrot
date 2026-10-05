"""Mock-based lint coverage for the ArangoDB backend (FEAT-625 AC7)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from parrot.knowledge.lint import LintOptions, LintRunner
from parrot.knowledge.wiki.arango_store import ArangoDBWikiStore


def _arango_store(pages: list[dict], edges: list[dict]) -> ArangoDBWikiStore:
    """An ArangoDBWikiStore whose read surface is mocked (no server needed)."""
    store = object.__new__(ArangoDBWikiStore)
    store.dump_pages = AsyncMock(return_value=pages)
    store.dump_edges = AsyncMock(return_value=edges)
    store.list_pages = AsyncMock(return_value=pages)
    store.broken_edges = AsyncMock(return_value=[e for e in edges if e["dst"] not in {p["concept_id"] for p in pages}])
    store.orphan_sources = AsyncMock(return_value=[])
    store.missing_bodies = AsyncMock(return_value=[])
    store.stats = AsyncMock(return_value={"pages": len(pages), "edges": len(edges)})
    return store


@pytest.mark.asyncio
async def test_lint_runs_on_arango_store_and_flags_broken_link() -> None:
    """Rules run against an Arango-typed store; a dangling edge is reported as broken-link."""
    pages = [{"concept_id": "a", "title": "a"}, {"concept_id": "b", "title": "b"}]
    edges = [{"src": "a", "dst": "ghost", "rel": "references", "provenance": "asserted"}]
    runner = LintRunner(_arango_store(pages, edges))

    report = await runner.run(LintOptions(fix=False, ledger=False, notes=False))

    assert any(f.rule_id == "broken-link" for f in report.findings), report.findings
    assert report.fixed == []


@pytest.mark.asyncio
async def test_arango_index_hooks_default_to_noop() -> None:
    """Arango has no derived index: rebuild/drift inherit the clean no-op defaults."""
    store = _arango_store([], [])
    assert await store.index_drift() == {}
    assert await store.rebuild_index() == {"rebuilt": []}
