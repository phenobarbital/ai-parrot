"""EPUB ingestion preserving navigation identities and section relationships."""

from __future__ import annotations

import asyncio
import hashlib
import posixpath
from collections.abc import Callable
from pathlib import Path, PurePath
from typing import Any
from urllib.parse import unquote, urlsplit

from parrot.loaders.abstract import AbstractLoader
from parrot.loaders.ebook import EbookSection, ebook_markdown
from parrot.stores.models import Document

try:
    from ebooklib import ITEM_DOCUMENT, epub

    EBOOKLIB_AVAILABLE = True
except ImportError:
    EBOOKLIB_AVAILABLE = False

try:
    from bs4 import BeautifulSoup, NavigableString, Tag

    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

try:
    from markdownify import MarkdownConverter

    MD_AVAILABLE = True
except ImportError:
    MD_AVAILABLE = False


def normalize_href(href: str) -> str:
    """Normalize local navigation paths without discarding fragment identity."""
    parsed = urlsplit(href)
    if parsed.scheme or parsed.netloc:
        return href
    path = posixpath.normpath(unquote(parsed.path)) if parsed.path else ""
    fragment = unquote(parsed.fragment)
    return path + (f"#{fragment}" if fragment else "")


def section_id(href: str, position: str) -> str:
    """Disambiguate repeated targets using their stable navigation position."""
    return hashlib.sha256(f"{position}:{href}".encode()).hexdigest()[:20]


