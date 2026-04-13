"""Tests for recall_processor.py — RecallProcessor."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from parrot_tools.scraping.extraction_models import (
    EntityFieldSpec,
    EntitySpec,
    ExtractedEntity,
    ExtractionPlan,
)
from parrot_tools.scraping.recall_processor import RecallProcessor


# ---------------------------------------------------------------------------
# Fixtures & Helpers
# ---------------------------------------------------------------------------

SAMPLE_HTML = """
<html>
<body>
  <main>
    <div class="product-card">
      <h2 class="product-name">Widget A</h2>
      <span class="price">$9.99</span>
    </div>
    <div class="product-card">
      <h2 class="product-name">Widget B</h2>
      <span class="price">$14.99</span>
    </div>
  </main>
</body>
</html>
"""


def _make_plan() -> ExtractionPlan:
    return ExtractionPlan(
        url="https://example.com/products",
        objective="Extract products",
        entities=[
            EntitySpec(
                entity_type="product",
                description="A product",
                container_selector=".product-card",
                fields=[
                    EntityFieldSpec(name="product_name", description="Name", selector=".product-name"),
                    EntityFieldSpec(name="price", description="Price", selector=".price"),
                ],
            )
        ],
    )


def _make_entities() -> list[ExtractedEntity]:
    return [
        ExtractedEntity(
            entity_type="product",
            fields={"product_name": "Widget A", "price": "$9.99"},
            source_url="https://example.com/products",
        ),
        ExtractedEntity(
            entity_type="product",
            fields={"product_name": "Widget B", "price": None},
            source_url="https://example.com/products",
        ),
    ]


VALID_RECALL_RESPONSE = json.dumps({
    "entities": [
        {
            "index": 0,
            "rag_text": "Widget A is priced at $9.99.",
            "filled_fields": {},
        },
        {
            "index": 1,
            "rag_text": "Widget B is priced at $14.99.",
            "filled_fields": {"price": "$14.99"},
        },
    ]
})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRecallProcessorRecall:
    """Tests for RecallProcessor.recall()."""

    @pytest.mark.asyncio
    async def test_recall_populates_rag_text(self) -> None:
        """recall() populates rag_text for each entity."""
        mock_client = AsyncMock()
        mock_client.complete.return_value = VALID_RECALL_RESPONSE

        processor = RecallProcessor(llm_client=mock_client)
        result = await processor.recall(
            entities=_make_entities(),
            page_html=SAMPLE_HTML,
            extraction_plan=_make_plan(),
            url="https://example.com/products",
        )

        assert result[0].rag_text == "Widget A is priced at $9.99."
        assert result[1].rag_text == "Widget B is priced at $14.99."

    @pytest.mark.asyncio
    async def test_recall_fills_missing_fields(self) -> None:
        """recall() fills null fields from HTML context."""
        mock_client = AsyncMock()
        mock_client.complete.return_value = VALID_RECALL_RESPONSE

        processor = RecallProcessor(llm_client=mock_client)
        result = await processor.recall(
            entities=_make_entities(),
            page_html=SAMPLE_HTML,
            extraction_plan=_make_plan(),
            url="https://example.com/products",
        )

        # Second entity had price=None, should be filled
        assert result[1].fields["price"] == "$14.99"

    @pytest.mark.asyncio
    async def test_recall_returns_originals_on_llm_failure(self) -> None:
        """recall() returns original entities when LLM call raises."""
        mock_client = AsyncMock()
        mock_client.complete.side_effect = RuntimeError("LLM unavailable")

        processor = RecallProcessor(llm_client=mock_client)
        original = _make_entities()
        result = await processor.recall(
            entities=original,
            page_html=SAMPLE_HTML,
            extraction_plan=_make_plan(),
            url="https://example.com/products",
        )

        assert len(result) == len(original)
        assert result[0].rag_text == ""  # unchanged

    @pytest.mark.asyncio
    async def test_recall_returns_originals_on_bad_json(self) -> None:
        """recall() returns original entities when LLM response is not valid JSON."""
        mock_client = AsyncMock()
        mock_client.complete.return_value = "This is not JSON."

        processor = RecallProcessor(llm_client=mock_client)
        original = _make_entities()
        result = await processor.recall(
            entities=original,
            page_html=SAMPLE_HTML,
            extraction_plan=_make_plan(),
            url="https://example.com/products",
        )

        assert result[0].rag_text == ""

    @pytest.mark.asyncio
    async def test_recall_empty_entities_returns_empty(self) -> None:
        """recall() returns empty list without calling LLM when entities is empty."""
        mock_client = AsyncMock()
        processor = RecallProcessor(llm_client=mock_client)
        result = await processor.recall(
            entities=[],
            page_html=SAMPLE_HTML,
            extraction_plan=_make_plan(),
            url="https://example.com/products",
        )
        assert result == []
        mock_client.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_recall_does_not_mutate_originals(self) -> None:
        """recall() returns copies and does not mutate the original entities."""
        mock_client = AsyncMock()
        mock_client.complete.return_value = VALID_RECALL_RESPONSE

        processor = RecallProcessor(llm_client=mock_client)
        originals = _make_entities()
        result = await processor.recall(
            entities=originals,
            page_html=SAMPLE_HTML,
            extraction_plan=_make_plan(),
            url="https://example.com/products",
        )

        # Originals should be unchanged
        assert originals[0].rag_text == ""
        assert result[0].rag_text != ""


class TestRecallProcessorPrepareContext:
    """Tests for RecallProcessor._prepare_html_context()."""

    def test_extracts_container_elements(self) -> None:
        """_prepare_html_context() extracts container elements from page HTML."""
        processor = RecallProcessor(llm_client=None)
        plan = _make_plan()
        context = processor._prepare_html_context(SAMPLE_HTML, plan)
        assert "Widget A" in context
        assert "Widget B" in context

    def test_falls_back_to_body_when_no_containers(self) -> None:
        """_prepare_html_context() falls back to body when no selectors match."""
        plan = ExtractionPlan(
            url="https://example.com",
            objective="Test",
            entities=[
                EntitySpec(
                    entity_type="item",
                    description="Item",
                    container_selector=".nonexistent-class",
                    fields=[],
                )
            ],
        )
        processor = RecallProcessor(llm_client=None)
        context = processor._prepare_html_context(SAMPLE_HTML, plan)
        # Should fall back to body content
        assert "Widget" in context
