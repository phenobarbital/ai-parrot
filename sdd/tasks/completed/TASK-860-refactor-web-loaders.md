# TASK-860: Refactor web and webscraping loaders to use canonical metadata

**Feature**: FEAT-125 — AI-Parrot Loaders Metadata Standardization
**Spec**: `sdd/specs/ai-parrot-loaders-metadata-standarization.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-855
**Assigned-to**: unassigned

---

## Context

`WebLoader` and `WebScrapingLoader` are the most complex refactor targets.
Both extend `AbstractLoader` directly. `WebScrapingLoader` emits many Document
variants per scraped page (fragment, video_link, navigation, table) and
currently stores trafilatura output inside `document_meta` (line 680–759).

After this refactor, trafilatura fields and `content_kind` move to top-level
metadata, and `document_meta` contains only the 5 canonical keys.

This is part of **Module 3** of the spec.

---

## Scope

- **`web.py`** (WebLoader, extends AbstractLoader):
  - Emit sites at lines 456, 466, 674, 696, 705.
  - Replace raw `metadata = {...}` dicts with `self.create_metadata(...)`.
  - Loader-specific keys to preserve at top level: `request_url`, `fetched_at`, `content_kind`.

- **`webscraping.py`** (WebScrapingLoader, extends AbstractLoader):
  - Many emit sites (lines 459, 470, 576, 594, 610, 624, 763, 783, 794, 806, 820, 841, 850, 860).
  - Currently stores trafilatura metadata inside `document_meta` (lines 680, 756–759) — move to top level.
  - `content_kind` values: `"fragment"`, `"video_link"`, `"navigation"`, `"table"`.
  - Loader-specific keys to preserve at top level: `content_kind`, trafilatura fields (`author`, `sitename`, `date`, `categories`, `tags`, `license`, `hostname`, `description`, `image`, etc.), `request_url`, `fetched_at`.

**NOT in scope**: Video/audio loaders (TASK-858/859). File loaders (TASK-857).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-loaders/src/parrot_loaders/web.py` | MODIFY | Replace 5+ raw metadata dicts with create_metadata calls |
| `packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py` | MODIFY | Replace 14+ raw metadata dicts; move trafilatura from document_meta to top level |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.loaders.abstract import AbstractLoader     # abstract.py:36
from parrot.stores.models import Document              # stores/models.py:21
```

### Existing Signatures to Use
```python
# packages/ai-parrot-loaders/src/parrot_loaders/web.py
class WebLoader(AbstractLoader):                                    # line 176
    # Emit sites:
    #   metadata = {...}                                            # line 456
    #   metadata = {k: v for ...}                                   # line 466
    #   metadata = {...}                                            # line 674
    #   metadata={**metadata, "content_kind": ...}                  # line 696
    #   metadata={**metadata, "content_kind": "fragment"}           # line 705
    async def _load(self, address, **kwargs) -> List[Document]:     # line 632

# packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py
class WebScrapingLoader(AbstractLoader):                            # line 58
    # Emit sites (many):
    #   metadata = {...}                                            # line 459
    #   metadata = {k: v for ...}                                   # line 470
    #   metadata={...}                                              # lines 576, 594, 610, 624
    #   metadata={...}                                              # lines 763, 783, 794, 806, 820
    #   metadata={**base_metadata, "content_kind": "video_link"}    # line 841
    #   metadata={**base_metadata, "content_kind": "navigation"}    # line 850
    #   metadata={**base_metadata, "content_kind": "table"}         # line 860
    # Trafilatura integration:
    #   "document_meta": {...trafilatura fields...}                 # line 680
    #   doc_meta = base_metadata.get("document_meta", {})           # line 757
    #   base_metadata["document_meta"] = doc_meta                   # line 759
    async def _load(self, address, **kwargs) -> List[Document]:     # line 955

