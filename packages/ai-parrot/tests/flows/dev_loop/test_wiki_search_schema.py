"""Tests for DevLoopWikiSearch schema (`table:` pages) context fold (FEAT-600)."""

from __future__ import annotations

import pytest

from parrot.flows.dev_loop.wiki_search import DevLoopWikiSearch
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord


class TestDevLoopWikiSchemaContext:
    """Test DevLoopWikiSearch with schema (`table:` page) context."""

    @pytest.mark.asyncio
    async def test_related_tables_block(self, tmp_path) -> None:
        """A seeded `category='table'` page matching the query surfaces a `## Related Tables` block."""
        store = SQLiteWikiStore(tmp_path / "w.db", wiki_name="w")
        await store.upsert_pages(
            [
                WikiPageRecord(
                    concept_id="table:bigquery/epson.sales",
                    title="epson.sales",
                    category="table",
                    summary="Daily sales",
                    body="sales store_id",
                )
            ]
        )
        search = DevLoopWikiSearch(store=store, wiki_name="w")
        ctx = await search.build_research_context("epson sales table", budget_tokens=800)

        assert ctx is not None
        assert "## Related Tables" in ctx
        assert "table:bigquery/epson.sales" in ctx

    @pytest.mark.asyncio
    async def test_absent_table_pages_leaves_output_unchanged(self, tmp_path) -> None:
        """No `table` pages match ⇒ no `## Related Tables` block; output is unaffected."""
        store = SQLiteWikiStore(tmp_path / "w.db", wiki_name="w")
        await store.upsert_pages(
            [
                WikiPageRecord(
                    concept_id="concept:unrelated",
                    title="Unrelated concept",
                    category="concept",
                    summary="Nothing to do with tables",
                    body="unrelated content",
                )
            ]
        )
        search = DevLoopWikiSearch(store=store, wiki_name="w")
        ctx = await search.build_research_context("epson sales table", budget_tokens=800)

        assert ctx is None or "## Related Tables" not in ctx

    @pytest.mark.asyncio
    async def test_schema_context_error_is_best_effort(self, tmp_path) -> None:
        """`search_fts` raising never breaks `build_research_context` — schema context degrades to None."""

        class BrokenStore(SQLiteWikiStore):
            async def search_fts(self, query, category=None, limit=10):
                raise RuntimeError("schema plane unavailable")

        store = BrokenStore(tmp_path / "w.db", wiki_name="w")
        search = DevLoopWikiSearch(store=store, wiki_name="w")
        ctx = await search.build_research_context("epson sales table", budget_tokens=800)

        assert ctx is None or "## Related Tables" not in ctx

    @pytest.mark.asyncio
    async def test_get_schema_context_directly(self, tmp_path) -> None:
        """`_get_schema_context` returns None when no table pages match."""
        store = SQLiteWikiStore(tmp_path / "w.db", wiki_name="w")
        search = DevLoopWikiSearch(store=store, wiki_name="w")

        result = await search._get_schema_context("epson sales table", 200)

        assert result is None
