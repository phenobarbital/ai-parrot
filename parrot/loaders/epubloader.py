from typing import List, Optional, Union, Tuple, Dict
from pathlib import PurePath
from collections.abc import Callable
from ..stores.models import Document
from .abstract import AbstractLoader

# Optional deps: install via
# pip install ebooklib beautifulsoup4 markdownify
try:
    from ebooklib import epub
    EBOOKLIB_AVAILABLE = True
    try:
        ITEM_DOCUMENT = epub.ITEM_DOCUMENT
    except AttributeError:
        try:
            from ebooklib.epub import ITEM_DOCUMENT
        except ImportError:
            ITEM_DOCUMENT = 9  # Known constant value
except Exception:
    EBOOKLIB_AVAILABLE = False

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except Exception:
    BS4_AVAILABLE = False

try:
    from markdownify import MarkdownConverter
    MD_AVAILABLE = True
except Exception:
    MD_AVAILABLE = False


class EpubLoader(AbstractLoader):
    """
    EPUB loader that extracts clean Markdown (or plain text) from chapters/sections.

    Features:
    - Per-chapter documents with titles from TOC/HTML
    - Optional full-book document (merged)
    - Clean Markdown conversion (lists, headers, links)
    - Skips non-document items (css, images, fonts)
    - Configurable minimum content length
    """

    extensions: List[str] = ['.epub']

    def __init__(
        self,
        source: Optional[Union[str, PurePath, List[PurePath]]] = None,
        *,
        tokenizer: Union[str, Callable] = None,
        text_splitter: Union[str, Callable] = None,
        source_type: str = 'file',

        # Output controls
        as_markdown: bool = True,          # emit markdown instead of plain text
        per_chapter: bool = True,          # True => one Document per chapter; False => single full-book doc
        include_toc_document: bool = False,# optional separate TOC document
        min_section_length: int = 50,      # drop tiny/empty sections

        # Markdown conversion tuning
        heading_style: str = "ATX",        # for markdownify; "ATX" => # Heading
        strip_whitespace: bool = True,

        **kwargs
    ):
        super().__init__(
            source,
            tokenizer=tokenizer,
            text_splitter=text_splitter,
            source_type=source_type,
            **kwargs
        )
        self.doctype = 'epub'
        self._source_type = 'ebook'

        # Options
        self.as_markdown = as_markdown
        self.per_chapter = per_chapter
        self.include_toc_document = include_toc_document
        self.min_section_length = int(min_section_length)
        self.strip_whitespace = bool(strip_whitespace)
        self.heading_style = heading_style

        # sanity checks
        if not EBOOKLIB_AVAILABLE or not BS4_AVAILABLE:
            missing = []
            if not EBOOKLIB_AVAILABLE:
                missing.append("ebooklib")
            if not BS4_AVAILABLE:
                missing.append("beautifulsoup4")
            raise ImportError(
                f"EpubLoader requires {', '.join(missing)}. "
                f"Install with: pip install ebooklib beautifulsoup4"
            )

    def _html_to_markdown(self, html: str) -> str:
        """Convert XHTML chapter html to Markdown (fallback to plain text)."""
        soup = BeautifulSoup(html, "html.parser")

        # remove scripts/styles
        for bad in soup(["script", "style", "noscript"]):
            bad.decompose()

        if MD_AVAILABLE and self.as_markdown:
            md = MarkdownConverter(
                heading_style=self.heading_style,
                strip=['style', 'script', 'noscript']
            ).convert_soup(soup)
            return self._clean(md)

        # plain text fallback
        text = soup.get_text("\n", strip=True)
        return self._clean(text)

    def _clean(self, text: str) -> str:
        if not text:
            return ""
        if self.strip_whitespace:
            # Normalize multiple blank lines; trim trailing spaces
            lines = [ln.rstrip() for ln in text.splitlines()]
            # Collapse >2 blank lines to just one
            cleaned = []
            blank = 0
            for ln in lines:
                if ln.strip():
                    blank = 0
                    cleaned.append(ln)
                else:
                    blank += 1
                    if blank <= 1:
                        cleaned.append("")
            text = "\n".join(cleaned)
        return text.strip()

    def _flatten_toc(self, toc) -> List[Tuple[str, str]]:
        """
        Flatten ebooklib TOC into a list of (href, title) entries.
        toc entries are like: Link(title, href) or nested lists/tuples.
        """
        flat = []

        def _walk(node):
            if isinstance(node, (list, tuple)):
                for child in node:
                    _walk(child)
            else:
                # epub.Link or epub.Section
                try:
                    href = getattr(node, "href", None)
                    title = getattr(node, "title", None)
                    if href and title:
                        flat.append((href.split("#", 1)[0], str(title)))
                except Exception:
                    pass

        _walk(toc)
        return flat

    def _toc_title_lookup(self, book: "epub.EpubBook") -> Dict[str, str]:
        """
        Build a mapping from href→title using TOC (best effort).
        Keys are hrefs without fragments; values are strings.
        """
        try:
            flat = self._flatten_toc(book.toc or [])
            # Normalize: keep last title if duplicates
            return {href: title for href, title in flat}
        except Exception:
            return {}

    def _iter_document_items(self, book: "epub.EpubBook"):
        """
        Yield (order_idx, item) for spine items that are HTML documents.
        """
        id_to_item = {it.get_id(): it for it in book.get_items()}
        order = 0
        for entry in (book.spine or []):
            if isinstance(entry, tuple) and entry and isinstance(entry[0], str):
                idref = entry[0]
                item = id_to_item.get(idref)
                if item is None:
                    continue
                if item.get_type() == ITEM_DOCUMENT:
                    yield order, item
                    order += 1

        if order == 0:
            for i, item in enumerate(book.get_items_of_type(ITEM_DOCUMENT)):
                yield i, item

    def _derive_title_from_html(self, html: str) -> Optional[str]:
        soup = BeautifulSoup(html, "html.parser")
        # Try <title>
        if soup.title and soup.title.string:
            t = soup.title.string.strip()
            if t:
                return t
        # Try first heading
        for tag in ["h1", "h2", "h3"]:
            h = soup.find(tag)
            if h and h.get_text(strip=True):
                return h.get_text(strip=True)
        return None

    async def _load(self, path: PurePath, **kwargs) -> List[Document]:
        """
        Load an EPUB file into Parrot Documents.

        Returns:
            - Per-chapter Documents (default), or
            - Single full-book Document if per_chapter=False
        """
        self.logger.info(f"Loading EPUB file: {path}")

        docs: List[Document] = []
        try:
            book = epub.read_epub(str(path))
        except Exception as e:
            self.logger.error(f"Failed to open EPUB {path}: {e}")
            return docs

        toc_map = self._toc_title_lookup(book)

        # Optionally create a separate TOC document
        if self.include_toc_document and toc_map:
            toc_lines = ["# Table of Contents"]
            for href, title in toc_map.items():
                toc_lines.append(f"- {title} (Link: {href})")
            toc_content = "\n".join(toc_lines)
            toc_meta = self.create_metadata(
                path=path,
                doctype="epub",
                source_type="epub_toc",
                doc_metadata={
                    "content_type": "toc",
                    "entries": len(toc_map)
                },
            )
            docs.append(self.create_document(toc_content, path, toc_meta))

        # Collect per-chapter or full text
        all_sections = []
        for order_idx, item in self._iter_document_items(book):
            try:
                html = item.get_content().decode("utf-8", errors="ignore")
            except Exception:
                continue

            content = self._html_to_markdown(html)

            if len(content) < self.min_section_length:
                # skip boilerplate/empty stubs
                continue

            # Derive title from TOC → HTML <title> → filename
            href = getattr(item, "file_name", "") or ""
            title = toc_map.get(href) or self._derive_title_from_html(html) or PurePath(href).name or f"Section {order_idx+1}"

            # Track for full-book option
            all_sections.append((order_idx, title, content, href))

            # Per-chapter Document
            if self.per_chapter:
                section_meta = self.create_metadata(
                    path=path,
                    doctype="epub",
                    source_type="epub_section",
                    doc_metadata={
                        "section_order": order_idx + 1,
                        "section_title": title,
                        "href": href,
                        "content_type": "chapter",
                        "output_format": "markdown" if self.as_markdown else "text",
                        "min_section_length": self.min_section_length
                    },
                )

                # Prepend a lightweight context header (like your PPT/PDF style)
                context = [
                    f"File Name: {path.name if hasattr(path, 'name') else str(path)}",
                    f"Section: {order_idx + 1}",
                    f"Title: {title}",
                    f"Document Type: epub",
                    f"Source Type: ebook",
                ]
                full_content = "\n".join(context) + "\n======\n\n" + content

                docs.append(self.create_document(full_content, path, section_meta))

        if not all_sections:
            self.logger.warning(f"No textual sections extracted from {path}")
            return docs

        # Full-book Document (if requested)
        if not self.per_chapter:
            merged = []
            for order_idx, title, content, href in all_sections:
                merged.append(f"# {title}\n\n{content}\n")
            book_text = "\n\n".join(merged).strip()

            full_meta = self.create_metadata(
                path=path,
                doctype="epub",
                source_type="epub_full",
                doc_metadata={
                    "sections": len(all_sections),
                    "content_type": "full_document",
                    "output_format": "markdown" if self.as_markdown else "text",
                },
            )
            docs.append(self.create_document(book_text, path, full_meta))

        return docs