class EpubLoader(AbstractLoader):
    """Read EPUB spine content and preserve the full nested source TOC.

    Per-chapter output means one document per structural section, including
    fragment targets and contentless parents. ebook_section metadata carries
    the authoritative hierarchy. Full-book output carries ebook_sections.
    """

    extensions: list[str] = [".epub"]

    def __init__(
        self,
        source: str | PurePath | list[PurePath] | None = None,
        *,
        tokenizer: str | Callable | None = None,
        text_splitter: str | Callable | None = None,
        source_type: str = "file",
        as_markdown: bool = True,
        per_chapter: bool = True,
        include_toc_document: bool = False,
        min_section_length: int = 0,
        heading_style: str = "ATX",
        strip_whitespace: bool = True,
        **kwargs: Any,
    ) -> None:
        missing = []
        if not EBOOKLIB_AVAILABLE:
            missing.append("ebooklib")
        if not BS4_AVAILABLE:
            missing.append("beautifulsoup4")
        if as_markdown and not MD_AVAILABLE:
            missing.append("markdownify")
        if missing:
            raise ImportError(f"EpubLoader requires {', '.join(missing)}")
        super().__init__(
            source,
            tokenizer=tokenizer,
            text_splitter=text_splitter,
            source_type=source_type,
            **kwargs,
        )
        self.doctype = "epub"
        self._source_type = "ebook"
        self.as_markdown = as_markdown
        self.per_chapter = per_chapter
        self.include_toc_document = include_toc_document
        self.min_section_length = max(0, int(min_section_length))
        self.heading_style = heading_style
        self.strip_whitespace = strip_whitespace

    def _html_to_markdown(self, html: str) -> str:
        """Convert content without silently falling back from Markdown to text."""
        soup = BeautifulSoup(html, "html.parser")
        for bad in soup(["script", "style", "noscript"]):
            bad.decompose()
        if self.as_markdown:
            text = MarkdownConverter(heading_style=self.heading_style).convert_soup(soup)
        else:
            text = soup.get_text("\n", strip=True)
        if self.strip_whitespace:
            text = "\n".join(line.rstrip() for line in text.splitlines()).strip()
        return text

    def _toc_sections(self, toc: Any) -> list[EbookSection]:
        """Walk EbookLib's (parent, children) pairs without flattening parents."""
        sections: list[EbookSection] = []

        def walk(entries: Any, parent: EbookSection | None, prefix: str) -> None:
            for index, entry in enumerate(entries):
                position = f"{prefix}.{index}"
                children: Any = []
                if isinstance(entry, tuple) and len(entry) == 2:
                    entry, children = entry
                if isinstance(entry, (tuple, list)):
                    walk(entry, parent, position)
                    continue
                href = normalize_href(getattr(entry, "href", "") or getattr(entry, "file_name", "") or "")
                section = EbookSection(
                    section_id=section_id(href, position),
                    title=str(getattr(entry, "title", "") or "Section"),
                    href=href,
                    parent_id=parent.section_id if parent else None,
                    depth=parent.depth + 1 if parent else 1,
                    toc_order=len(sections),
                )
                sections.append(section)
                if children:
                    walk(children, section, position)

        walk(toc or [], None, "toc")
        return sections

    def _iter_document_items(self, book: Any) -> list[Any]:
        """Read spine items once, including appendices but excluding navigation."""
        items = {item.get_id(): item for item in book.get_items()}
        result: list[Any] = []
        seen: set[str] = set()
        for entry in book.spine or []:
            identifier = entry[0] if isinstance(entry, tuple) else entry
            item = items.get(identifier)
            if (
                item is not None
                and identifier not in seen
                and item.get_type() == ITEM_DOCUMENT
                and not isinstance(item, epub.EpubNav)
            ):
                result.append(item)
                seen.add(identifier)
        if not result:
            result = [item for item in book.get_items_of_type(ITEM_DOCUMENT) if not isinstance(item, epub.EpubNav)]
        return result

    def _partition_item(self, href: str, html: str, sections: list[EbookSection], order: int) -> int:
        """Partition a DOM at anchors, preserving wrappers around fragments."""
        soup = BeautifulSoup(html, "html.parser")
        for bad in soup(["script", "style", "noscript"]):
            bad.decompose()
        body = soup.body or soup
        matching = [s for s in sections if s.href.split("#", 1)[0] == href]
        file_entries = [s for s in matching if "#" not in s.href]
        current = file_entries[-1] if file_entries else None
        for section in file_entries:
            section.target_found = True
            section.reading_order = order
        triggers: dict[int, list[EbookSection]] = {}
        for section in matching:
            if "#" not in section.href:
                continue
            fragment = section.href.split("#", 1)[1]
            target = body.find(id=fragment) or body.find("a", attrs={"name": fragment})
            if target is not None:
                triggers.setdefault(id(target), []).append(section)

        fallback: EbookSection | None = None
        if current is None:
            title_tag = soup.title or body.find(["h1", "h2", "h3"])
            fallback = EbookSection(
                section_id=section_id(href, "spine"),
                title=title_tag.get_text(" ", strip=True) if title_tag else Path(href).stem,
                href=href,
                toc_order=len(sections),
                origin="spine",
                target_found=True,
            )
            current = fallback

        if not matching:
            stack: list[tuple[int, EbookSection]] = []
            for index, heading in enumerate(body.find_all([f"h{i}" for i in range(1, 7)])):
                level = int(heading.name[1])
                while stack and stack[-1][0] >= level:
                    stack.pop()
                parent = stack[-1][1] if stack else None
                anchor = heading.get("id") or f"heading-{index + 1}"
                section = EbookSection(
                    section_id=section_id(f"{href}#{anchor}", "heading"),
                    title=heading.get_text(" ", strip=True) or "Section",
                    href=f"{href}#{anchor}",
                    parent_id=parent.section_id if parent else None,
                    depth=parent.depth + 1 if parent else 1,
                    toc_order=len(sections),
                    origin="heading",
                )
                sections.append(section)
                triggers[id(heading)] = [section]
                stack.append((level, section))

        fragments: dict[str, list[str]] = {}
        encountered: set[str] = set()

        def activate(section: EbookSection) -> None:
            nonlocal order, current
            current = section
            section.target_found = True
            if section.section_id not in encountered:
                section.reading_order = order
                order += 1
                encountered.add(section.section_id)

        activate(current)

        def partition(node: Any) -> dict[str, str]:
            if id(node) in triggers:
                for section in triggers[id(node)]:
                    activate(section)
            assert current is not None
            if isinstance(node, NavigableString):
                return {current.section_id: str(node.output_ready())}
            if not isinstance(node, Tag):
                return {}
            grouped: dict[str, list[str]] = {}
            for child in node.children:
                for key, text in partition(child).items():
                    grouped.setdefault(key, []).append(text)
            if not grouped:
                grouped[current.section_id] = []
            result: dict[str, str] = {}
            for key, children in grouped.items():
                wrapper = soup.new_tag(node.name, attrs=dict(node.attrs))
                inner = BeautifulSoup("".join(children), "html.parser")
                for child in list(inner.contents):
                    wrapper.append(child.extract())
                result[key] = str(wrapper)
            return result

        for child in body.children:
            for key, html_part in partition(child).items():
                fragments.setdefault(key, []).append(html_part)
        if fallback is not None:
            fallback_html = "".join(fragments.get(fallback.section_id, []))
            if BeautifulSoup(fallback_html, "html.parser").get_text(strip=True):
                fallback.toc_order = len(sections)
                sections.append(fallback)
        by_id = {s.section_id: s for s in sections}
        for key, parts in fragments.items():
            if key not in by_id:
                continue
            section = by_id[key]
            fragment_soup = BeautifulSoup("".join(parts), "html.parser")
            first_heading = fragment_soup.find([f"h{i}" for i in range(1, 7)])
            if first_heading and first_heading.get_text(" ", strip=True) == section.title:
                first_heading.decompose()
            headings = fragment_soup.find_all([f"h{i}" for i in range(1, 7)])
            if headings:
                lowest = min(int(h.name[1]) for h in headings)
                for heading in headings:
                    heading.name = f"h{min(6, section.depth + 1 + int(heading.name[1]) - lowest)}"
            section.content = self._html_to_markdown(str(fragment_soup))
        return order

    def _read_sections(self, path: Path) -> tuple[list[EbookSection], str | None, str]:
        """Decode the EPUB off the event loop and resolve structural records."""
        book = epub.read_epub(str(path))
        sections = self._toc_sections(book.toc)
        order = 0
        for item in self._iter_document_items(book):
            order = self._partition_item(
                normalize_href(item.file_name),
                item.get_content().decode("utf-8", errors="replace"),
                sections,
                order,
            )
        for section in sections:
            section.source_uri = str(path)
            if not section.target_found:
                section.reading_order = order
                order += 1
        language = book.get_metadata("DC", "language")
        titles = book.get_metadata("DC", "title")
        return (
            sections,
            language[0][0] if language else self.language,
            titles[0][0] if titles else path.stem,
        )

    def _documents(self, path: Path, sections: list[EbookSection], language: str | None, title: str) -> list[Document]:
        """Render the same section contract for EPUB and decoded MOBI books."""
        documents: list[Document] = []
        parent_ids = {s.parent_id for s in sections}
        sections = [
            s
            for s in sections
            if s.origin == "toc" or s.section_id in parent_ids or len(s.content) >= self.min_section_length
        ]
        if self.include_toc_document:
            toc = "\n".join(
                f"{'  ' * (s.depth - 1)}- [{s.title}]({s.href})" for s in sorted(sections, key=lambda s: s.toc_order)
            )
            metadata = self.create_metadata(
                path=path,
                doctype=self.doctype,
                source_type=f"{self.doctype}_toc",
                language=language,
                title=title,
                content_type="toc",
                toc=[s.model_dump(exclude={"content"}) for s in sections],
            )
            documents.append(self.create_document(f"# Table of Contents\n\n{toc}", path, metadata))
        if self.per_chapter:
            for section in sorted(sections, key=lambda s: s.reading_order):
                metadata = self.create_metadata(
                    path=path,
                    doctype=self.doctype,
                    source_type=f"{self.doctype}_section",
                    language=language,
                    title=section.title,
                    section_order=section.reading_order + 1,
                    section_title=section.title,
                    href=section.href,
                    content_type="chapter",
                    output_format="markdown" if self.as_markdown else "text",
                    ebook_section=section.model_dump(exclude={"content"}),
                )
                documents.append(self.create_document(section.content, path, metadata))
        else:
            metadata = self.create_metadata(
                path=path,
                doctype=self.doctype,
                source_type=f"{self.doctype}_full",
                language=language,
                title=title,
                content_type="full_document",
                sections=len(sections),
                ebook_sections=[s.model_dump() for s in sections],
                output_format="markdown" if self.as_markdown else "text",
            )
            documents.append(self.create_document(ebook_markdown(sections), path, metadata))
        return documents

    async def _load(self, path: PurePath | str, **kwargs: Any) -> list[Document]:
        """Load a book without discarding short sections or navigation parents."""
        source = Path(path)
        sections, language, title = await asyncio.to_thread(self._read_sections, source)
        return self._documents(source, sections, language, title)

    async def load(
        self,
        source: str | PurePath | list[PurePath] | None = None,
        split_documents: bool = False,
        **kwargs: Any,
    ) -> list[Document]:
        """Preserve structural records by default; chunking is explicitly opt-in."""
        return await super().load(source, split_documents=split_documents, **kwargs)
