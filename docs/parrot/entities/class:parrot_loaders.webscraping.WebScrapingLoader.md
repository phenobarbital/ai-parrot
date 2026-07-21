---
type: Wiki Entity
title: WebScrapingLoader
id: class:parrot_loaders.webscraping.WebScrapingLoader
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Load web pages via WebScrapingToolkit and convert to Documents.
relates_to:
- concept: class:parrot.loaders.abstract.AbstractLoader
  rel: extends
---

# WebScrapingLoader

Defined in [`parrot_loaders.webscraping`](../summaries/mod:parrot_loaders.webscraping.md).

```python
class WebScrapingLoader(AbstractLoader)
```

Load web pages via WebScrapingToolkit and convert to Documents.

Delegates browser automation and crawling to the scraping infrastructure
(``parrot_tools.scraping``) while exposing the standard Loader interface
(``_load`` / ``load``).

Args:
    source: URL or list of URLs to scrape.
    selectors: CSS/XPath selectors for structured extraction.
        Each dict has keys: ``name``, ``selector``, and optionally
        ``selector_type`` (css|xpath|tag), ``extract_type``
        (text|html|attribute), ``attribute``, ``multiple``.
    tags: HTML tags to extract text as independent fragment documents
        (e.g. ``['p', 'h1', 'article']``). **Opt-in**: defaults to an
        empty list because per-tag fragments often produce sub-chunks
        smaller than ``min_chunk_size`` (e.g. a lone ``<h2>Frequently
        asked questions</h2>`` becomes a 4-token "chunk" after the
        splitter, polluting vector stores with noise). When needed,
        pass an explicit list; an empty list disables fragment emission.
        The full-page markdown/trafilatura document is always emitted
        and will be chunked coherently by the splitter.
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
    extract_only: Controls which documents are emitted.
        - ``None`` (default): auto-detect — True when ``objective``,
          ``plan``, or ``selectors`` is provided (targeted extraction
          implies the caller wants only the structured results),
          False otherwise (plain page scrape yields full content).
        - ``True``: force-yield ONLY ``content_kind="selector"``
          documents from ``result.extracted_data``.
        - ``False``: always emit full-page markdown/trafilatura,
          fragments, tables, videos, navs alongside selector docs.
    llm_client: LLM client for plan auto-generation (required when
        ``objective`` is provided without a plan).
    plans_dir: Directory for plan caching.
    save_plan: Persist auto-generated plans after scraping.
    max_refinement_attempts: How many LLM refinement passes to allow
        when the first plan's extraction scores poorly (empty rows,
        mostly-null fields, or step errors). Set to 0 to disable.
        Default 1 — so at most 2 LLM calls total per URL. Only
        applies when the plan is LLM-generated; explicit/cached
        plans are never refined.
    jsonld_types: Control which JSON-LD ``@type`` values are extracted.
        - ``None`` (default): extract all supported types via
          ``EXTRACTOR_REGISTRY``.
        - Non-empty list (e.g. ``["Product", "Event"]``): extract only
          the listed types.  Note that alias types are separate registry
          keys and must be listed explicitly — e.g. to capture both
          ``Product`` and ``IndividualProduct`` nodes, pass
          ``["Product", "IndividualProduct"]``.
        - Empty list ``[]``: disable all JSON-LD extraction.
    **kwargs: Passed through to ``AbstractLoader``.
