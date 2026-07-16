---
type: Wiki Overview
title: 'TASK-974: Integrate JSON-LD Registry Dispatch into WebScrapingLoader'
id: doc:sdd-tasks-completed-task-974-webscraping-jsonld-registry-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task wires the extractor functions (from TASK-973) into WebScrapingLoader.
relates_to:
- concept: mod:parrot.loaders.abstract
  rel: mentions
- concept: mod:parrot.stores.models
  rel: mentions
- concept: mod:parrot_loaders.jsonld_extractors
  rel: mentions
---

# TASK-974: Integrate JSON-LD Registry Dispatch into WebScrapingLoader

**Feature**: FEAT-142 — WebScrapingLoader JSON-LD Multi-Type Support
**Spec**: `sdd/specs/webscrapingloader-jsonld-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-973
**Assigned-to**: unassigned

---

## Context

This task wires the extractor functions (from TASK-973) into WebScrapingLoader.
It replaces the single-type `_extract_faqpage_jsonld` + `_docs_from_faqpage`
pipeline with a generic `_extract_jsonld` + `_docs_from_jsonld_items` that
dispatches to registered extractors by `@type`.

It also adds the `jsonld_types` constructor parameter and updates
`_ATOMIC_CONTENT_KINDS` in `abstract.py` so new JSON-LD document types
pass through the splitter without fragmentation.

Implements spec §2 (Architectural Design), §3 Module 2 + Module 3.

---

## Scope

- Add `jsonld_types` parameter to `WebScrapingLoader.__init__()` with
  `Optional[List[str]] = None` (None = all types, [] = disabled)
- Create `_extract_jsonld(self, soup: BeautifulSoup) -> List[JsonLdItem]`:
  - Parse all `<script type="application/ld+json">` blocks
  - Walk JSON-LD graphs (`@graph`, arrays, nested nodes)
  - Dispatch each node to `EXTRACTOR_REGISTRY` by `@type`
  - Filter by `self._jsonld_types` if set
  - De-duplicate items (by content_kind + page_content hash)
- Create `_docs_from_jsonld_items(self, items, base_metadata) -> List[Document]`:
  - Convert `JsonLdItem` → `Document` with proper metadata
  - Assign `row_index` / `row_count` per content_kind group
- Refactor `_result_to_documents()`:
  - Replace `faq_pairs = self._extract_faqpage_jsonld(soup)` → `jsonld_items = self._extract_jsonld(soup)`
  - Replace `self._docs_from_faqpage(faq_pairs, ...)` → `self._docs_from_jsonld_items(jsonld_items, ...)`
- Keep `_strip_html`, `_iter_faqpage_pairs`, `_extract_faqpage_jsonld`,
  `_docs_from_faqpage` as deprecated private methods (or remove if no
  external callers — these are private). The new pipeline must produce
  **identical** Documents for FAQPage inputs.
- Update `_ATOMIC_CONTENT_KINDS` in `abstract.py` line 1312 to include all
  new content kinds:
  ```python
  _ATOMIC_CONTENT_KINDS = frozenset({
      'fragment', 'video_link', 'navigation', 'selector', 'faq', 'table',
      'jsonld-product', 'jsonld-event', 'jsonld-person', 'jsonld-place',
      'jsonld-recipe', 'jsonld-article', 'jsonld-organization',
      'jsonld-howto', 'jsonld-breadcrumb',
  })
  ```

**NOT in scope**:
- Writing extractor functions — those are in TASK-973
- Full integration tests with mocked ScrapingResult — that is TASK-975

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py` | MODIFY | Add `jsonld_types` param, `_extract_jsonld`, `_docs_from_jsonld_items`, refactor `_result_to_documents` |
| `packages/ai-parrot/src/parrot/loaders/abstract.py` | MODIFY | Add new content kinds to `_ATOMIC_CONTENT_KINDS` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Import from TASK-973's new module:
from parrot_loaders.jsonld_extractors import (
    JsonLdItem,
    strip_html_text,
    EXTRACTOR_REGISTRY,
)
# After TASK-973 is complete, this import will resolve.

# Existing imports already in webscraping.py (do not re-add):
from bs4 import BeautifulSoup  # verified: webscraping.py:47
import json  # verified: webscraping.py:42
import re  # verified: webscraping.py:43
from parrot.loaders.abstract import AbstractLoader  # verified: webscraping.py:50
from parrot.stores.models import Document  # verified: webscraping.py:51
```

### Existing Signatures to Use

```python
# packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py

