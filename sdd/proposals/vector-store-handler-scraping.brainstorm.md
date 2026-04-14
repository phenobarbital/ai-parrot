# Brainstorm: Vector Store Handler — Clean Content Extraction from Scraped Pages

**Date**: 2026-04-09
**Author**: Claude / Jesus
**Status**: exploration
**Recommended Option**: Option C

---

## Problem Statement

The `VectorStoreHandler._load_urls()` method (handler.py:777-795) uses the **legacy `WebScrapingTool`** directly to fetch web pages, storing the raw `result.content` (complete HTML with `<script>`, `<style>`, navigation, ads, etc.) into the vector store. This raw HTML is unsuitable for RAG retrieval because:

1. **Noise drowns signal** — scripts, stylesheets, navigation menus, footers, and tracking code dilute the actual page content, degrading embedding quality and retrieval relevance.
2. **Token waste** — raw HTML is 3-10x larger than extracted text, consuming embedding model tokens and vector store space unnecessarily.
3. **Bypasses existing infrastructure** — a `WebScrapingLoader` already exists in `parrot_loaders/webscraping.py` that converts HTML to Markdown with metadata extraction, but the handler doesn't use it.
4. **Product pages are especially noisy** — pages like `att.com/prepaid/plans/` have heavy JavaScript rendering, promotional banners, and complex layouts where the useful content is a small fraction of the total DOM.

**Who is affected**: Any user loading web content into a vector store via the REST API (`PUT /api/v1/ai/stores` with `url` field). The poor extraction quality directly impacts RAG answer quality downstream.

## Constraints & Requirements

- Must preserve backward compatibility with the existing `PUT /api/v1/ai/stores` API contract
- Must work with the existing `JobManager` async batching pattern
- Must produce Markdown-formatted output preserving links, headers, and semantic structure
- Must extract page metadata (title, description, language, author, date) into `Document.metadata`
- Must handle both single-page scraping and multi-page crawling (via `CrawlEngine`, depth=2 default)
- Content extraction must handle JavaScript-rendered pages (SPA, dynamic content)
- Smart chunking: large documents should be chunked; short pages kept whole to preserve context
- Must not break the existing `WebScrapingLoader` or `WebLoader` — additive changes only

---

## Options Explored

### Option A: Wire Existing WebScrapingLoader into VectorStoreHandler

Replace the direct `WebScrapingTool` usage in `_load_urls()` with the existing `WebScrapingLoader`, which already handles HTML-to-Markdown conversion via `markdownify`, tag-based extraction, table parsing, video link extraction, and metadata extraction.

This is the minimal fix: the handler would delegate to the loader instead of doing raw scraping.

**Pros:**
- Immediate improvement — markdownify removes scripts/styles and produces readable Markdown
- Zero new dependencies — uses only existing `markdownify` + `BeautifulSoup`
- Low risk — `WebScrapingLoader` is already tested and working
- Consistent architecture — handler uses loader (same pattern as file uploads)
- Metadata extraction already built in (title, description, language)

**Cons:**
- `markdownify` does naive full-page conversion — it doesn't isolate "main content" from navigation, sidebars, and footer noise
- For noisy product pages (att.com), the Markdown output will still contain menu items, footer links, cookie banners, etc.
- No readability-style content isolation — all DOM content is converted equally
- Tables and structured pricing data may not be extracted optimally

**Effort:** Low

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `markdownify` | HTML-to-Markdown | Already a dependency |
| `beautifulsoup4` | HTML parsing | Already a dependency |

**Existing Code to Reuse:**
- `packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py` — the full WebScrapingLoader
- `packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py:375-508` — `_result_to_documents()` with all extraction helpers

---

### Option B: Integrate Trafilatura for Main Content Extraction

Add `trafilatura` as a content extraction engine. Trafilatura is a Python library specifically designed for web content extraction — it uses a combination of heuristics, readability algorithms, and fallback strategies to isolate the "main content" of a page, stripping navigation, ads, sidebars, and boilerplate.

The WebScrapingLoader would gain a new `content_extraction` mode that runs trafilatura on the raw HTML before producing Documents. Trafilatura outputs clean text or XML with structural markup, which can then be converted to Markdown.

**Pros:**
- Purpose-built for exactly this problem — main content extraction from noisy web pages
- Excellent at removing boilerplate (nav, footer, sidebars, cookie banners, ads)
- Built-in metadata extraction (author, date, categories, tags, sitename)
- Supports both text and XML output (XML preserves structural hierarchy)
- Handles multilingual content well
- Active maintenance, widely used (5k+ GitHub stars), well-tested on diverse web pages
- Can extract structured data like tables when configured
- Supports fallback strategies (tries multiple extraction methods)

