# Feature Specification: Vector Store Handler — Clean Content Extraction from Scraped Pages

**Feature ID**: FEAT-091
**Date**: 2026-04-09
**Author**: Jesus Lara
**Status**: approved
**Target version**: next
**Brainstorm**: `sdd/proposals/vector-store-handler-scraping.brainstorm.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

The `VectorStoreHandler._load_urls()` method uses the legacy `WebScrapingTool` directly, storing raw HTML content (complete with `<script>`, `<style>`, navigation, ads, cookie banners, and tracking code) into the vector store. This raw HTML is unsuitable for RAG retrieval:

- **Noise drowns signal**: scripts, stylesheets, navigation menus, and footer links dilute embedding quality and degrade retrieval relevance.
- **Token waste**: raw HTML is 3-10x larger than extracted text, consuming embedding model tokens and vector store space unnecessarily.
- **Bypasses existing infrastructure**: a fully-featured `WebScrapingLoader` already exists with HTML-to-Markdown conversion, metadata extraction, and table parsing, but the handler doesn't use it.
- **Product pages are especially noisy**: pages like `att.com/prepaid/plans/` have heavy JavaScript rendering, promotional banners, and complex layouts where the useful content is a small fraction of the total DOM.

### Goals

- Refactor `VectorStoreHandler._load_urls()` to delegate to `WebScrapingLoader` instead of using legacy `WebScrapingTool` directly
- Integrate `trafilatura` into `WebScrapingLoader` for intelligent main-content extraction with boilerplate removal
- Provide intelligent fallback to `markdownify` when trafilatura strips too aggressively
- Extract rich page metadata (title, description, language, author, date, sitename) into `Document.metadata`
- Implement size-aware chunking: keep short pages whole, section-split large ones
- Support both single-page scraping and multi-page crawling (depth=2 default)

### Non-Goals (explicitly out of scope)

- Changing the REST API contract for `PUT /api/v1/ai/stores` (backward-compatible additions only)
- LLM-assisted content extraction (too expensive for batch operations)
- Modifying `WebLoader` (the older Selenium-based loader) — only `WebScrapingLoader` is enhanced
- Changing the `WebScrapingToolkit` or `CrawlEngine` internals
- Adding new HTTP endpoints

---

## 2. Architectural Design

### Overview

The solution has two parts:

1. **Handler refactor**: Replace the direct `WebScrapingTool` usage in `VectorStoreHandler._load_urls()` with `WebScrapingLoader`, aligning the URL loading path with the proper loader pattern already used for file uploads.

2. **Content extraction enhancement**: Add a trafilatura-based extraction pipeline to `WebScrapingLoader._result_to_documents()` with intelligent fallback to the existing markdownify path when trafilatura's output is too sparse.

### Component Diagram

```
PUT /api/v1/ai/stores {url: [...]}
  │
  ▼
VectorStoreHandler._load_urls()  ←── REFACTORED: uses WebScrapingLoader
  │
  ▼
WebScrapingLoader(source=urls, crawl=..., depth=..., content_extraction=...)
  │
  ├── WebScrapingToolkit.scrape() / .crawl()    [browser automation, JS rendering]
  │     └── ScrapingResult (raw HTML + bs_soup)
  │
  ▼
Content Extraction Pipeline (NEW in _result_to_documents):
  │
  ├─ 1. trafilatura.extract(html) → main content text + metadata
  │     ├── Quality check: len(extracted) / len(raw_text) < threshold?
  │     │     YES → fallback to markdownify (existing path)
  │     │     NO  → use trafilatura output
  │     └── Extract metadata: author, date, categories, sitename
  │
  ├─ 2. BeautifulSoup: extract tables, structured data (existing helpers)
  │
  ├─ 3. Merge metadata from trafilatura + BeautifulSoup extractors
  │
  └─ 4. Smart chunking: short pages → single Document; large → section-split
  │
  ▼
List[Document]  →  store.add_documents()
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `VectorStoreHandler` | modifies | `_load_urls()` refactored to use `WebScrapingLoader` |
| `WebScrapingLoader` | extends | New extraction mode, metadata enrichment, smart chunking |
| `WebScrapingToolkit` | uses (unchanged) | Backend for browser automation, no changes needed |
| `CrawlEngine` | uses (unchanged) | Multi-page crawling, already integrated in loader |
| `AbstractLoader` | inherits (unchanged) | Provides `load()`, chunking, text splitting infrastructure |
| `Document` model | uses (unchanged) | `page_content` + `metadata` fields sufficient |
| `JobManager` | uses (unchanged) | Async background job handling for URL loading |

