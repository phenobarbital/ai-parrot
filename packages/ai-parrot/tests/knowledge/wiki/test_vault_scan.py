"""Tests for the wikitoolkit Obsidian vault build mode (Phase E)."""
import pytest

from parrot.knowledge.wiki.vault_scan import (
    is_obsidian_vault,
    scan_vault,
    tag_concept_id,
)
from tests.interfaces.obsidian.conftest import fixture_vault  # noqa: F401


@pytest.fixture
def scanned(fixture_vault):
    return scan_vault(fixture_vault)


class TestDetection:
    def test_detects_vault(self, fixture_vault):
        assert is_obsidian_vault(fixture_vault) is True

    def test_plain_dir_not_vault(self, tmp_path):
        assert is_obsidian_vault(tmp_path) is False


class TestScanPages:
    def test_note_pages(self, scanned):
        scan, stats = scanned
        assert stats.notes == 7
        by_id = {fs.record.concept_id: fs.record for fs in scan.files}
        record = by_id["file:projects/ai-parrot.md"]
        assert record.category == "document"
        assert record.title == "ai-parrot"
        # Tags + aliases rendered into the body so FTS finds them.
        assert "#project" in record.body
        assert "Aliases: parrot, AI Parrot" in record.body
        assert record.token_count > 0

    def test_summary_from_first_line(self, scanned):
        scan, _ = scanned
        by_id = {fs.record.concept_id: fs.record for fs in scan.files}
        assert by_id["file:orphan.md"].summary.startswith("Just a lonely note")

    def test_vault_internals_skipped(self, scanned):
        scan, _ = scanned
        ids = {fs.record.concept_id for fs in scan.files}
        assert not any(".obsidian" in cid or ".trash" in cid for cid in ids)

    def test_non_utf8_skipped(self, scanned):
        scan, _ = scanned
        assert "non-utf8.md" in scan.skipped

    def test_tag_pages(self, scanned):
        scan, stats = scanned
        tag_records = {
            record.concept_id: record
            for record in scan.dir_records
            if record.category == "tag"
        }
        assert tag_concept_id("daily") in tag_records
        daily = tag_records[tag_concept_id("daily")]
        assert daily.title == "#daily"
        assert "file:daily/2026-07-30.md" in daily.body
        assert stats.tags == len(tag_records)


class TestScanEdges:
    def test_wikilink_reference_edges(self, scanned):
        scan, _ = scanned
        assert (
            "file:daily/2026-07-30.md",
            "file:projects/ai-parrot.md",
            "references",
        ) in scan.import_edges

    def test_embed_edges(self, scanned):
        scan, stats = scanned
        embeds = [edge for edge in scan.import_edges if edge[2] == "embeds"]
        assert stats.embed_edges == len(embeds)

    def test_unresolved_dropped_but_counted(self, scanned):
        scan, stats = scanned
        targets = {edge[1] for edge in scan.import_edges}
        assert not any("nonexistent-target" in target for target in targets)
        assert ("broken-link-note.md", "nonexistent-target") in stats.unresolved_links

    def test_tagged_edges(self, scanned):
        scan, _ = scanned
        assert (
            "file:projects/ai-parrot.md",
            tag_concept_id("project"),
            "tagged",
        ) in scan.dir_edges

    def test_directory_contains_edges(self, scanned):
        scan, _ = scanned
        assert (
            "dir:daily",
            "file:daily/2026-07-30.md",
            "contains",
        ) in scan.dir_edges


class TestStorePlane:
    @pytest.mark.asyncio
    async def test_fts_and_backlinks_through_sqlite(
        self, fixture_vault, tmp_path
    ):
        """End-to-end: scan → SQLiteWikiStore → FTS hit + backlink query."""
        from parrot.knowledge.wiki.store import create_wiki_store

        scan, _ = scan_vault(fixture_vault)
        store = create_wiki_store(tmp_path / "wiki", wiki_name="vault")
        await store.upsert_pages([fs.record for fs in scan.files])
        await store.upsert_pages(scan.dir_records)
        await store.add_edges(scan.import_edges)
        await store.add_edges(scan.dir_edges)

        # FTS search finds notes by tag text rendered into the body.
        hits = await store.search_fts("machine learning", limit=5)
        assert any("machine-learning" in hit["concept_id"] for hit in hits)

        # Backlinks: incoming 'references' edges to the ML note.
        neighbors = await store.neighbors(
            "file:concepts/machine-learning.md", direction="in"
        )
        sources = {row["concept_id"] for row in neighbors}
        assert "file:daily/2026-07-30.md" in sources

        # Tag page reachable via the 'tagged' relation.
        tagged = await store.neighbors(
            tag_concept_id("project"), rel="tagged", direction="in"
        )
        assert any(
            row["concept_id"] == "file:projects/ai-parrot.md" for row in tagged
        )


class TestRepoScanExclusions:
    def test_repo_scan_never_descends_into_vault_internals(self):
        from parrot.knowledge.wiki.repo_scan import DEFAULT_EXCLUDE_DIRS

        assert ".obsidian" in DEFAULT_EXCLUDE_DIRS
        assert ".trash" in DEFAULT_EXCLUDE_DIRS
