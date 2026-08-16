"""Tests for ObsidianVaultLoader ingest / incremental update (FEAT-392)."""
import pytest

from parrot.loaders.obsidian import ObsidianLoader, ObsidianVaultLoader

pytestmark = pytest.mark.asyncio


class TestDiscover:
    async def test_discover_vault(self, fixture_vault):
        loader = ObsidianVaultLoader(fixture_vault)
        notes, canvases = await loader.discover()
        note_paths = {note.path.as_posix() for note in notes}
        assert "daily/2026-07-30.md" in note_paths
        assert "non-utf8.md" not in note_paths          # skipped, not fatal
        assert ".trash/old.md" not in note_paths        # skip patterns
        assert [canvas.path.as_posix() for canvas in canvases] == [
            "canvas/overview.canvas"
        ]


class TestFullIngest:
    async def test_full_ingest(self, fixture_vault, stub_pageindex, source_manager):
        loader = ObsidianVaultLoader(fixture_vault)
        report = await loader.ingest(stub_pageindex, "wiki", source_manager)
        assert report.phase == "raw_ingest"
        assert report.notes_processed == 7
        assert report.canvas_processed == 1
        assert report.nodes_created == 8
        titles = stub_pageindex.node_titles("wiki")
        assert "Daily 2026-07-30" in titles     # frontmatter title
        assert "overview" in titles             # canvas node
        # Tags become categories; obsidian extras land in node metadata.
        node = stub_pageindex.node_by_title("wiki", "ai-parrot")
        assert "project" in node["categories"]
        assert node["metadata"]["aliases"] == ["parrot", "AI Parrot"]
        assert node["metadata"]["obsidian_path"] == "projects/ai-parrot.md"

    async def test_dataview_queries_in_metadata(
        self, fixture_vault, stub_pageindex, source_manager
    ):
        loader = ObsidianVaultLoader(fixture_vault)
        await loader.ingest(stub_pageindex, "wiki", source_manager)
        node = stub_pageindex.node_by_title("wiki", "ai-parrot")
        assert node["metadata"]["dataview_queries"] == ["LIST FROM #project"]

    async def test_sources_registered(
        self, fixture_vault, stub_pageindex, source_manager
    ):
        loader = ObsidianVaultLoader(fixture_vault)
        await loader.ingest(stub_pageindex, "wiki", source_manager)
        uris = {entry.source_uri for entry in source_manager.list_sources()}
        assert any(uri.endswith("orphan.md") for uri in uris)

    async def test_circular_embeds_detected(
        self, fixture_vault, stub_pageindex, source_manager
    ):
        (fixture_vault / "cycle-a.md").write_text("![[cycle-b]]", encoding="utf-8")
        (fixture_vault / "cycle-b.md").write_text("![[cycle-a]]", encoding="utf-8")
        loader = ObsidianVaultLoader(fixture_vault)
        report = await loader.ingest(stub_pageindex, "wiki", source_manager)
        assert any("Circular embed" in error for error in report.errors)


class TestIncrementalUpdate:
    async def test_incremental_add_update_delete(
        self, fixture_vault, stub_pageindex, source_manager
    ):
        loader = ObsidianVaultLoader(fixture_vault)
        first = await loader.ingest(stub_pageindex, "wiki", source_manager)
        assert first.files_added == 8

        # Add a new note, modify one, delete one.
        (fixture_vault / "fresh.md").write_text("Brand new.", encoding="utf-8")
        (fixture_vault / "orphan.md").write_text(
            "Changed content entirely.", encoding="utf-8"
        )
        (fixture_vault / "broken-link-note.md").unlink()
        loader.vault.invalidate_index()

        second = await loader.incremental_update(
            stub_pageindex, "wiki", source_manager
        )
        assert second.files_added == 1
        assert second.files_updated >= 1
        assert second.files_deleted == 1
        assert stub_pageindex.deleted  # old node ids removed
        titles = stub_pageindex.node_titles("wiki")
        assert "fresh" in titles
        assert "broken-link-note" not in titles

    async def test_incremental_noop_when_unchanged(
        self, fixture_vault, stub_pageindex, source_manager
    ):
        loader = ObsidianVaultLoader(fixture_vault)
        await loader.ingest(stub_pageindex, "wiki", source_manager)
        report = await loader.incremental_update(
            stub_pageindex, "wiki", source_manager
        )
        assert report.files_added == 0
        assert report.files_updated == 0
        assert report.files_deleted == 0

    async def test_incremental_requires_local_backend(self, fixture_vault):
        from parrot.interfaces.obsidian import RestVaultBackend

        loader = ObsidianVaultLoader(RestVaultBackend())
        with pytest.raises(NotImplementedError):
            await loader.incremental_update(None, "wiki", None)


class TestAbstractLoaderAdapter:
    async def test_load_single_note(self, fixture_vault):
        loader = ObsidianLoader()
        documents = await loader._load(fixture_vault / "projects" / "ai-parrot.md")
        assert len(documents) == 1
        document = documents[0]
        assert "New body" not in document.page_content
        assert document.metadata["obsidian_vault"] == "vault"
        assert document.metadata["obsidian_path"] == "projects/ai-parrot.md"
        assert "project" in document.metadata["tags"]
        assert document.metadata["document_meta"]["title"] == "ai-parrot"

    async def test_load_whole_vault(self, fixture_vault):
        loader = ObsidianLoader()
        documents = await loader._load(fixture_vault)
        assert len(documents) == 7