**Cons:**
- New dependency — adds `trafilatura` (+ its transitive deps: `courlan`, `htmldate`, `justext`, etc.)
- May over-strip content on some pages — aggressive boilerplate removal can lose relevant sidebar information
- Trafilatura's Markdown output is basic — may need post-processing for richer formatting
- No built-in support for JavaScript-rendered pages — needs the already-fetched HTML (which WebScrapingToolkit provides via browser automation)
- Less control over what gets extracted compared to explicit CSS selectors

**Effort:** Medium

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `trafilatura` | Main content extraction, boilerplate removal | v1.12+, actively maintained |
| `beautifulsoup4` | Fallback HTML parsing | Already a dependency |
| `markdownify` | XML/HTML-to-Markdown post-processing | Already a dependency |

**Existing Code to Reuse:**
- `packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py` — extend WebScrapingLoader
- `packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py:370-434` — `scrape()` method provides `ScrapingResult` with `bs_soup`

---

### Option C: Hybrid Trafilatura + Markdownify with Intelligent Fallback

Combine trafilatura for main content isolation with markdownify as a fallback strategy. The extraction pipeline would be:

1. **Primary**: Run trafilatura on the raw HTML to extract main content + metadata
2. **Quality check**: If trafilatura returns content that is too sparse (below a configurable threshold relative to the original page size), fall back to markdownify-based extraction
3. **Metadata merge**: Combine trafilatura's metadata (author, date, categories) with BeautifulSoup-extracted metadata (og:tags, structured data)
4. **Structured extras**: Extract tables, pricing data, and structured elements separately using BeautifulSoup (trafilatura sometimes strips these)
5. **Smart chunking**: If content exceeds a size threshold, chunk with section-aware splitting; otherwise keep as single document

The handler (`_load_urls`) would be refactored to delegate to `WebScrapingLoader` with this enhanced pipeline.

**Pros:**
- Best content quality — trafilatura handles main content isolation; markdownify catches what trafilatura misses
- Resilient — fallback prevents data loss on pages where trafilatura is too aggressive
- Rich metadata — combines both extraction engines' metadata capabilities
- Structured data preserved — tables and pricing grids extracted separately via BeautifulSoup
- Smart chunking preserves context for short pages while properly splitting large ones
- Handler cleanup — removes legacy `WebScrapingTool` direct usage, uses proper loader pattern
- Crawl support — `WebScrapingLoader` already supports `CrawlEngine` with depth parameter

**Cons:**
- Higher complexity — two extraction paths with quality-check logic
- New dependency (trafilatura) with transitive deps
- Slightly slower — runs trafilatura then potentially markdownify on fallback
- Quality threshold tuning may need iteration per domain/page-type
- More testing surface area

**Effort:** Medium

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `trafilatura` | Main content extraction, metadata, boilerplate removal | v1.12+, core extraction engine |
| `markdownify` | Fallback HTML-to-Markdown conversion | Already a dependency |
| `beautifulsoup4` | Structured data extraction (tables, selectors) | Already a dependency |

**Existing Code to Reuse:**
- `packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py` — extend the full WebScrapingLoader
- `packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py:275-333` — table extraction helpers
- `packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py:335-371` — metadata extraction helpers
- `packages/ai-parrot/src/parrot/handlers/stores/handler.py:746-797` — `_load_urls()` to refactor
- `packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py` — WebScrapingToolkit backend
- `packages/ai-parrot-tools/src/parrot_tools/scraping/crawler.py:24-62` — CrawlEngine for multi-page

---

### Option D: LLM-Assisted Content Extraction

Use an LLM (via the existing `llm_client` parameter) to analyze the raw HTML and extract structured, clean content. The LLM would receive the page HTML (or a simplified version) and produce clean Markdown with semantic structure.

**Pros:**
- Most flexible — LLM can understand page intent and extract contextually relevant content
- Handles ambiguous layouts where heuristics fail
- Can produce high-quality summaries alongside extracted content
- Can extract structured data (pricing tables, product specs) into consistent formats

**Cons:**
- Expensive — API calls per page, especially for batch/crawl operations
- Slow — adds significant latency per page (seconds vs milliseconds for trafilatura)
- Token limits — large pages may exceed context windows
- Non-deterministic — same page may produce different extractions
- Overkill for most pages where trafilatura works fine
- Doesn't scale for crawling dozens of pages

