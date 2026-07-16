---
type: Wiki Overview
title: 'Feature Specification: WebScrapingLoader JSON-LD Multi-Type Support'
id: doc:sdd-specs-webscrapingloader-jsonld-support-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: WebScrapingLoader currently extracts JSON-LD structured data only for
relates_to:
- concept: mod:parrot.loaders.abstract
  rel: mentions
- concept: mod:parrot.stores.models
  rel: mentions
- concept: mod:parrot_loaders.jsonld_extractors
  rel: mentions
- concept: mod:parrot_loaders.webscraping
  rel: mentions
- concept: mod:parrot_tools.scraping
  rel: mentions
---

# Feature Specification: WebScrapingLoader JSON-LD Multi-Type Support

**Feature ID**: FEAT-142
**Date**: 2026-05-04
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

WebScrapingLoader currently extracts JSON-LD structured data only for
`schema.org/FAQPage` (the `_extract_faqpage_jsonld` / `_docs_from_faqpage`
pipeline). However, real-world web pages embed a much broader set of JSON-LD
types — Product, Event, Person, Place, Recipe, Article, Organization,
LocalBusiness, BreadcrumbList, HowTo, and more. These structured data blocks
are deterministic, drift-resistant, and far richer than anything recoverable
from the rendered DOM, yet the loader currently ignores all of them.

Extending JSON-LD extraction to cover the most common schema.org types gives
RAG pipelines access to high-quality, pre-structured content that embeds and
retrieves well — exactly the same benefit the FAQPage extractor already
delivers for Q&A pairs.

### Goals

- Extract and emit Documents from the following JSON-LD `@type` families
  (in addition to the existing FAQPage support):
  - **Product** — name, description, price, brand, rating, availability
  - **Event** — name, description, startDate, endDate, location, performer
  - **Person** — name, jobTitle, affiliation, description, url
  - **Place** / **LocalBusiness** — name, address, geo, telephone, openingHours
  - **Recipe** — name, description, ingredients, instructions, cookTime, nutrition
  - **Article** / **NewsArticle** / **BlogPosting** — headline, author, datePublished, articleBody
  - **Organization** — name, description, url, contactPoint, address
  - **HowTo** — name, description, steps, totalTime
  - **BreadcrumbList** — ordered navigation path items
- Each JSON-LD type produces Documents with a type-specific `content_kind`
  (e.g. `"jsonld-product"`, `"jsonld-event"`) so downstream consumers can
  filter or handle them distinctly.
- Maintain backward compatibility: existing FAQPage extraction must continue
  to work identically (same `content_kind="faq"`, same `source_type="faq-jsonld"`).
- The extraction must be extensible: adding a new JSON-LD type handler should
  require only registering a new extractor class/function, not modifying the
  core dispatch logic.

### Non-Goals (explicitly out of scope)

- Modifying the scraping toolkit (`parrot_tools.scraping`) — JSON-LD extraction
  is purely a loader-side concern operating on the HTML already fetched.
- Supporting JSON-LD types that don't have a natural text representation for
  embedding (e.g. `ImageObject`, `VideoObject`, `WebSite`, `SearchAction`).
- Extracting Microdata or RDFa — only `<script type="application/ld+json">` blocks.
- Replacing the existing FAQPage extractor — it is preserved as-is for backward
  compatibility and only refactored internally to use the new registry.

---

## 2. Architectural Design

### Overview

Introduce a **JSON-LD extractor registry** pattern inside `WebScrapingLoader`.
Each supported `@type` has a corresponding extractor that:

1. Receives a parsed JSON-LD node (a `dict`).
2. Returns a list of `JsonLdItem` (a simple dataclass/Pydantic model) with
   `content_kind`, `page_content` (pre-formatted text), and `row_data` (the
   raw structured fields).

The main extraction method (`_extract_jsonld`) replaces the current
`_extract_faqpage_jsonld` as the entry point. It parses all
`<script type="application/ld+json">` blocks, walks the JSON-LD graph, and
dispatches each node to the appropriate registered extractor based on `@type`.

The existing FAQPage logic becomes one extractor registered under `"FAQPage"`.

