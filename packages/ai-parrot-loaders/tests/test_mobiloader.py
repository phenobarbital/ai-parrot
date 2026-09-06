"""MOBI decoding and ebook-index integration regressions."""

from __future__ import annotations

import json
import shutil
import struct
from pathlib import Path
from unittest.mock import patch

import pytest
from parrot.loaders.ebook import ebook_sections
from parrot_loaders.factory import get_loader_class
from parrot_loaders.mobiloader import MobiLoader, MobiLoaderError

pytest.importorskip("mobi")
epub = pytest.importorskip("ebooklib.epub")


@pytest.fixture
def mobi_book(tmp_path: Path) -> Path:
    """Generate an uncompressed MOBI6 container with real Palm database records."""
    title = b"Synthetic MOBI"
    body = (
        b"<html><head><title>Synthetic MOBI</title></head><body>"
        b"<h1>Chapter One</h1><p>ALPHACONTENT</p><h2>Nested Section</h2>"
        b"<p>BETACONTENT</p><h1>Chapter Two</h1><p>GAMMACONTENT</p>"
        b"</body></html>"
    )
    header = bytearray(0xF8)
    struct.pack_into(">HHIHHHH", header, 0, 1, 0, len(body), 1, 4096, 0, 0)
    header[16:20] = b"MOBI"
    struct.pack_into(">IIIII", header, 20, 0xE8, 2, 65001, 12345, 6)
    for offset in (0x28, 0x2C, 0x50, 0x6C, 0xF4):
        struct.pack_into(">I", header, offset, 0xFFFFFFFF)
    struct.pack_into(">II", header, 0x54, len(header), len(title))
    struct.pack_into(">I", header, 0x5C, 9)  # English
    struct.pack_into(">I", header, 0x68, 6)
    record = bytes(header) + title
    palm = bytearray(78)
    palm[: len(title)] = title
    palm[60:68] = b"BOOKMOBI"
    struct.pack_into(">H", palm, 76, 2)
    first = 78 + 16 + 2
    records = struct.pack(">IIII", first, 0, first + len(record), 1)
    path = tmp_path / "synthetic.mobi"
    path.write_bytes(bytes(palm) + records + b"\0\0" + record + body)
    return path


@pytest.mark.asyncio
async def test_real_mobi_decode(mobi_book: Path) -> None:
    assert get_loader_class(".mobi") is MobiLoader
    documents = await MobiLoader(mobi_book).load()
    sections = ebook_sections(documents)
    by_title = {section.title: section for section in sections}
    assert by_title["Nested Section"].parent_id == by_title["Chapter One"].section_id
    assert by_title["Chapter One"].content == "ALPHACONTENT"
    assert by_title["Nested Section"].content == "BETACONTENT"
    assert by_title["Chapter Two"].content == "GAMMACONTENT"
    assert all(section.source_uri == str(mobi_book) for section in sections)
    assert all(document.metadata["type"] == "mobi" for document in documents)


def unpack_legacy(infile: str, outdir: str, **kwargs: object) -> None:
    """Supply representative decoder HTML/NCX with nested filepos targets."""
    root = Path(outdir) / "mobi7"
    root.mkdir()
    (root / "book.html").write_text(
        "<html><head><title>Legacy Book</title></head><body>"
        '<a id="filepos0"></a><h1>Chapter</h1><p>ALPHA</p>'
        '<a id="filepos80"></a><h2>Subsection</h2><p>BETA</p>'
        '<a id="filepos160"></a><h1>Next</h1><p>GAMMA</p></body></html>'
    )
    (root / "toc.ncx").write_text(
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap>'
        '<navPoint id="part"><navLabel><text>Part</text></navLabel>'
        '<navPoint id="chapter"><navLabel><text>Chapter</text></navLabel>'
        '<content src="book.html#filepos0"/>'
        '<navPoint id="sub"><navLabel><text>Subsection</text></navLabel>'
        '<content src="book.html#filepos80"/></navPoint></navPoint>'
        '<navPoint id="next"><navLabel><text>Next</text></navLabel>'
        '<content src="book.html#filepos160"/></navPoint>'
        "</navPoint></navMap></ncx>"
    )
    (root / "content.opf").write_text(
        '<package xmlns="http://www.idpf.org/2007/opf"><metadata '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">'
        "<dc:title>Legacy Book</dc:title><dc:language>es</dc:language>"
        "</metadata></package>"
    )