### Data Models

No new data models required. The existing `Document` model is sufficient:

```python
# parrot/stores/models.py:21 — unchanged
class Document(BaseModel):
    page_content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
```

The `metadata` dict will be enriched with new fields from trafilatura:

```python
# New metadata fields (added by extraction pipeline, not a new model):
{
    "source": "https://example.com/page",
    "url": "https://example.com/page",
    "filename": "Page Title",
    "source_type": "webpage",
    "type": "webpage",
    "content_kind": "markdown_full",  # or "trafilatura_main"
    "content_extraction": "trafilatura",  # or "markdownify_fallback"
    "document_meta": {
        "language": "en",
        "title": "Page Title",
        "description": "Meta description",
        "author": "Author Name",         # NEW from trafilatura
        "date": "2026-01-15",            # NEW from trafilatura
        "sitename": "Example.com",       # NEW from trafilatura
        "categories": ["tech", "news"],  # NEW from trafilatura
    },
}
```

### New Public Interfaces

No new public classes. The changes are internal to existing classes:

```python
# WebScrapingLoader gains a new constructor parameter:
class WebScrapingLoader(AbstractLoader):
    def __init__(
        self,
        ...,
        content_extraction: Literal["auto", "trafilatura", "markdown", "text"] = "auto",
        trafilatura_fallback_threshold: float = 0.1,
        ...
    ) -> None: ...
```

---

## 3. Module Breakdown

### Module 1: Trafilatura Content Extraction in WebScrapingLoader

- **Path**: `packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py`
- **Responsibility**: Add trafilatura-based content extraction to `_result_to_documents()` with intelligent fallback to markdownify. Add new `content_extraction` parameter. Extract enriched metadata from trafilatura.
- **Depends on**: `trafilatura` package (new dependency)

**Changes**:
- Add `content_extraction` and `trafilatura_fallback_threshold` constructor parameters
- Add `_extract_with_trafilatura(html: str) -> Tuple[Optional[str], Dict[str, Any]]` private method
- Modify `_result_to_documents()` to route through trafilatura when `content_extraction` is `"auto"` or `"trafilatura"`
- Fallback logic: if trafilatura output is less than `trafilatura_fallback_threshold` (default 10%) of raw text length, fall back to existing markdownify path
- Enrich `Document.metadata["document_meta"]` with trafilatura-extracted fields (author, date, sitename, categories)
- Tables continue to be extracted separately via existing `_collect_tables()` (trafilatura often strips them)

### Module 2: Handler Refactor — _load_urls Uses WebScrapingLoader

- **Path**: `packages/ai-parrot/src/parrot/handlers/stores/handler.py`
- **Responsibility**: Replace the legacy `WebScrapingTool` + `CrawlEngine` direct usage in `_load_urls()` with `WebScrapingLoader`, delegating all content extraction to the loader.
- **Depends on**: Module 1 (enhanced WebScrapingLoader)

**Changes**:
- Rewrite `_load_urls()` (lines 746-797) to instantiate `WebScrapingLoader` with appropriate parameters
- Map existing handler parameters to loader parameters:
  - `crawl_entire_site` → `crawl=True, depth=2`
  - URLs → `source` parameter
- Remove direct imports of `WebScrapingTool`, `CrawlEngine`, `ScrapingStep`, `Navigate` from the handler
- Keep YouTube URL special-casing (delegate to `YoutubeLoader` as before)
- Pass `content_extraction="auto"` by default

### Module 3: Dependency Addition

- **Path**: `packages/ai-parrot-loaders/pyproject.toml`
- **Responsibility**: Add `trafilatura` as an optional dependency for the loaders package.
- **Depends on**: None

**Changes**:
- Add `trafilatura>=1.12` to `[project.optional-dependencies]` under a `scraping` extra or to the main dependencies
- Ensure `WebScrapingLoader` handles missing trafilatura gracefully (import guard, fall back to markdownify if not installed)

### Module 4: Tests

