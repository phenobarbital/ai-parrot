"""
WebScrapingLoader — Loader interface for WebScrapingToolkit + CrawlEngine.

Bridges parrot's Loader abstraction with the scraping/crawling infrastructure
in ``parrot_tools.scraping``, converting ``ScrapingResult`` / ``CrawlResult``
into chunked ``Document`` objects suitable for vector stores and PageIndex.

Single-page usage::

    loader = WebScrapingLoader(
        source="https://example.com/docs",
        selectors=[
            {"name": "content", "selector": "article.main", "extract_type": "text"},
            {"name": "title", "selector": "h1", "extract_type": "text"},
        ],
        tags=["p", "h1", "h2", "h3", "article", "section"],
    )
    docs = await loader.load()

Crawl usage::

    loader = WebScrapingLoader(
        source="https://example.com/docs",
        crawl=True,
        depth=2,
        max_pages=50,
        follow_pattern=r"/docs/.*",
    )
    docs = await loader.load()

With a ScrapingPlan::

    from parrot_tools.scraping.plan import ScrapingPlan
    plan = ScrapingPlan(url="https://example.com", objective="Extract docs", steps=[...])
    loader = WebScrapingLoader(source="https://example.com", plan=plan)
    docs = await loader.load()
"""
from __future__ import annotations

from datetime import datetime
from pathlib import PurePath
from typing import Any, Dict, List, Literal, Optional, Union

from bs4 import BeautifulSoup, NavigableString
from markdownify import MarkdownConverter

from parrot.loaders.abstract import AbstractLoader
from parrot.stores.models import Document

try:
    import trafilatura
    HAS_TRAFILATURA = True
except ImportError:
    trafilatura = None  # type: ignore[assignment]
    HAS_TRAFILATURA = False