@pytest.mark.asyncio
async def test_legacy_ncx_parentage_and_cleanup(mobi_book: Path) -> None:
    roots: list[Path] = []

    def unpack(infile: str, outdir: str, **kwargs: object) -> None:
        roots.append(Path(outdir))
        unpack_legacy(infile, outdir, **kwargs)

    with patch("mobi.kindleunpack.unpackBook", side_effect=unpack):
        documents = await MobiLoader(mobi_book).load()
    sections = ebook_sections(documents)
    by_title = {s.title: s for s in sections}
    assert len(sections) == 4
    assert by_title["Subsection"].parent_id == by_title["Chapter"].section_id
    assert by_title["Chapter"].parent_id == by_title["Part"].section_id
    assert by_title["Subsection"].href == "book.html#filepos80"
    assert by_title["Subsection"].content == "BETA"
    assert all(d.metadata["document_meta"]["language"] == "es" for d in documents)
    assert all(not root.exists() for root in roots)


@pytest.mark.asyncio
async def test_kf8_epub_output(mobi_book: Path, tmp_path: Path) -> None:
    book = epub.EpubBook()
    book.set_identifier("kf8-fixture")
    book.set_title("KF8 Book")
    book.set_language("en")
    chapter = epub.EpubHtml(title="Chapter", file_name="chapter.xhtml")
    chapter.content = '<h1>Chapter</h1><p>ALPHA</p><h2 id="sub">Section</h2><p>BETA</p>'
    book.add_item(chapter)
    book.toc = [(epub.Link("chapter.xhtml", "Chapter", "ch"), [epub.Link("chapter.xhtml#sub", "Section", "sub")])]
    book.spine = [chapter]
    book.add_item(epub.EpubNcx())
    source_epub = tmp_path / "decoded.epub"
    epub.write_epub(str(source_epub), book)
    roots: list[Path] = []

    def unpack(infile: str, outdir: str, **kwargs: object) -> None:
        roots.append(Path(outdir))
        output = Path(outdir) / "mobi8"
        output.mkdir()
        shutil.copyfile(source_epub, output / "book.epub")

    with patch("mobi.kindleunpack.unpackBook", side_effect=unpack):
        sections = ebook_sections(await MobiLoader(mobi_book).load())
    assert len(sections) == 2
    assert sections[1].parent_id == sections[0].section_id
    assert sections[1].content == "BETA"
    assert all(s.source_uri == str(mobi_book) for s in sections)
    assert all(not root.exists() for root in roots)


@pytest.mark.asyncio
async def test_decoder_error_cleans_temporary_directory(mobi_book: Path) -> None:
    roots: list[Path] = []

    def fail(infile: str, outdir: str, **kwargs: object) -> None:
        roots.append(Path(outdir))
        (Path(outdir) / "partial.html").write_text("partial")
        raise ValueError("Book is encrypted")

    with patch("mobi.kindleunpack.unpackBook", side_effect=fail):
        with pytest.raises(MobiLoaderError, match="encrypted"):
            await MobiLoader(mobi_book)._load(mobi_book)
    assert all(not root.exists() for root in roots)


@pytest.mark.asyncio
async def test_invalid_binary_is_not_read_as_markdown(tmp_path: Path) -> None:
    path = tmp_path / "invalid.mobi"
    path.write_bytes(b"not a mobi file")
    with pytest.raises(MobiLoaderError, match="Could not decode MOBI"):
        await MobiLoader(path)._load(path)


@pytest.mark.asyncio
async def test_print_replica_fails_clearly(mobi_book: Path) -> None:
    def unpack(infile: str, outdir: str, **kwargs: object) -> None:
        (Path(outdir) / "book.001.pdf").write_bytes(b"%PDF-1.4")

    with patch("mobi.kindleunpack.unpackBook", side_effect=unpack):
        with pytest.raises(MobiLoaderError, match="Print Replica"):
            await MobiLoader(mobi_book)._load(mobi_book)


@pytest.mark.asyncio
async def test_full_book_with_toc(mobi_book: Path) -> None:
    with patch("mobi.kindleunpack.unpackBook", side_effect=unpack_legacy):
        documents = await MobiLoader(mobi_book, per_chapter=False, include_toc_document=True).load()
    assert documents[0].metadata["content_type"] == "toc"
    assert len(ebook_sections(documents)) == 4
    assert all(marker in documents[1].page_content for marker in ("ALPHA", "BETA", "GAMMA"))


@pytest.mark.asyncio
async def test_bookstore_wiki_and_graphindex(mobi_book: Path, tmp_path: Path) -> None:
    from parrot.knowledge.bookstore.config import LibraryLocation
    from parrot.knowledge.bookstore.library import Bookstore
    from parrot.knowledge.graphindex.extractors.loader import LoaderExtractor
    from parrot.knowledge.wiki.documents import DocumentAcquirer, DocumentRef

    location = LibraryLocation(scope="project", root=tmp_path / "library")
    store = Bookstore([location])
    with patch("mobi.kindleunpack.unpackBook", side_effect=unpack_legacy):
        card, status = await store.add_book(mobi_book)
        acquired = await DocumentAcquirer().acquire(DocumentRef(uri=str(mobi_book), suffix=".mobi"))
        nodes, edges = await LoaderExtractor().extract(MobiLoader(mobi_book), str(mobi_book))
    assert status == "added"
    assert card.source_format == "mobi"
    tree = json.loads((location.trees_dir / f"{card.book_id}.json").read_text())
    assert tree["structure"][0]["nodes"][0]["nodes"][0]["title"] == "Subsection"
    assert len(acquired.ebook_sections) == 4
    assert all(marker in acquired.text for marker in ("ALPHA", "BETA", "GAMMA"))
    by_title = {node.title: node for node in nodes}
    assert by_title["Subsection"].parent_id == by_title["Chapter"].node_id
    assert len(edges) == 4
    assert mobi_book in Bookstore.iter_folder_files(mobi_book.parent)[0]