- **Path**: `tests/loaders/test_webscraping_loader.py` (new) and `tests/handlers/test_vectorstore_handler.py` (extend)
- **Responsibility**: Test trafilatura extraction pipeline, fallback logic, metadata enrichment, and handler integration.
- **Depends on**: Modules 1, 2, 3

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_trafilatura_extraction_clean_content` | Module 1 | Verify trafilatura extracts main content from sample HTML, stripping nav/footer/scripts |
| `test_trafilatura_metadata_extraction` | Module 1 | Verify author, date, sitename, categories extracted into metadata |
| `test_trafilatura_fallback_on_sparse_output` | Module 1 | When trafilatura returns < threshold, verify markdownify fallback is used |
| `test_trafilatura_fallback_on_empty_output` | Module 1 | When trafilatura returns empty/None, verify markdownify fallback |
| `test_content_extraction_mode_auto` | Module 1 | `content_extraction="auto"` tries trafilatura first |
| `test_content_extraction_mode_markdown` | Module 1 | `content_extraction="markdown"` skips trafilatura entirely |
| `test_content_extraction_mode_trafilatura` | Module 1 | `content_extraction="trafilatura"` forces trafilatura, no fallback |
| `test_tables_extracted_separately` | Module 1 | Tables preserved as separate Documents regardless of extraction mode |
| `test_missing_trafilatura_graceful` | Module 3 | If trafilatura not installed, falls back to markdownify without error |
| `test_load_urls_uses_loader` | Module 2 | Verify `_load_urls()` instantiates WebScrapingLoader, not WebScrapingTool |
| `test_load_urls_crawl_mode` | Module 2 | Verify `crawl_entire_site=True` maps to `crawl=True, depth=2` |
| `test_load_urls_youtube_bypass` | Module 2 | YouTube URLs still route to YoutubeLoader |

### Integration Tests

| Test | Description |
|---|---|
| `test_put_url_produces_clean_documents` | Full PUT request with URL → verify stored Documents contain clean Markdown, not raw HTML |
| `test_put_url_crawl_produces_multiple_documents` | Crawl mode produces Documents from multiple pages |
| `test_extraction_quality_product_page` | Verify extraction of a product-like page produces meaningful content without nav/footer noise |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_product_page_html():
    """HTML mimicking a product page with nav, footer, scripts, and main content."""
    return """
    <html lang="en">
    <head>
        <title>Prepaid Plans | Example Wireless</title>
        <meta name="description" content="Check out our prepaid plans">
        <meta name="author" content="Example Wireless">
        <script>var tracking = true;</script>
        <style>.nav { color: blue; }</style>
    </head>
    <body>
        <nav><a href="/">Home</a><a href="/plans">Plans</a></nav>
        <main>
            <h1>Prepaid Plans</h1>
            <p>Get the best prepaid wireless plans starting at $25/mo.</p>
            <table>
                <thead><tr><th>Plan</th><th>Price</th><th>Data</th></tr></thead>
                <tbody>
                    <tr><td>Basic</td><td>$25/mo</td><td>5GB</td></tr>
                    <tr><td>Plus</td><td>$40/mo</td><td>15GB</td></tr>
                </tbody>
            </table>
            <h2>Why Choose Prepaid?</h2>
            <p>No credit check. No annual contract. No surprises.</p>
        </main>
        <footer>Copyright 2026 Example Wireless</footer>
        <script>analytics.track('page_view');</script>
    </body>
    </html>
    """

@pytest.fixture
def sample_scraping_result(sample_product_page_html):
    """Mock ScrapingResult with bs_soup from sample HTML."""
    from unittest.mock import MagicMock
    from bs4 import BeautifulSoup
    result = MagicMock()
    result.success = True
    result.url = "https://example.com/plans"
    result.bs_soup = BeautifulSoup(sample_product_page_html, "html.parser")
    result.extracted_data = {}
    result.content = sample_product_page_html
    return result
```

---

## 5. Acceptance Criteria

- [x] `VectorStoreHandler._load_urls()` delegates to `WebScrapingLoader` — no direct `WebScrapingTool` usage
- [ ] `WebScrapingLoader` supports `content_extraction` parameter with modes: `"auto"`, `"trafilatura"`, `"markdown"`, `"text"`
- [ ] In `"auto"` mode, trafilatura is tried first; falls back to markdownify if output is sparse (< threshold)
- [ ] Extracted Documents contain clean structured Markdown, not raw HTML
- [ ] `Document.metadata["document_meta"]` includes trafilatura-extracted fields (author, date, sitename) when available
- [ ] Tables extracted as separate Documents with `content_kind="table"` regardless of extraction mode
- [ ] If `trafilatura` package is not installed, loader gracefully falls back to markdownify without raising ImportError
- [ ] YouTube URLs continue to route to `YoutubeLoader` in the handler
- [ ] All existing unit tests continue to pass
- [ ] New unit tests cover: trafilatura extraction, fallback logic, metadata enrichment, handler delegation
- [ ] No breaking changes to the `PUT /api/v1/ai/stores` API contract
- [ ] REST API backward-compatible: existing requests without `content_extraction` work identically (default `"auto"`)

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
# Core loader base class:
from parrot.loaders.abstract import AbstractLoader
# verified: packages/ai-parrot/src/parrot/loaders/abstract.py:35

