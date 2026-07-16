---
type: Wiki Overview
title: 'TASK-973: Create JSON-LD Extractor Functions and JsonLdItem Model'
id: doc:sdd-tasks-completed-task-973-jsonld-extractors-module-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the foundation task for FEAT-142. It creates the new
relates_to:
- concept: mod:parrot_loaders
  rel: mentions
- concept: mod:parrot_loaders.jsonld_extractors
  rel: mentions
---

# TASK-973: Create JSON-LD Extractor Functions and JsonLdItem Model

**Feature**: FEAT-142 — WebScrapingLoader JSON-LD Multi-Type Support
**Spec**: `sdd/specs/webscrapingloader-jsonld-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundation task for FEAT-142. It creates the new
`jsonld_extractors.py` module containing the `JsonLdItem` data model and
individual extractor functions for each supported schema.org JSON-LD type.

These extractors are pure data transformations: they receive a parsed JSON-LD
node (a `dict`) and return a list of `JsonLdItem` instances. They have no
dependencies on WebScrapingLoader or BeautifulSoup — the dispatch integration
happens in TASK-974.

Implements spec §2 (Data Models), §3 Module 1 (JSON-LD Extractors).

---

## Scope

- Create `packages/ai-parrot-loaders/src/parrot_loaders/jsonld_extractors.py`
- Define `JsonLdItem` dataclass with fields: `content_kind`, `source_type`,
  `page_content`, `row_data`, `selector_name`
- Implement a `strip_html_text(text)` utility function (extracted from
  `WebScrapingLoader._strip_html` logic — same algorithm: unescape HTML
  entities, strip tags via BeautifulSoup, collapse whitespace)
- Implement extractor functions for **10 JSON-LD types**, each returning
  `List[JsonLdItem]`:
  1. `faq_extractor(node)` — FAQPage with Question/Answer mainEntity
  2. `product_extractor(node)` — Product with offers, brand, rating
  3. `event_extractor(node)` — Event with dates, location, performer
  4. `person_extractor(node)` — Person with jobTitle, affiliation
  5. `place_extractor(node)` — Place / LocalBusiness with address, geo
  6. `recipe_extractor(node)` — Recipe with ingredients, instructions
  7. `article_extractor(node)` — Article / NewsArticle / BlogPosting
  8. `organization_extractor(node)` — Organization with contacts
  9. `howto_extractor(node)` — HowTo with steps
  10. `breadcrumb_extractor(node)` — BreadcrumbList with ordered items
- Export a `EXTRACTOR_REGISTRY: Dict[str, Callable]` mapping `@type` strings
  to extractor functions (including aliases like `"LocalBusiness"` → `place_extractor`,
  `"NewsArticle"` → `article_extractor`, etc.)
- Write unit tests for every extractor in
  `packages/ai-parrot-loaders/tests/test_jsonld_extractors.py`

**NOT in scope**:
- Modifying `webscraping.py` — that is TASK-974
- Modifying `abstract.py` — that is TASK-974
- Integration tests with full WebScrapingLoader pipeline — that is TASK-975

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-loaders/src/parrot_loaders/jsonld_extractors.py` | CREATE | JsonLdItem model + all extractor functions + EXTRACTOR_REGISTRY |
| `packages/ai-parrot-loaders/tests/test_jsonld_extractors.py` | CREATE | Unit tests for every extractor function |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# This task creates a NEW module — it depends only on stdlib + beautifulsoup4
from dataclasses import dataclass, field  # stdlib
from typing import Any, Dict, List, Optional, Callable  # stdlib
import html as _html  # stdlib
import re  # stdlib
from bs4 import BeautifulSoup  # verified: already a dependency of parrot_loaders
```

### Existing Signatures to Use

```python
# packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py:510
# The existing _strip_html logic to replicate in the new module:
@staticmethod
def _strip_html(text: Any) -> str:
    """Render an acceptedAnswer.text payload as clean plain text."""
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    decoded = _html.unescape(text)
    soup = BeautifulSoup(decoded, "html.parser")
    flat = soup.get_text(separator=" ", strip=False)
    return re.sub(r"\s+", " ", flat).strip()

# packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py:531
# The existing FAQ iteration logic (for reference when building faq_extractor):
@classmethod
def _iter_faqpage_pairs(cls, data: Any):
    """Yield (question, answer) tuples from a parsed JSON-LD object."""
    # Handles: @graph, arrays, FAQPage→mainEntity, Question→acceptedAnswer