**Effort:** High

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| LLM client | Content extraction via prompt | Existing AbstractClient infrastructure |
| `beautifulsoup4` | Pre-processing HTML before sending to LLM | Already a dependency |

**Existing Code to Reuse:**
- `packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py:119-121` — `llm_client` parameter already exists
- `packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py:188-227` — `plan_create()` already uses LLM

---

## Recommendation

**Option C** (Hybrid Trafilatura + Markdownify with Intelligent Fallback) is recommended because:

1. **It solves the actual problem**: Noisy product pages like `att.com/prepaid/plans/` need readability-style extraction that trafilatura provides. Pure markdownify (Option A) won't isolate main content from navigation noise.

2. **Fallback prevents data loss**: Trafilatura can be aggressive on pages with unusual layouts. The markdownify fallback ensures we never lose content — we just get a less-clean version in edge cases.

3. **The handler fix is included**: Refactoring `_load_urls()` to use `WebScrapingLoader` instead of raw `WebScrapingTool` is the architectural fix that should have been done regardless. Option C includes this as part of the work.

4. **Metadata enrichment is valuable for RAG**: Trafilatura extracts author, date, categories, and sitename — these metadata fields improve retrieval quality when stored alongside embeddings.

5. **LLM extraction (Option D) is overkill**: For batch URL processing, the latency and cost of LLM calls don't justify the marginal quality improvement over trafilatura.

6. **Effort is reasonable**: Medium effort for a significant improvement in RAG content quality. The existing `WebScrapingLoader` provides most of the infrastructure — we're adding a new extraction layer, not rewriting.

The tradeoff is adding `trafilatura` as a new dependency with its transitive deps. This is acceptable because trafilatura is stable, well-maintained, and purpose-built for this exact use case.

---

## Feature Description

### User-Facing Behavior

**API contract unchanged**: Users continue to call `PUT /api/v1/ai/stores` with a `url` field (single URL or list). The response format remains identical (job_id for background processing).

**New optional parameters** in the JSON body:
- `content_extraction`: `"auto"` (default) | `"trafilatura"` | `"markdown"` | `"text"` — controls the extraction strategy
- `crawl_depth`: `int` (default 2) — maximum crawl depth when `crawl_entire_site=true`
- `extract_tables`: `bool` (default true) — extract tables as separate Markdown documents
- `extract_metadata`: `bool` (default true) — extract rich page metadata

**Improved output quality**: Documents stored in the vector store will contain clean, structured Markdown text instead of raw HTML. Metadata will include page title, description, language, author, date, and source URL.

### Internal Behavior

The data flow for URL loading becomes:

```
PUT /api/v1/ai/stores {url: [...]}
  → VectorStoreHandler._load_urls()
    → WebScrapingLoader(source=urls, crawl=crawl_entire_site, depth=crawl_depth)
      → WebScrapingToolkit.scrape() / .crawl()    [browser automation, JS rendering]
        → ScrapingResult (raw HTML + bs_soup)
      → Content Extraction Pipeline:
        1. trafilatura.extract(html) → main content + metadata
        2. Quality check: if len(extracted) / len(raw_text) < threshold → fallback to markdownify
        3. BeautifulSoup: extract tables, structured data separately
        4. Merge metadata from trafilatura + BeautifulSoup
      → List[Document] (clean Markdown + rich metadata)
    → store.add_documents(documents)
```

**Smart chunking logic**:
- If extracted content < `chunk_size` (configurable, default from AbstractLoader): store as single Document
- If extracted content > `chunk_size`: use section-aware splitting (split on `##` headers first, then paragraphs)
- Tables are always stored as separate Documents (they have their own semantic meaning)

### Edge Cases & Error Handling

- **trafilatura returns empty**: Fall back to markdownify extraction of the full page
- **trafilatura returns very sparse content** (< 10% of raw text size): Fall back to markdownify
- **Page fails to load** (timeout, 404, etc.): Log warning, skip page, continue with remaining URLs
- **JavaScript-heavy SPA with no server-rendered content**: WebScrapingToolkit handles JS rendering via browser automation; trafilatura receives the rendered HTML
- **Non-HTML content** (PDF link, image URL): Detect content-type and delegate to appropriate loader or skip
- **Very large pages** (> 1MB HTML): Apply extraction with a size cap; warn in logs
- **Rate limiting / blocking**: Respect existing `CrawlEngine` concurrency and delay settings
- **Crawl discovers non-HTML pages**: Skip binary content types, only process text/html

---

## Capabilities