# After TASK-855, AbstractLoader provides:
# create_metadata(path, doctype, source_type, doc_metadata, *, language=None, title=None, **kwargs)
# self.language: str
```

### Does NOT Exist
- ~~`WebLoader.build_default_meta`~~ — WebLoader extends AbstractLoader directly; no `build_default_meta` helper (that's on basepdf/basevideo only).
- ~~`WebScrapingLoader.create_metadata`~~ — inherits from AbstractLoader; no override.
- ~~`WebScrapingLoader.language`~~ — will exist after TASK-855 via AbstractLoader.

---

## Implementation Notes

### Refactor strategy for webscraping.py
This is the most complex loader:

1. **Base metadata construction** (lines 459–470): Replace the raw dict with `self.create_metadata(url, doctype='web_page', source_type='url', language=detected_lang, title=page_title, request_url=url, fetched_at=timestamp)`.

2. **Content-kind variants** (lines 576–860): Each `Document(page_content=..., metadata={**base_metadata, "content_kind": "..."})` should be changed to `Document(page_content=..., metadata={**base_meta, "content_kind": "..."})` where `base_meta` was produced by `create_metadata`. The `content_kind` is added as a top-level key (it already is — just verify it stays there and doesn't leak into `document_meta`).

3. **Trafilatura enrichment** (lines 680, 756–759): Currently trafilatura fields get stuffed INTO `document_meta`. After the refactor, they become top-level keys. Change:
   ```python
   # BEFORE:
   doc_meta = base_metadata.get("document_meta", {})
   doc_meta.update(trafilatura_fields)
   base_metadata["document_meta"] = doc_meta
   
   # AFTER:
   base_metadata.update(trafilatura_fields)
   # document_meta stays closed-shape (set by create_metadata)
   ```

### Key Constraints
- `webscraping.py` has the most emit sites of any loader. Be methodical — refactor one group at a time.
- Downstream consumers that read trafilatura fields from `document_meta` must now read from top-level. The spec accepts this as a known migration.
- `content_kind` is always a top-level key (already is in current code for some variants).
- Do NOT change `__init__` signatures.

### References in Codebase
- `packages/ai-parrot-loaders/src/parrot_loaders/web.py`
- `packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py`

---

## Acceptance Criteria

- [ ] `web.py` — all 5 emit sites route through `create_metadata`
- [ ] `webscraping.py` — all 14+ emit sites route through `create_metadata`
- [ ] Trafilatura fields moved from `document_meta` to top-level metadata
- [ ] `content_kind` is a top-level key on every webscraping Document variant
- [ ] `document_meta` is closed-shape (5 canonical keys) on every emitted Document
- [ ] No raw `metadata = {...}` dicts remain in either file (except filter comprehensions that process existing metadata)
- [ ] Loader-specific extras preserved at top level
- [ ] Tests pass: `pytest packages/ai-parrot-loaders/tests/ -v -k "web"`
- [ ] No breaking changes to loader public signatures

---

## Test Specification

```python
# packages/ai-parrot-loaders/tests/test_web_loaders_metadata.py
import pytest

CANONICAL_DOC_META_KEYS = {"source_type", "category", "type", "language", "title"}


class TestWebScrapingLoaderMetadata:
    def test_canonical_document_meta(self):
        from parrot_loaders.webscraping import WebScrapingLoader
        loader = WebScrapingLoader()
        meta = loader.create_metadata(
            "https://example.com/page",
            doctype="web_page",
            source_type="url",
            content_kind="fragment",
            author="John",
            sitename="Example"
        )
        assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS
        assert "content_kind" in meta
        assert "author" in meta
        assert "sitename" in meta
        assert "content_kind" not in meta["document_meta"]
        assert "author" not in meta["document_meta"]

    def test_document_meta_closed_shape(self):
        from parrot_loaders.webscraping import WebScrapingLoader
        loader = WebScrapingLoader()
        meta = loader.create_metadata(
            "https://example.com",
            doctype="web_page",
            source_type="url"
        )
        assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS


class TestWebLoaderMetadata:
    def test_canonical_metadata(self):
        from parrot_loaders.web import WebLoader
        loader = WebLoader()
        meta = loader.create_metadata(
            "https://example.com/api",
            doctype="web_content",
            source_type="url",
            request_url="https://example.com/api",
            fetched_at="2026-04-27T10:00:00"
        )
        assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS
        assert "request_url" in meta
        assert "fetched_at" in meta
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-855 is in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm TASK-855 changes are present in `abstract.py`
   - Read both loader files to verify emit-site line numbers
   - Pay special attention to the trafilatura integration in `webscraping.py`
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-860-refactor-web-loaders.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker agent (session feat-125)
**Date**: 2026-04-27
**Notes**: Refactored both web loaders to use canonical metadata.
  - web.py: Replaced raw doc_meta dict + metadata dict construction with
    self.create_metadata(url, doctype="webpage", source_type=source_type, ...).
    Trafilatura fields (author, date, sitename, etc.) now passed as **kwargs
    so they land at top level instead of inside document_meta.
  - webscraping.py: Replaced raw base_metadata dict with self.create_metadata().
    Changed trafilatura enrichment from doc_meta.update(traf_metadata) to
    base_metadata.update(traf_metadata) so fields go to top level.
    All downstream {**base_metadata, "content_kind": ...} patterns preserved.
  - Created test_web_loaders_metadata.py with 8 tests — all pass.

**Deviations from spec**: none
