"""Tests for extraction_models.py — ExtractionPlan data models."""
from __future__ import annotations

import pytest

from parrot_tools.scraping.extraction_models import (
    EntityFieldSpec,
    EntitySpec,
    ExtractionPlan,
    ExtractedEntity,
    ExtractionResult,
)
from parrot_tools.scraping.plan import ScrapingPlan


# ---------------------------------------------------------------------------
# TestEntityFieldSpec
# ---------------------------------------------------------------------------

class TestEntityFieldSpec:
    """Tests for EntityFieldSpec model."""

    def test_defaults(self) -> None:
        """EntityFieldSpec has correct default values."""
        spec = EntityFieldSpec(name="price", description="Product price")
        assert spec.field_type == "text"
        assert spec.required is True
        assert spec.selector is None
        assert spec.selector_type == "css"
        assert spec.extract_from == "text"
        assert spec.attribute is None

    def test_all_field_types(self) -> None:
        """EntityFieldSpec accepts all supported field_type values."""
        for field_type in ("text", "number", "currency", "url", "boolean", "list"):
            spec = EntityFieldSpec(
                name="field",
                description="Some field",
                field_type=field_type,
            )
            assert spec.field_type == field_type

    def test_with_selector(self) -> None:
        """EntityFieldSpec stores selector and attribute correctly."""
        spec = EntityFieldSpec(
            name="image",
            description="Product image",
            field_type="url",
            selector="img.product-img",
            selector_type="css",
            extract_from="attribute",
            attribute="src",
        )
        assert spec.selector == "img.product-img"
        assert spec.attribute == "src"
        assert spec.extract_from == "attribute"


# ---------------------------------------------------------------------------
# TestExtractionPlan
# ---------------------------------------------------------------------------

class TestExtractionPlan:
    """Tests for ExtractionPlan model."""

    def _make_plan(self, **kwargs) -> ExtractionPlan:
        defaults = {
            "url": "https://example.com/products",
            "objective": "Extract product listings",
            "entities": [],
        }
        defaults.update(kwargs)
        return ExtractionPlan(**defaults)

    def test_auto_fields(self) -> None:
        """model_post_init auto-populates domain, name, and fingerprint."""
        plan = self._make_plan()
        assert plan.domain == "example.com"
        assert plan.name == "example-com"
        assert len(plan.fingerprint) == 16

    def test_fingerprint_stable(self) -> None:
        """Same URL always produces the same fingerprint."""
        p1 = self._make_plan()
        p2 = self._make_plan()
        assert p1.fingerprint == p2.fingerprint

    def test_to_scraping_plan_no_selectors(self) -> None:
        """to_scraping_plan() with no entity selectors returns ScrapingPlan with None selectors."""
        entity = EntitySpec(
            entity_type="product",
            description="A product",
            fields=[
                EntityFieldSpec(name="name", description="Name", selector=None),
            ],
        )
        plan = self._make_plan(entities=[entity])
        sp = plan.to_scraping_plan()
        assert isinstance(sp, ScrapingPlan)
        assert sp.url == plan.url
        assert sp.selectors is None
        # Should have navigate + wait steps
        assert any(s["action"] == "navigate" for s in sp.steps)
        assert any(s["action"] == "wait" for s in sp.steps)

    def test_to_scraping_plan_with_selectors(self) -> None:
        """to_scraping_plan() translates field specs into selectors."""
        entity = EntitySpec(
            entity_type="product",
            description="A product",
            container_selector=".product-card",
            fields=[
                EntityFieldSpec(
                    name="title",
                    description="Product title",
                    selector="h2.title",
                ),
                EntityFieldSpec(
                    name="price",
                    description="Product price",
                    selector=".price",
                ),
            ],
        )
        plan = self._make_plan(entities=[entity])
        sp = plan.to_scraping_plan()
        assert sp.selectors is not None
        assert len(sp.selectors) == 2
        names = {s["name"] for s in sp.selectors}
        assert "product__title" in names
        assert "product__price" in names
        # Container selector should be prepended
        for sel in sp.selectors:
            assert sel["selector"].startswith(".product-card ")

    def test_to_scraping_plan_no_container(self) -> None:
        """to_scraping_plan() with no container_selector uses bare field selector."""
        entity = EntitySpec(
            entity_type="item",
            description="An item",
            container_selector=None,
            fields=[
                EntityFieldSpec(name="name", description="Name", selector=".item-name"),
            ],
        )
        plan = self._make_plan(entities=[entity])
        sp = plan.to_scraping_plan()
        assert sp.selectors is not None
        assert sp.selectors[0]["selector"] == ".item-name"

    def test_serialization_roundtrip(self) -> None:
        """ExtractionPlan survives model_dump / model_validate roundtrip."""
        entity = EntitySpec(
            entity_type="plan",
            description="A telecom plan",
            fields=[
                EntityFieldSpec(name="plan_name", description="Plan name"),
                EntityFieldSpec(name="monthly_price", description="Price", field_type="currency"),
            ],
        )
        original = ExtractionPlan(
            url="https://telecom.example.com/plans",
            objective="Extract prepaid plans",
            entities=[entity],
            page_category="telecom_prepaid",
        )
        data = original.model_dump()
        restored = ExtractionPlan.model_validate(data)
        assert restored.fingerprint == original.fingerprint
        assert restored.domain == original.domain
        assert len(restored.entities) == 1
        assert len(restored.entities[0].fields) == 2


# ---------------------------------------------------------------------------
# TestExtractedEntity
# ---------------------------------------------------------------------------

class TestExtractedEntity:
    """Tests for ExtractedEntity model."""

    def test_defaults(self) -> None:
        """ExtractedEntity has correct default values."""
        entity = ExtractedEntity(
            entity_type="product",
            fields={"name": "Widget"},
            source_url="https://example.com",
        )
        assert entity.confidence == 0.0
        assert entity.raw_text is None
        assert entity.rag_text == ""

    def test_rag_text_settable(self) -> None:
        """rag_text field is settable."""
        entity = ExtractedEntity(
            entity_type="product",
            fields={"name": "Widget"},
            source_url="https://example.com",
            rag_text="Widget is a product available at example.com",
        )
        assert "Widget" in entity.rag_text


# ---------------------------------------------------------------------------
# TestExtractionResult
# ---------------------------------------------------------------------------

class TestExtractionResult:
    """Tests for ExtractionResult model."""

    def test_defaults(self) -> None:
        """ExtractionResult has correct default values."""
        plan = ExtractionPlan(
            url="https://example.com",
            objective="Test",
            entities=[],
        )
        result = ExtractionResult(
            url="https://example.com",
            objective="Test",
            entities=[],
            plan_used=plan,
            extraction_strategy="hybrid",
        )
        assert result.success is True
        assert result.total_entities == 0
        assert result.error_message is None
        assert result.elapsed_seconds == 0.0
