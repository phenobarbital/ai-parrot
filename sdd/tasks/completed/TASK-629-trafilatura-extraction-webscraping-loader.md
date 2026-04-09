# TASK-629: Add trafilatura content extraction to WebScrapingLoader

**Feature**: vector-store-handler-scraping
**Spec**: `sdd/specs/vector-store-handler-scraping.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-628
**Assigned-to**: unassigned

---

## Context

> This is the core task for FEAT-091. The `WebScrapingLoader._result_to_documents()` method
> currently converts HTML to Markdown via `markdownify`, which does a naive full-page conversion
> that includes navigation, sidebars, footers, and other boilerplate. For RAG retrieval,
> we need main content isolation.
>
> This task adds a trafilatura-based extraction pipeline with intelligent fallback to the
> existing markdownify path when trafilatura's output is too sparse.
>
> Implements: Spec Module 1.

---

## Scope

- Add `content_extraction` parameter to `WebScrapingLoader.__init__()` with modes: `"auto"`, `"trafilatura"`, `"markdown"`, `"text"`
- Add `trafilatura_fallback_threshold` parameter (default `0.1` = 10%)
- Add private method `_extract_with_trafilatura(html: str) -> Tuple[Optional[str], Dict[str, Any]]` that:
  - Calls `trafilatura.extract()` for main content text
  - Calls `trafilatura.bare_extraction()` for metadata (author, date, sitename, categories)
  - Returns `(extracted_text, metadata_dict)` or `(None, {})` on failure
- Add graceful import guard: `try: import trafilatura; HAS_TRAFILATURA = True except ImportError: HAS_TRAFILATURA = False`
- Modify `_result_to_documents()` to route through extraction pipeline:
  - `"auto"`: try trafilatura first, fall back to markdownify if output < threshold or trafilatura unavailable
  - `"trafilatura"`: force trafilatura, no fallback (error if not installed)
  - `"markdown"`: existing markdownify path (no change)
  - `"text"`: existing plain text path (no change)
- Enrich `Document.metadata["document_meta"]` with trafilatura-extracted fields: `author`, `date`, `sitename`, `categories`
- Add `content_extraction` field to `Document.metadata` indicating which method was used (`"trafilatura"` or `"markdownify_fallback"`)
- Tables continue to be extracted separately via existing `_collect_tables()` regardless of extraction mode

**NOT in scope**:
- Modifying the handler (`handler.py`) — that's TASK-631
- Modifying `WebLoader` — that's TASK-630
- Writing tests — that's TASK-632

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py` | MODIFY | Add trafilatura extraction pipeline |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Existing imports in webscraping.py (keep all):
from bs4 import BeautifulSoup, NavigableString          # line 44
from markdownify import MarkdownConverter               # line 45
from parrot.loaders.abstract import AbstractLoader      # line 47
from parrot.stores.models import Document               # line 48

# New import to add (with guard):
# try:
#     import trafilatura
#     HAS_TRAFILATURA = True
# except ImportError:
#     HAS_TRAFILATURA = False
```

### Existing Signatures to Use

```python
# packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py

class WebScrapingLoader(AbstractLoader):  # line 51
    def __init__(
        self,
        source: Optional[Union[str, List[str]]] = None,
        *,
        # ... existing params through line 123 ...
        content_format: Literal["markdown", "text"] = "markdown",  # line 118
        **kwargs: Any,
    ) -> None: ...  # line 124

    # The primary method to modify:
    def _result_to_documents(
        self,
        result: Any,
        url: str,
        crawl_depth: Optional[int] = None,
    ) -> List[Document]: ...  # line 375
    # Currently at line 404: soup = result.bs_soup
    # At line 407: removes script/style/link/noscript elements
    # At line 434: branches on self._content_format == "markdown"

    # Helpers that remain unchanged:
    @staticmethod
    def _md(soup: BeautifulSoup, **options) -> str: ...               # line 187
    @staticmethod
    def _text(node: Any) -> str: ...                                  # line 192
    def _collect_tables(self, soup, max_tables=25) -> List[str]: ...  # line 323
    def _extract_page_title(self, soup) -> str: ...                   # line 335
    def _extract_page_language(self, soup) -> str: ...                # line 347
    def _extract_meta_description(self, soup) -> str: ...             # line 360
```

```python
# packages/ai-parrot/src/parrot/stores/models.py:21
class Document(BaseModel):
    page_content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
