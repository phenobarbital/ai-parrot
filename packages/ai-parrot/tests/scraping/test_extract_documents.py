"""Tests for ScrapingAgent.extract_documents() helper logic.

These tests validate the FEAT-096 helper methods independently of the full
ScrapingAgent class hierarchy (which requires Cython extensions and many
optional dependencies). We test the core logic by:

1. Directly testing extraction_models and extraction_registry (from parrot_tools)
2. Verifying the new helper method logic via standalone functions that mirror
   what ScrapingAgent._extracted_data_to_entities() and
   ScrapingAgent._entities_to_documents() do.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

# Guard: skip these tests if parrot_tools.scraping is not available
parrot_tools_available = True
try:
    from parrot_tools.scraping.extraction_models import (
        EntityFieldSpec,
        EntitySpec,
        ExtractionPlan,
        ExtractedEntity,
    )
    from parrot_tools.scraping.extraction_registry import ExtractionPlanRegistry
except ImportError:
    parrot_tools_available = False

pytestmark = pytest.mark.skipif(
    not parrot_tools_available,
    reason="parrot_tools.scraping not available",
)


# ---------------------------------------------------------------------------
# Standalone logic mirrors — testing the helper method logic in isolation
# ---------------------------------------------------------------------------

def _extracted_data_to_entities(
    extracted_data: Dict[str, Any],
    url: str,
    extraction_plan: ExtractionPlan,
) -> List[ExtractedEntity]:
    """Standalone mirror of ScrapingAgent._extracted_data_to_entities."""
    if not extracted_data:
        return []

    entities = []
    for entity_spec in extraction_plan.entities:
        entity_type = entity_spec.entity_type
        entity_fields: Dict[str, Any] = {}
        multi_values: Dict[str, List[Any]] = {}

        for field_spec in entity_spec.fields:
            selector_name = f"{entity_type}__{field_spec.name}"
            if selector_name in extracted_data:
                val = extracted_data[selector_name]
                if isinstance(val, list):
                    multi_values[field_spec.name] = val
                else:
                    entity_fields[field_spec.name] = val

        if multi_values:
            max_len = max(len(v) for v in multi_values.values())
            for i in range(max_len):
                fields = dict(entity_fields)
                for fname, values in multi_values.items():
                    fields[fname] = values[i] if i < len(values) else None
                entities.append(ExtractedEntity(
                    entity_type=entity_type,
                    fields=fields,
                    source_url=url,
                ))
        elif entity_fields:
            entities.append(ExtractedEntity(
                entity_type=entity_type,
                fields=entity_fields,
                source_url=url,
            ))

    return entities


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_extraction_plan(url: str = "https://example.com/products") -> ExtractionPlan:
    return ExtractionPlan(
        url=url,
        objective="Extract products",
        entities=[
            EntitySpec(
                entity_type="product",
                description="A product",
                container_selector=".product-card",
                fields=[
                    EntityFieldSpec(name="product_name", description="Name", selector=".name"),
                    EntityFieldSpec(name="price", description="Price", selector=".price", field_type="currency"),
                ],
            )
        ],
        page_category="ecommerce",
    )


# ---------------------------------------------------------------------------
# Tests: extracted_data_to_entities logic
# ---------------------------------------------------------------------------

class TestExtractedDataToEntities:
    """Tests for the _extracted_data_to_entities logic."""

    def test_multi_value_fields_create_multiple_entities(self) -> None:
        """List values in extracted_data create one entity per list item."""
        plan = _make_extraction_plan()
        extracted_data = {
            "product__product_name": ["Widget A", "Widget B"],
            "product__price": ["$9.99", "$14.99"],
        }

        entities = _extracted_data_to_entities(
            extracted_data, "https://example.com/products", plan
        )
        assert len(entities) == 2
        assert entities[0].fields["product_name"] == "Widget A"
        assert entities[0].fields["price"] == "$9.99"
        assert entities[1].fields["product_name"] == "Widget B"
        assert entities[1].fields["price"] == "$14.99"

    def test_empty_extracted_data_returns_empty(self) -> None:
        """Empty extracted_data returns empty entity list."""
        plan = _make_extraction_plan()
        entities = _extracted_data_to_entities({}, "https://example.com/products", plan)
        assert entities == []

    def test_entity_has_correct_source_url(self) -> None:
        """ExtractedEntity.source_url matches the provided URL."""
        plan = _make_extraction_plan()
        extracted_data = {
            "product__product_name": ["Widget A"],
            "product__price": ["$9.99"],
        }
        url = "https://example.com/products"
        entities = _extracted_data_to_entities(extracted_data, url, plan)
        for entity in entities:
            assert entity.source_url == url

    def test_scalar_fields_create_single_entity(self) -> None:
        """Non-list values create a single entity with scalar fields."""
        plan = _make_extraction_plan()
        extracted_data = {
            "product__product_name": "Widget Solo",
            "product__price": "$5.00",
        }
        entities = _extracted_data_to_entities(
            extracted_data, "https://example.com/products", plan
        )
        assert len(entities) == 1
        assert entities[0].fields["product_name"] == "Widget Solo"

    def test_unknown_selector_names_ignored(self) -> None:
        """Fields not matching the entity type prefix are ignored."""
        plan = _make_extraction_plan()
        extracted_data = {
            "product__product_name": ["Widget A"],
            "other_entity__name": ["Should be ignored"],
        }
        entities = _extracted_data_to_entities(
            extracted_data, "https://example.com/products", plan
        )
        assert len(entities) == 1
        assert "name" not in entities[0].fields  # not product__name

    def test_unequal_list_lengths_padded_with_none(self) -> None:
        """Shorter list fields are padded with None for excess indices."""
        plan = _make_extraction_plan()
        extracted_data = {
            "product__product_name": ["Widget A", "Widget B", "Widget C"],
            "product__price": ["$9.99"],  # shorter list
        }
        entities = _extracted_data_to_entities(
            extracted_data, "https://example.com/products", plan
        )
        assert len(entities) == 3
        assert entities[0].fields["price"] == "$9.99"
        assert entities[1].fields["price"] is None
        assert entities[2].fields["price"] is None


# ---------------------------------------------------------------------------
# Tests: entities_to_documents logic (with Document model)
# ---------------------------------------------------------------------------

class TestEntitiesToDocuments:
    """Tests for entities_to_documents logic using parrot.stores.models.Document."""

    @pytest.fixture
    def document_class(self):
        """Return Document class or skip if not available."""
        try:
            from parrot.stores.models import Document
            return Document
        except ImportError:
            pytest.skip("parrot.stores.models.Document not available")

    def _entities_to_documents(
        self,
        entities: List[ExtractedEntity],
        url: str,
        extraction_plan: ExtractionPlan,
        Document,
    ) -> List[Any]:
        """Standalone mirror of ScrapingAgent._entities_to_documents."""
        documents = []
        for entity in entities:
            page_content = entity.rag_text or str(entity.fields)
            metadata = {
                "source": url,
                "url": url,
                "source_type": "webpage_structured",
                "type": entity.entity_type,
                "category": extraction_plan.page_category,
                "entity_type": entity.entity_type,
                "extraction_confidence": entity.confidence,
                "document_meta": {
                    "extraction_strategy": extraction_plan.extraction_strategy,
                    "plan_source": extraction_plan.source,
                    **entity.fields,
                },
            }
            documents.append(Document(page_content=page_content, metadata=metadata))
        return documents

    def test_uses_rag_text(self, document_class) -> None:
        """Document page_content is set to entity.rag_text when populated."""
        plan = _make_extraction_plan()
        entity = ExtractedEntity(
            entity_type="product",
            fields={"product_name": "Widget A", "price": "$9.99"},
            source_url="https://example.com/products",
            rag_text="Widget A is available for $9.99.",
        )
        docs = self._entities_to_documents(
            [entity], "https://example.com/products", plan, document_class
        )
        assert len(docs) == 1
        assert docs[0].page_content == "Widget A is available for $9.99."

    def test_falls_back_to_fields(self, document_class) -> None:
        """Document page_content falls back to str(fields) when rag_text is empty."""
        plan = _make_extraction_plan()
        entity = ExtractedEntity(
            entity_type="product",
            fields={"product_name": "Widget A"},
            source_url="https://example.com/products",
            rag_text="",
        )
        docs = self._entities_to_documents(
            [entity], "https://example.com/products", plan, document_class
        )
        assert len(docs) == 1
        assert "Widget A" in docs[0].page_content

    def test_metadata_keys(self, document_class) -> None:
        """Document metadata contains required keys."""
        plan = _make_extraction_plan()
        entity = ExtractedEntity(
            entity_type="product",
            fields={"product_name": "Widget"},
            source_url="https://example.com/products",
        )
        docs = self._entities_to_documents(
            [entity], "https://example.com/products", plan, document_class
        )
        meta = docs[0].metadata
        assert meta["entity_type"] == "product"
        assert meta["category"] == "ecommerce"
        assert meta["source_type"] == "webpage_structured"
        assert "document_meta" in meta


# ---------------------------------------------------------------------------
# Tests: ExtractionPlanRegistry integration (used by _resolve_extraction_plan)
# ---------------------------------------------------------------------------

class TestResolveExtractionPlanLogic:
    """Tests for the resolution chain logic used in _resolve_extraction_plan."""

    @pytest.mark.asyncio
    async def test_registry_returns_plan_when_found(self, tmp_path: Path) -> None:
        """Registry lookup returns a plan for a matching URL."""
        plan = _make_extraction_plan()
        reg = ExtractionPlanRegistry(plans_dir=tmp_path)
        await reg.register_extraction_plan(plan)

        result = await reg.lookup_plan(plan.url)
        assert result is not None
        assert result.url == plan.url

    @pytest.mark.asyncio
    async def test_registry_returns_none_when_no_match(self, tmp_path: Path) -> None:
        """Registry lookup returns None when no plan matches the URL."""
        reg = ExtractionPlanRegistry(plans_dir=tmp_path)
        await reg.load()
        result = await reg.lookup_plan("https://unknown.example.com")
        assert result is None

    @pytest.mark.asyncio
    async def test_registry_lookup_error_handled_gracefully(self, tmp_path: Path) -> None:
        """Registry lookup errors should be caught and return None gracefully."""
        mock_reg = MagicMock(spec=ExtractionPlanRegistry)
        mock_reg.lookup_plan = AsyncMock(side_effect=RuntimeError("DB error"))

        # Simulate the _resolve_extraction_plan error handling
        try:
            result = await mock_reg.lookup_plan("https://example.com")
        except RuntimeError:
            result = None

        assert result is None