```
<script type="application/ld+json"> blocks
         │
         ▼
  _extract_jsonld()
    │  parses JSON, walks @graph / arrays
    │
    ▼
  _JSONLD_EXTRACTORS registry  ──▶  { "FAQPage": faq_extractor,
    │                                  "Product": product_extractor,
    │                                  "Event": event_extractor,
    │                                  "Person": person_extractor,
    │                                  ... }
    ▼
  List[JsonLdItem]
    │
    ▼
  _docs_from_jsonld_items()  ──▶  List[Document]
```

### Component Diagram

```
WebScrapingLoader
  ├── _extract_jsonld(soup) → List[JsonLdItem]
  │     ├── parses <script type="application/ld+json"> blocks
  │     ├── walks @graph, arrays, nested nodes
  │     └── dispatches to registered extractors by @type
  │
  ├── _docs_from_jsonld_items(items, base_metadata) → List[Document]
  │     └── converts JsonLdItem → Document with proper metadata
  │
  ├── _JSONLD_EXTRACTORS: Dict[str, Callable]  (class-level registry)
  │
  └── extractors module (parrot_loaders/jsonld_extractors.py)
        ├── JsonLdItem (dataclass)
        ├── faq_extractor(node) → List[JsonLdItem]
        ├── product_extractor(node) → List[JsonLdItem]
        ├── event_extractor(node) → List[JsonLdItem]
        ├── person_extractor(node) → List[JsonLdItem]
        ├── place_extractor(node) → List[JsonLdItem]
        ├── recipe_extractor(node) → List[JsonLdItem]
        ├── article_extractor(node) → List[JsonLdItem]
        ├── organization_extractor(node) → List[JsonLdItem]
        ├── howto_extractor(node) → List[JsonLdItem]
        └── breadcrumb_extractor(node) → List[JsonLdItem]
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `WebScrapingLoader._result_to_documents()` | modifies | Replace `_extract_faqpage_jsonld` call with `_extract_jsonld`; replace `_docs_from_faqpage` with `_docs_from_jsonld_items` |
| `AbstractLoader._chunk_with_text_splitter()` | extends | New `content_kind` values must be added to `_ATOMIC_CONTENT_KINDS` if they should pass through without splitting |
| `WebScrapingLoader._strip_html()` | reuses | Existing HTML-to-text utility, shared across extractors |
| `Document` model | uses | No changes needed — uses existing `page_content` + `metadata` |

### Data Models

```python
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

@dataclass
class JsonLdItem:
    """A single extracted item from a JSON-LD block."""
    content_kind: str          # e.g. "faq", "jsonld-product", "jsonld-event"
    source_type: str           # e.g. "faq-jsonld", "product-jsonld"
    page_content: str          # pre-formatted text for embedding
    row_data: Dict[str, Any]   # raw structured fields
    selector_name: Optional[str] = None  # grouping key (e.g. "faq", "product")
```

### New Public Interfaces

No new public interfaces — the extraction is internal to WebScrapingLoader.
The only user-visible change is that `load()` may now emit additional Documents
with new `content_kind` values from pages containing non-FAQ JSON-LD data.

A new optional constructor parameter controls which JSON-LD types to extract:

```python
class WebScrapingLoader(AbstractLoader):
    def __init__(
        self,
        ...,
        jsonld_types: Optional[List[str]] = None,
        # None = extract all supported types (default)
        # ["FAQPage", "Product"] = extract only these types
        # [] = disable JSON-LD extraction entirely
        ...
    ) -> None: ...
