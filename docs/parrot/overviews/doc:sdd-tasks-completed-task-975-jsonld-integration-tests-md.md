---
type: Wiki Overview
title: 'TASK-975: Integration Tests and Backward Compatibility Regression Suite'
id: doc:sdd-tasks-completed-task-975-jsonld-integration-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task adds comprehensive integration tests that exercise the full
relates_to:
- concept: mod:parrot.stores.models
  rel: mentions
- concept: mod:parrot_loaders.webscraping
  rel: mentions
---

# TASK-975: Integration Tests and Backward Compatibility Regression Suite

**Feature**: FEAT-142 — WebScrapingLoader JSON-LD Multi-Type Support
**Spec**: `sdd/specs/webscrapingloader-jsonld-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-973, TASK-974
**Assigned-to**: unassigned

---

## Context

This task adds comprehensive integration tests that exercise the full
WebScrapingLoader pipeline (from HTML → mocked ScrapingResult → Documents)
with JSON-LD data of every supported type. It also adds explicit backward
compatibility regression tests to ensure FAQPage extraction is unchanged.

Implements spec §4 (Test Specification — Integration Tests) and validates
spec §5 Acceptance Criteria.

---

## Scope

- Add integration tests to `packages/ai-parrot-loaders/tests/test_webscraping_loader.py`
  that use mocked `ScrapingResult` objects (following the existing test pattern)
  with HTML containing JSON-LD blocks for each type
- Test the full pipeline: `_load()` → documents with correct `content_kind`,
  `source_type`, `row_data`, and `page_content` formatting
- Backward compatibility regression:
  - Run the existing `ATT_FAQ_FIXTURE_HTML` through the new pipeline
  - Assert all metadata fields match the expected values from the existing tests
  - Ensure `content_kind="faq"` (not `"jsonld-faq"`)
  - Ensure `source_type="faq-jsonld"`
  - Ensure `page_content` format is `"Q: ...\n\nA: ..."`
- Test `jsonld_types` filtering in the full pipeline
- Test mixed JSON-LD pages (FAQ + Product + Event in one `@graph`)
- Test pages with JSON-LD alongside regular content (full-page markdown +
  JSON-LD structured data coexist)
- Test `extract_only=True` behavior with JSON-LD data

**NOT in scope**:
- Modifying any implementation code — this is a test-only task
- Unit tests for individual extractors — those are in TASK-973
- Testing with real browser sessions — all tests use mocked results

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-loaders/tests/test_webscraping_loader.py` | MODIFY | Add integration test classes for JSON-LD multi-type support |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Existing test infrastructure (verified from test_webscraping_loader.py):
from parrot_loaders.webscraping import WebScrapingLoader  # line 16
from parrot.stores.models import Document  # line 17
from bs4 import BeautifulSoup  # line 14
from unittest.mock import AsyncMock, MagicMock, patch  # line 9
from dataclasses import dataclass, field  # line 7
import pytest  # line 11
import pytest_asyncio  # line 12
```

### Existing Signatures to Use

```python
# packages/ai-parrot-loaders/tests/test_webscraping_loader.py

# Existing test helpers to REUSE (do not redefine):
@dataclass
class FakeScrapingResult:  # line 55
    url: str
    content: str
    bs_soup: BeautifulSoup
    extracted_data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    success: bool = True
    error_message: Optional[str] = None

def _make_result(url, html, extracted_data, success) -> FakeScrapingResult:  # line 80

def _mock_toolkit(scrape_result, crawl_result):  # line 96

# Existing fixture:
ATT_FAQ_FIXTURE_HTML  # line 479 — the AT&T FAQ HTML fixture

