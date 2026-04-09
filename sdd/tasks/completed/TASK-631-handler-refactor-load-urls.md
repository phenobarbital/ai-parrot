# TASK-631: Refactor VectorStoreHandler._load_urls() to use WebScrapingLoader

**Feature**: vector-store-handler-scraping
**Spec**: `sdd/specs/vector-store-handler-scraping.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-629
**Assigned-to**: unassigned

---

## Context

> This is the handler-side fix for FEAT-091. Currently, `VectorStoreHandler._load_urls()`
> (handler.py:746-797) uses the legacy `WebScrapingTool` directly, imports `ScrapingStep`
> and `Navigate` models, and stores raw `result.content` (complete HTML) into the vector
> store without any content extraction.
>
> This task replaces that entire flow with `WebScrapingLoader`, which now includes
> trafilatura-based content extraction (from TASK-629). The handler becomes a thin
> orchestrator that delegates content loading to the proper loader.
>
> Additionally, the `content_extraction` parameter must be exposed in the REST API body
> per the user's decision on open question #2.
>
> Implements: Spec Module 2.

---

## Scope

- Rewrite `_load_urls()` method (handler.py:746-797) to:
  - Instantiate `WebScrapingLoader` with source URLs
  - Map `crawl_entire_site` → `crawl=True, depth=2`
  - Call `await loader.load()` and return the resulting Documents
  - Remove direct usage of `WebScrapingTool`, `CrawlEngine`, `ScrapingStep`, `Navigate`
- Keep YouTube URL special-casing: YouTube URLs still route to `YoutubeLoader` before non-YouTube URLs go to `WebScrapingLoader`
- Expose `content_extraction` parameter in the REST API:
  - Read from request JSON body in `_put_json_body()` (handler.py:609)
  - Pass it through to `WebScrapingLoader` constructor
  - Default to `"auto"` if not provided
- Remove unused imports: `WebScrapingTool`, `ScrapingStep`, `Navigate` from handler.py

**NOT in scope**:
- Modifying `WebScrapingLoader` internals (that's TASK-629)
- Modifying `WebLoader` (that's TASK-630)
- Writing tests (that's TASK-632)
- Changing any other handler methods (POST, PATCH, GET)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/handlers/stores/handler.py` | MODIFY | Rewrite `_load_urls()`, update `_put_json_body()`, remove legacy imports |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Current imports in handler.py to REMOVE:
from parrot_tools.scraping import WebScrapingTool, CrawlEngine  # handler.py:777
from parrot_tools.scraping.models import ScrapingStep, Navigate  # handler.py:778

# New import to ADD:
from parrot_loaders.webscraping import WebScrapingLoader
# verified: packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py:51

# Keep existing:
from parrot_loaders.youtube import YoutubeLoader  # handler.py:771 (inside _load_urls)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/handlers/stores/handler.py

class VectorStoreHandler(BaseView):  # line 36
    # Method to REWRITE:
    async def _load_urls(
        self,
        store: AbstractStore,
        urls: list[str],
        config: StoreConfig,
        crawl_entire_site: bool = False,
        prompt: Optional[str] = None,
    ) -> list[Document]: ...  # line 746

    # Caller to MODIFY (pass content_extraction):
    async def _put_json_body(self, jm: Optional[JobManager]) -> web.Response: ...  # line 609
    # At line 651-653: reads 'url', 'crawl_entire_site' from body
    # At line 670-676: creates job and calls _load_urls

    # Helper to keep unchanged:
    @staticmethod
    def _is_youtube_url(url: str) -> bool: ...  # line 799
```

```python
# WebScrapingLoader constructor (from TASK-629):
# packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py:51
class WebScrapingLoader(AbstractLoader):
    def __init__(
        self,
        source: Optional[Union[str, List[str]]] = None,
        *,
        crawl: bool = False,
        depth: int = 1,
        content_extraction: Literal["auto", "trafilatura", "markdown", "text"] = "auto",
        # ... other params ...
        **kwargs: Any,
    ) -> None: ...

    async def load(self, source=None, ...) -> List[Document]: ...
    # Inherited from AbstractLoader (abstract.py:560)