```

---

## 3. Module Breakdown

### Module 1: JSON-LD Extractors

- **Path**: `packages/ai-parrot-loaders/src/parrot_loaders/jsonld_extractors.py`
- **Responsibility**: Define `JsonLdItem` dataclass and individual extractor
  functions for each supported JSON-LD type. Each extractor receives a parsed
  JSON-LD node dict and returns `List[JsonLdItem]`.
- **Depends on**: None (pure data transformation, uses only stdlib + `_strip_html`)

### Module 2: JSON-LD Registry and Dispatch

- **Path**: `packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py` (modifications)
- **Responsibility**: Replace the single-type `_extract_faqpage_jsonld` with a
  generic `_extract_jsonld` that walks JSON-LD graphs and dispatches to
  registered extractors. Refactor `_docs_from_faqpage` into the generic
  `_docs_from_jsonld_items`. Add `jsonld_types` constructor parameter.
- **Depends on**: Module 1

### Module 3: Atomic Content Kinds Update

- **Path**: `packages/ai-parrot/src/parrot/loaders/abstract.py` (minor modification)
- **Responsibility**: Add new JSON-LD content kinds to `_ATOMIC_CONTENT_KINDS`
  so structured JSON-LD items pass through the splitter without fragmentation.
- **Depends on**: Module 2 (needs to know the content_kind values)

### Module 4: Tests

- **Path**: `packages/ai-parrot-loaders/tests/test_jsonld_extractors.py`
- **Path**: `packages/ai-parrot-loaders/tests/test_webscraping_loader.py` (additions)
- **Responsibility**: Unit tests for each extractor function, integration tests
  for the full JSON-LD pipeline within WebScrapingLoader. Regression tests to
  ensure FAQPage extraction is unchanged.
- **Depends on**: Module 1, Module 2

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_product_extractor_basic` | Module 1 | Extracts name, price, description from Product node |
| `test_product_extractor_with_offers` | Module 1 | Handles `offers` array with multiple prices |
| `test_event_extractor_basic` | Module 1 | Extracts name, date, location from Event node |
| `test_person_extractor_basic` | Module 1 | Extracts name, jobTitle, affiliation from Person node |
| `test_place_extractor_basic` | Module 1 | Extracts name, address, geo from Place node |
| `test_recipe_extractor_basic` | Module 1 | Extracts name, ingredients, instructions from Recipe node |
| `test_article_extractor_basic` | Module 1 | Extracts headline, author, body from Article node |
| `test_organization_extractor_basic` | Module 1 | Extracts name, description, url from Organization node |
| `test_howto_extractor_basic` | Module 1 | Extracts name, steps from HowTo node |
| `test_breadcrumb_extractor_basic` | Module 1 | Extracts ordered path from BreadcrumbList node |
| `test_extractor_handles_missing_fields` | Module 1 | Gracefully handles incomplete JSON-LD nodes |
| `test_extractor_strips_html_in_values` | Module 1 | HTML entities/tags in field values are cleaned |
| `test_extract_jsonld_dispatches_multiple_types` | Module 2 | Page with Product + FAQPage yields both |
| `test_extract_jsonld_with_graph_wrapper` | Module 2 | `@graph` array dispatches correctly |
| `test_extract_jsonld_deduplicates` | Module 2 | Same node in multiple blocks is not duplicated |
| `test_jsonld_types_filter` | Module 2 | `jsonld_types=["Product"]` excludes FAQPage |
| `test_jsonld_types_empty_disables` | Module 2 | `jsonld_types=[]` disables all extraction |
| `test_faqpage_backward_compat` | Module 2 | FAQPage output is byte-identical to current behavior |
| `test_new_content_kinds_are_atomic` | Module 3 | New kinds pass through splitter without fragmentation |

### Integration Tests

| Test | Description |
|---|---|
| `test_full_pipeline_product_page` | WebScrapingLoader with Product JSON-LD produces correct Documents |
| `test_full_pipeline_mixed_jsonld` | Page with FAQ + Product + Event produces all document types |
| `test_crawl_with_jsonld_extraction` | Crawled pages with JSON-LD yield documents at all depths |

### Test Data / Fixtures

```python
PRODUCT_JSONLD_HTML = '''
<html><head><title>Widget Pro</title></head><body>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "Widget Pro",
  "description": "A professional-grade widget for all your needs.",
  "brand": {"@type": "Brand", "name": "WidgetCo"},
  "offers": {
    "@type": "Offer",
    "price": "29.99",
    "priceCurrency": "USD",
    "availability": "https://schema.org/InStock"
  },
  "aggregateRating": {
    "@type": "AggregateRating",
    "ratingValue": "4.5",
    "reviewCount": "120"
  }
}
</script>
<p>Product page content.</p>
</body></html>
'''

EVENT_JSONLD_HTML = '''
<html><head><title>Tech Conference 2026</title></head><body>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Event",
  "name": "Tech Conference 2026",
  "description": "Annual technology conference.",
  "startDate": "2026-09-15T09:00:00-05:00",
  "endDate": "2026-09-17T17:00:00-05:00",
  "location": {
    "@type": "Place",
    "name": "Convention Center",
    "address": "123 Main St, Austin, TX"
  },
  "performer": {"@type": "Person", "name": "Jane Smith"}
}
</script>
</body></html>
'''

MIXED_JSONLD_HTML = '''
<html><head><title>Shop Page</title></head><body>
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
  {"@type":"FAQPage","mainEntity":[
    {"@type":"Question","name":"Is it good?","acceptedAnswer":{"@type":"Answer","text":"Yes"}}
  ]},
  {"@type":"Product","name":"Widget","offers":{"@type":"Offer","price":"10.00","priceCurrency":"USD"}}
]}
</script>
</body></html>
'''
```