# Existing test class for FAQ regression baseline:
class TestFAQPageJSONLD:  # line 527
class TestFAQPageDocumentEmission:  # line 633
```

### Does NOT Exist

- ~~`FakeScrapingResult.jsonld_data`~~ — not a field; JSON-LD is in `content` / `bs_soup`
- ~~`WebScrapingLoader.extract_jsonld()`~~ — it's `_extract_jsonld()` (private, with underscore)
- ~~`test_webscraping_jsonld.py`~~ — does not exist; tests go in existing `test_webscraping_loader.py`

---

## Implementation Notes

### Pattern to Follow

Follow the existing test pattern in `test_webscraping_loader.py`:

```python
@pytest.mark.asyncio
async def test_product_jsonld_produces_documents():
    """Page with Product JSON-LD emits jsonld-product documents."""
    html = '''<html><head><title>Shop</title></head><body>
    <script type="application/ld+json">
    {"@type":"Product","name":"Widget","description":"Great widget.",
     "offers":{"@type":"Offer","price":"29.99","priceCurrency":"USD"}}
    </script>
    <p>Product page content.</p>
    </body></html>'''
    result = _make_result(html=html)
    loader = WebScrapingLoader(source="https://example.com/product")
    loader._toolkit = _mock_toolkit(scrape_result=result)

    docs = await loader._load("https://example.com/product")

    product_docs = [d for d in docs if d.metadata.get("content_kind") == "jsonld-product"]
    assert len(product_docs) == 1
    assert "Widget" in product_docs[0].page_content
    assert product_docs[0].metadata["row_data"]["name"] == "Widget"
    assert product_docs[0].metadata["source_type"] == "product-jsonld"
```

### Key Constraints

- Reuse `_make_result`, `_mock_toolkit`, `FakeScrapingResult` from the
  existing test file — do NOT redefine them
- FAQPage regression tests must verify metadata at the field level, not
  just existence (compare exact `content_kind`, `source_type`,
  `selector_name`, `row_data` keys)
- Use `stub_loader` fixture for testing `_extract_jsonld` directly (same
  pattern as existing `TestFAQPageJSONLD`)
- HTML fixtures should be realistic (include `<head>`, `<title>`, `<body>`)
  since `_result_to_documents` extracts metadata from these elements

### References in Codebase

- `packages/ai-parrot-loaders/tests/test_webscraping_loader.py:55-103` — test helpers
- `packages/ai-parrot-loaders/tests/test_webscraping_loader.py:479-515` — ATT_FAQ_FIXTURE_HTML
- `packages/ai-parrot-loaders/tests/test_webscraping_loader.py:527-675` — existing FAQ tests (regression baseline)

---

## Acceptance Criteria

- [ ] Integration test for each JSON-LD type (Product, Event, Person, Place, Recipe, Article, Organization, HowTo, BreadcrumbList)
- [ ] FAQPage backward compatibility regression test passes
- [ ] Mixed JSON-LD page test (multiple types in one `@graph`) passes
- [ ] `jsonld_types` filtering test in full pipeline passes
- [ ] `extract_only=True` with JSON-LD data test passes
- [ ] JSON-LD alongside regular content (markdown_full + jsonld docs coexist) test passes
- [ ] All existing tests still pass (no regressions)
- [ ] Tests pass: `pytest packages/ai-parrot-loaders/tests/test_webscraping_loader.py -v`

---

## Test Specification

```python
# packages/ai-parrot-loaders/tests/test_webscraping_loader.py
# Add these test classes to the existing file


class TestJsonLdMultiTypeIntegration:
    """Full pipeline tests for each JSON-LD type."""

    @pytest.mark.asyncio
    async def test_product_jsonld(self):
        """Product JSON-LD → jsonld-product documents."""
        # Use PRODUCT_JSONLD_HTML fixture
        pass

    @pytest.mark.asyncio
    async def test_event_jsonld(self):
        """Event JSON-LD → jsonld-event documents."""
        pass

    @pytest.mark.asyncio
    async def test_person_jsonld(self):
        """Person JSON-LD → jsonld-person documents."""
        pass

    @pytest.mark.asyncio
    async def test_place_jsonld(self):
        """Place/LocalBusiness JSON-LD → jsonld-place documents."""
        pass

    @pytest.mark.asyncio
    async def test_recipe_jsonld(self):
        """Recipe JSON-LD → jsonld-recipe documents."""
        pass

    @pytest.mark.asyncio
    async def test_article_jsonld(self):
        """Article JSON-LD → jsonld-article documents."""
        pass

    @pytest.mark.asyncio
    async def test_organization_jsonld(self):
        """Organization JSON-LD → jsonld-organization documents."""
        pass

    @pytest.mark.asyncio
    async def test_howto_jsonld(self):
        """HowTo JSON-LD → jsonld-howto documents."""
        pass

    @pytest.mark.asyncio
    async def test_breadcrumb_jsonld(self):
        """BreadcrumbList JSON-LD → jsonld-breadcrumb documents."""
        pass


