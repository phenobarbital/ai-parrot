"""
RecallProcessor — Post-extraction LLM recall for rag_text generation and gap-filling.

After mechanical extraction has produced a list of ``ExtractedEntity`` objects,
RecallProcessor makes a single LLM call to:
  1. Generate natural language ``rag_text`` for each entity
  2. Fill missing field values from original page content
  3. (Optionally flag potentially missed entities — logged, not surfaced)
"""
from __future__ import annotations

import json
import logging
from typing import Any, List

from bs4 import BeautifulSoup

from .extraction_models import ExtractedEntity, ExtractionPlan
from .plan_generator import _strip_code_fences, _extract_json_object


RECALL_PROMPT = """\
You are a data enrichment expert. Below are entities extracted from a web page.
Your job is to:
1. Generate a natural language rag_text sentence for each entity (information-dense, self-contained)
2. Fill any null/empty fields if the data is visible in the HTML context
3. Note if any expected entities appear to be missing

EXTRACTED ENTITIES (JSON):
{entities_json}

ENTITY DEFINITIONS (what was expected):
{entity_definitions}

HTML CONTEXT (sections matching entity selectors):
{html_context}

Respond with a JSON object in this exact format:
{{
  "entities": [
    {{
      "index": 0,
      "rag_text": "Natural language description of entity 0",
      "filled_fields": {{"field_name": "value"}}
    }},
    ...
  ]
}}

Rules:
- rag_text should be a complete, self-contained sentence with all key information
- filled_fields should only include fields that were null/empty and you found in the HTML
- Keep the same order as the input entities (use index to match)
"""


class RecallProcessor:
    """Post-extraction LLM recall for rag_text generation and gap-filling.

    Makes a single LLM call after mechanical extraction to:
    1. Generate natural language rag_text for each entity
    2. Fill missing field values from original page content
    3. Flag potentially missed entities (logged at WARNING level)

    If the LLM call or response parsing fails, the original entities are
    returned unchanged so the pipeline can continue gracefully.

    The LLM client must support ``async def complete(prompt: str) -> str``.

    Args:
        llm_client: Any object with an async ``complete(prompt)`` method.
    """

    def __init__(self, llm_client: Any) -> None:
        self._client = llm_client
        self.logger = logging.getLogger(__name__)

    async def recall(
        self,
        entities: List[ExtractedEntity],
        page_html: str,
        extraction_plan: ExtractionPlan,
        url: str,
    ) -> List[ExtractedEntity]:
        """Enrich extracted entities with rag_text and gap-filling.

        Args:
            entities: List of extracted entities from mechanical extraction.
            page_html: Raw HTML of the source page.
            extraction_plan: The ExtractionPlan used for extraction.
            url: Source URL (used for logging).

        Returns:
            Enriched list of ExtractedEntity with rag_text populated.
            Returns the original list on LLM/parse failure.
        """
        if not entities:
            return entities

        context = self._prepare_html_context(page_html, extraction_plan)
        prompt = self._build_recall_prompt(entities, context, extraction_plan)

        try:
            raw = await self._client.complete(prompt)
            return self._parse_recall_response(raw, entities)
        except Exception as exc:
            self.logger.warning("Recall failed, returning original entities: %s", exc)
            return entities

    def _prepare_html_context(self, page_html: str, plan: ExtractionPlan) -> str:
        """Extract HTML sections matching plan selectors + context window.

        Selects up to 10 container elements per entity spec.  Falls back to
        the main/article/body element if no containers match.  Truncates
        to ~8K characters to stay within LLM context limits.

        Args:
            page_html: Raw HTML of the page.
            plan: ExtractionPlan with entity selectors.

        Returns:
            Relevant HTML sections as a string, limited to ~8K chars.
        """
        soup = BeautifulSoup(page_html, "html.parser")
        sections: List[str] = []

        for entity_spec in plan.entities:
            if entity_spec.container_selector:
                try:
                    containers = soup.select(entity_spec.container_selector)
                    for container in containers[:10]:  # limit to 10 containers
                        sections.append(str(container))
                except Exception:
                    pass

        # Fall back to main/article/body if no selectors matched
        if not sections:
            main = soup.find("main") or soup.find("article") or soup.find("body")
            if main:
                sections.append(str(main)[:4000])

        return "\n".join(sections)[:8000]

    def _build_recall_prompt(
        self,
        entities: List[ExtractedEntity],
        html_context: str,
        plan: ExtractionPlan,
    ) -> str:
        """Build the LLM recall prompt.

        Args:
            entities: Extracted entities to enrich.
            html_context: Relevant HTML sections.
            plan: ExtractionPlan with entity definitions.

        Returns:
            Formatted prompt string.
        """
        entities_json = json.dumps(
            [e.model_dump() for e in entities],
            indent=2,
            default=str,
        )
        entity_defs = json.dumps(
            [
                {
                    "entity_type": e.entity_type,
                    "description": e.description,
                    "fields": [
                        {"name": f.name, "description": f.description}
                        for f in e.fields
                    ],
                }
                for e in plan.entities
            ],
            indent=2,
        )
        return RECALL_PROMPT.format(
            entities_json=entities_json,
            entity_definitions=entity_defs,
            html_context=html_context,
        )

    def _parse_recall_response(
        self,
        raw: str,
        original_entities: List[ExtractedEntity],
    ) -> List[ExtractedEntity]:
        """Parse LLM recall response and merge into entities.

        Applies rag_text and filled_fields from each entry in the LLM response
        to the corresponding entity by index.  Returns originals on parse failure.

        Args:
            raw: Raw LLM response.
            original_entities: Original entity list to enrich.

        Returns:
            Enriched entities with rag_text populated. Returns originals on parse failure.
        """
        try:
            cleaned = _strip_code_fences(raw)
            json_str = _extract_json_object(cleaned)
            data = json.loads(json_str)
            enriched_list = data.get("entities", [])
        except (json.JSONDecodeError, ValueError) as exc:
            self.logger.warning("Failed to parse recall response: %s", exc)
            return original_entities

        # Build a copy of entities to enrich
        result = [e.model_copy() for e in original_entities]

        for enriched in enriched_list:
            idx = enriched.get("index", -1)
            if not isinstance(idx, int) or idx < 0 or idx >= len(result):
                continue

            rag_text = enriched.get("rag_text", "")
            if rag_text:
                result[idx].rag_text = rag_text

            filled_fields = enriched.get("filled_fields", {})
            if isinstance(filled_fields, dict):
                result[idx].fields.update(filled_fields)

        return result
