"""Integration tests for the extract_jsonld BrowserAction — FEAT-154 / TASK-1050."""

import json

import pytest
from unittest.mock import AsyncMock

from parrot.tools.scraping.executor import (
    _action_extract_jsonld,
    _dispatch_step,
)
from parrot.tools.scraping.models import ExtractJsonLd, ScrapingStep

pytestmark = pytest.mark.asyncio


# ── Fixtures ───────────────────────────────────────────────────────────

PRODUCT_HTML = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product",
 "name":"Acme Widget","description":"A useful widget"}
</script>
</head><body></body></html>
"""

MULTI_TYPE_GRAPH_HTML = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
  {"@type":"Product","name":"Widget","description":"thing"},
  {"@type":"Recipe","name":"Pancakes","description":"breakfast",
   "recipeIngredient":["flour","milk"]},
  {"@type":"FAQPage","mainEntity":[
    {"@type":"Question","name":"Q1?",
     "acceptedAnswer":{"@type":"Answer","text":"A1."}}
  ]}
]}
</script>
</head><body></body></html>
"""

EMPTY_HTML = "<html><head></head><body><p>nothing here</p></body></html>"

MALFORMED_PLUS_VALID_HTML = """
<html><head>
<script type="application/ld+json">{ broken json </script>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"OK","description":"valid"}
</script>
</head><body></body></html>
"""


def _driver_returning(html: str):
    drv = AsyncMock()
    drv.get_page_source = AsyncMock(return_value=html)
    return drv


# ── Tests ──────────────────────────────────────────────────────────────

class TestActionExtractJsonLd:

    async def test_action_extract_jsonld_basic(self) -> None:
        action = ExtractJsonLd()
        step = ScrapingStep(action=action)
        step_extracted: dict = {}
        ok = await _action_extract_jsonld(
            _driver_returning(PRODUCT_HTML), action, step, step_extracted,
        )
        assert ok is True
        rows = step_extracted["jsonld"]
        assert len(rows) == 1
        assert rows[0]["content_kind"] == "jsonld-product"
        # JSON-serializable
        assert json.dumps(rows[0])

    async def test_action_extract_jsonld_multi_type(self) -> None:
        action = ExtractJsonLd()
        step = ScrapingStep(action=action)
        step_extracted: dict = {}
        await _action_extract_jsonld(
            _driver_returning(MULTI_TYPE_GRAPH_HTML), action, step, step_extracted,
        )
        kinds = {r["content_kind"] for r in step_extracted["jsonld"]}
        # The shared registry emits exactly these kinds for the documented types
        assert "jsonld-product" in kinds
        assert "jsonld-recipe" in kinds
        assert "faq" in kinds  # faq_extractor uses content_kind="faq"

    async def test_action_extract_jsonld_types_filter(self) -> None:
        action = ExtractJsonLd(types=["Product"])
        step = ScrapingStep(action=action)
        step_extracted: dict = {}
        await _action_extract_jsonld(
            _driver_returning(MULTI_TYPE_GRAPH_HTML), action, step, step_extracted,
        )
        kinds = {r["content_kind"] for r in step_extracted["jsonld"]}
        assert kinds == {"jsonld-product"}

    async def test_action_extract_jsonld_empty_list_filter(self) -> None:
        """types=[] disables extraction (parity with loader's _jsonld_types==[])."""
        action = ExtractJsonLd(types=[])
        step = ScrapingStep(action=action)
        step_extracted: dict = {}
        await _action_extract_jsonld(
            _driver_returning(MULTI_TYPE_GRAPH_HTML), action, step, step_extracted,
        )
        assert step_extracted["jsonld"] == []

    async def test_action_extract_jsonld_empty_page(self) -> None:
        action = ExtractJsonLd()
        step = ScrapingStep(action=action)
        step_extracted: dict = {}
        await _action_extract_jsonld(
            _driver_returning(EMPTY_HTML), action, step, step_extracted,
        )
        assert step_extracted["jsonld"] == []

    async def test_action_extract_jsonld_malformed_block(self) -> None:
        action = ExtractJsonLd()
        step = ScrapingStep(action=action)
        step_extracted: dict = {}
        await _action_extract_jsonld(
            _driver_returning(MALFORMED_PLUS_VALID_HTML),
            action, step, step_extracted,
        )
        rows = step_extracted["jsonld"]
        # Valid block survives; malformed silently skipped
        assert len(rows) == 1
        assert rows[0]["content_kind"] == "jsonld-product"

    async def test_action_extract_jsonld_custom_extract_name(self) -> None:
        action = ExtractJsonLd(extract_name="products")
        step = ScrapingStep(action=action)
        step_extracted: dict = {}
        await _action_extract_jsonld(
            _driver_returning(PRODUCT_HTML), action, step, step_extracted,
        )
        assert "products" in step_extracted
        assert "jsonld" not in step_extracted

    async def test_action_extract_jsonld_dispatch_wiring(self) -> None:
        """`_dispatch_step` routes extract_jsonld to the new handler."""
        action = ExtractJsonLd()
        step = ScrapingStep(action=action)
        step_extracted: dict = {}
        ok = await _dispatch_step(
            _driver_returning(PRODUCT_HTML),
            step,
            base_url="https://example.com",
            timeout=10,
            step_extracted=step_extracted,
        )
        assert ok is True
        assert step_extracted["jsonld"][0]["content_kind"] == "jsonld-product"

    async def test_action_extract_jsonld_key_collision_merge(self) -> None:
        """A second extract_jsonld step on the same key appends new rows without duplicates.

        Covers the O(1) merge path (merged_sigs set) and verifies that:
        1. Pre-existing rows in step_extracted[key] are preserved.
        2. New rows from the current page are appended.
        3. Running the same step again does NOT introduce duplicates.
        """
        action = ExtractJsonLd()
        step = ScrapingStep(action=action)

        # Pre-populate with a distinct item (different page_content from PRODUCT_HTML).
        pre_existing = {
            "content_kind": "jsonld-product",
            "source_type": "product-jsonld",
            "page_content": "Pre-existing product that won't appear in PRODUCT_HTML",
            "row_data": {},
            "selector_name": None,
        }
        step_extracted: dict = {"jsonld": [pre_existing]}

        # First run: PRODUCT_HTML yields a new product row; merges with pre-existing.
        await _action_extract_jsonld(
            _driver_returning(PRODUCT_HTML), action, step, step_extracted,
        )
        rows = step_extracted["jsonld"]
        assert len(rows) == 2, "Pre-existing row + new product row expected"
        content_kinds = {r["content_kind"] for r in rows}
        assert content_kinds == {"jsonld-product"}

        # Second run with the same HTML must NOT duplicate the product row.
        await _action_extract_jsonld(
            _driver_returning(PRODUCT_HTML), action, step, step_extracted,
        )
        assert len(step_extracted["jsonld"]) == 2, (
            "Duplicate merge detected — O(1) merged_sigs guard failed"
        )
