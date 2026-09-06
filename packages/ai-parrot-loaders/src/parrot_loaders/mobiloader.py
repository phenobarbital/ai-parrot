"""MOBI/KF8 adapter for the shared structured ebook loader."""

from __future__ import annotations

import asyncio
from pathlib import Path, PurePath
from tempfile import TemporaryDirectory
from threading import Lock
from typing import TYPE_CHECKING, Any
from xml.etree import ElementTree

from parrot.loaders.ebook import EbookSection
from parrot.stores.models import Document

from .epubloader import EpubLoader, normalize_href

if TYPE_CHECKING:
    from bs4 import BeautifulSoup, Tag

# KindleUnpack mutates module globals. Serialize decoding, not downstream indexing.
_DECODE_LOCK = Lock()


class MobiLoaderError(ValueError):
    """A MOBI source cannot be decoded into a structured text ebook."""


class MobiLoader(EpubLoader):
    """Load unencrypted MOBI using the same section contract as EPUB.

    KF8 output is parsed as EPUB. Legacy MOBI7 output uses its NCX navigation
    and HTML anchors; explicit HTML navigation or headings provide fallbacks.
    Source provenance always refers to the original MOBI, never temporary files.
    """

    extensions: list[str] = [".mobi"]

    def __init__(
        self,
        source: str | PurePath | list[PurePath] | None = None,
        **kwargs: Any,
    ) -> None:
        try:
            from mobi.kindleunpack import unpackBook
        except ImportError as exc:
            raise ImportError("MOBI support requires ai-parrot-loaders[ebook] (including mobi)") from exc
        super().__init__(source, **kwargs)
        self.doctype = "mobi"
        self._unpack_book = unpackBook

    async def _load_tasks(self, tasks: list[asyncio.Task[list[Document]]]) -> list[Document]:
        """Drain decoder jobs and propagate failures instead of returning an empty book."""
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        documents: list[Document] = []
        for outcome in outcomes:
            if isinstance(outcome, BaseException):
                raise outcome
            documents.extend(outcome)
        for document in documents:
            document.metadata = self._validate_metadata(document.metadata)
        return documents

    def _read_sections(self, path: Path) -> tuple[list[EbookSection], str | None, str]:
        """Decode in an owned temporary directory, including on parse failures."""
        path = path.resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        try:
            with TemporaryDirectory(prefix="parrot-mobi-") as directory:
                root = Path(directory)
                with _DECODE_LOCK:
                    self._unpack_book(str(path), str(root), epubver="A")
                epub_files = sorted((root / "mobi8").glob("*.epub"))
                if epub_files:
                    sections, language, title = super()._read_sections(epub_files[0])
                elif (html_path := root / "mobi7" / "book.html").is_file():
                    sections, language, title = self._read_legacy(html_path)
                else:
                    raise MobiLoaderError(
                        "Decoder produced no text EPUB or HTML; PDF-only Print Replica "
                        "and unsupported MOBI variants cannot preserve an ebook TOC"
                    )
                if not sections or not any(section.content.strip() for section in sections):
                    raise MobiLoaderError("Decoder produced no readable ebook section content")
                for section in sections:
                    section.source_uri = str(path)
                return sections, language, title
        except MobiLoaderError:
            raise
        except Exception as exc:
            raise MobiLoaderError(f"Could not decode MOBI {path.name}: {exc}") from exc

    def _read_legacy(self, html_path: Path) -> tuple[list[EbookSection], str | None, str]:
        """Resolve legacy HTML content against NCX or explicit HTML navigation."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html_path.read_bytes(), "html.parser")
        ncx_path = html_path.with_name("toc.ncx")
        toc = self._read_ncx(ncx_path) if ncx_path.is_file() else []
        if not toc:
            toc = self._html_toc(soup, html_path.name)
        sections = self._toc_sections(toc)
        order = self._partition_item(html_path.name, str(soup), sections, 0)
        for section in sections:
            if not section.target_found:
                section.reading_order = order
                order += 1
        title = soup.title.get_text(" ", strip=True) if soup.title else html_path.stem
        language = self.language
        opf_path = html_path.with_name("content.opf")
        if opf_path.is_file():
            metadata = ElementTree.parse(opf_path).getroot().find("{*}metadata")
            if metadata is not None:
                title = metadata.findtext("{*}title") or title
                language = metadata.findtext("{*}language") or language
        return sections, language, title

    @staticmethod
    def _read_ncx(path: Path) -> list[Any]:
        """Keep every NCX navPoint and its original parent/child relationship."""
        from ebooklib import epub

        nav_map = ElementTree.parse(path).getroot().find("{*}navMap")
        if nav_map is None:
            return []

        def walk(parent: ElementTree.Element) -> list[Any]:
            entries: list[Any] = []
            for index, point in enumerate(parent.findall("{*}navPoint")):
                title = point.findtext("{*}navLabel/{*}text") or "Section"
                content = point.find("{*}content")
                href = normalize_href(content.get("src", "")) if content is not None else ""
                entry = epub.Link(href, title, point.get("id", f"nav-{index}"))
                children = walk(point)
                entries.append((entry, children) if children else entry)
            return entries

        return walk(nav_map)

    @staticmethod
    def _html_toc(soup: BeautifulSoup, filename: str) -> list[Any]:
        """Read an explicit nested HTML navigation list without guessing parents."""
        from bs4 import BeautifulSoup
        from ebooklib import epub

        container = soup.find("nav", attrs={"epub:type": "toc"})
        container = container or soup.find("nav", attrs={"role": "doc-toc"})
        container = container or soup.find(id="toc")
        if container is None:
            guide = soup.find("reference", attrs={"type": "toc"})
            href = guide.get("href", "") if guide else ""
            if "#" in href:
                fragment = href.split("#", 1)[1]
                target = soup.find(id=fragment) or soup.find("a", attrs={"name": fragment})
                if target is not None:
                    container = target.find_next(["ol", "ul"])
        if container is None:
            return []
        listing = container if container.name in ("ol", "ul") else container.find(["ol", "ul"])
        if listing is None:
            return []

        def walk(parent: Tag) -> list[Any]:
            entries: list[Any] = []
            for index, item in enumerate(parent.find_all("li", recursive=False)):
                anchor = next(
                    (a for a in item.find_all("a", href=True) if a.find_parent("li") is item),
                    None,
                )
                nested = item.find(["ol", "ul"])
                children = walk(nested) if nested else []
                # A grouping label may have no link of its own.
                label_soup = BeautifulSoup(str(item), "html.parser")
                for child_list in label_soup.find_all(["ol", "ul"]):
                    child_list.decompose()
                label = label_soup.get_text(" ", strip=True)
                title = anchor.get_text(" ", strip=True) if anchor else label or "Section"
                href = str(anchor["href"]) if anchor else ""
                if href.startswith("#"):
                    href = filename + href
                entry = epub.Link(normalize_href(href), title, f"html-nav-{index}")
                entries.append((entry, children) if children else entry)
            return entries

        return walk(listing)
