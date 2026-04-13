"""
ExtractionPlan Data Models.

Pydantic v2 models for schema-driven extraction: what to extract (entities,
fields, selectors) and result containers for extracted data.

ExtractionPlan is a richer cousin of ScrapingPlan — it describes WHAT to
extract (entity types, field specs) rather than HOW to navigate (steps).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from .plan import ScrapingPlan, _normalize_url, _compute_fingerprint, _sanitize_domain


class EntityFieldSpec(BaseModel):
    """Specification for a single field within an entity.

    Args:
        name: Snake_case name for this field (e.g. ``plan_name``).
        description: Human-readable description of what this field contains.
        field_type: Type of value expected (text, number, currency, url, boolean, list).
        required: Whether this field must be present for the entity to be valid.
        selector: CSS or XPath selector to locate this field's element.
        selector_type: Whether ``selector`` is ``css`` or ``xpath``.
        extract_from: What to extract from the element: ``text``, ``attribute``, or ``html``.
        attribute: HTML attribute name to extract when ``extract_from`` is ``attribute``.
    """

    name: str
    description: str
    field_type: str = "text"  # text | number | currency | url | boolean | list
    required: bool = True
    selector: Optional[str] = None
    selector_type: str = "css"  # css | xpath
    extract_from: str = "text"  # text | attribute | html
    attribute: Optional[str] = None


class EntitySpec(BaseModel):
    """Specification for one type of entity to extract.

    Args:
        entity_type: Identifier for this entity type (e.g. ``product``, ``plan``).
        description: Human-readable description of what this entity represents.
        fields: List of field specs that make up this entity.
        repeating: Whether multiple instances of this entity appear on the page.
        container_selector: CSS/XPath selector wrapping one entity instance.
        container_selector_type: Whether ``container_selector`` is ``css`` or ``xpath``.
    """

    entity_type: str
    description: str
    fields: List[EntityFieldSpec]
    repeating: bool = True
    container_selector: Optional[str] = None
    container_selector_type: str = "css"


class ExtractionPlan(BaseModel):
    """Rich schema describing WHAT to extract — translates to ScrapingPlan for execution.

    Auto-populates ``domain``, ``name``, and ``fingerprint`` from the URL in
    ``model_post_init``, matching the behaviour of ``ScrapingPlan``.

    Args:
        name: Human-readable plan name; auto-derived from domain if not given.
        url: Target URL for extraction.
        domain: Netloc of the target URL; auto-populated from ``url``.
        objective: Natural language description of extraction goal.
        fingerprint: 16-char SHA-256 prefix of the normalised URL; auto-computed.
        entities: Entity type specs defining what to extract.
        ignore_sections: CSS selectors for page sections to skip.
        page_category: Descriptive category label (e.g. ``telecom_prepaid_plans``).
        extraction_strategy: How to extract: ``hybrid``, ``selector``, or ``llm``.
        source: Origin of the plan: ``llm``, ``developer``, or ``user``.
        version: Numeric plan version, incremented on updates.
        confidence: LLM confidence score (0.0–1.0) when source is ``llm``.
        created_at: ISO-8601 timestamp of plan creation.
        last_used_at: ISO-8601 timestamp of last use.
        success_count: Cumulative successful extraction count.
        failure_count: Cumulative failed extraction count.
    """

    name: Optional[str] = None
    url: str
    domain: str = ""
    objective: str
    fingerprint: str = ""
    entities: List[EntitySpec]
    ignore_sections: List[str] = Field(default_factory=list)
    page_category: str = ""
    extraction_strategy: str = "hybrid"
    source: str = "llm"
    version: int = 1
    confidence: float = 0.0
    created_at: Optional[str] = None
    last_used_at: Optional[str] = None
    success_count: int = 0
    failure_count: int = 0

    def model_post_init(self, __context: Any) -> None:
        """Auto-populate domain, name, and fingerprint from URL."""
        parsed = urlparse(self.url)
        if not self.domain:
            self.domain = parsed.netloc
        if self.name is None:
            self.name = _sanitize_domain(self.domain)
        if not self.fingerprint:
            self.fingerprint = _compute_fingerprint(_normalize_url(self.url))

    def to_scraping_plan(self) -> ScrapingPlan:
        """Translate entity/field specs into a ScrapingPlan for mechanical execution.

        Builds navigation steps (navigate + wait) and derives selector entries
        from each ``EntityFieldSpec`` that has a ``selector`` defined.

        Returns:
            ScrapingPlan with navigate steps and selectors derived from entity definitions.
        """
        steps: List[Dict[str, Any]] = [
            {"action": "navigate", "url": self.url},
            {"action": "wait", "condition": "body", "condition_type": "selector"},
        ]
        selectors: List[Dict[str, Any]] = []

        for entity in self.entities:
            for field in entity.fields:
                if field.selector is None:
                    continue
                # Compose selector with container if available
                if entity.container_selector:
                    composed = f"{entity.container_selector} {field.selector}"
                else:
                    composed = field.selector
                selectors.append({
                    "name": f"{entity.entity_type}__{field.name}",
                    "selector": composed,
                    "selector_type": field.selector_type,
                    "extract_type": field.extract_from,
                    "multiple": entity.repeating,
                    "attribute": field.attribute,
                })

        return ScrapingPlan(
            url=self.url,
            objective=self.objective,
            steps=steps,
            selectors=selectors if selectors else None,
            source="extraction_plan",
            created_at=datetime.now(timezone.utc),
        )


class ExtractedEntity(BaseModel):
    """A single structured entity extracted from a page.

    Args:
        entity_type: Type label matching the EntitySpec that produced this entity.
        fields: Mapping of field name to extracted value.
        source_url: URL of the page this entity was extracted from.
        confidence: Confidence score (0.0–1.0) for this extraction.
        raw_text: Raw text content associated with this entity.
        rag_text: Natural language sentence for RAG indexing, populated by RecallProcessor.
    """

    entity_type: str
    fields: Dict[str, Any]
    source_url: str
    confidence: float = 0.0
    raw_text: Optional[str] = None
    rag_text: str = ""


class ExtractionResult(BaseModel):
    """Complete result from an extraction run.

    Args:
        url: Target URL that was scraped.
        objective: Extraction goal.
        entities: All entities extracted from the page.
        plan_used: The ExtractionPlan that governed extraction.
        extraction_strategy: Strategy used (hybrid, selector, llm).
        total_entities: Total count of extracted entities.
        success: Whether the extraction succeeded.
        error_message: Error details if ``success`` is False.
        elapsed_seconds: Wall-clock time for the extraction run.
    """

    url: str
    objective: str
    entities: List[ExtractedEntity]
    plan_used: ExtractionPlan
    extraction_strategy: str
    total_entities: int = 0
    success: bool = True
    error_message: Optional[str] = None
    elapsed_seconds: float = 0.0