```

### Does NOT Exist

- ~~`parrot_loaders.jsonld_extractors`~~ — does not exist yet; this task creates it
- ~~`parrot_loaders.jsonld`~~ — does not exist
- ~~`parrot_loaders.schema_org`~~ — does not exist
- ~~`JsonLdItem`~~ — does not exist yet; this task creates it
- ~~`EXTRACTOR_REGISTRY`~~ — does not exist yet; this task creates it

---

## Implementation Notes

### Pattern to Follow

Each extractor function follows this consistent pattern:

```python
def product_extractor(node: Dict[str, Any]) -> List[JsonLdItem]:
    """Extract Product data from a JSON-LD node."""
    name = strip_html_text(node.get("name", ""))
    description = strip_html_text(node.get("description", ""))
    # ... extract other fields ...

    if not name:
        return []

    row_data = {"name": name, "description": description, ...}

    # Format page_content as structured text for embedding
    parts = [f"# {name}"]
    if description:
        parts.append(f"\n{description}")
    # ... add other fields ...

    return [JsonLdItem(
        content_kind="jsonld-product",
        source_type="product-jsonld",
        page_content="\n".join(parts),
        row_data=row_data,
        selector_name="product",
    )]
```

**The FAQPage extractor is special**: it yields **multiple** `JsonLdItem`
instances (one per Q&A pair), matching the existing behavior of
`_iter_faqpage_pairs`. Its `content_kind` must remain `"faq"` and
`source_type` must remain `"faq-jsonld"` for backward compatibility.

### Key Constraints

- All text values must pass through `strip_html_text()` for entity decoding
  and tag stripping
- Extractors must gracefully handle missing fields (return `[]` or skip
  missing fields) — never raise exceptions on malformed input
- `EXTRACTOR_REGISTRY` must map ALL recognized `@type` strings including
  aliases:
  ```python
  EXTRACTOR_REGISTRY: Dict[str, Callable] = {
      "FAQPage": faq_extractor,
      "Product": product_extractor,
      "IndividualProduct": product_extractor,
      "Event": event_extractor,
      "Person": person_extractor,
      "Place": place_extractor,
      "LocalBusiness": place_extractor,
      "Restaurant": place_extractor,
      "Recipe": recipe_extractor,
      "Article": article_extractor,
      "NewsArticle": article_extractor,
      "BlogPosting": article_extractor,
      "Organization": organization_extractor,
      "HowTo": howto_extractor,
      "BreadcrumbList": breadcrumb_extractor,
  }
  ```
- `page_content` formatting:
  - FAQPage: `"Q: {question}\n\nA: {answer}"` (matches existing format exactly)
  - All others: Markdown-like format with `# Name` heading + labeled sections
- BreadcrumbList: emit ONE item with the full path as page_content
  (e.g. `"Home > Products > Widget Pro"`)

### References in Codebase

- `packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py:506-584` — existing FAQ extraction logic to replicate in `faq_extractor`
- `packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py:510-528` — `_strip_html` logic to extract into `strip_html_text`

---

## Acceptance Criteria

- [ ] `jsonld_extractors.py` created with `JsonLdItem` dataclass
- [ ] `strip_html_text()` function works identically to `WebScrapingLoader._strip_html()`
- [ ] `faq_extractor` produces items with `content_kind="faq"`, `source_type="faq-jsonld"`
- [ ] All 10 extractor functions implemented and handle missing fields gracefully
- [ ] `EXTRACTOR_REGISTRY` maps all type strings (including aliases) to extractors
- [ ] Unit tests pass: `pytest packages/ai-parrot-loaders/tests/test_jsonld_extractors.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-loaders/src/parrot_loaders/jsonld_extractors.py`

---

## Test Specification