class WebScrapingLoader(AbstractLoader):  # line 61
    def __init__(self, source, *, selectors, tags, steps, plan, objective,
                 crawl, depth, max_pages, follow_selector, follow_pattern,
                 concurrency, driver_type, browser, headless, parse_videos,
                 parse_navs, parse_tables, content_format, content_extraction,
                 trafilatura_fallback_threshold, extract_only, llm_client,
                 plans_dir, save_plan, max_refinement_attempts,
                 **kwargs) -> None:  # line 132

    _FAQPAGE_TYPES = {"FAQPage"}  # line 506
    _QUESTION_TYPES = {"Question"}  # line 507

    @staticmethod
    def _strip_html(text: Any) -> str:  # line 510

    @classmethod
    def _iter_faqpage_pairs(cls, data: Any):  # line 531

    def _extract_faqpage_jsonld(self, soup: BeautifulSoup) -> List[Dict[str, str]]:  # line 586

    def _docs_from_faqpage(self, pairs, base_metadata) -> List[Document]:  # line 629

    def _result_to_documents(self, result, url, crawl_depth=None) -> List[Document]:  # line 811
        # line 847: faq_pairs = self._extract_faqpage_jsonld(soup)
        # line 877: docs.extend(self._docs_from_faqpage(faq_pairs, base_metadata))

# packages/ai-parrot/src/parrot/loaders/abstract.py
# Inside method _chunk_with_text_splitter (NOT a class attribute):
    _ATOMIC_CONTENT_KINDS = frozenset({  # line 1312
        'fragment', 'video_link', 'navigation', 'selector', 'faq', 'table',
    })
