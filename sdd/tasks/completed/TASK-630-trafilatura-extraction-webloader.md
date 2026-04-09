# TASK-630: Add trafilatura content extraction to WebLoader

**Feature**: vector-store-handler-scraping
**Spec**: `sdd/specs/vector-store-handler-scraping.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-628, TASK-629
**Assigned-to**: unassigned

---

## Context

> Per the user's decision on open question #4, the older `WebLoader` should also gain
> trafilatura support. This task mirrors TASK-629's extraction logic but adapts it to
> `WebLoader`'s different architecture.
>
> `WebLoader` uses Selenium WebDriver directly (via `WebDriverPool`) and processes HTML
> through its `clean_html()` method, which returns `(content_list, md_text, page_title)`.
> The trafilatura extraction should be added as an alternative to the existing
> BeautifulSoup + markdownify pipeline inside `clean_html()`.
>
> Implements: Spec Open Question #4 resolution (WebLoader gains trafilatura support).

---

## Scope

- Add `content_extraction` parameter to `WebLoader.__init__()` with modes: `"auto"`, `"trafilatura"`, `"markdown"`, `"text"` (default `"auto"`)
- Add `trafilatura_fallback_threshold` parameter (default `0.1`)
- Modify `clean_html()` to optionally route through trafilatura:
  - When `content_extraction` is `"auto"` or `"trafilatura"`: run trafilatura on raw HTML before BeautifulSoup processing
  - If trafilatura output is adequate (above threshold): use it as the `md_text` return value and extract content fragments from it
  - If trafilatura output is sparse: fall back to existing markdownify path
  - Tables always extracted via existing `_collect_tables()` regardless
- Modify `_load()` to pass `content_extraction` metadata into Document metadata
- Reuse the same `HAS_TRAFILATURA` import guard pattern from TASK-629
- Extract metadata (author, date, sitename) via `trafilatura.bare_extraction()` and include in Document metadata

**NOT in scope**:
- Modifying `WebScrapingLoader` (that's TASK-629)
- Modifying the handler (that's TASK-631)
- Writing tests (that's TASK-632)
- Changing the `WebDriverPool` or Selenium interaction

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-loaders/src/parrot_loaders/web.py` | MODIFY | Add trafilatura extraction to clean_html() and _load() |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Existing imports in web.py (keep all):
from bs4 import BeautifulSoup, NavigableString
from markdownify import MarkdownConverter

# New import to add (with guard, same pattern as TASK-629):
# try:
#     import trafilatura
#     HAS_TRAFILATURA = True
# except ImportError:
#     HAS_TRAFILATURA = False
```

### Existing Signatures to Use

```python
# packages/ai-parrot-loaders/src/parrot_loaders/web.py

class WebLoader(AbstractLoader):  # line 169
    def __init__(
        self,
        source_type: str = 'website',
        *,
        browser: str = "chrome",
        timeout: int = 60,
        page_load_strategy: str = "normal",
        user_agent: Optional[str] = DEFAULT_UA,
        max_drivers: int = 3,
        driver_pool: Optional[WebDriverPool] = None,
        **kwargs
    ): ...

    def clean_html(
        self,
        html: str,
        tags: List[str],
        objects: List[Dict[str, Dict[str, Any]]] = [],
        *,
        parse_videos: bool = True,
        parse_navs: bool = True,
        parse_tables: bool = True
    ) -> Tuple[List[str], str, str]: ...  # line 412
    # Returns: (content_fragments, markdown_full_text, page_title)

    async def _load(self, address: Union[str, dict], **kwargs) -> List[Document]: ...
    # Calls clean_html() and builds Document objects

    # Helper methods (unchanged):
    def md(self, soup: BeautifulSoup, **options) -> str: ...
    def _text(self, node: Any) -> str: ...
    def _collect_video_links(self, soup) -> List[str]: ...
    def _collect_navbars(self, soup) -> List[str]: ...
    def _table_to_markdown(self, table) -> str: ...
    def _collect_tables(self, soup, max_tables=25) -> List[str]: ...
