"""FEAT-498 TASK-2748 — atomic symbol-plane ingest, sqlite + memory."""

from __future__ import annotations

from pathlib import Path

import pytest
from parrot.knowledge.wiki import cli
from parrot.knowledge.wiki.repo_scan import scan_repository
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.store import BaseWikiStore, create_wiki_store


def _write(root: Path, rel: str, content: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture(params=["sqlite", "memory"])
def store(tmp_path: Path, request: pytest.FixtureRequest) -> BaseWikiStore:
    return create_wiki_store(tmp_path / "wiki", wiki_name="test-wiki", backend=request.param)


@pytest.fixture
def sources(tmp_path: Path) -> SourceCollectionManager:
    return SourceCollectionManager(tmp_path / "wiki" / "sources")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _write(root, "a.py", "def helper():\n    return 1\n")
    _write(root, "b.py", "from a import helper\n\n\ndef run():\n    return helper()\n")
    return root


class TestAtomicSymbolIngest:
    @pytest.mark.asyncio
    async def test_symbol_pages_carry_source_id(self, repo, sources, store):
        scan = scan_repository(repo, use_git=False)
        await cli._ingest_files(store, sources, repo, scan)

        pages = await store.list_pages(category="symbol", limit=100)
        assert len(pages) == 2
        for page in pages:
            assert page["source_id"]

    @pytest.mark.asyncio
    async def test_reingest_same_content_no_duplicates(self, repo, sources, store):
        scan1 = scan_repository(repo, use_git=False)
        await cli._ingest_files(store, sources, repo, scan1)

        scan2 = scan_repository(repo, use_git=False)
        result = await cli._ingest_files(store, sources, repo, scan2)

        assert result["written"] == 0
        assert result["unchanged"] == 2
        pages = await store.list_pages(category="symbol", limit=100)
        assert len(pages) == 2

    @pytest.mark.asyncio
    async def test_no_broken_edges(self, repo, sources, store):
        scan = scan_repository(repo, use_git=False)
        await cli._ingest_files(store, sources, repo, scan)
        assert await store.broken_edges() == []

    @pytest.mark.asyncio
    async def test_forced_reingest_replaces_slice_atomically(self, repo, sources, store):
        scan1 = scan_repository(repo, use_git=False)
        await cli._ingest_files(store, sources, repo, scan1)

        # Rename the function -> the old sym: page must disappear, not
        # accumulate alongside the new one.
        _write(repo, "a.py", "def renamed_helper():\n    return 1\n")
        scan2 = scan_repository(repo, use_git=False)
        result = await cli._ingest_files(store, sources, repo, scan2, force=True)
        assert result["written"] == 2

        pages = await store.list_pages(category="symbol", limit=100)
        titles = {p["title"] for p in pages}
        assert "helper" not in titles
        assert "renamed_helper" in titles

    @pytest.mark.asyncio
    async def test_content_hash_persists(self, repo, sources, store):
        scan = scan_repository(repo, use_git=False)
        await cli._ingest_files(store, sources, repo, scan)
        page = await store.get_page("file:a.py", include_body=False)
        assert page is not None
        assert page["content_hash"]
        hashes = await store.page_hashes(["file:a.py", "sym:a.py#helper"])
        assert hashes["file:a.py"] == page["content_hash"]
        assert hashes["sym:a.py#helper"]

    @pytest.mark.asyncio
    async def test_symbols_for_file(self, repo, sources, store):
        scan = scan_repository(repo, use_git=False)
        await cli._ingest_files(store, sources, repo, scan)
        symbols = await store.symbols_for("a.py")
        assert [s.qualname for s in symbols] == ["helper"]
