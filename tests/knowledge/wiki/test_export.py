"""Tests for the OKF v0.1 export boundary (wiki/export.py)."""

from pathlib import Path

import pytest
import yaml

from parrot.knowledge.wiki.export import (
    WikiExportReport,
    category_dir,
    okf_type,
    export_okf_bundle,
)
from parrot.knowledge.wiki.store import WikiPageRecord, WikiStore


@pytest.fixture
def store(tmp_path: Path) -> WikiStore:
    return WikiStore(tmp_path / "wiki.db", wiki_name="export-wiki")


async def _seed(store: WikiStore) -> None:
    await store.upsert_pages(
        [
            WikiPageRecord(
                concept_id="neural-networks",
                node_id="0001",
                title="Neural Networks",
                category="summary",
                summary="Computational models inspired by the brain.",
                body="# Neural Networks\n\nFull body here.",
            ),
            WikiPageRecord(
                concept_id="deep-learning",
                node_id="0002",
                title="Deep Learning",
                category="entity",
                summary="Extends neural networks.",
                body="# Deep Learning\n\nMore body.",
            ),
        ]
    )
    await store.add_edges(
        [("deep-learning", "neural-networks", "references")]
    )


def _parse_front(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    _, front, body = text.split("---\n", 2)
    return yaml.safe_load(front), body


class TestHelpers:
    def test_okf_type_known_categories(self):
        assert okf_type("summary") == "Wiki Summary"
        assert okf_type("entity") == "Wiki Entity"
        assert okf_type("concept") == "Concept"

    def test_okf_type_open_fallback(self):
        assert okf_type("answer") == "Answer"
        assert okf_type("custom-thing") == "Custom-Thing"

    def test_category_dir(self):
        assert category_dir("summary") == "summaries"
        assert category_dir("entity") == "entities"
        assert category_dir("concept") == "concepts"
        assert category_dir("synthesis") == "synthesis"


class TestExportBundle:
    @pytest.mark.asyncio
    async def test_bundle_layout(self, store: WikiStore, tmp_path: Path):
        await _seed(store)
        out = tmp_path / "bundle"
        report = await export_okf_bundle(store, out, wiki_name="export-wiki")
        assert isinstance(report, WikiExportReport)
        assert report.files_written == 2
        assert report.index_generated is True
        assert (out / "index.md").exists()
        assert (out / "summaries" / "neural-networks.md").exists()
        assert (out / "entities" / "deep-learning.md").exists()

    @pytest.mark.asyncio
    async def test_frontmatter_is_okf_conformant(
        self, store: WikiStore, tmp_path: Path
    ):
        await _seed(store)
        out = tmp_path / "bundle"
        await export_okf_bundle(store, out, wiki_name="export-wiki")
        front, body = _parse_front(out / "summaries" / "neural-networks.md")
        # OKF v0.1: `type` is the only required field
        assert front["type"] == "Wiki Summary"
        assert front["title"] == "Neural Networks"
        assert front["id"] == "neural-networks"
        assert front["tags"] == ["summary"]
        assert "Full body here." in body

    @pytest.mark.asyncio
    async def test_relates_to_from_edges(self, store: WikiStore, tmp_path: Path):
        await _seed(store)
        out = tmp_path / "bundle"
        await export_okf_bundle(store, out, wiki_name="export-wiki")
        front, _ = _parse_front(out / "entities" / "deep-learning.md")
        assert front["relates_to"] == [
            {"concept": "neural-networks", "rel": "references"}
        ]

    @pytest.mark.asyncio
    async def test_index_lists_pages(self, store: WikiStore, tmp_path: Path):
        await _seed(store)
        out = tmp_path / "bundle"
        await export_okf_bundle(store, out, wiki_name="export-wiki")
        index = (out / "index.md").read_text(encoding="utf-8")
        assert index.startswith("# export-wiki")
        assert "[Neural Networks](summaries/neural-networks.md)" in index
        assert "[Deep Learning](entities/deep-learning.md)" in index

    @pytest.mark.asyncio
    async def test_empty_store_exports_index_only(
        self, store: WikiStore, tmp_path: Path
    ):
        out = tmp_path / "bundle"
        report = await export_okf_bundle(store, out, wiki_name="empty")
        assert report.files_written == 0
        assert (out / "index.md").exists()

    @pytest.mark.asyncio
    async def test_bundle_reimportable_by_okf_parser(
        self, store: WikiStore, tmp_path: Path
    ):
        """The exported files must parse with the shared OKF frontmatter
        parser — producer/consumer independence at the boundary."""
        from parrot.knowledge.okf.frontmatter import parse_frontmatter

        await _seed(store)
        out = tmp_path / "bundle"
        await export_okf_bundle(store, out, wiki_name="export-wiki")
        parsed = parse_frontmatter(
            (out / "summaries" / "neural-networks.md").read_text(encoding="utf-8")
        )
        assert parsed.type.value == "Wiki Summary"
        assert parsed.id == "neural-networks"


class TestToolkitExport:
    @pytest.mark.asyncio
    async def test_wiki_export_okf_tool(self, wiki_toolkit, tmp_path: Path):
        await wiki_toolkit.create_page(
            "test-wiki", "Some Page", "Body content.", category="summary"
        )
        out = tmp_path / "okf-out"
        result = await wiki_toolkit.export_okf("test-wiki", str(out))
        assert result["files_written"] == 1
        assert (out / "index.md").exists()
