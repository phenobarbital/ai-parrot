"""Dual-path intent resolution for ontology graph RAG.

Resolves user queries into graph traversal intents using two paths:
    - Fast path (~0ms): keyword scan against trigger_intents.
    - LLM path (~200-800ms): structured output for ambiguous queries.
"""
from __future__ import annotations

import json as _json
import logging
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from .schema import MergedOntology, ResolvedIntent
from .validators import validate_aql

logger = logging.getLogger("Parrot.Ontology.Intent")


class IntentDecision(BaseModel):
    """Structured output from LLM intent classification.

    Args:
        action: Whether graph traversal is needed.
        pattern: Known pattern name, "dynamic", or None.
        aql: Dynamic AQL query (only when pattern="dynamic").
        suggested_post_action: Post-action hint from LLM.
    """

    action: Literal["graph_query", "vector_only"]
    pattern: str | None = None
    aql: str | None = None
    suggested_post_action: str | None = None

    model_config = ConfigDict(extra="ignore")


class OntologyIntentResolver:
    """Resolve user queries into graph traversal intents.

    Two resolution paths:

    **Fast path** (deterministic, ~0ms):
        Scans query for keywords matching ``trigger_intents`` in traversal
        patterns. If match found, immediately returns the predefined pattern.

    **LLM path** (~200-800ms):
        Sends query + ontology schema to LLM for classification using
        structured output. LLM either selects a known pattern or generates
        dynamic AQL.

    The fast path is tried first. If no match, the LLM path is used.
    If neither matches, returns ``vector_only``.

    Args:
        ontology: The merged ontology for this tenant.
        llm_client: LLM client for the LLM path (optional — fast path works without it).
    """

    def __init__(
        self,
        ontology: MergedOntology,
        llm_client: Any = None,
    ) -> None:
        self.ontology = ontology
        self.llm = llm_client
        self._schema_prompt = ontology.build_schema_prompt()

    async def resolve(
        self,
        query: str,
        user_context: dict[str, Any],
    ) -> ResolvedIntent:
        """Resolve a user query into an intent.

        Args:
            query: The user's natural language query.
            user_context: Session data (user_id, tenant, etc.) needed
                to populate AQL bind variables.

        Returns:
            ResolvedIntent indicating graph_query or vector_only.
        """
        # ── Fast Path ──
        fast = self._try_fast_path(query, user_context)
        if fast is not None:
            logger.debug("Fast path match for query: '%s'", query[:80])
            return fast

        # ── LLM Path ──
        if self.llm:
            llm_result = await self._try_llm_path(query, user_context)
            if llm_result is not None:
                logger.debug("LLM path match for query: '%s'", query[:80])
                return llm_result

        # ── Fallback ──
        logger.debug("No ontology match for query: '%s'", query[:80])
        return ResolvedIntent(action="vector_only")

    def _try_fast_path(
        self,
        query: str,
        user_context: dict[str, Any],
    ) -> ResolvedIntent | None:
        """Try fast-path keyword matching against trigger_intents.

        Args:
            query: User query.
            user_context: Session context for bind vars.

        Returns:
            ResolvedIntent if a match is found, None otherwise.
        """
        query_lower = query.lower()
        for pattern_name, pattern in self.ontology.traversal_patterns.items():
            for keyword in pattern.trigger_intents:
                if keyword.lower() in query_lower:
                    return ResolvedIntent(
                        action="graph_query",
                        pattern=pattern_name,
                        aql=pattern.query_template,
                        params={"user_id": user_context.get("user_id")},
                        collection_binds=self._build_collection_binds(),
                        post_action=pattern.post_action,
                        post_query=pattern.post_query,
                        source="fast_path",
                    )
        return None

    async def _try_llm_path(
        self,
        query: str,
        user_context: dict[str, Any],
    ) -> ResolvedIntent | None:
        """Try LLM-based intent classification.

        Args:
            query: User query.
            user_context: Session context for bind vars.

        Returns:
            ResolvedIntent if the LLM identifies a graph query, None otherwise.
        """
        prompt = self._build_intent_prompt()

        try:
            response = await self.llm.completion(
                f"{prompt}\n\nUser query: {query}"
            )
            output = getattr(response, "output", str(response))

            # Parse structured output
            if isinstance(output, str):
                # Try to extract JSON from the response
                try:
                    parsed = _json.loads(output)
                except _json.JSONDecodeError:
                    # Try to find JSON in the response
                    start = output.find("{")
                    end = output.rfind("}") + 1
                    if start >= 0 and end > start:
                        parsed = _json.loads(output[start:end])
                    else:
                        return None
            else:
                parsed = output

            decision = IntentDecision.model_validate(parsed)

            if decision.action == "vector_only":
                return None

            if decision.action == "graph_query":
                if decision.pattern and decision.pattern != "dynamic":
                    # LLM selected a known pattern
                    pattern = self.ontology.traversal_patterns.get(
                        decision.pattern
                    )
                    if pattern:
                        return ResolvedIntent(
                            action="graph_query",
                            pattern=decision.pattern,
                            aql=pattern.query_template,
                            params={"user_id": user_context.get("user_id")},
                            collection_binds=self._build_collection_binds(),
                            post_action=pattern.post_action,
                            post_query=pattern.post_query,
                            source="llm",
                        )

                elif decision.aql:
                    # LLM generated dynamic AQL — must validate
                    validated = await validate_aql(decision.aql)
                    return ResolvedIntent(
                        action="graph_query",
                        pattern="dynamic",
                        aql=validated,
                        params={"user_id": user_context.get("user_id")},
                        collection_binds=self._build_collection_binds(),
                        post_action=decision.suggested_post_action or "none",
                        source="llm_dynamic",
                    )

        except Exception as e:
            logger.warning("LLM intent resolution failed: %s", e)

        return None

    def _build_collection_binds(self) -> dict[str, str]:
        """Build @@collection bind variables from the ontology.

        Returns:
            Dict mapping @@collection names to actual collection names.
        """
        binds: dict[str, str] = {}
        for entity in self.ontology.entities.values():
            if entity.collection:
                binds[f"@{entity.collection}"] = entity.collection
        for relation in self.ontology.relations.values():
            binds[f"@{relation.edge_collection}"] = relation.edge_collection
        return binds

    def _build_intent_prompt(self) -> str:
        """Build the system prompt for LLM-based intent detection.

        Returns:
            System prompt string with ontology schema and instructions.
        """
        return (
            "You have access to an ontology graph with the following structure:\n\n"
            f"{self._schema_prompt}\n\n"
            "Given a user query, determine if it requires graph traversal to "
            "answer accurately.\n\n"
            "Rules:\n"
            "- If the query asks about relationships between entities (who reports "
            "to whom, what project someone is on, what portal to use), it needs "
            "graph traversal.\n"
            "- If the query asks for general information that can be found via text "
            "search (how to use a tool, documentation, procedures), it's vector-only.\n"
            "- If you can match the query to a known traversal pattern, use that "
            "pattern name.\n"
            "- If the query needs graph traversal but doesn't match a known pattern, "
            "generate a read-only AQL query using the available collections.\n\n"
            'Respond with a JSON object: {"action": "graph_query" or "vector_only", '
            '"pattern": "<pattern_name>" or "dynamic" or null, '
            '"aql": "<AQL query>" or null, '
            '"suggested_post_action": "vector_search" or "tool_call" or "none" or null}'
        )
