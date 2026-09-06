"""Structural ebook regression tests using real generated EPUB containers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from parrot.loaders.ebook import EbookSection, ebook_sections
from parrot_loaders.epubloader import EpubLoader

epub = pytest.importorskip("ebooklib.epub")
pytest.importorskip("bs4")
pytest.importorskip("markdownify")


@pytest.fixture
def nested_epub(tmp_path: Path) -> Path:
    book = epub.EpubBook()
    book.set_identifier("synthetic-structure-fixture")
    book.set_title("Structured Book")
    book.set_language("en")
    one = epub.EpubHtml(title="Chapter One", file_name="text/one.xhtml")
    one.content = (
        '<h1>Chapter One</h1><p>ALPHACONTENT</p><div><h2 id="sub">Subsection</h2>'
        '<p>BETACONTENT</p><h3 id="deep">Deep Section</h3><p>GAMMACONTENT</p></div>'
    )
    two = epub.EpubHtml(title="Chapter Two", file_name="text/two.xhtml")
    two.content = "<h1>Chapter Two</h1><p>DELTACONTENT</p>"
    book.add_item(one)
    book.add_item(two)
    book.toc = [
        (
            epub.Section("Part One"),
            [
                (
                    epub.Link("text/one.xhtml", "Chapter One", "one"),
                    [
                        (
                            epub.Link("text/one.xhtml#sub", "Subsection", "sub"),
                            [
                                epub.Link("text/one.xhtml#deep", "Deep Section", "deep"),
                            ],
                        ),
                        epub.Link("text/one.xhtml#missing", "Missing Target", "missing"),
                    ],
                ),
                epub.Link("text/two.xhtml", "Chapter Two", "two"),
            ],
        ),
    ]
    book.spine = ["nav", one, two]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    path = tmp_path / "structured.epub"
    epub.write_epub(str(path), book)
    return path


@pytest.mark.asyncio
async def test_nested_toc_and_exact_content(nested_epub: Path) -> None:
    documents = await EpubLoader(nested_epub)._load(nested_epub)
    sections = ebook_sections(documents)
    by_title = {s.title: s for s in sections}
    assert len(sections) == 6
    part = by_title["Part One"]
    chapter = by_title["Chapter One"]
    sub = by_title["Subsection"]
    deep = by_title["Deep Section"]
    assert chapter.parent_id == part.section_id
    assert sub.parent_id == chapter.section_id
    assert deep.parent_id == sub.section_id
    assert sub.href == "text/one.xhtml#sub"
    assert deep.depth == 4
    assert chapter.content == "ALPHACONTENT"
    assert sub.content == "BETACONTENT"
    assert deep.content == "GAMMACONTENT"
    assert by_title["Chapter Two"].content == "DELTACONTENT"
    assert not by_title["Missing Target"].target_found
    assert by_title["Missing Target"].content == ""
    assert all(s.source_uri == str(nested_epub) for s in sections)
    again = ebook_sections(await EpubLoader(nested_epub)._load(nested_epub))
    assert [s.section_id for s in again] == [s.section_id for s in sections]


@pytest.mark.asyncio
async def test_full_book_and_toc_output(nested_epub: Path) -> None:
    documents = await EpubLoader(
        nested_epub,
        per_chapter=False,
        include_toc_document=True,
        min_section_length=1000,
    )._load(nested_epub)
    assert documents[0].metadata["content_type"] == "toc"
    assert "    - [Subsection](text/one.xhtml#sub)" in documents[0].page_content
    sections = ebook_sections(documents)
    assert len(sections) == 6
    assert all(
        marker in documents[1].page_content
        for marker in [
            "ALPHACONTENT",
            "BETACONTENT",
            "GAMMACONTENT",
            "DELTACONTENT",
        ]
    )


def test_no_toc_heading_fallback() -> None:
    loader = EpubLoader()
    sections: list[EbookSection] = []
    loader._partition_item(
        "book.xhtml",
        "<h1>Chapter</h1><p>Alpha</p><h2>Section</h2><p>Beta</p>" "<h1>Next</h1><p>Gamma</p>",
        sections,
        0,
    )
    chapter, section, following = sections
    assert section.parent_id == chapter.section_id
    assert following.parent_id is None
    assert [s.content for s in sections] == ["Alpha", "Beta", "Gamma"]


@pytest.mark.asyncio
async def test_wiki_acquires_every_section(nested_epub: Path) -> None:
    from parrot.knowledge.wiki.documents import DocumentAcquirer, DocumentRef

    acquired = await DocumentAcquirer().acquire(DocumentRef(uri=str(nested_epub), suffix=".epub"))
    assert len(acquired.ebook_sections) == 6
    assert all(
        marker in acquired.text
        for marker in [
            "ALPHACONTENT",
            "BETACONTENT",
            "GAMMACONTENT",
            "DELTACONTENT",
        ]
    )


@pytest.mark.asyncio
async def test_pageindex_keeps_small_nodes_and_parents(nested_epub: Path, tmp_path: Path) -> None:
    from parrot.knowledge.pageindex.toolkit import PageIndexToolkit

    sections = ebook_sections(await EpubLoader(nested_epub)._load(nested_epub))
    toolkit = PageIndexToolkit(adapter=SimpleNamespace(model="offline"), storage_dir=tmp_path / "trees")
    await toolkit.create_tree("book")
    result = await toolkit.insert_ebook("book", [s.model_dump() for s in sections])
    assert len(result["new_node_ids"]) == 6
    tree = await toolkit.get_tree("book")
    part = tree["structure"][0]
    chapter = part["nodes"][0]
    sub = chapter["nodes"][0]
    assert (part["title"], chapter["title"], sub["title"]) == ("Part One", "Chapter One", "Subsection")
    assert sub["nodes"][0]["title"] == "Deep Section"
    assert sub["metadata"]["href"] == "text/one.xhtml#sub"
    assert "text" not in sub
    assert toolkit._content_store.load("book", sub["node_id"]) == "BETACONTENT"


@pytest.mark.asyncio
async def test_graphindex_preserves_parent_edges(nested_epub: Path) -> None:
    from parrot.knowledge.graphindex.extractors.loader import LoaderExtractor

    nodes, edges = await LoaderExtractor().extract(EpubLoader(nested_epub), str(nested_epub))
    by_title = {node.title: node for node in nodes}
    assert by_title["Deep Section"].parent_id == by_title["Subsection"].node_id
    assert len(nodes) == 7
    assert len(edges) == 6


@pytest.mark.asyncio
async def test_bookstore_indexes_source_toc(nested_epub: Path, tmp_path: Path) -> None:
    from parrot.knowledge.bookstore.config import LibraryLocation
    from parrot.knowledge.bookstore.library import Bookstore

    location = LibraryLocation(scope="project", root=tmp_path / "library")
    store = Bookstore([location])
    card, status = await store.add_book(nested_epub)
    assert status == "added"
    assert card.source_format == "epub"
    import json

    tree = json.loads((location.trees_dir / f"{card.book_id}.json").read_text())
    assert tree["structure"][0]["nodes"][0]["nodes"][0]["title"] == "Subsection"


@pytest.mark.asyncio
async def test_public_load_keeps_empty_parents(nested_epub: Path) -> None:
    sections = ebook_sections(await EpubLoader(nested_epub).load())
    assert len(sections) == 6
    assert next(s for s in sections if s.title == "Part One").content == ""


def test_repeated_href_keeps_each_navigation_identity() -> None:
    loader = EpubLoader()
    sections = loader._toc_sections(
        [
            (
                epub.Link("book.xhtml", "Part", "part"),
                [
                    epub.Link("book.xhtml", "Chapter", "chapter"),
                ],
            ),
            epub.Link("book.xhtml#s", "Section", "section"),
            epub.Link("book.xhtml#s", "Alias", "alias"),
        ]
    )
    loader._partition_item("book.xhtml", '<p>Alpha</p><h2 id="s">Section</h2><p>Beta</p>', sections, 0)
    assert len({s.section_id for s in sections}) == 4
    assert sections[1].parent_id == sections[0].section_id
    assert all(s.target_found for s in sections)
    assert sum(s.content.count("Alpha") for s in sections) == 1
    assert sum(s.content.count("Beta") for s in sections) == 1


def test_partition_preserves_inline_markup_and_old_style_anchors() -> None:
    loader = EpubLoader()
    sections = loader._toc_sections(
        [
            epub.Link("one.xhtml", "Opening", "a"),
            epub.Link("one.xhtml#two", "Following", "b"),
        ]
    )
    loader._partition_item(
        "one.xhtml",
        "<div><p>Alpha <strong>bold</strong> &amp; beta</p>" '<a name="two"></a><p>Gamma <em>italic</em></p></div>',
        sections,
        0,
    )
    assert "Alpha **bold** & beta" in sections[0].content
    assert "Gamma *italic*" in sections[1].content
    assert "Gamma" not in sections[0].content
    assert "Alpha" not in sections[1].content


def test_tree_rejects_cycles_and_orphans() -> None:
    from parrot.knowledge.pageindex.ebook import ebook_tree

    with pytest.raises(ValueError, match="Missing ebook parent"):
        ebook_tree([EbookSection(section_id="a", title="A", parent_id="missing")])
    with pytest.raises(ValueError, match="Cyclic"):
        ebook_tree(
            [
                EbookSection(section_id="a", title="A", parent_id="b"),
                EbookSection(section_id="b", title="B", parent_id="a"),
            ]
        )
    with pytest.raises(ValueError, match="Duplicate"):
        ebook_tree([EbookSection(section_id="a", title="A")] * 2)


def test_deep_toc_is_not_limited_to_markdown_heading_depth() -> None:
    from parrot.knowledge.pageindex.ebook import ebook_tree

    sections = [
        EbookSection(
            section_id=str(i),
            title=f"Level {i}",
            depth=i + 1,
            toc_order=i,
            parent_id=str(i - 1) if i else None,
        )
        for i in range(9)
    ]
    node = ebook_tree(sections)["structure"][0]
    for i in range(1, 9):
        node = node["nodes"][0]
        assert node["title"] == f"Level {i}"


@pytest.mark.asyncio
async def test_wiki_ingests_exact_sections_without_llm(nested_epub: Path, tmp_path: Path) -> None:
    from unittest.mock import AsyncMock

    from parrot.knowledge.pageindex.toolkit import PageIndexToolkit
    from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
    from parrot.knowledge.wiki.ingest import WikiIngestOrchestrator
    from parrot.knowledge.wiki.models import WikiConfig
    from parrot.knowledge.wiki.sources import SourceCollectionManager

    toolkit = PageIndexToolkit(adapter=SimpleNamespace(model="offline"), storage_dir=tmp_path / "trees")
    await toolkit.create_tree("wiki")
    toolkit.insert_content = AsyncMock(side_effect=AssertionError("Ebooks must not be rewritten"))
    orchestrator = WikiIngestOrchestrator(
        toolkit, None, SourceCollectionManager(tmp_path / "sources"), WikiBookkeeper()
    )
    report = await orchestrator.ingest(str(nested_epub), WikiConfig(wiki_name="wiki", storage_dir=tmp_path / "wiki"))
    assert report.status == "ok", report.error
    assert report.pages_created == 6
    toolkit.insert_content.assert_not_awaited()