```

### Does NOT Exist

- ~~`WebScrapingLoader._extract_jsonld()`~~ — does not exist; this task creates it
- ~~`WebScrapingLoader._docs_from_jsonld_items()`~~ — does not exist; this task creates it
- ~~`WebScrapingLoader._jsonld_types`~~ — does not exist; this task adds it
- ~~`WebScrapingLoader._JSONLD_EXTRACTORS`~~ — does not exist; use `EXTRACTOR_REGISTRY` from `jsonld_extractors.py` instead
- ~~`AbstractLoader._ATOMIC_CONTENT_KINDS` as class attribute~~ — it is a LOCAL variable inside `_chunk_with_text_splitter()`, not a class or module attribute

---

## Implementation Notes

### Pattern to Follow

The new `_extract_jsonld` method follows the same structure as the existing
`_extract_faqpage_jsonld` but generalizes the dispatch:

```python
def _extract_jsonld(self, soup: BeautifulSoup) -> List[JsonLdItem]:
    """Extract structured data from all JSON-LD blocks on the page."""
    items: List[JsonLdItem] = []
    scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
    for s in scripts:
        raw = (s.string or s.text or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            self.logger.debug("Skipping malformed JSON-LD block: %s", exc)
            continue
        self._walk_jsonld_node(data, items)
    return items

def _walk_jsonld_node(self, data: Any, items: List[JsonLdItem]) -> None:
    """Recursively walk a JSON-LD structure, dispatching nodes to extractors."""
    if isinstance(data, list):
        for item in data:
            self._walk_jsonld_node(item, items)
        return
    if not isinstance(data, dict):
        return
    if "@graph" in data:
        self._walk_jsonld_node(data["@graph"], items)
        return
    node_type = data.get("@type")
    type_set = {node_type} if isinstance(node_type, str) else set(node_type or [])
    # Filter by user-requested types
    allowed = self._jsonld_types  # None means all
    for t in type_set:
        if t in EXTRACTOR_REGISTRY:
            if allowed is not None and t not in allowed:
                continue
            items.extend(EXTRACTOR_REGISTRY[t](data))
            break  # one match per node
```

The new `_docs_from_jsonld_items` generalizes `_docs_from_faqpage`:

```python
def _docs_from_jsonld_items(
    self,
    items: List[JsonLdItem],
    base_metadata: Dict[str, Any],
) -> List[Document]:
    """Convert JsonLdItem instances to Documents."""
    # Group by content_kind for row_index/row_count
    from collections import Counter
    kind_counts = Counter(item.content_kind for item in items)
    kind_indices: Dict[str, int] = {}
    docs = []
    for item in items:
        idx = kind_indices.get(item.content_kind, 0)
        kind_indices[item.content_kind] = idx + 1
        docs.append(Document(
            page_content=item.page_content,
            metadata={
                **base_metadata,
                "content_kind": item.content_kind,
                "selector_name": item.selector_name or item.content_kind,
                "source_type": item.source_type,
                "row_index": idx,
                "row_count": kind_counts[item.content_kind],
                "row_data": item.row_data,
            },
        ))
    return docs
```

### Key Constraints

- **Backward compatibility**: For FAQPage inputs, the new pipeline MUST produce
  Documents with identical `metadata` to the old `_docs_from_faqpage` output:
  - `content_kind="faq"` (NOT `"jsonld-faq"`)
  - `source_type="faq-jsonld"`
  - `selector_name="faq"`
  - `page_content="Q: ...\n\nA: ..."`
- **Extraction timing**: `_extract_jsonld` must be called BEFORE `soup(["script", ...]).decompose()`
  at line 849 — exactly where `_extract_faqpage_jsonld` is called now (line 847)
- **`_ATOMIC_CONTENT_KINDS` is local**: Edit the frozenset directly at line 1312
  in `abstract.py` — do NOT try to set it as a class attribute
- **De-duplication**: If the same JSON-LD block appears multiple times (e.g.
  server-side rendering artifacts), items with identical `(content_kind, page_content)`
  should be de-duplicated

### References in Codebase

- `packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py:811-894` — `_result_to_documents` method to modify
- `packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py:586-662` — existing FAQ pipeline to replace
- `packages/ai-parrot/src/parrot/loaders/abstract.py:1312-1319` — `_ATOMIC_CONTENT_KINDS` to extend

---

## Acceptance Criteria

- [ ] `jsonld_types` parameter added to `WebScrapingLoader.__init__()`
- [ ] `_extract_jsonld()` walks JSON-LD blocks and dispatches to `EXTRACTOR_REGISTRY`
- [ ] `_docs_from_jsonld_items()` converts `JsonLdItem` list to `Document` list
- [ ] `_result_to_documents()` uses the new pipeline instead of the old FAQ-only one
- [ ] FAQPage extraction produces identical output to the old pipeline
- [ ] `_ATOMIC_CONTENT_KINDS` includes all new `jsonld-*` content kinds
- [ ] `jsonld_types=["Product"]` filters to only Product extraction
- [ ] `jsonld_types=[]` disables all JSON-LD extraction
- [ ] Malformed JSON-LD blocks are logged and skipped
- [ ] No linting errors: `ruff check packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py`

---

## Test Specification

```python
# Inline tests within this task (add to existing test file or run ad-hoc)
# Full integration tests are in TASK-975

def test_extract_jsonld_dispatches_product():
    """_extract_jsonld finds Product nodes and dispatches to product_extractor."""
    html = '''<script type="application/ld+json">
    {"@type":"Product","name":"Widget","offers":{"@type":"Offer","price":"10"}}
    </script>'''
    soup = BeautifulSoup(html, "html.parser")
    loader = WebScrapingLoader.__new__(WebScrapingLoader)
    loader.logger = logging.getLogger("test")
    loader._jsonld_types = None
    items = loader._extract_jsonld(soup)
    assert any(i.content_kind == "jsonld-product" for i in items)

def test_jsonld_types_filter():
    """jsonld_types restricts which types are extracted."""
    html = '''<script type="application/ld+json">
    {"@graph":[
      {"@type":"Product","name":"W"},
      {"@type":"FAQPage","mainEntity":[{"@type":"Question","name":"Q?",
       "acceptedAnswer":{"@type":"Answer","text":"A"}}]}
    ]}</script>'''
    soup = BeautifulSoup(html, "html.parser")
    loader = WebScrapingLoader.__new__(WebScrapingLoader)
    loader.logger = logging.getLogger("test")
    loader._jsonld_types = ["Product"]
    items = loader._extract_jsonld(soup)
    assert all(i.content_kind == "jsonld-product" for i in items)

def test_faq_backward_compat():
    """FAQPage through new pipeline produces same metadata as old pipeline."""
    # Compare _docs_from_jsonld_items output against _docs_from_faqpage output
    # for the same ATT_FAQ_FIXTURE_HTML
    pass
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/webscrapingloader-jsonld-support.spec.md`
2. **Check dependencies** — TASK-973 must be completed first; verify `jsonld_extractors.py` exists
3. **Verify the Codebase Contract** — confirm line numbers in `webscraping.py` and `abstract.py`
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** the changes to `webscraping.py` and `abstract.py`
6. **Run tests**: `source .venv/bin/activate && pytest packages/ai-parrot-loaders/tests/test_webscraping_loader.py -v`
7. **Run lint**: `source .venv/bin/activate && ruff check packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py`
8. **Move this file** to `tasks/completed/TASK-974-webscraping-jsonld-registry.md`
9. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker agent
**Date**: 2026-05-04
**Notes**: Implemented _extract_jsonld, _walk_jsonld_node, _docs_from_jsonld_items.
Added jsonld_types parameter (None=all, []=disabled, list=filtered).
_result_to_documents now uses the new generic pipeline.
_ATOMIC_CONTENT_KINDS extended with 9 new jsonld-* kinds in abstract.py.
Legacy _extract_faqpage_jsonld and _docs_from_faqpage kept as deprecated private methods.
92 tests pass (2 pre-existing failures unchanged).

**Deviations from spec**: none