---

## 5. Acceptance Criteria

- [x] Existing FAQPage extraction produces byte-identical output (no regression)
- [ ] Product JSON-LD is extracted with `content_kind="jsonld-product"`
- [ ] Event JSON-LD is extracted with `content_kind="jsonld-event"`
- [ ] Person JSON-LD is extracted with `content_kind="jsonld-person"`
- [ ] Place/LocalBusiness JSON-LD is extracted with `content_kind="jsonld-place"`
- [ ] Recipe JSON-LD is extracted with `content_kind="jsonld-recipe"`
- [ ] Article/NewsArticle/BlogPosting is extracted with `content_kind="jsonld-article"`
- [ ] Organization JSON-LD is extracted with `content_kind="jsonld-organization"`
- [ ] HowTo JSON-LD is extracted with `content_kind="jsonld-howto"`
- [ ] BreadcrumbList JSON-LD is extracted with `content_kind="jsonld-breadcrumb"`
- [ ] `jsonld_types` constructor parameter filters extraction to specified types
- [ ] All new content kinds are in `_ATOMIC_CONTENT_KINDS` (pass through splitter)
- [ ] Each Document has `row_data` metadata with the raw structured fields
- [ ] HTML entities/tags in JSON-LD values are cleaned (via `_strip_html`)
- [ ] Malformed JSON-LD blocks are logged and skipped (no crash)
- [ ] `@graph` wrapper and nested arrays are handled correctly
- [ ] All unit tests pass: `pytest packages/ai-parrot-loaders/tests/test_jsonld_extractors.py -v`
- [ ] All integration tests pass: `pytest packages/ai-parrot-loaders/tests/test_webscraping_loader.py -v`
- [ ] No breaking changes to existing public API

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
from parrot.loaders.abstract import AbstractLoader  # verified: packages/ai-parrot/src/parrot/loaders/abstract.py:37
from parrot.stores.models import Document  # verified: packages/ai-parrot/src/parrot/stores/models.py:40
from parrot_loaders.webscraping import WebScrapingLoader  # verified: packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py:61
```

### Existing Class Signatures

```python
# packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py
class WebScrapingLoader(AbstractLoader):  # line 61
    _FAQPAGE_TYPES = {"FAQPage"}  # line 506
    _QUESTION_TYPES = {"Question"}  # line 507

    @staticmethod
    def _strip_html(text: Any) -> str:  # line 510
        """Render an acceptedAnswer.text payload as clean plain text."""

    @classmethod
    def _iter_faqpage_pairs(cls, data: Any):  # line 531
        """Yield (question, answer) tuples from a parsed JSON-LD object."""

    def _extract_faqpage_jsonld(self, soup: BeautifulSoup) -> List[Dict[str, str]]:  # line 586
        """Return a list of {question, answer} pairs found in JSON-LD."""

    def _docs_from_faqpage(
        self,
        pairs: List[Dict[str, str]],
        base_metadata: Dict[str, Any],
    ) -> List[Document]:  # line 629

    def _result_to_documents(
        self,
        result: Any,
        url: str,
        crawl_depth: Optional[int] = None,
    ) -> List[Document]:  # line 811
        # Calls _extract_faqpage_jsonld at line 847
        # Calls _docs_from_faqpage at line 877

# packages/ai-parrot/src/parrot/loaders/abstract.py
class AbstractLoader(ABC):  # line 37
    def create_metadata(
        self,
        path: Union[str, PurePath],
        doctype: str = 'document',
        source_type: str = 'source',
        doc_metadata: Optional[dict] = None,
        *,
        language: Optional[str] = None,
        title: Optional[str] = None,
        **kwargs
    ) -> dict:  # line 871

    # _ATOMIC_CONTENT_KINDS at line 1312 (inside _chunk_with_text_splitter):
    # frozenset({'fragment', 'video_link', 'navigation', 'selector', 'faq', 'table'})