```

### Does NOT Exist

- ~~`WebScrapingLoader` import in handler.py~~ — not currently imported; must be added
- ~~`content_extraction` in the handler~~ — not currently read from request body; must be added
- ~~`_load_urls()` using WebScrapingLoader~~ — currently uses `WebScrapingTool` directly (lines 777-795)
- ~~`handler.py` importing `parrot_loaders.webscraping`~~ — this import does not exist yet in the handler

---

## Implementation Notes

### Pattern to Follow

The refactored `_load_urls()` should follow this structure:

```python
async def _load_urls(
    self,
    store: AbstractStore,
    urls: list[str],
    config: StoreConfig,
    crawl_entire_site: bool = False,
    prompt: Optional[str] = None,
    content_extraction: str = "auto",
) -> list[Document]:
    docs: list[Document] = []

    # YouTube URLs handled separately (existing behavior)
    youtube_urls = [u for u in urls if self._is_youtube_url(u)]
    other_urls = [u for u in urls if not self._is_youtube_url(u)]

    if youtube_urls:
        from parrot_loaders.youtube import YoutubeLoader
        for url in youtube_urls:
            loader = YoutubeLoader(source=url)
            docs.extend(await loader.load())

    if other_urls:
        from parrot_loaders.webscraping import WebScrapingLoader
        loader = WebScrapingLoader(
            source=other_urls,
            crawl=crawl_entire_site,
            depth=2 if crawl_entire_site else 1,
            content_extraction=content_extraction,
        )
        docs.extend(await loader.load())

    return docs
```

### Updating _put_json_body

In `_put_json_body()`, read `content_extraction` from the request body and pass it through:

```python
# Around line 653, after reading crawl_entire_site:
content_extraction = body.get("content_extraction", "auto")

# In the _url_bg closure (around line 671):
async def _url_bg():
    docs = await self._load_urls(
        store, urls, config, crawl_entire_site, prompt,
        content_extraction=content_extraction,
    )
    ...
```

### Key Constraints

- `_load_urls()` signature changes (adds `content_extraction` param) — update all callers
- The only caller is `_put_json_body()` at line 671 — update this call site
- Keep the lazy import pattern for `WebScrapingLoader` (import inside method, not at top)
- Remove the now-unused imports of `WebScrapingTool`, `CrawlEngine`, `ScrapingStep`, `Navigate` from lines 777-778

### References in Codebase

- `packages/ai-parrot/src/parrot/handlers/stores/handler.py:746-797` — current `_load_urls()` to rewrite
- `packages/ai-parrot/src/parrot/handlers/stores/handler.py:609-690` — `_put_json_body()` to modify
- `packages/ai-parrot/src/parrot/handlers/scraping/handler.py` — ScrapingHandler as reference for how handlers delegate to toolkit

---

## Acceptance Criteria

- [ ] `_load_urls()` uses `WebScrapingLoader` — no direct `WebScrapingTool` usage
- [ ] `_load_urls()` accepts `content_extraction` parameter (default `"auto"`)
- [ ] `_put_json_body()` reads `content_extraction` from request body and passes it through
- [ ] `crawl_entire_site=True` maps to `crawl=True, depth=2` in WebScrapingLoader
- [ ] YouTube URLs still route to `YoutubeLoader`
- [ ] Legacy imports (`WebScrapingTool`, `ScrapingStep`, `Navigate`) removed from handler
- [ ] No breaking changes to the `PUT /api/v1/ai/stores` API contract (new param is optional)
- [ ] Existing handler methods (POST, PATCH, GET) unchanged

---

## Test Specification

```python
# tests/handlers/test_vectorstore_handler.py (extended in TASK-632)
# Test cases:

# test_load_urls_uses_loader
# - Mock WebScrapingLoader
# - Call _load_urls() with a list of URLs
# - Verify WebScrapingLoader was instantiated (not WebScrapingTool)

# test_load_urls_crawl_mode
# - Call _load_urls(crawl_entire_site=True)
# - Verify WebScrapingLoader called with crawl=True, depth=2

# test_load_urls_youtube_bypass
# - Call _load_urls() with YouTube URLs mixed with regular URLs
# - Verify YouTube URLs went to YoutubeLoader, others to WebScrapingLoader

# test_load_urls_content_extraction_passthrough
# - Call _load_urls(content_extraction="trafilatura")
# - Verify WebScrapingLoader instantiated with content_extraction="trafilatura"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/vector-store-handler-scraping.spec.md` for full context
2. **Check dependencies** — verify TASK-629 is in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Read `packages/ai-parrot/src/parrot/handlers/stores/handler.py` lines 746-797
   - Confirm `from parrot_loaders.webscraping import WebScrapingLoader` works
   - Check that `WebScrapingLoader` now accepts `content_extraction` parameter (from TASK-629)
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-631-handler-refactor-load-urls.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
