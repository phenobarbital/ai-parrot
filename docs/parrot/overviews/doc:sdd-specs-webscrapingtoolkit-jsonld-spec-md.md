---
type: Wiki Overview
title: 'Feature Specification: WebScrapingToolkit `extract_jsonld` Browser Action'
id: doc:sdd-specs-webscrapingtoolkit-jsonld-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The `WebScrapingTool` browser-action system (used by LLM-directed scraping
relates_to:
- concept: mod:parrot.utils
  rel: mentions
- concept: mod:parrot.utils.jsonld_extractors
  rel: mentions
- concept: mod:parrot.utils.parsers
  rel: mentions
- concept: mod:parrot_loaders.jsonld_extractors
  rel: mentions
- concept: mod:parrot_loaders.webscraping
  rel: mentions
- concept: mod:parrot_tools.scraping.executor
  rel: mentions
- concept: mod:parrot_tools.scraping.models
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: WebScrapingToolkit `extract_jsonld` Browser Action

**Feature ID**: FEAT-154
**Date**: 2026-05-08
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

The `WebScrapingTool` browser-action system (used by LLM-directed scraping
plans) currently offers a single content-extraction primitive: `Extract`,
which targets DOM nodes via CSS selectors or XPath. CSS/XPath selectors are
fragile — they break when sites restructure their markup and require a human
to author and maintain a per-site selector strategy.

Many real-world pages embed structured data directly in
`<script type="application/ld+json">` blocks following the schema.org
conventions (Person, Event, Place, Product, Recipe, FAQPage, Article,
Organization, HowTo, BreadcrumbList, LocalBusiness, …). This data is
deterministic, drift-resistant, and far richer than anything recoverable from
the rendered DOM. The companion `WebScrapingLoader` already exploits it
(FEAT-142) via a fully-featured extractor registry living in
`parrot_loaders.jsonld_extractors` — but the toolkit (which drives the
*active scraping* path that LLMs use to script browsers) cannot reach that
logic and so falls back to brittle selector-based extraction even when a page
exposes clean JSON-LD.

### Goals

- Add a new `extract_jsonld` BrowserAction (Pydantic model `ExtractJsonLd`)
  to `parrot_tools.scraping.models` that, when executed, parses every
  `<script type="application/ld+json">` block in the current DOM, dispatches
  each typed node through the existing extractor registry, and writes the
  flattened results into the step-extracted dict so they can be consumed by
  downstream plan steps and toolkit callers.
- Reuse the existing `EXTRACTOR_REGISTRY` (FAQPage, Question, Product,
  IndividualProduct, Event, Person, Place, LocalBusiness, Restaurant,
  Recipe, Article, NewsArticle, BlogPosting, Organization, HowTo,
  BreadcrumbList) without duplication. To enable cross-package reuse from
  `ai-parrot-tools` (which does not depend on `ai-parrot-loaders`), the
  module is **promoted into the core `ai-parrot` package** at
  `parrot.utils.jsonld_extractors`. The loader-side import path is preserved
  via a thin backward-compat re-export shim in
  `parrot_loaders.jsonld_extractors`.
- Allow plan authors / LLMs to **filter by `@type`** via an optional
  `types: list[str] | None` field on the action. `None` (the default)
  extracts every registered type; `["Product", "Recipe"]` keeps only those.
- Land results in `step_extracted[extract_name]` as a **flat list of
  JSON-serializable dicts** (one per `JsonLdItem`) so they round-trip cleanly
  through the plan-result serializer and integrate naturally with the
  existing `Extract(multiple=True)` output shape.
- Wire the action into the executor dispatcher (`_dispatch_step`), the
  `ACTION_MAP` lookup table, and the `ActionList` discriminated union so the
  Pydantic plan parser, LLM-facing JSON schema, and runtime dispatch all see
  it without further changes.

### Non-Goals (explicitly out of scope)

- Modifying or extending `EXTRACTOR_REGISTRY` itself (e.g. adding new
  schema.org types). New types are added separately to the shared module
  and instantly become available to both loader and toolkit.
- Replacing or deprecating the existing `Extract` action — CSS/XPath
  extraction remains the right answer for any data that isn't exposed via
  JSON-LD.
- Supporting non-JSON-LD structured-data formats (Microdata, RDFa) — only
  `<script type="application/ld+json">` blocks are in scope.
- Changing the runtime behavior of `WebScrapingLoader._extract_jsonld`. The
  loader continues to emit `Document` objects exactly as today; only the
  import path of its dependency moves.

---

## 2. Architectural Design

### Overview

The change has three layers:

1. **Shared module promotion.** Move
   `packages/ai-parrot-loaders/src/parrot_loaders/jsonld_extractors.py` to
   `packages/ai-parrot/src/parrot/utils/jsonld_extractors.py` (verbatim, no
   API changes). Replace the original file with a 5-line re-export shim
   that imports the public symbols (`JsonLdItem`, `EXTRACTOR_REGISTRY`,
   `strip_html_text`, every `*_extractor` function) from the new location
   and re-exports them via `__all__`. This makes
   `from parrot_loaders.jsonld_extractors import …` continue to work for
   any external user while letting `ai-parrot-tools` (which depends on
   `ai-parrot` core but not on `ai-parrot-loaders`) reach the same symbols.
2. **New `ExtractJsonLd` action model.** Add a Pydantic class to
   `parrot_tools.scraping.models` mirroring the field conventions of the
   existing `Extract` action (`name`, `action`, `description`, `extract_name`)
   plus a single new field — `types: Optional[List[str]] = None`. Register
   it in the `ACTION_MAP` dict and the `ActionList` discriminated union under
   the discriminator string `"extract_jsonld"`.
3. **New executor handler.** Add `_action_extract_jsonld` to
   `parrot_tools.scraping.executor`. It captures the current DOM via
   `driver.get_page_source()`, parses it with BeautifulSoup, walks every
   JSON-LD `<script>` block exactly like `WebScrapingLoader._extract_jsonld`
   does (same recursion into `@graph` and arrays, same de-duplication by
   `(content_kind, page_content)`), respects the optional `types` filter,
   and writes a flat list of `dict(content_kind=..., source_type=...,
   page_content=..., row_data={...}, selector_name=...)` records into
   `step_extracted[key]`. Dispatch is added to `_dispatch_step` between
   the existing `extract` and `get_text` branches.

The toolkit's executor and the loader thereafter share a single registry —
new schema.org types added to the shared module become instantly available
to both.

### Component Diagram

```
                ┌────────────────────────────────────────────────────────┐
                │  parrot.utils.jsonld_extractors  (promoted to core)    │
                │  - JsonLdItem                                          │
                │  - EXTRACTOR_REGISTRY                                  │
                │  - faq/product/event/person/place/recipe/article/…    │
                └────────────────┬───────────────────────────────┬───────┘
                                 │                               │
                       imports   │                               │  imports
                                 ▼                               ▼
   ┌──────────────────────────────────────┐       ┌─────────────────────────────────────┐
   │ parrot_loaders.webscraping           │       │ parrot_tools.scraping.executor      │
   │   WebScrapingLoader._extract_jsonld  │       │   _action_extract_jsonld (new)      │
   │   (unchanged behavior)               │       │                                     │
   └──────────────────────────────────────┘       └────────────┬────────────────────────┘
                                                               │
                                                               ▼
                                                 ┌─────────────────────────────────────┐
                                                 │ parrot_tools.scraping.models        │
                                                 │   ExtractJsonLd  (new)              │
                                                 │   ACTION_MAP["extract_jsonld"]      │
                                                 │   ActionList (discriminated union)  │
                                                 └─────────────────────────────────────┘

  Backward-compat shim:
   parrot_loaders.jsonld_extractors → re-exports from parrot.utils.jsonld_extractors
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot_loaders.jsonld_extractors` (module) | move + shim | File becomes a re-export shim; canonical home is `parrot.utils.jsonld_extractors`. |
| `parrot_loaders.webscraping.WebScrapingLoader` | re-import | Update line 52 import to `from parrot.utils.jsonld_extractors import EXTRACTOR_REGISTRY, JsonLdItem`. Behavior unchanged. |
| `parrot_tools.scraping.models.BrowserAction` | extends | New `ExtractJsonLd(BrowserAction)` subclass. |
| `parrot_tools.scraping.models.ACTION_MAP` | adds entry | `"extract_jsonld": ExtractJsonLd`. |
| `parrot_tools.scraping.models.ActionList` | adds member | Discriminated union learns the new action. |
| `parrot_tools.scraping.executor._dispatch_step` | adds branch | New `elif action_type == "extract_jsonld":` clause routes to `_action_extract_jsonld`. |
| `parrot_tools.scraping.executor` step_extracted dict | writes | Same key-collision semantics as `_action_extract`. |

### Data Models

```python
# parrot_tools/scraping/models.py — new action

class ExtractJsonLd(BrowserAction):
    """Extract structured data from JSON-LD blocks on the current page.

    Iterates every ``<script type="application/ld+json">`` block, walks
    the JSON graph (descending into ``@graph`` and arrays), and dispatches
    typed nodes through the shared ``EXTRACTOR_REGISTRY`` from
    ``parrot.utils.jsonld_extractors``. Result is a flat list of dicts,
    one per extracted ``JsonLdItem``, written to
    ``step_extracted[extract_name]``.

    Two filtering modes:
    - ``types=None`` (default): extract every registered ``@type``.
    - ``types=["Product", "Recipe"]``: only those types.
    """
    name: str = "extract_jsonld"
    action: Literal["extract_jsonld"] = "extract_jsonld"
    description: str = Field(
        default="Extract JSON-LD structured data",
        description="Extract structured data from <script type='application/ld+json'> blocks",
    )
    extract_name: str = Field(
        default="jsonld",
        description=(
            "Key under which the result list is stored in extracted_data. "
            "Falls back to the step's `name` field, then 'jsonld'."
        ),
    )
    types: Optional[List[str]] = Field(
        default=None,
        description=(
            "Optional whitelist of schema.org @type values to extract "
            "(e.g. ['Product', 'Recipe']). None = every type registered "
            "in EXTRACTOR_REGISTRY."
        ),
    )
```

Output record shape (one dict per item, returned as a list):

```python
{
    "content_kind": "jsonld-product",  # str — semantic label from JsonLdItem
    "source_type": "product-jsonld",   # str — provenance label
    "page_content": "Name: Acme Widget\nPrice: $19.99\n...",  # str — embedding-ready text
    "row_data": {"name": "...", "price": "...", ...},          # dict — raw structured fields
    "selector_name": "jsonld-product"                          # str — falls back to content_kind
}
```

### New Public Interfaces

```python
# parrot/utils/jsonld_extractors.py  (promoted from parrot_loaders)
# Public API — unchanged from the original module:
from parrot.utils.jsonld_extractors import (
    JsonLdItem,
    EXTRACTOR_REGISTRY,
    strip_html_text,
    faq_extractor, product_extractor, event_extractor, person_extractor,
    place_extractor, recipe_extractor, article_extractor,
    organization_extractor, howto_extractor, breadcrumb_extractor,
    question_extractor,
)

# parrot_tools/scraping/models.py
from parrot_tools.scraping.models import ExtractJsonLd  # new

# parrot_loaders/jsonld_extractors.py  (backward-compat shim)
# Continues to expose every symbol above for any external importer.
```

---

## 3. Module Breakdown

### Module 1: Shared `jsonld_extractors` module promotion
- **Path**: `packages/ai-parrot/src/parrot/utils/jsonld_extractors.py` (new
  canonical location); `packages/ai-parrot-loaders/src/parrot_loaders/jsonld_extractors.py`
  (becomes a 5-line re-export shim).
- **Responsibility**: Host the `JsonLdItem` dataclass, `strip_html_text`,
  every `*_extractor` function, and the `EXTRACTOR_REGISTRY` dict. The shim
  preserves backward compatibility for any external user importing from the
  loader package.
- **Depends on**: `bs4` (already a transitive core dep); `dataclasses`,
  `html`, `re` (stdlib).

### Module 2: `WebScrapingLoader` import update
- **Path**: `packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py`.
- **Responsibility**: Replace the import on line 52 with the new core path:
  `from parrot.utils.jsonld_extractors import EXTRACTOR_REGISTRY, JsonLdItem`.
  No behavior change. All existing FEAT-142 tests (`tests/test_webscraping_loader.py`
  and `tests/test_jsonld_extractors.py` in the loaders package) must continue
  to pass unchanged.
- **Depends on**: Module 1.

### Module 3: `ExtractJsonLd` action model
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/scraping/models.py`.
- **Responsibility**: Add the `ExtractJsonLd(BrowserAction)` Pydantic class
  (between `Extract` and `Submit` to keep related actions together). Add
  `"extract_jsonld": ExtractJsonLd` to `ACTION_MAP`. Add `ExtractJsonLd` to
  the `ActionList` discriminated union so the Pydantic plan parser accepts
  `{"action": "extract_jsonld", ...}` payloads from LLMs and JSON plans.
- **Depends on**: nothing new at runtime — only stdlib and Pydantic.

### Module 4: `_action_extract_jsonld` executor handler
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py`.
- **Responsibility**:
  - New private async function `_action_extract_jsonld(driver, action,
    step, step_extracted)` modeled after `_action_extract`.
  - Captures `await driver.get_page_source()`, parses with
    `BeautifulSoup(html, "html.parser")`.
  - Walks JSON-LD blocks and dispatches via `EXTRACTOR_REGISTRY` (imported
    from `parrot.utils.jsonld_extractors`). Reuse the same recursion shape
    as `WebScrapingLoader._walk_jsonld_node` (handle `@graph`, arrays,
    typed objects, single-extractor-per-node tie-break).
  - Honors `action.types` as the type filter (None means "all").
  - De-duplicates by `(content_kind, page_content)` (parity with the loader).
  - Resolves the storage key the same way `_action_extract` does:
    `extract_name` → `name` → step description → `"jsonld"`.
  - Writes the flat list of dicts into `step_extracted[key]`. On key
    collision with an existing list, append non-duplicate items
    (parity with `_action_extract`'s merge semantics).
  - Add the dispatch branch in `_dispatch_step` between the existing
    `"extract"` and `"get_text"` branches.
- **Depends on**: Modules 1 and 3.

### Module 5: Tests
- **Path**: `packages/ai-parrot-tools/tests/scraping/test_executor.py`
  (extend), plus a new `test_jsonld_action.py` for focused coverage.
- **Responsibility**: Verify model schema, dispatch wiring, single-page
  extraction across multiple `@type` values, the `types` filter, key
  collision merge, and empty-page behavior. See §4 for the detailed list.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_extract_jsonld_model_defaults` | Module 3 | `ExtractJsonLd().action == "extract_jsonld"`, `name == "extract_jsonld"`, `types is None`, `extract_name == "jsonld"`. |
| `test_extract_jsonld_in_action_map` | Module 3 | `ACTION_MAP["extract_jsonld"] is ExtractJsonLd`. |
| `test_action_list_accepts_extract_jsonld` | Module 3 | Pydantic discriminator parses `{"action":"extract_jsonld","types":["Product"]}` into `ExtractJsonLd` with `types=["Product"]`. |
| `test_scrapingstep_from_dict_extract_jsonld` | Module 3 | `ScrapingStep.from_dict({"action":"extract_jsonld",...})` round-trips correctly. |
| `test_jsonld_extractors_promoted_import` | Module 1 | `from parrot.utils.jsonld_extractors import EXTRACTOR_REGISTRY, JsonLdItem` succeeds. |
| `test_jsonld_extractors_backcompat_shim` | Module 1 | `from parrot_loaders.jsonld_extractors import EXTRACTOR_REGISTRY, JsonLdItem` still works and refers to the same objects (`is` comparison). |

### Integration Tests
| Test | Description |
|---|---|
| `test_action_extract_jsonld_basic` | Stub driver returning HTML with one `<script type="application/ld+json">` Product block — `step_extracted["jsonld"]` is a list of one dict with `content_kind == "jsonld-product"`. |
| `test_action_extract_jsonld_multi_type` | HTML with FAQ + Product + Recipe blocks and a `@graph` wrapper — output flat list contains items for all three, dedup by (content_kind, page_content). |
| `test_action_extract_jsonld_types_filter` | Same multi-type page, but `types=["Product"]` — output list contains only product items. |
| `test_action_extract_jsonld_empty_page` | HTML with no JSON-LD blocks — `step_extracted[key]` is `[]`, no exception. |
| `test_action_extract_jsonld_malformed_block` | One valid + one malformed JSON-LD block — valid items emitted, malformed silently skipped (logged at debug). |
| `test_action_extract_jsonld_custom_extract_name` | `extract_name="products"` lands in `step_extracted["products"]`. |
| `test_action_extract_jsonld_dispatch_wiring` | `_dispatch_step` routes `action_type == "extract_jsonld"` to `_action_extract_jsonld` and returns `True`. |
| `test_webscraping_loader_unchanged` | Existing `test_webscraping_loader.py` and `test_jsonld_extractors.py` test suites pass without modification — proves the shim + import-path change is invisible to the loader. |

### Test Data / Fixtures

```python
# tests/scraping/conftest.py — extend
@pytest.fixture
def html_with_product_jsonld() -> str:
    """Minimal page with one schema.org/Product JSON-LD block."""
    return """
    <html><head>
    <script type="application/ld+json">
    {"@context":"https://schema.org","@type":"Product",
     "name":"Acme Widget","description":"A useful widget"}
    </script>
    </head><body></body></html>
    """

@pytest.fixture
def html_with_multi_type_graph() -> str:
    """Page with @graph containing FAQ + Product + Recipe nodes."""
    ...

class StubDriver:
    """Async stub implementing get_page_source() for executor tests."""
    def __init__(self, html: str) -> None:
        self._html = html
    async def get_page_source(self) -> str:
        return self._html
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `parrot/utils/jsonld_extractors.py` exists in the core package with
      identical public API to the original `parrot_loaders.jsonld_extractors`
      module.
- [ ] `parrot_loaders.jsonld_extractors` is reduced to a backward-compat
      re-export shim (≤ 10 lines including imports + `__all__`); existing
      external imports continue to resolve.
- [ ] `WebScrapingLoader` imports `EXTRACTOR_REGISTRY` and `JsonLdItem` from
      `parrot.utils.jsonld_extractors`; all existing tests in
      `packages/ai-parrot-loaders/tests/test_webscraping_loader.py` and
      `test_jsonld_extractors.py` pass without modification.
- [ ] `ExtractJsonLd` Pydantic model exists in `parrot_tools.scraping.models`
      with discriminator `action: Literal["extract_jsonld"]`, default
      `extract_name="jsonld"`, and `types: Optional[List[str]] = None`.
- [ ] `ACTION_MAP["extract_jsonld"] is ExtractJsonLd` and `ActionList`
      discriminated union accepts `extract_jsonld` payloads.
- [ ] `_action_extract_jsonld` is dispatched from `_dispatch_step` and writes
      a `list[dict]` into `step_extracted[extract_name]`.
- [ ] Each emitted dict has the keys `content_kind`, `source_type`,
      `page_content`, `row_data`, `selector_name` and is JSON-serializable
      (`json.dumps(record)` succeeds on every record).
- [ ] When `types=None`, every registered `@type` from `EXTRACTOR_REGISTRY`
      is extracted; when `types` is set, only listed types appear.
- [ ] Empty pages (no JSON-LD) yield an empty list, not `None` and not an
      exception.
- [ ] Malformed JSON-LD blocks are silently skipped (logged at debug);
      sibling valid blocks still produce items.
- [ ] All new unit and integration tests pass:
      `pytest packages/ai-parrot-tools/tests/scraping/ -v` and
      `pytest packages/ai-parrot-loaders/tests/ -v`.
- [ ] `mypy packages/ai-parrot-tools/src/parrot_tools/scraping/` and
      `mypy packages/ai-parrot/src/parrot/utils/jsonld_extractors.py` clean.
- [ ] No breaking changes to existing public API (existing `Extract` action
      and any direct `parrot_loaders.jsonld_extractors` consumers behave
      identically).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
# In parrot_tools/scraping/models.py (existing, line 1-11):
from __future__ import annotations
from typing import Optional, List, Dict, Any, Union, Literal, Annotated
from abc import ABC
import time
from dataclasses import dataclass, field
from pydantic import BaseModel, Field, field_validator, model_validator
from bs4 import BeautifulSoup

# In parrot_tools/scraping/executor.py (existing):
from bs4 import BeautifulSoup
from parrot_tools.scraping.models import ScrapingStep
# (verify exact existing import block at executor.py top before editing)

# NEW — to add in executor.py and models.py respectively:
from parrot.utils.jsonld_extractors import EXTRACTOR_REGISTRY, JsonLdItem

# In parrot_loaders/webscraping.py (existing, line 52-55) — UPDATE:
# OLD: from parrot_loaders.jsonld_extractors import EXTRACTOR_REGISTRY, JsonLdItem
# NEW: from parrot.utils.jsonld_extractors import EXTRACTOR_REGISTRY, JsonLdItem
```

### Existing Class & Function Signatures

```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/models.py:14
class BrowserAction(BaseModel, ABC):
    name: str          # Field default ""
    action: str        # Field default "" — opcode for discriminated union
    description: str   # Field default ""
    timeout: Optional[int]  # default None

    def get_action_type(self) -> str:  # line 24
        return self.action or self.name


# packages/ai-parrot-tools/src/parrot_tools/scraping/models.py:146
class Extract(BrowserAction):
    name: str = "extract"                      # line 161
    action: Literal["extract"] = "extract"     # line 162
    description: str = ...                     # line 163
    selector: str = Field(...)                 # line 164
    selector_type: Literal["css","xpath"]      # line 165 — default "css"
    extract_type: Literal["html","text","attribute"]  # line 169 — default "text"
    attribute: Optional[str] = None            # line 173
    multiple: bool = False                     # line 174
    extract_name: str = ""                     # line 175
    fields: Optional[Dict[str, FieldSpec]]     # line 182


# packages/ai-parrot-tools/src/parrot_tools/scraping/models.py:671
ActionList = Annotated[
    Union[
        Navigate, Click, Hover, Fill, Type, Select, Evaluate, PressKey,
        Refresh, Back, Scroll, GetCookies, SetCookies, Wait, Authenticate,
        AwaitHuman, AwaitKeyPress, AwaitBrowserEvent,
        GetText, GetHTML, Extract, Submit, WaitForDownload, UploadFile,
        Screenshot, Loop, Conditional,
    ],
    Field(discriminator="action"),
]


# packages/ai-parrot-tools/src/parrot_tools/scraping/models.py:688
ACTION_MAP = {
    "navigate": Navigate, "click": Click, "hover": Hover, "fill": Fill,
    "type": Type, "select": Select, "evaluate": Evaluate, "press_key": PressKey,
    "refresh": Refresh, "back": Back, "scroll": Scroll,
    "get_cookies": GetCookies, "set_cookies": SetCookies, "wait": Wait,
    "authenticate": Authenticate, "await_human": AwaitHuman,
    "await_keypress": AwaitKeyPress, "await_browser_event": AwaitBrowserEvent,
    "loop": Loop, "get_text": GetText, "get_html": GetHTML,
    "extract": Extract, "submit": Submit,
    "wait_for_download": WaitForDownload, "upload_file": UploadFile,
    "screenshot": Screenshot, "conditional": Conditional,
}

…(truncated)…