def test_missing_dependency_is_actionable(mobi_book: Path) -> None:
    import builtins

    original = builtins.__import__

    def blocked(name: str, *args: object, **kwargs: object) -> object:
        if name == "mobi.kindleunpack":
            raise ImportError("not installed")
        return original(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=blocked):
        with pytest.raises(ImportError, match="ai-parrot-loaders\\[ebook\\]"):
            MobiLoader(mobi_book)


def test_html_navigation_retains_unlinked_parent() -> None:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(
        '<nav role="doc-toc"><ol><li><span>Part</span><ul>'
        '<li><a href="#chapter">Chapter</a><ol><li><a href="#sub">Subsection</a>'
        "</li></ol></li></ul></li></ol></nav>",
        "html.parser",
    )
    loader = MobiLoader()
    sections = loader._toc_sections(loader._html_toc(soup, "book.html"))
    assert [s.title for s in sections] == ["Part", "Chapter", "Subsection"]
    assert sections[1].parent_id == sections[0].section_id
    assert sections[2].href == "book.html#sub"


@pytest.mark.asyncio
async def test_public_load_propagates_decoder_error(mobi_book: Path) -> None:
    with patch("mobi.kindleunpack.unpackBook", side_effect=ValueError("Book is encrypted")):
        with pytest.raises(MobiLoaderError, match="encrypted"):
            await MobiLoader(mobi_book).load()


@pytest.mark.asyncio
async def test_parse_failure_also_cleans_up(mobi_book: Path) -> None:
    roots: list[Path] = []

    def unpack(infile: str, outdir: str, **kwargs: object) -> None:
        roots.append(Path(outdir))
        unpack_legacy(infile, outdir, **kwargs)
        (Path(outdir) / "mobi7" / "toc.ncx").write_text("<broken")

    with patch("mobi.kindleunpack.unpackBook", side_effect=unpack):
        with pytest.raises(MobiLoaderError, match="Could not decode"):
            await MobiLoader(mobi_book).load()
    assert all(not root.exists() for root in roots)


@pytest.mark.asyncio
async def test_decoder_calls_are_serialized(mobi_book: Path) -> None:
    import asyncio
    import time

    active = 0
    peak = 0

    def unpack(infile: str, outdir: str, **kwargs: object) -> None:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        time.sleep(0.02)
        unpack_legacy(infile, outdir, **kwargs)
        active -= 1

    with patch("mobi.kindleunpack.unpackBook", side_effect=unpack):
        first, second = await asyncio.gather(MobiLoader(mobi_book).load(), MobiLoader(mobi_book).load())
    assert peak == 1
    assert len(ebook_sections(first)) == len(ebook_sections(second)) == 4


@pytest.mark.asyncio
async def test_real_encrypted_mobi_is_rejected(mobi_book: Path) -> None:
    binary = bytearray(mobi_book.read_bytes())
    first_record = struct.unpack_from(">I", binary, 78)[0]
    struct.pack_into(">H", binary, first_record + 12, 2)
    mobi_book.write_bytes(binary)
    with pytest.raises(MobiLoaderError, match="encrypted"):
        await MobiLoader(mobi_book).load()


def test_factory_does_not_fall_back_for_missing_ebook_module() -> None:
    with patch("parrot_loaders.factory.importlib.import_module", side_effect=ImportError("missing")):
        with pytest.raises(ImportError, match="ebook"):
            get_loader_class(".mobi")


@pytest.mark.asyncio
async def test_bookstore_error_is_actionable(mobi_book: Path, tmp_path: Path) -> None:
    from parrot.knowledge.bookstore.config import LibraryLocation
    from parrot.knowledge.bookstore.library import Bookstore, BookstoreError

    store = Bookstore([LibraryLocation(scope="project", root=tmp_path / "library")])
    with patch("mobi.kindleunpack.unpackBook", side_effect=ValueError("Book is encrypted")):
        with pytest.raises(BookstoreError, match="encrypted"):
            await store.add_book(mobi_book)
    assert not list((tmp_path / "library").rglob("synthetic.json"))