```

### Does NOT Exist

- ~~`WebScrapingLoader.extract_with_trafilatura()`~~ — does not exist yet; must be created as `_extract_with_trafilatura()`
- ~~`WebScrapingLoader.content_extraction`~~ — this parameter does not exist yet; must be added to `__init__`
- ~~`WebScrapingLoader.trafilatura_fallback_threshold`~~ — does not exist yet; must be added
- ~~`trafilatura.extract_metadata()`~~ — NOT a real function. Use `trafilatura.bare_extraction()` which returns a dict with metadata fields
- ~~`result.content`~~ — ScrapingResult has `bs_soup` (BeautifulSoup) but `content` may or may not exist; use `str(result.bs_soup)` to get HTML string for trafilatura
- ~~`HAS_TRAFILATURA`~~ — does not exist yet; must be defined as module-level constant

---

## Implementation Notes

### Pattern to Follow

The extraction method should follow this logic in `_result_to_documents()`:

```python
# Pseudocode for the extraction routing:
if self._content_extraction in ("auto", "trafilatura"):
    if HAS_TRAFILATURA:
        extracted_text, traf_metadata = self._extract_with_trafilatura(html_str)
        if extracted_text and self._content_extraction == "trafilatura":
            # Force mode: use trafilatura output even if sparse
            use_trafilatura = True
        elif extracted_text:
            # Auto mode: check quality threshold
            raw_text = soup.get_text(strip=True)
            ratio = len(extracted_text) / max(len(raw_text), 1)
            use_trafilatura = ratio >= self._trafilatura_fallback_threshold
        else:
            use_trafilatura = False
    elif self._content_extraction == "trafilatura":
        raise ImportError("trafilatura is required but not installed")
    else:
        use_trafilatura = False  # auto mode, trafilatura not installed

if use_trafilatura:
    # Build Document from trafilatura output
    # Merge traf_metadata into document_meta
else:
    # Existing markdownify or text path (unchanged)
```

### trafilatura API Reference

```python
# Main content extraction:
text = trafilatura.extract(
    html_string,
    include_comments=False,
    include_tables=False,  # We extract tables separately
    output_format='txt',   # or 'xml' for structural markup
)

# Full extraction with metadata:
result = trafilatura.bare_extraction(html_string)
# Returns dict with keys: 'text', 'title', 'author', 'date',
# 'sitename', 'categories', 'tags', 'description', 'language', etc.
```

### Key Constraints

- Trafilatura expects raw HTML string, NOT a BeautifulSoup object. Get HTML via `str(result.bs_soup)` or `result.content` if available.
- Always run `_collect_tables()` on the original soup regardless of extraction mode (trafilatura strips tables)
- Always run video/nav extraction on original soup (existing behavior, unchanged)
- The `content_extraction` parameter is independent of `content_format` — `content_format` controls the fallback path
- Use `self.logger` for extraction mode decisions and fallback triggers

### References in Codebase

- `packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py:375-508` — current `_result_to_documents()` to modify
- `packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py:92-158` — constructor to extend
- `packages/ai-parrot-loaders/src/parrot_loaders/web.py:412-462` — WebLoader.clean_html() for reference on HTML cleaning pattern

---

## Acceptance Criteria

- [ ] `WebScrapingLoader` accepts `content_extraction` parameter with modes: `"auto"`, `"trafilatura"`, `"markdown"`, `"text"`
- [ ] `WebScrapingLoader` accepts `trafilatura_fallback_threshold` parameter (default 0.1)
- [ ] In `"auto"` mode with trafilatura installed: tries trafilatura first, falls back to markdownify if output < threshold
- [ ] In `"auto"` mode without trafilatura installed: falls back to markdownify silently
- [ ] In `"trafilatura"` mode without trafilatura installed: raises `ImportError`
- [ ] In `"markdown"` mode: existing behavior unchanged
- [ ] `Document.metadata["document_meta"]` includes trafilatura-extracted fields when available
- [ ] `Document.metadata["content_extraction"]` indicates which method was used
- [ ] Tables extracted as separate Documents regardless of extraction mode
- [ ] No breaking changes to existing `WebScrapingLoader` API (new params are optional with defaults)

---

## Test Specification

```python
# tests/loaders/test_webscraping_loader.py (created in TASK-632)
# These are the test cases this task must support:

# test_trafilatura_extraction_clean_content
# - Given HTML with nav/footer/scripts + main content
# - When _result_to_documents called with content_extraction="auto"
# - Then main content extracted, nav/footer stripped

# test_trafilatura_metadata_extraction
# - Given HTML with meta tags
# - When _result_to_documents called
# - Then metadata dict contains author, date, sitename

# test_trafilatura_fallback_on_sparse_output
# - Given HTML where trafilatura returns very little
# - When _result_to_documents called with content_extraction="auto"
# - Then markdownify fallback is used

# test_content_extraction_mode_markdown
# - Given content_extraction="markdown"
# - Then trafilatura is NOT called, markdownify used directly
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/vector-store-handler-scraping.spec.md` for full context
2. **Check dependencies** — verify TASK-628 is in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Read `packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py` to confirm signatures
   - Confirm `import trafilatura` works after TASK-628
   - Check `trafilatura.bare_extraction()` API matches expectations
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-629-trafilatura-extraction-webscraping-loader.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