class TestJsonLdMixedContent:
    """Test JSON-LD extraction alongside other content types."""

    @pytest.mark.asyncio
    async def test_mixed_graph_multiple_types(self):
        """Page with @graph containing FAQ + Product yields both doc types."""
        pass

    @pytest.mark.asyncio
    async def test_jsonld_with_regular_content(self):
        """JSON-LD docs coexist with markdown_full, tables, videos."""
        pass

    @pytest.mark.asyncio
    async def test_extract_only_includes_jsonld(self):
        """extract_only=True still emits JSON-LD documents."""
        pass


class TestJsonLdTypesFilter:
    """Test the jsonld_types constructor parameter."""

    @pytest.mark.asyncio
    async def test_filter_to_single_type(self):
        """jsonld_types=['Product'] extracts only Product from mixed page."""
        pass

    @pytest.mark.asyncio
    async def test_filter_empty_disables(self):
        """jsonld_types=[] disables all JSON-LD extraction."""
        pass

    @pytest.mark.asyncio
    async def test_filter_none_extracts_all(self):
        """jsonld_types=None (default) extracts all supported types."""
        pass


class TestFAQPageBackwardCompat:
    """Regression: FAQPage via new pipeline must match old output exactly."""

    @pytest.mark.asyncio
    async def test_att_fixture_produces_same_faq_docs(self):
        """ATT_FAQ_FIXTURE_HTML through new pipeline → identical FAQ docs."""
        result = _make_result(html=ATT_FAQ_FIXTURE_HTML)
        loader = WebScrapingLoader(source="https://www.att.com/prepaid/")
        loader._toolkit = _mock_toolkit(scrape_result=result)
        docs = await loader._load("https://www.att.com/prepaid/")
        faq_docs = [d for d in docs if d.metadata.get("content_kind") == "faq"]
        assert len(faq_docs) == 3
        for doc in faq_docs:
            assert doc.metadata["content_kind"] == "faq"
            assert doc.metadata["source_type"] == "faq-jsonld"
            assert doc.metadata["selector_name"] == "faq"
            assert "question" in doc.metadata["row_data"]
            assert "answer" in doc.metadata["row_data"]
            assert doc.page_content.startswith("Q: ")
            assert "\n\nA: " in doc.page_content

    @pytest.mark.asyncio
    async def test_no_jsonld_faq_content_kind(self):
        """FAQPage must use 'faq', never 'jsonld-faq'."""
        result = _make_result(html=ATT_FAQ_FIXTURE_HTML)
        loader = WebScrapingLoader(source="https://example.com")
        loader._toolkit = _mock_toolkit(scrape_result=result)
        docs = await loader._load("https://example.com")
        kinds = {d.metadata.get("content_kind") for d in docs}
        assert "jsonld-faq" not in kinds
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/webscrapingloader-jsonld-support.spec.md`
2. **Check dependencies** — TASK-973 and TASK-974 must be completed first
3. **Read existing tests** in `test_webscraping_loader.py` to understand patterns
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Add tests** to the existing test file (do NOT create a separate file)
6. **Run all tests**: `source .venv/bin/activate && pytest packages/ai-parrot-loaders/tests/test_webscraping_loader.py -v`
7. **Ensure existing tests still pass** — no regressions
8. **Move this file** to `tasks/completed/TASK-975-jsonld-integration-tests.md`
9. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker agent
**Date**: 2026-05-04
**Notes**: Added 5 test classes with 29 new test methods to test_webscraping_loader.py:
  - TestJsonLdMultiTypeIntegration: 13 tests for _extract_jsonld (all 9 types + edge cases)
  - TestJsonLdDocsFromItems: 3 tests for _docs_from_jsonld_items
  - TestJsonLdMixedContent: 4 tests for mixed content scenarios
  - TestJsonLdTypesFilter: 5 tests for jsonld_types parameter
  - TestFAQPageBackwardCompat: 5 regression tests for FAQ backward compatibility
Total: 121 tests pass (2 pre-existing failures unchanged — test_text_format and test_registry_entry
were already failing on dev before this feature).

**Deviations from spec**: test_jsonld_with_regular_content checks for
{"markdown_full","trafilatura_main","trafilatura_full","text_full"} instead of just "full" suffix,
because the actual trafilatura content kind is "trafilatura_main" not "trafilatura_full".