```

### Does NOT Exist

- ~~`WebLoader.content_extraction`~~ — does not exist yet; must be added to `__init__`
- ~~`WebLoader._extract_with_trafilatura()`~~ — does not exist; must be created
- ~~`WebLoader.trafilatura_fallback_threshold`~~ — does not exist yet
- ~~`trafilatura.extract_metadata()`~~ — NOT a real function; use `trafilatura.bare_extraction()`

---

## Implementation Notes

### Pattern to Follow

The key difference from `WebScrapingLoader` (TASK-629) is that `WebLoader.clean_html()` returns a tuple `(content_list, md_text, page_title)` rather than building Documents directly. The trafilatura integration should:

1. Run trafilatura on the raw `html` string parameter (before BeautifulSoup parsing)
2. If successful and above threshold: use trafilatura output as `md_text`; still build `content_list` from BeautifulSoup for fragments
3. The `_load()` method then adds metadata (including extraction method) to Documents

```python
# In clean_html(), add trafilatura path before the existing BeautifulSoup flow:
if self._content_extraction in ("auto", "trafilatura") and HAS_TRAFILATURA:
    traf_text = trafilatura.extract(html, include_comments=False, include_tables=False)
    traf_meta = trafilatura.bare_extraction(html)
    if traf_text:
        raw_text_len = len(BeautifulSoup(html, 'html.parser').get_text(strip=True))
        ratio = len(traf_text) / max(raw_text_len, 1)
        if ratio >= self._trafilatura_fallback_threshold or self._content_extraction == "trafilatura":
            md_text = traf_text  # Use trafilatura output instead of markdownify
            # Still extract page_title from soup for consistency
            # Store traf_meta for _load() to use
            self._last_trafilatura_meta = traf_meta or {}
            # Continue to extract content fragments from soup for tables/videos
```

### Key Constraints

- `clean_html()` signature must remain backward-compatible (existing callers expect the same return type)
- Store trafilatura metadata temporarily so `_load()` can include it in Document metadata
- The `_load()` method already builds Documents — extend its metadata dict with trafilatura fields
- Use `self.logger` for extraction mode decisions

### References in Codebase

- `packages/ai-parrot-loaders/src/parrot_loaders/web.py:412-462` — `clean_html()` to modify
- `packages/ai-parrot-loaders/src/parrot_loaders/web.py:495-560` — `_load()` to extend with metadata
- `packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py` — TASK-629 implementation for reference pattern

---

## Acceptance Criteria

- [ ] `WebLoader` accepts `content_extraction` parameter (default `"auto"`)
- [ ] `WebLoader` accepts `trafilatura_fallback_threshold` parameter (default 0.1)
- [ ] In `"auto"` mode: tries trafilatura first, falls back to markdownify if sparse
- [ ] `clean_html()` return signature unchanged (backward compatible)
- [ ] Document metadata includes `content_extraction` and trafilatura metadata fields when available
- [ ] Tables/videos/nav extraction unchanged regardless of extraction mode
- [ ] If trafilatura not installed, falls back silently in `"auto"` mode

---

## Test Specification

```python
# tests/loaders/test_webloader_trafilatura.py (created in TASK-632)
# Test cases:

# test_webloader_trafilatura_clean_html
# - Given HTML with noise + main content
# - When clean_html() called with content_extraction="auto"
# - Then md_text contains clean main content

# test_webloader_trafilatura_fallback
# - Given HTML where trafilatura returns sparse output
# - When clean_html() called
# - Then markdownify path used as fallback

# test_webloader_backward_compatible
# - Given existing WebLoader usage without content_extraction param
# - Then behavior identical to before (no breaking change)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/vector-store-handler-scraping.spec.md` for full context
2. **Check dependencies** — verify TASK-628 and TASK-629 are in `tasks/completed/`
3. **Read TASK-629's implementation** to follow the same trafilatura patterns
4. **Verify the Codebase Contract** — read `packages/ai-parrot-loaders/src/parrot_loaders/web.py`
5. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
6. **Implement** following the scope, codebase contract, and notes above
7. **Verify** all acceptance criteria are met
8. **Move this file** to `tasks/completed/TASK-630-trafilatura-extraction-webloader.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