```python
# packages/ai-parrot-loaders/tests/test_jsonld_extractors.py
import pytest
from parrot_loaders.jsonld_extractors import (
    JsonLdItem,
    strip_html_text,
    faq_extractor,
    product_extractor,
    event_extractor,
    person_extractor,
    place_extractor,
    recipe_extractor,
    article_extractor,
    organization_extractor,
    howto_extractor,
    breadcrumb_extractor,
    EXTRACTOR_REGISTRY,
)


class TestStripHtmlText:
    def test_strips_tags(self):
        assert strip_html_text("<p>Hello <b>world</b></p>") == "Hello world"

    def test_decodes_entities(self):
        assert strip_html_text("AT&amp;T &amp; Verizon") == "AT&T & Verizon"

    def test_collapses_whitespace(self):
        assert strip_html_text("  lots   of   space  ") == "lots of space"

    def test_handles_none(self):
        assert strip_html_text(None) == ""


class TestFaqExtractor:
    def test_basic_faq(self):
        node = {
            "@type": "FAQPage",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": "What is X?",
                    "acceptedAnswer": {"@type": "Answer", "text": "X is great."},
                }
            ],
        }
        items = faq_extractor(node)
        assert len(items) == 1
        assert items[0].content_kind == "faq"
        assert items[0].source_type == "faq-jsonld"
        assert "Q: What is X?" in items[0].page_content
        assert "A: X is great." in items[0].page_content

    def test_empty_main_entity(self):
        assert faq_extractor({"@type": "FAQPage", "mainEntity": []}) == []


class TestProductExtractor:
    def test_basic_product(self):
        node = {
            "@type": "Product",
            "name": "Widget Pro",
            "description": "A great widget.",
            "offers": {"@type": "Offer", "price": "29.99", "priceCurrency": "USD"},
        }
        items = product_extractor(node)
        assert len(items) == 1
        assert items[0].content_kind == "jsonld-product"
        assert "Widget Pro" in items[0].page_content
        assert items[0].row_data["name"] == "Widget Pro"

    def test_missing_name_returns_empty(self):
        assert product_extractor({"@type": "Product"}) == []


class TestEventExtractor:
    def test_basic_event(self):
        node = {
            "@type": "Event",
            "name": "Tech Conf",
            "startDate": "2026-09-15",
            "location": {"@type": "Place", "name": "Convention Center"},
        }
        items = event_extractor(node)
        assert len(items) == 1
        assert items[0].content_kind == "jsonld-event"
        assert "Tech Conf" in items[0].page_content


class TestPersonExtractor:
    def test_basic_person(self):
        node = {"@type": "Person", "name": "Jane Doe", "jobTitle": "Engineer"}
        items = person_extractor(node)
        assert len(items) == 1
        assert items[0].content_kind == "jsonld-person"


class TestPlaceExtractor:
    def test_local_business(self):
        node = {
            "@type": "LocalBusiness",
            "name": "Joe's Pizza",
            "address": "123 Main St",
        }
        items = place_extractor(node)
        assert len(items) == 1
        assert items[0].content_kind == "jsonld-place"


class TestRecipeExtractor:
    def test_basic_recipe(self):
        node = {
            "@type": "Recipe",
            "name": "Chocolate Cake",
            "recipeIngredient": ["flour", "sugar", "cocoa"],
            "recipeInstructions": [
                {"@type": "HowToStep", "text": "Mix dry ingredients."}
            ],
        }
        items = recipe_extractor(node)
        assert len(items) == 1
        assert items[0].content_kind == "jsonld-recipe"


class TestArticleExtractor:
    def test_basic_article(self):
        node = {
            "@type": "Article",
            "headline": "Breaking News",
            "author": {"@type": "Person", "name": "Reporter"},
            "datePublished": "2026-01-15",
        }
        items = article_extractor(node)
        assert len(items) == 1
        assert items[0].content_kind == "jsonld-article"


class TestOrganizationExtractor:
    def test_basic_org(self):
        node = {"@type": "Organization", "name": "Acme Corp", "url": "https://acme.com"}
        items = organization_extractor(node)
        assert len(items) == 1
        assert items[0].content_kind == "jsonld-organization"


class TestHowToExtractor:
    def test_basic_howto(self):
        node = {
            "@type": "HowTo",
            "name": "Change a Tire",
            "step": [
                {"@type": "HowToStep", "text": "Loosen the nuts."},
                {"@type": "HowToStep", "text": "Jack up the car."},
            ],
        }
        items = howto_extractor(node)
        assert len(items) == 1
        assert items[0].content_kind == "jsonld-howto"


class TestBreadcrumbExtractor:
    def test_basic_breadcrumb(self):
        node = {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Home"},
                {"@type": "ListItem", "position": 2, "name": "Products"},
                {"@type": "ListItem", "position": 3, "name": "Widget"},
            ],
        }
        items = breadcrumb_extractor(node)
        assert len(items) == 1
        assert items[0].content_kind == "jsonld-breadcrumb"
        assert "Home" in items[0].page_content


class TestExtractorRegistry:
    def test_all_types_registered(self):
        expected = {
            "FAQPage", "Product", "IndividualProduct", "Event", "Person",
            "Place", "LocalBusiness", "Restaurant", "Recipe", "Article",
            "NewsArticle", "BlogPosting", "Organization", "HowTo",
            "BreadcrumbList",
        }
        assert expected.issubset(set(EXTRACTOR_REGISTRY.keys()))

    def test_aliases_point_to_same_function(self):
        assert EXTRACTOR_REGISTRY["LocalBusiness"] is EXTRACTOR_REGISTRY["Place"]
        assert EXTRACTOR_REGISTRY["NewsArticle"] is EXTRACTOR_REGISTRY["Article"]

    def test_handles_missing_fields(self):
        """Every extractor should return [] for an empty node."""
        for name, extractor in EXTRACTOR_REGISTRY.items():
            if name == "FAQPage":
                result = extractor({"@type": "FAQPage", "mainEntity": []})
            else:
                result = extractor({"@type": name})
            assert isinstance(result, list), f"{name} extractor should return a list"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — confirm `webscraping.py` still has `_strip_html` at line 510
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** the `jsonld_extractors.py` module and tests
6. **Run tests**: `source .venv/bin/activate && pytest packages/ai-parrot-loaders/tests/test_jsonld_extractors.py -v`
7. **Run lint**: `source .venv/bin/activate && ruff check packages/ai-parrot-loaders/src/parrot_loaders/jsonld_extractors.py`
8. **Move this file** to `tasks/completed/TASK-973-jsonld-extractors-module.md`
9. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker agent
**Date**: 2026-05-04
**Notes**: All 10 extractor functions implemented. 62 unit tests pass. Lint clean.
strip_html_text replicates WebScrapingLoader._strip_html exactly.
EXTRACTOR_REGISTRY includes all 15 type strings (canonical + aliases).

**Deviations from spec**: none
