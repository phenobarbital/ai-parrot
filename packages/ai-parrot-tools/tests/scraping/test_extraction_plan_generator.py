"""Tests for extraction_plan_generator.py — ExtractionPlanGenerator."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from parrot_tools.scraping.extraction_models import ExtractionPlan
from parrot_tools.scraping.extraction_plan_generator import ExtractionPlanGenerator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head>
  <script>console.log('ignore me');</script>
  <style>body { color: red; }</style>
</head>
<body>
  <main>
    <div class="product-grid">
      <div class="product-card">
        <h2 class="product-name">Widget A</h2>
        <span class="price">$9.99</span>
      </div>
      <div class="product-card">
        <h2 class="product-name">Widget B</h2>
        <span class="price">$14.99</span>
      </div>
    </div>
  </main>
</body>
</html>
"""

VALID_PLAN_RESPONSE = json.dumps({
    "url": "https://example.com/products",
    "objective": "Extract product listings",
    "entities": [
        {
            "entity_type": "product",
            "description": "A product on the page",
            "repeating": True,
            "container_selector": ".product-card",
            "fields": [
                {
                    "name": "product_name",
                    "description": "Name of the product",
                    "selector": ".product-name",
                },
                {
                    "name": "price",
                    "description": "Product price",
                    "field_type": "currency",
                    "selector": ".price",
                },
            ],
        }
    ],
    "page_category": "ecommerce_products",
    "extraction_strategy": "hybrid",
})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestExtractionPlanGeneratorGenerate:
    """Tests for ExtractionPlanGenerator.generate()."""

    @pytest.mark.asyncio
    async def test_generate_returns_extraction_plan(self) -> None:
        """generate() returns a validated ExtractionPlan from LLM response."""
        mock_client = AsyncMock()
        mock_client.complete.return_value = VALID_PLAN_RESPONSE

        gen = ExtractionPlanGenerator(llm_client=mock_client)
        plan = await gen.generate(
            url="https://example.com/products",
            objective="Extract product listings",
            content=SAMPLE_HTML,
        )

        assert isinstance(plan, ExtractionPlan)
        assert plan.url == "https://example.com/products"
        assert plan.source == "llm"
        assert len(plan.entities) == 1
        assert plan.entities[0].entity_type == "product"

    @pytest.mark.asyncio
    async def test_generate_sets_source_to_llm(self) -> None:
        """generate() always sets source to 'llm'."""
        mock_client = AsyncMock()
        response_with_wrong_source = json.loads(VALID_PLAN_RESPONSE)
        response_with_wrong_source["source"] = "developer"
        mock_client.complete.return_value = json.dumps(response_with_wrong_source)

        gen = ExtractionPlanGenerator(llm_client=mock_client)
        plan = await gen.generate(
            url="https://example.com/products",
            objective="Test",
            content="<html><body>test</body></html>",
        )
        assert plan.source == "llm"

    @pytest.mark.asyncio
    async def test_generate_with_code_fence_response(self) -> None:
        """generate() handles LLM responses wrapped in markdown code fences."""
        mock_client = AsyncMock()
        mock_client.complete.return_value = f"```json\n{VALID_PLAN_RESPONSE}\n```"

        gen = ExtractionPlanGenerator(llm_client=mock_client)
        plan = await gen.generate(
            url="https://example.com/products",
            objective="Extract products",
            content=SAMPLE_HTML,
        )
        assert isinstance(plan, ExtractionPlan)

    @pytest.mark.asyncio
    async def test_generate_raises_on_invalid_json(self) -> None:
        """generate() raises ValueError when LLM returns non-JSON."""
        mock_client = AsyncMock()
        mock_client.complete.return_value = "This is not JSON at all."

        gen = ExtractionPlanGenerator(llm_client=mock_client)
        with pytest.raises(ValueError, match="Failed to parse LLM response"):
            await gen.generate(
                url="https://example.com/products",
                objective="Test",
                content=SAMPLE_HTML,
            )

    @pytest.mark.asyncio
    async def test_generate_uses_fallback_url(self) -> None:
        """generate() fills in url from parameter if LLM omits it."""
        mock_client = AsyncMock()
        response_without_url = json.loads(VALID_PLAN_RESPONSE)
        del response_without_url["url"]
        mock_client.complete.return_value = json.dumps(response_without_url)

        gen = ExtractionPlanGenerator(llm_client=mock_client)
        plan = await gen.generate(
            url="https://example.com/products",
            objective="Extract products",
            content=SAMPLE_HTML,
        )
        assert plan.url == "https://example.com/products"

    @pytest.mark.asyncio
    async def test_generate_with_hints(self) -> None:
        """generate() passes hints to the LLM prompt."""
        mock_client = AsyncMock()
        mock_client.complete.return_value = VALID_PLAN_RESPONSE
        hints = {"focus": "price"}

        gen = ExtractionPlanGenerator(llm_client=mock_client)
        plan = await gen.generate(
            url="https://example.com/products",
            objective="Test",
            content=SAMPLE_HTML,
            hints=hints,
        )
        # Verify the client was called with a prompt containing the hints
        call_args = mock_client.complete.call_args[0][0]
        assert "price" in call_args


class TestExtractionPlanGeneratorCleanHTML:
    """Tests for ExtractionPlanGenerator._clean_html_content()."""

    def test_removes_script_and_style_tags(self) -> None:
        """_clean_html_content() strips script and style tags."""
        gen = ExtractionPlanGenerator(llm_client=None)
        result = gen._clean_html_content(SAMPLE_HTML)
        assert "<script>" not in result
        assert "<style>" not in result
        assert "Widget A" in result

    def test_truncates_to_max_chars(self) -> None:
        """_clean_html_content() truncates output to max_chars."""
        gen = ExtractionPlanGenerator(llm_client=None)
        long_html = "<body>" + "x" * 50000 + "</body>"
        result = gen._clean_html_content(long_html, max_chars=1000)
        assert len(result) <= 1000

    def test_extracts_main_section(self) -> None:
        """_clean_html_content() prefers <main> over full <body>."""
        html = "<html><body><aside>ignore</aside><main><p>keep this</p></main></body></html>"
        gen = ExtractionPlanGenerator(llm_client=None)
        result = gen._clean_html_content(html)
        assert "keep this" in result