### New Capabilities
- `trafilatura-content-extraction`: Main content isolation from web pages using trafilatura with intelligent fallback
- `smart-web-chunking`: Section-aware document chunking based on page size

### Modified Capabilities
- `vector-store-url-loading`: Refactor `_load_urls()` to use `WebScrapingLoader` instead of legacy `WebScrapingTool`
- `web-scraping-loader`: Enhance with trafilatura extraction mode and metadata enrichment

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/handlers/stores/handler.py` | modifies | Refactor `_load_urls()` to use WebScrapingLoader |
| `parrot_loaders/webscraping.py` | extends | Add trafilatura extraction pipeline + smart chunking |
| `parrot_loaders/__init__.py` or `factory.py` | may modify | Ensure WebScrapingLoader is discoverable |
| `pyproject.toml` (ai-parrot-loaders) | modifies | Add `trafilatura` dependency |
| `parrot/stores/models.py` | no change | Document model is already sufficient |
| `parrot_tools/scraping/toolkit.py` | no change | Used as backend, no modifications needed |
| `parrot_tools/scraping/crawler.py` | no change | CrawlEngine used as-is |

No breaking changes. The API contract is backward-compatible (new parameters are optional with sensible defaults).

---

## Code Context

### User-Provided Code

No code snippets provided by the user during discovery.

### Verified Codebase References

#### Classes & Signatures

```python
# From packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py:51
class WebScrapingLoader(AbstractLoader):
    def __init__(
        self,
        source: Optional[Union[str, List[str]]] = None,
        *,
        selectors: Optional[List[Dict[str, Any]]] = None,
        tags: Optional[List[str]] = None,
        steps: Optional[List[Dict[str, Any]]] = None,
        plan: Optional[Any] = None,
        objective: Optional[str] = None,
        crawl: bool = False,
        depth: int = 1,
        max_pages: Optional[int] = None,
        follow_selector: Optional[str] = None,
        follow_pattern: Optional[str] = None,
        concurrency: int = 1,
        driver_type: Literal["selenium", "playwright"] = "selenium",
        browser: Literal[...] = "chrome",
        headless: bool = True,
        parse_videos: bool = True,
        parse_navs: bool = False,
        parse_tables: bool = True,
        content_format: Literal["markdown", "text"] = "markdown",
        llm_client: Optional[Any] = None,
        plans_dir: Optional[str] = None,
        save_plan: bool = False,
        **kwargs: Any,
    ) -> None: ...

    def _get_toolkit(self) -> Any: ...                          # line 165
    def _md(soup: BeautifulSoup, **options) -> str: ...         # line 187 (static)
    def _text(node: Any) -> str: ...                            # line 192 (static)
    def _collect_video_links(self, soup) -> List[str]: ...      # line 201
    def _collect_navbars(self, soup) -> List[str]: ...          # line 219
    def _table_to_markdown(self, table) -> str: ...             # line 275
    def _collect_tables(self, soup, max_tables=25) -> List[str]: ...  # line 323
    def _extract_page_title(self, soup) -> str: ...             # line 335
    def _extract_page_language(self, soup) -> str: ...          # line 347
    def _extract_meta_description(self, soup) -> str: ...       # line 360
    def _result_to_documents(self, result, url, crawl_depth=None) -> List[Document]: ...  # line 375
    async def _scrape_single(self, url: str) -> List[Document]: ...    # line 512
    async def _crawl_site(self, start_url: str) -> List[Document]: ... # line 551
    async def _load(self, source, **kwargs) -> List[Document]: ...     # line 599
```

```python
# From packages/ai-parrot/src/parrot/handlers/stores/handler.py:36
class VectorStoreHandler(BaseView):
    async def _load_urls(
        self, store, urls, config, crawl_entire_site=False, prompt=None
    ) -> list[Document]: ...  # line 746 — THIS IS THE METHOD TO REFACTOR

    async def _put_json_body(self, jm) -> web.Response: ...  # line 609
    # _put_json_body calls _load_urls at line 671
```

```python
# From packages/ai-parrot/src/parrot/stores/models.py:21
class Document(BaseModel):
    page_content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
```

```python
# From packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py:27
class WebScrapingToolkit(AbstractToolkit):
    async def scrape(self, url, plan=None, objective=None, steps=None,
                     selectors=None, save_plan=False,
                     browser_config_override=None) -> ScrapingResult: ...  # line 370
    async def crawl(self, start_url, depth=1, max_pages=None,
                    follow_selector=None, follow_pattern=None,
                    plan=None, objective=None, save_plan=False,
                    concurrency=1) -> Any: ...  # line 436