# packages/ai-parrot/src/parrot/stores/models.py
class Document(BaseModel):  # line 40
    page_content: str  # line 45
    metadata: Dict[str, Any] = Field(default_factory=dict)  # line 46
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_extract_jsonld()` | `_result_to_documents()` | replaces `_extract_faqpage_jsonld()` call | `webscraping.py:847` |
| `_docs_from_jsonld_items()` | `_result_to_documents()` | replaces `_docs_from_faqpage()` call | `webscraping.py:877` |
| New content kinds | `_ATOMIC_CONTENT_KINDS` | added to frozenset | `abstract.py:1312` |
| `JsonLdItem` | `_docs_from_jsonld_items()` | data model | new module |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot_loaders.jsonld_extractors`~~ — does not exist yet; must be created
- ~~`WebScrapingLoader._extract_jsonld()`~~ — does not exist; must be created
- ~~`WebScrapingLoader._docs_from_jsonld_items()`~~ — does not exist; must be created
- ~~`WebScrapingLoader._JSONLD_EXTRACTORS`~~ — does not exist; must be created
- ~~`WebScrapingLoader.jsonld_types`~~ — no such parameter exists yet
- ~~`JsonLdItem`~~ — does not exist; must be created
- ~~`parrot.loaders.abstract._ATOMIC_CONTENT_KINDS` as module-level~~ — it is a local variable inside `_chunk_with_text_splitter()`, not a class or module attribute

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Extractor registration pattern**: Use a class-level dict mapping `@type`
  strings to extractor callables. This mirrors how the existing code uses
  `_FAQPAGE_TYPES` / `_QUESTION_TYPES` class variables, but generalized.
- **`_strip_html` reuse**: All extractors must use the existing static method
  for cleaning HTML entities and tags from JSON-LD values. Move it to the
  new `jsonld_extractors.py` module (or import from WebScrapingLoader).
- **Document emission pattern**: Follow the existing `_docs_from_faqpage`
  pattern — each item becomes one Document with `page_content` as formatted
  text and `row_data` in metadata containing the raw structured fields.
- **`content_kind` naming**: Use `"jsonld-{type}"` lowercase for new types
  (e.g. `"jsonld-product"`). Keep `"faq"` unchanged for backward compatibility.
- **Extraction order**: JSON-LD extraction must happen BEFORE the
  `decompose("script")` call in `_result_to_documents` — this is already the
  pattern for FAQPage and must be preserved.

### Known Risks / Gotchas

- **`_ATOMIC_CONTENT_KINDS` is a local variable**: It's defined inside
  `_chunk_with_text_splitter()` at line 1312, not a class attribute. Adding
  new kinds requires editing that local frozenset directly.
- **JSON-LD nesting**: Real-world JSON-LD can be deeply nested (`@graph` with
  mixed types, `mainEntity` arrays, `itemListElement` inside BreadcrumbList).
  The walker must handle arbitrary depth without stack overflow.
- **Multi-type nodes**: A single JSON-LD node can have `@type: ["Product", "IndividualProduct"]`.
  The dispatcher must match any type in the list.
- **Backward compatibility**: The existing `_extract_faqpage_jsonld` returns
  `List[Dict[str, str]]` while the new system returns `List[JsonLdItem]`.
  Ensure the FAQPage extractor's output, when converted to Documents, produces
  metadata identical to the current `_docs_from_faqpage` output.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `beautifulsoup4` | `>=4.12` | Already a dependency — parses HTML to find `<script>` tags |

No new external dependencies required.

---

## 8. Open Questions

- [x] Should JSON-LD items from types like Product/Event be treated as atomic
  (no splitting), or should long `description` / `articleBody` fields be
  chunked? Current design treats them as atomic (in `_ATOMIC_CONTENT_KINDS`).
  — *Owner: Jesus*: Yes, all items be treated as atomic (no splitting).
- [x] Should `BreadcrumbList` produce one Document per breadcrumb item or one
  Document for the entire path? — *Owner: Jesus*: one document for the entire path, atomic.
- [x] Should the `page_content` format for each type be configurable (e.g.
  markdown vs. key-value), or is a single opinionated format per type
  sufficient? — *Owner: Jesus*: be configurable

---

## Worktree Strategy

- **Isolation unit**: `per-spec` (sequential tasks).
- All tasks modify the same two files (`webscraping.py` and `jsonld_extractors.py`)
  plus tests, so parallel execution would cause merge conflicts.
- **Cross-feature dependencies**: None — this spec only modifies the loader layer.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-04 | Jesus Lara | Initial draft |