# Document model:
from parrot.stores.models import Document
# verified: packages/ai-parrot/src/parrot/stores/models.py:21

# WebScrapingLoader:
from parrot_loaders.webscraping import WebScrapingLoader
# verified: packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py:51

# HTML processing (already installed):
from bs4 import BeautifulSoup, NavigableString
from markdownify import MarkdownConverter

# Scraping toolkit (used by loader internally):
from parrot_tools.scraping.toolkit import WebScrapingToolkit
# verified: packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py:27

# Crawl engine (used by loader internally):
from parrot_tools.scraping import CrawlEngine, CrawlResult
# verified: packages/ai-parrot-tools/src/parrot_tools/scraping/__init__.py

# YouTube loader (used by handler):
from parrot_loaders.youtube import YoutubeLoader
# verified: used in handler.py:771

# Legacy imports currently in handler (TO BE REMOVED):
from parrot_tools.scraping import WebScrapingTool, CrawlEngine
from parrot_tools.scraping.models import ScrapingStep, Navigate
# verified: handler.py:777-778
```

### Existing Class Signatures

```python
# packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py:51
class WebScrapingLoader(AbstractLoader):
    def __init__(
        self,
        source: Optional[Union[str, List[str]]] = None,
        *,
        selectors: Optional[List[Dict[str, Any]]] = None,
        tags: Optional[List[str]] = None,           # default: ["p","h1","h2","h3","h4","article","section"]
        steps: Optional[List[Dict[str, Any]]] = None,
        plan: Optional[Any] = None,
        objective: Optional[str] = None,
        crawl: bool = False,                         # line 102
        depth: int = 1,                              # line 103
        max_pages: Optional[int] = None,             # line 104
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

    # Key methods that will be modified:
    def _result_to_documents(self, result, url, crawl_depth=None) -> List[Document]: ...  # line 375
    # This is the primary method to enhance with trafilatura.

    # Methods that remain unchanged:
    def _get_toolkit(self) -> Any: ...                                # line 165
    @staticmethod
    def _md(soup: BeautifulSoup, **options) -> str: ...               # line 187
    @staticmethod
    def _text(node: Any) -> str: ...                                  # line 192
    def _collect_video_links(self, soup) -> List[str]: ...            # line 201
    def _collect_navbars(self, soup) -> List[str]: ...                # line 219
    def _table_to_markdown(self, table) -> str: ...                   # line 275
    def _collect_tables(self, soup, max_tables=25) -> List[str]: ...  # line 323
    def _extract_page_title(self, soup) -> str: ...                   # line 335
    def _extract_page_language(self, soup) -> str: ...                # line 347
    def _extract_meta_description(self, soup) -> str: ...             # line 360
    async def _scrape_single(self, url: str) -> List[Document]: ...   # line 512
    async def _crawl_site(self, start_url: str) -> List[Document]: ...# line 551
    async def _load(self, source, **kwargs) -> List[Document]: ...    # line 599
```

```python
# packages/ai-parrot/src/parrot/handlers/stores/handler.py:36
class VectorStoreHandler(BaseView):
    # Method to refactor:
    async def _load_urls(
        self, store, urls, config, crawl_entire_site=False, prompt=None
    ) -> list[Document]: ...  # line 746

    # Caller of _load_urls:
    async def _put_json_body(self, jm) -> web.Response: ...  # line 609
    # Creates job and calls _load_urls at line 670-676
```

```python
# packages/ai-parrot/src/parrot/loaders/abstract.py:35
class AbstractLoader(ABC):
    chunk_size: int       # default 800, line 62
    chunk_overlap: int    # default 100, line 63

    @abstractmethod
    async def _load(self, source: Union[str, PurePath], **kwargs) -> List[Document]: ...  # line 420

    async def load(
        self,
        source: Optional[Any] = None,
        split_documents: bool = True,
        late_chunking: bool = False,
        vector_store=None,
        store_full_document: bool = True,
        auto_detect_content_type: bool = None,
        **kwargs
    ) -> List[Document]: ...  # line 560
```

```python
# packages/ai-parrot/src/parrot/stores/models.py:21
class Document(BaseModel):
    page_content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_load_urls()` (refactored) | `WebScrapingLoader` | `loader = WebScrapingLoader(source=urls, ...)` then `await loader.load()` | handler.py:746 |
| `_result_to_documents()` (enhanced) | `trafilatura.extract()` | function call on raw HTML string | webscraping.py:375 |
| `_result_to_documents()` (fallback) | `MarkdownConverter.convert_soup()` | existing `_md()` static method | webscraping.py:187 |

### Does NOT Exist (Anti-Hallucination)

- ~~`trafilatura`~~ — **not currently installed** in the project; must be added as dependency
- ~~`WebScrapingLoader.extract_with_trafilatura()`~~ — does not exist yet; must be created
- ~~`WebScrapingLoader.content_extraction`~~ — this parameter does not exist yet; must be added
- ~~`WebScrapingLoader.smart_chunk()`~~ — no smart chunking method exists; chunking is handled by `AbstractLoader`'s generic `text_splitter`
- ~~`parrot_tools.scraping.ContentExtractor`~~ — does not exist; no dedicated content extraction class
- ~~`VectorStoreHandler._load_urls()` using WebScrapingLoader~~ — it currently uses legacy `WebScrapingTool` directly (handler.py:777-795), NOT the loader
- ~~`trafilatura.extract_metadata()`~~ — trafilatura uses `trafilatura.extract()` with `include_comments=False, output_format='txt'` and `trafilatura.metadata.extract_metadata()` for metadata; do not assume API — check trafilatura docs

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Loader pattern**: All content loading goes through `AbstractLoader` subclasses; the handler should never directly use scraping tools
- **Graceful import guard**: Use try/except for trafilatura import so the feature degrades gracefully:
  ```python
  try:
      import trafilatura
      HAS_TRAFILATURA = True
  except ImportError:
      HAS_TRAFILATURA = False
  ```
- **Metadata enrichment**: Add new fields to `Document.metadata["document_meta"]` dict, don't create new top-level keys
- **Existing helper reuse**: Continue using `_extract_page_title()`, `_extract_page_language()`, `_extract_meta_description()`, `_collect_tables()` — trafilatura supplements, not replaces
- **Logging**: Use `self.logger` for extraction mode decisions, fallback triggers, and quality metrics

### Known Risks / Gotchas

- **trafilatura API stability**: trafilatura's API has been stable since v1.0, but verify the exact function signatures against the installed version. Key functions: `trafilatura.extract(html, include_comments=False, include_tables=False, output_format='txt')` and `trafilatura.bare_extraction(html)` for metadata.
- **trafilatura + BeautifulSoup interaction**: trafilatura expects raw HTML string, not a BeautifulSoup object. Use `str(result.bs_soup)` or the original HTML from `result.content` if available.
- **Fallback threshold tuning**: The 10% threshold is a starting point. Product pages with lots of navigation and little content may need a lower threshold. Consider making this configurable per-request in the future.
- **Table extraction**: trafilatura strips tables by default. Always run `_collect_tables()` on the original soup regardless of extraction mode.
- **CrawlEngine depth**: Default changed from 1 to 2 in the handler. Ensure the loader respects this when `crawl_entire_site=True`.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `trafilatura` | `>=1.12` | Main content extraction, boilerplate removal, metadata extraction |
| `markdownify` | (existing) | Fallback HTML-to-Markdown conversion |
| `beautifulsoup4` | (existing) | HTML parsing, table extraction, metadata extraction |

---

## 8. Open Questions

- [x] What should the trafilatura fallback threshold be? Starting at 0.1 (10%). May need per-domain tuning. — *Owner: Jesus*: starting at 10%
- [x] Should `content_extraction` parameter be exposed in the REST API body, or always default to `"auto"`? — *Owner: Jesus*: exposed in api for granular control.
- [x] Should we deprecate the legacy `WebScrapingTool` direct usage patterns, or just remove them from the handler? — *Owner: Jesus*: remove from the handler.
- [x] Should the `WebLoader` (older Selenium loader) also gain trafilatura support, or is enhancing only `WebScrapingLoader` sufficient? — *Owner: Jesus*: gain trafilatura support.

---

## Worktree Strategy

**Default isolation**: `per-spec` (sequential tasks in one worktree)

While Modules 1 and 2 modify different files (`webscraping.py` vs `handler.py`), Module 2 depends on Module 1's new `content_extraction` parameter being available. Sequential execution in a single worktree is simpler and avoids integration issues.

**Task execution order**:
1. Module 3 (add trafilatura dependency) — prerequisite for all
2. Module 1 (trafilatura extraction in WebScrapingLoader) — core feature
3. Module 2 (handler refactor) — uses enhanced loader
4. Module 4 (tests) — validates everything

**Cross-feature dependencies**: None. No other in-flight specs modify `webscraping.py` or `handler.py:_load_urls()`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-09 | Jesus Lara / Claude | Initial draft from brainstorm |