```

```python
# From packages/ai-parrot-tools/src/parrot_tools/scraping/crawler.py:24
class CrawlEngine:
    def __init__(self, scrape_fn, strategy=None, follow_selector="a[href]",
                 follow_pattern=None, allow_external=False,
                 concurrency=1, logger=None) -> None: ...
    async def run(self, start_url, plan, depth=1, max_pages=None) -> CrawlResult: ...  # line 68
```

```python
# From packages/ai-parrot-loaders/src/parrot_loaders/web.py:169
class WebLoader(AbstractLoader):
    # Older Selenium-based loader; WebScrapingLoader is its successor
    def clean_html(self, html, tags, objects=[], *,
                   parse_videos=True, parse_navs=True,
                   parse_tables=True) -> Tuple[List[str], str, str]: ...
    async def _load(self, address, **kwargs) -> List[Document]: ...
```

#### Verified Imports

```python
# These imports have been confirmed to work:
from parrot.loaders.abstract import AbstractLoader     # packages/ai-parrot/src/parrot/loaders/abstract.py
from parrot.stores.models import Document              # packages/ai-parrot/src/parrot/stores/models.py
from parrot_loaders.webscraping import WebScrapingLoader  # packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py
from parrot_tools.scraping.toolkit import WebScrapingToolkit  # packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py
from parrot_tools.scraping import CrawlEngine, CrawlResult   # packages/ai-parrot-tools/src/parrot_tools/scraping/__init__.py
from bs4 import BeautifulSoup, NavigableString         # third-party, already installed
from markdownify import MarkdownConverter              # third-party, already installed
```

#### Key Attributes & Constants

- `WebScrapingLoader._tags` default: `["p", "h1", "h2", "h3", "h4", "article", "section"]` (webscraping.py:131)
- `WebScrapingLoader._content_format` default: `"markdown"` (webscraping.py:153)
- `WebScrapingLoader._depth` default: `1` (webscraping.py:138)
- `VectorStoreHandler._load_urls()` uses legacy `WebScrapingTool` directly (handler.py:777-795)
- `_JOB_MANAGER_KEY` = `"vectorstore_job_manager"` (handler.py:21)

### Does NOT Exist (Anti-Hallucination)

- ~~`trafilatura`~~ — **not currently installed** as a dependency anywhere in the project
- ~~`parrot_loaders.webscraping.WebScrapingLoader.extract_with_trafilatura()`~~ — does not exist; no trafilatura integration exists yet
- ~~`parrot_tools.scraping.ContentExtractor`~~ — does not exist; no dedicated content extraction class
- ~~`VectorStoreHandler._load_urls()` using WebScrapingLoader~~ — it currently uses legacy `WebScrapingTool` directly, NOT the loader
- ~~`WebScrapingLoader.smart_chunk()`~~ — no smart chunking method exists; chunking is handled by AbstractLoader's generic text_splitter

---

## Parallelism Assessment

**Internal parallelism**: Yes — this feature can be split into at least 2 independent tasks:
1. **Handler refactor** (`_load_urls()` → use `WebScrapingLoader`) — touches only `handler.py`
2. **Trafilatura integration** (add extraction pipeline to `WebScrapingLoader`) — touches only `webscraping.py` and `pyproject.toml`

These two tasks modify different files and can be developed in parallel, with a final integration task that wires them together.

**Cross-feature independence**: No conflicts with in-flight specs detected. The `WebScrapingLoader` and `VectorStoreHandler` are not being modified by other features.

**Recommended isolation**: `mixed` — the handler refactor and trafilatura integration can use individual worktrees, with a short integration step at the end.

**Rationale**: The two main files (`handler.py` and `webscraping.py`) have no shared code changes, making parallel development safe. The integration step is just ensuring the handler passes the right parameters to the enhanced loader.

---

## Open Questions

- [ ] What should the trafilatura fallback threshold be? (e.g., if extracted < 10% of raw text, fall back) — *Owner: Jesus*
- [ ] Should the `content_extraction` parameter be exposed in the REST API, or should `"auto"` (trafilatura-first) always be the default? — *Owner: Jesus*
- [ ] Should we deprecate the legacy `WebScrapingTool` direct usage in the handler, or keep it as an option? — *Owner: Jesus*
- [ ] Do we need to handle pages that require authentication (login-gated content) differently in the extraction pipeline? — *Owner: Jesus*
- [ ] Should the `WebLoader` (older Selenium loader) also gain trafilatura support, or is it sufficient to enhance only `WebScrapingLoader`? — *Owner: Jesus*
