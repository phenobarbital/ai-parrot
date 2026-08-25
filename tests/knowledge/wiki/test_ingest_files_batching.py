"""The build pipeline's manifest phase must scale by BATCH, not by file.

`_ingest_files` used to call the per-file manifest API (find_by_uri,
add_source, is_stale, mark_ingested) once per scanned file. On a local
sqlite manifest that is invisible; on a server-hosted one (ArangoDB) each
call is a network round trip, which measured ~0.5s per file — ~80 minutes
for a 9k-file corpus. These tests pin the batching down by COUNTING the
manifest operations, so a refactor that quietly reintroduces a per-file
call fails here rather than in production wall-clock.
"""

import asyncio
from pathlib import Path

import pytest
from parrot.knowledge.wiki import cli
from parrot.knowledge.wiki.repo_scan import FileSlice, RepoScan
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.store import WikiPageRecord


class CountingSources(SourceCollectionManager):
    """A real manifest that tallies every call the pipeline makes."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls: dict[str, int] = {}

    def _tally(self, name: str) -> None:
        self.calls[name] = self.calls.get(name, 0) + 1

    # --- per-file API (must NOT be used by the pipeline) --------------
    def find_by_uri(self, source_uri):
        self._tally("find_by_uri")
        return super().find_by_uri(source_uri)

    def add_source(self, path):
        self._tally("add_source")
        return super().add_source(path)

    def is_stale(self, source_id):
        self._tally("is_stale")
        return super().is_stale(source_id)

    def mark_ingested(self, source_id, pages_generated, status="ingested"):
        self._tally("mark_ingested")
        return super().mark_ingested(source_id, pages_generated, status)

    # --- batch API ----------------------------------------------------
    def find_entries_by_uris(self, uris):
        self._tally("find_entries_by_uris")
        return super().find_entries_by_uris(uris)

    def add_sources(self, paths, known=None):
        self._tally("add_sources")
        return super().add_sources(paths, known)

    def mark_ingested_many(self, pages_by_source, status="ingested"):
        self._tally("mark_ingested_many")
        return super().mark_ingested_many(pages_by_source, status)


class FakeStore:
    """Minimal BaseWikiStore stand-in recording what the pipeline writes."""

    def __init__(self, pages: int = 0):
        self._pages = pages
        self.upserted: list = []
        self.edges: list = []
        self.slices: list = []

    async def stats(self):
        return {"pages": self._pages}

    async def upsert_pages(self, records):
        self.upserted.extend(records)
        return len(records)

    async def add_edges(self, edges):
        self.edges.extend(edges)
        return len(edges)

    async def replace_source_slice(self, source_id, records, edges):
        self.slices.append((source_id, records, edges))
        return {"pages_written": len(records)}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    for i in range(12):
        (root / f"mod{i}.py").write_text(f"def f{i}():\n    return {i}\n")
    return root


def _scan(root: Path) -> RepoScan:
    files = [
        FileSlice(
            rel_path=path.name,
            record=WikiPageRecord(
                concept_id=f"file:{path.name}",
                title=path.name,
                category="module",
                summary=f"summary of {path.name}",
                body="body",
            ),
        )
        for path in sorted(root.glob("*.py"))
    ]
    return RepoScan(root=root, files=files)


def _run(root: Path, sources: CountingSources, store: FakeStore, force: bool = False):
    return asyncio.run(cli._ingest_files(store, sources, root, _scan(root), force=force))


class TestManifestBatching:
    def test_manifest_calls_do_not_scale_with_file_count(self, repo, tmp_path):
        sources = CountingSources(tmp_path / "sources")
        store = FakeStore()

        result = _run(repo, sources, store)

        assert result["written"] == 12
        # One read, one registration, one mark — regardless of 12 files.
        # One read, one registration, one mark — regardless of file count.
        # The registration reuses the read (`known=`), so it costs nothing
        # extra: three manifest operations for twelve files, or twelve
        # thousand.
        assert sources.calls == {
            "find_entries_by_uris": 1,
            "add_sources": 1,
            "mark_ingested_many": 1,
        }, sources.calls

    def test_no_per_file_manifest_call_survives(self, repo, tmp_path):
        sources = CountingSources(tmp_path / "sources")

        _run(repo, sources, FakeStore())

        for banned in ("find_by_uri", "add_source", "is_stale", "mark_ingested"):
            assert banned not in sources.calls, f"{banned} is per-file — it must not be in the loop"

    def test_every_page_and_source_still_lands(self, repo, tmp_path):
        sources = CountingSources(tmp_path / "sources")
        store = FakeStore()

        _run(repo, sources, store)

        assert len(store.upserted) == 12
        tracked = sources.list_sources()
        assert len(tracked) == 12
        assert all(e.pages_generated for e in tracked), "each source records its page"
        assert all(e.status == "ingested" for e in tracked)

    def test_second_run_reports_everything_unchanged(self, repo, tmp_path):
        sources = CountingSources(tmp_path / "sources")
        _run(repo, sources, FakeStore())

        store = FakeStore(pages=12)
        result = _run(repo, sources, store)

        assert result == {"written": 0, "unchanged": 12}
        assert store.upserted == [] and store.slices == []
        # Nothing to register: the batch write is skipped entirely.
        assert sources.calls.get("add_sources", 0) == 2  # called with an empty list
        assert "mark_ingested_many" not in sources.calls or result["written"] == 0

    def test_only_changed_files_are_reingested(self, repo, tmp_path):
        sources = CountingSources(tmp_path / "sources")
        _run(repo, sources, FakeStore())
        (repo / "mod3.py").write_text("def f3():\n    return 'changed'\n")

        store = FakeStore(pages=12)
        result = _run(repo, sources, store)

        assert result == {"written": 1, "unchanged": 11}
        # Non-fresh plane → the changed file goes through replace_source_slice.
        assert len(store.slices) == 1
        assert store.slices[0][1][0].concept_id == "file:mod3.py"

    def test_force_reingests_everything(self, repo, tmp_path):
        sources = CountingSources(tmp_path / "sources")
        _run(repo, sources, FakeStore())

        store = FakeStore(pages=12)
        result = _run(repo, sources, store, force=True)

        assert result == {"written": 12, "unchanged": 0}
        assert len(store.slices) == 12

    def test_manifest_is_marked_only_after_the_pages_land(self, repo, tmp_path):
        """A store failure must not leave the manifest claiming success."""

        class ExplodingStore(FakeStore):
            async def upsert_pages(self, records):
                raise RuntimeError("plane write failed")

        sources = CountingSources(tmp_path / "sources")

        with pytest.raises(RuntimeError, match="plane write failed"):
            _run(repo, sources, ExplodingStore())

        assert "mark_ingested_many" not in sources.calls
        assert all(e.pages_generated == [] for e in sources.list_sources())