class WebScrapingLoader(AbstractLoader):
    """Load web pages via WebScrapingToolkit and convert to Documents.

    Delegates browser automation and crawling to the scraping infrastructure
    (``parrot_tools.scraping``) while exposing the standard Loader interface
    (``_load`` / ``load``).

    Args:
        source: URL or list of URLs to scrape.
        selectors: CSS/XPath selectors for structured extraction.
            Each dict has keys: ``name``, ``selector``, and optionally
            ``selector_type`` (css|xpath|tag), ``extract_type``
            (text|html|attribute), ``attribute``, ``multiple``.
        tags: HTML tags to extract text from (e.g. ``['p', 'h1', 'article']``).
            When provided alongside selectors, both are applied.
        steps: Raw scraping steps for browser automation (navigate, click, etc.).
            If omitted, a simple navigate step is generated from the URL.
        plan: An explicit ``ScrapingPlan`` for advanced scenarios.
        objective: Scraping objective string — triggers LLM plan auto-generation
            when no explicit plan or steps are provided.
        crawl: Enable multi-page crawling via ``CrawlEngine``.
        depth: Maximum crawl depth (0 = only the start URL).
        max_pages: Hard cap on total pages scraped during a crawl.
        follow_selector: CSS selector for links to follow during crawling.
        follow_pattern: URL regex pattern to filter discovered links.
        concurrency: Number of concurrent page scrapes during a crawl.
        driver_type: Browser driver backend (``selenium`` or ``playwright``).
        browser: Browser to launch.
        headless: Run browser in headless mode.
        parse_videos: Extract video links from pages.
        parse_navs: Extract navigation menus as markdown.
        parse_tables: Extract tables as markdown.
        content_format: How to format extracted content — ``markdown``
            converts HTML to markdown, ``text`` extracts plain text.
        content_extraction: Content extraction strategy. ``auto`` tries
            trafilatura first then falls back to markdownify.
            ``trafilatura`` forces trafilatura (raises ImportError if
            not installed). ``markdown`` uses markdownify directly.
            ``text`` extracts plain text.
        trafilatura_fallback_threshold: Minimum ratio of trafilatura
            output length to raw text length. If below this threshold
            in ``auto`` mode, falls back to markdownify. Default 0.1.
        llm_client: LLM client for plan auto-generation (required when
            ``objective`` is provided without a plan).
        plans_dir: Directory for plan caching.
        save_plan: Persist auto-generated plans after scraping.
        **kwargs: Passed through to ``AbstractLoader``.
    """

    def __init__(
        self,
        source: Optional[Union[str, List[str]]] = None,
        *,
        selectors: Optional[List[Dict[str, Any]]] = None,
        tags: Optional[List[str]] = None,
        steps: Optional[List[Dict[str, Any]]] = None,
        plan: Optional[Any] = None,
        objective: Optional[str] = None,
        # Crawl settings
        crawl: bool = False,
        depth: int = 1,
        max_pages: Optional[int] = None,
        follow_selector: Optional[str] = None,
        follow_pattern: Optional[str] = None,
        concurrency: int = 1,
        # Browser settings
        driver_type: Literal["selenium", "playwright"] = "selenium",
        browser: Literal[
            "chrome", "firefox", "edge", "safari", "undetected", "webkit"
        ] = "chrome",
        headless: bool = True,
        # Content extraction settings
        parse_videos: bool = True,
        parse_navs: bool = False,
        parse_tables: bool = True,
        content_format: Literal["markdown", "text"] = "markdown",
        content_extraction: Literal[
            "auto", "trafilatura", "markdown", "text"
        ] = "auto",
        trafilatura_fallback_threshold: float = 0.1,
        # Toolkit settings
        llm_client: Optional[Any] = None,
        plans_dir: Optional[str] = None,
        save_plan: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            source=source,
            source_type="webpage",
            **kwargs,
        )
        self._selectors = selectors
        self._tags = tags or ["p", "h1", "h2", "h3", "h4", "article", "section"]
        self._steps = steps
        self._plan = plan
        self._objective = objective

        # Crawl
        self._crawl = crawl
        self._depth = depth
        self._max_pages = max_pages
        self._follow_selector = follow_selector
        self._follow_pattern = follow_pattern
        self._concurrency = concurrency

        # Browser
        self._driver_type = driver_type
        self._browser = browser
        self._headless = headless

        # Content
        self._parse_videos = parse_videos
        self._parse_navs = parse_navs
        self._parse_tables = parse_tables
        self._content_format = content_format
        self._content_extraction = content_extraction
        self._trafilatura_fallback_threshold = trafilatura_fallback_threshold

        # Toolkit
        self._llm_client = llm_client
        self._plans_dir = plans_dir
        self._save_plan = save_plan

        # Lazy-initialized toolkit instance
        self._toolkit: Optional[Any] = None

    # ── Toolkit lifecycle ─────────────────────────────────────────────

    def _get_toolkit(self) -> Any:
        """Lazy-initialize the WebScrapingToolkit."""
        if self._toolkit is not None:
            return self._toolkit

        from parrot_tools.scraping.toolkit import WebScrapingToolkit

        kwargs: Dict[str, Any] = {
            "driver_type": self._driver_type,
            "browser": self._browser,
            "headless": self._headless,
        }
        if self._llm_client is not None:
            kwargs["llm_client"] = self._llm_client
        if self._plans_dir is not None:
            kwargs["plans_dir"] = self._plans_dir

        self._toolkit = WebScrapingToolkit(**kwargs)
        return self._toolkit

    # ── HTML content extraction ───────────────────────────────────────

    @staticmethod
    def _md(soup: BeautifulSoup, **options: Any) -> str:
        """Convert BeautifulSoup tree to Markdown."""
        return MarkdownConverter(**options).convert_soup(soup)

    @staticmethod
    def _text(node: Any) -> str:
        """Extract stripped text from a node."""
        if node is None:
            return ""
        if isinstance(node, NavigableString):
            return str(node).strip()
        return node.get_text(" ", strip=True)

    def _collect_video_links(self, soup: BeautifulSoup) -> List[str]:
        """Extract video links (iframes, <video>, <source>)."""
        items: List[str] = []
        for iframe in soup.find_all("iframe"):
            src = iframe.get("src")
            if src:
                items.append(f"Video Link: {src}")
        for video in soup.find_all("video"):
            src = video.get("src")
            if src:
                items.append(f"Video Link: {src}")
            for source in video.find_all("source"):
                s = source.get("src")
                if s:
                    items.append(f"Video Source: {s}")
        seen: set = set()
        return [x for x in items if x not in seen and not seen.add(x)]

    def _collect_navbars(self, soup: BeautifulSoup) -> List[str]:
        """Extract navigation menus as Markdown lists."""
        nav_texts: List[str] = []

        def nav_to_md(nav: Any) -> str:
            lines: List[str] = []
            blocks = nav.find_all(["ul", "ol"], recursive=True)
            if not blocks:
                for a in nav.find_all("a", href=True):
                    txt = self._text(a)
                    href = a.get("href", "")
                    lines.append(f"- {txt} (Link: {href})" if href else f"- {txt}")
            else:
                for block in blocks:
                    for li in block.find_all("li", recursive=False):
                        a = li.find("a", href=True)
                        if a:
                            txt = self._text(a)
                            href = a.get("href", "")
                            lines.append(
                                f"- {txt} (Link: {href})" if href else f"- {txt}"
                            )
                        else:
                            t = self._text(li)
                            if t:
                                lines.append(f"- {t}")
                        for sub in li.find_all(["ul", "ol"], recursive=False):
                            for sub_li in sub.find_all("li", recursive=False):
                                a2 = sub_li.find("a", href=True)
                                if a2:
                                    txt2 = self._text(a2)
                                    href2 = a2.get("href", "")
                                    lines.append(
                                        f"  - {txt2} (Link: {href2})"
                                        if href2 else f"  - {txt2}"
                                    )
                                else:
                                    t2 = self._text(sub_li)
                                    if t2:
                                        lines.append(f"  - {t2}")
            return "\n".join(lines)

        for nav in soup.find_all("nav"):
            md_list = nav_to_md(nav)
            if md_list.strip():
                nav_texts.append("Navigation:\n" + md_list)

        if not nav_texts:
            candidates = soup.select("[role='navigation'], .navbar, .menu, .nav")
            for nav in candidates:
                md_list = nav_to_md(nav)
                if md_list.strip():
                    nav_texts.append("Navigation:\n" + md_list)

        return nav_texts

    def _table_to_markdown(self, table: Any) -> str:
        """Convert an HTML <table> to GitHub-flavored Markdown."""
        caption_el = table.find("caption")
        caption = self._text(caption_el) if caption_el else ""

        headers: List[str] = []
        thead = table.find("thead")
        if thead:
            ths = thead.find_all("th")
            if ths:
                headers = [self._text(th) for th in ths]
        if not headers:
            first_row = table.find("tr")
            if first_row:
                cells = first_row.find_all(["th", "td"])
                headers = [self._text(c) for c in cells]

        rows: List[List[str]] = []
        for tr in table.find_all("tr"):
            cells = tr.find_all("td")
            if cells:
                rows.append([self._text(td) for td in cells])

        if not headers and rows:
            headers = [f"Col {i + 1}" for i in range(len(rows[0]))]

        ncol = len(headers)
        norm_rows = []
        for r in rows:
            if len(r) < ncol:
                r = r + [""] * (ncol - len(r))
            elif len(r) > ncol:
                r = r[:ncol]
            norm_rows.append(r)

        def esc(cell: str) -> str:
            return (cell or "").replace("|", "\\|").strip()

        md_lines: List[str] = []
        if caption:
            md_lines.append(f"Table: {caption}\n")
        if headers:
            md_lines.append("| " + " | ".join(esc(h) for h in headers) + " |")
            md_lines.append("| " + " | ".join("---" for _ in headers) + " |")
        for r in norm_rows:
            md_lines.append("| " + " | ".join(esc(c) for c in r) + " |")
        return "\n".join(md_lines).strip()

    def _collect_tables(self, soup: BeautifulSoup, max_tables: int = 25) -> List[str]:
        """Extract tables as Markdown."""
        out: List[str] = []
        for i, table in enumerate(soup.find_all("table")):
            if i >= max_tables:
                break
            try:
                out.append(self._table_to_markdown(table))
            except Exception:
                continue
        return out

    def _extract_page_title(self, soup: BeautifulSoup) -> str:
        """Extract page title from <title> or og:title."""
        try:
            if soup.title and soup.title.string:
                return soup.title.string.strip()
            og = soup.find("meta", property="og:title")
            if og and og.get("content"):
                return og["content"].strip()
        except Exception:
            pass
        return ""

    def _extract_page_language(self, soup: BeautifulSoup) -> str:
        """Extract page language from <html lang> or meta tags."""
        try:
            html_tag = soup.find("html")
            if html_tag and html_tag.get("lang"):
                return html_tag["lang"].strip()
            meta = soup.find("meta", attrs={"http-equiv": "Content-Language"})
            if meta and meta.get("content"):
                return meta["content"].strip()
        except Exception:
            pass
        return "en"

    def _extract_meta_description(self, soup: BeautifulSoup) -> str:
        """Extract meta description from the page."""
        try:
            meta = soup.find("meta", attrs={"name": "description"})
            if meta and meta.get("content"):
                return meta["content"].strip()
            og = soup.find("meta", property="og:description")
            if og and og.get("content"):
                return og["content"].strip()
        except Exception:
            pass
        return ""

    # ── Trafilatura extraction ───────────────────────────────────────

    def _extract_with_trafilatura(
        self,
        html: str,
    ) -> tuple[Optional[str], Dict[str, Any]]:
        """Extract main content and metadata using trafilatura.

        Args:
            html: Raw HTML string to extract from.

        Returns:
            Tuple of (extracted_text, metadata_dict). Returns (None, {})
            on failure or when trafilatura is not available.
        """
        if not HAS_TRAFILATURA:
            return None, {}

        try:
            # Extract main content text
            extracted_text = trafilatura.extract(
                html,
                include_comments=False,
                include_tables=False,  # Tables extracted separately
                output_format="txt",
            )

            # Extract metadata via bare_extraction
            metadata: Dict[str, Any] = {}
            try:
                result = trafilatura.bare_extraction(html)
                if result is not None:
                    metadata = {
                        "author": result.author or None,
                        "date": result.date or None,
                        "sitename": result.sitename or None,
                        "categories": result.categories or None,
                        "tags": result.tags or None,
                        "title": result.title or None,
                        "description": result.description or None,
                        "language": result.language or None,
                    }
                    # Remove None values
                    metadata = {k: v for k, v in metadata.items() if v is not None}
            except Exception as exc:
                self.logger.debug(
                    "trafilatura.bare_extraction failed: %s", exc
                )

            return extracted_text, metadata

        except Exception as exc:
            self.logger.warning(
                "trafilatura extraction failed: %s", exc
            )
            return None, {}

    # ── ScrapingResult → Documents ────────────────────────────────────

    def _result_to_documents(
        self,
        result: Any,
        url: str,
        crawl_depth: Optional[int] = None,
    ) -> List[Document]:
        """Convert a ScrapingResult into a list of Documents.

        Produces:
        1. A full-page markdown document (content_kind=markdown_full)
        2. One fragment per tag-extracted text block (content_kind=fragment)
        3. One document per named selector extraction (content_kind=selector)
        4. Optional video/nav/table fragments

        Args:
            result: A ``ScrapingResult`` from the scraping toolkit.
            url: The URL that was scraped.
            crawl_depth: Crawl depth level (None for single-page).

        Returns:
            List of Documents with rich metadata.
        """
        if not result.success:
            self.logger.warning(
                "Skipping failed result for %s: %s",
                url, result.error_message,
            )
            return []

        soup = result.bs_soup

        # Remove noise elements
        for el in soup(["script", "style", "link", "noscript"]):
            el.decompose()

        page_title = self._extract_page_title(soup) or url
        page_language = self._extract_page_language(soup)
        meta_description = self._extract_meta_description(soup)

        base_metadata: Dict[str, Any] = {
            "source": url,
            "url": result.url or url,
            "filename": page_title,
            "source_type": "webpage",
            "type": "webpage",
            "category": self.category,
            "created_at": datetime.now().strftime("%Y-%m-%d, %H:%M:%S"),
            "document_meta": {
                "language": page_language,
                "title": page_title,
                "description": meta_description,
            },
        }
        if crawl_depth is not None:
            base_metadata["crawl_depth"] = crawl_depth

        docs: List[Document] = []

        # 1. Full-page content extraction — with trafilatura pipeline
        use_trafilatura = False
        traf_metadata: Dict[str, Any] = {}

        if self._content_extraction in ("auto", "trafilatura"):
            if HAS_TRAFILATURA:
                # Get raw HTML for trafilatura (prefers result.content
                # since it's the original HTML; falls back to str(soup))
                html_str = getattr(result, "content", None) or str(soup)
                extracted_text, traf_metadata = self._extract_with_trafilatura(
                    html_str
                )

                if extracted_text and self._content_extraction == "trafilatura":
                    # Force mode: use trafilatura output even if sparse
                    use_trafilatura = True
                elif extracted_text:
                    # Auto mode: check quality threshold
                    raw_text = soup.get_text(strip=True)
                    ratio = len(extracted_text) / max(len(raw_text), 1)
                    use_trafilatura = ratio >= self._trafilatura_fallback_threshold
                    if not use_trafilatura:
                        self.logger.info(
                            "trafilatura output too sparse (ratio=%.2f < threshold=%.2f) "
                            "for %s, falling back to markdownify",
                            ratio,
                            self._trafilatura_fallback_threshold,
                            url,
                        )
                else:
                    use_trafilatura = False
                    self.logger.debug(
                        "trafilatura returned empty for %s, falling back",
                        url,
                    )
            elif self._content_extraction == "trafilatura":
                raise ImportError(
                    "trafilatura is required for content_extraction='trafilatura' "
                    "but is not installed. Install with: pip install trafilatura>=1.12"
                )
            else:
                # Auto mode, trafilatura not installed — silent fallback
                self.logger.debug(
                    "trafilatura not installed, using markdownify fallback"
                )

        if use_trafilatura:
            # Use trafilatura extracted content
            # Enrich document_meta with trafilatura metadata
            doc_meta = base_metadata.get("document_meta", {})
            doc_meta.update(traf_metadata)
            base_metadata["document_meta"] = doc_meta

            docs.append(Document(
                page_content=extracted_text,
                metadata={
                    **base_metadata,
                    "content_kind": "trafilatura_main",
                    "content_extraction": "trafilatura",
                },
            ))
        elif self._content_extraction in ("markdown", "auto") or (
            self._content_extraction == "trafilatura" and not use_trafilatura
        ):
            # Markdownify or text fallback
            extraction_label = (
                "markdownify_fallback"
                if self._content_extraction in ("auto", "trafilatura")
                else "markdown"
            )
            if self._content_format == "markdown":
                md_text = self._md(soup)
                if md_text.strip():
                    docs.append(Document(
                        page_content=md_text,
                        metadata={
                            **base_metadata,
                            "content_kind": "markdown_full",
                            "content_extraction": extraction_label,
                        },
                    ))
            else:
                full_text = soup.get_text("\n", strip=True)
                if full_text.strip():
                    docs.append(Document(
                        page_content=full_text,
                        metadata={
                            **base_metadata,
                            "content_kind": "text_full",
                            "content_extraction": extraction_label,
                        },
                    ))
        else:
            # content_extraction == "text"
            full_text = soup.get_text("\n", strip=True)
            if full_text.strip():
                docs.append(Document(
                    page_content=full_text,
                    metadata={
                        **base_metadata,
                        "content_kind": "text_full",
                        "content_extraction": "text",
                    },
                ))

        # 2. Tag-based fragments
        if self._tags:
            for tag_el in soup.find_all(self._tags):
                text = " ".join(tag_el.get_text(" ", strip=True).split())
                if text:
                    docs.append(Document(
                        page_content=text,
                        metadata={
                            **base_metadata,
                            "content_kind": "fragment",
                            "html_tag": tag_el.name,
                        },
                    ))

        # 3. Named selector extractions
        if result.extracted_data:
            for name, value in result.extracted_data.items():
                if isinstance(value, list):
                    content = "\n".join(str(v) for v in value if v)
                else:
                    content = str(value) if value else ""
                if content.strip():
                    docs.append(Document(
                        page_content=content,
                        metadata={
                            **base_metadata,
                            "content_kind": "selector",
                            "selector_name": name,
                        },
                    ))

        # 4. Video links
        if self._parse_videos:
            videos = self._collect_video_links(soup)
            for v in videos:
                docs.append(Document(
                    page_content=v,
                    metadata={**base_metadata, "content_kind": "video_link"},
                ))

        # 5. Navigation menus
        if self._parse_navs:
            navs = self._collect_navbars(soup)
            for nav in navs:
                docs.append(Document(
                    page_content=nav,
                    metadata={**base_metadata, "content_kind": "navigation"},
                ))

        # 6. Tables
        if self._parse_tables:
            tables = self._collect_tables(soup)
            for tbl in tables:
                if tbl.strip():
                    docs.append(Document(
                        page_content=tbl,
                        metadata={**base_metadata, "content_kind": "table"},
                    ))

        return docs

    # ── Core loader interface ─────────────────────────────────────────

    async def _scrape_single(self, url: str) -> List[Document]:
        """Scrape a single URL and return Documents.

        Args:
            url: The URL to scrape.

        Returns:
            List of Documents extracted from the page.
        """
        toolkit = self._get_toolkit()

        scrape_kwargs: Dict[str, Any] = {
            "url": url,
            "save_plan": self._save_plan,
        }

        if self._plan is not None:
            scrape_kwargs["plan"] = self._plan
        elif self._steps is not None:
            scrape_kwargs["steps"] = self._steps
            if self._selectors:
                scrape_kwargs["selectors"] = self._selectors
        elif self._objective is not None:
            scrape_kwargs["objective"] = self._objective
        else:
            # Default: simple navigate + selectors
            scrape_kwargs["steps"] = [
                {
                    "action": "navigate",
                    "url": url,
                    "description": f"Navigate to {url}",
                }
            ]
            if self._selectors:
                scrape_kwargs["selectors"] = self._selectors

        result = await toolkit.scrape(**scrape_kwargs)
        return self._result_to_documents(result, url)

    async def _crawl_site(self, start_url: str) -> List[Document]:
        """Crawl a site starting from a URL and return Documents.

        Args:
            start_url: The entry point URL for crawling.

        Returns:
            List of Documents from all successfully scraped pages.
        """
        toolkit = self._get_toolkit()

        crawl_kwargs: Dict[str, Any] = {
            "start_url": start_url,
            "depth": self._depth,
            "max_pages": self._max_pages,
            "concurrency": self._concurrency,
            "save_plan": self._save_plan,
        }
        if self._follow_selector is not None:
            crawl_kwargs["follow_selector"] = self._follow_selector
        if self._follow_pattern is not None:
            crawl_kwargs["follow_pattern"] = self._follow_pattern
        if self._plan is not None:
            crawl_kwargs["plan"] = self._plan
        elif self._objective is not None:
            crawl_kwargs["objective"] = self._objective

        crawl_result = await toolkit.crawl(**crawl_kwargs)

        docs: List[Document] = []
        for page_result in crawl_result.pages:
            page_url = getattr(page_result, "url", start_url)
            page_docs = self._result_to_documents(
                page_result,
                page_url,
                crawl_depth=getattr(page_result, "depth", None),
            )
            docs.extend(page_docs)

        self.logger.info(
            "Crawl complete: %d pages scraped, %d documents generated, "
            "%d failed URLs",
            crawl_result.total_pages,
            len(docs),
            len(crawl_result.failed_urls),
        )
        return docs

    async def _load(
        self,
        source: Union[str, PurePath],
        **kwargs: Any,
    ) -> List[Document]:
        """Load documents from a single URL.

        This is the core method required by ``AbstractLoader``. It dispatches
        to either ``_crawl_site`` or ``_scrape_single`` based on configuration.

        Args:
            source: URL to load from.
            **kwargs: Additional keyword arguments (unused).

        Returns:
            List of Documents.
        """
        url = str(source)
        self.logger.info("WebScrapingLoader loading: %s (crawl=%s)", url, self._crawl)

        if self._crawl:
            return await self._crawl_site(url)
        return await self._scrape_single(url)
