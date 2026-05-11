"""Entity extraction and resolution for the ontology pipeline (FEAT-158).

Converts natural-language entity mentions (e.g., "Jesús") to graph ``_id``s
using one of four pluggable strategies:

- ``exact_id_match``: exact AQL filter on the entity's key field.
- ``fuzzy_name_match``: case-insensitive LIKE filter with AQL.
- ``ai_assisted``: fuzzy shortlist + LLM ranking (requires ``llm_client``).
- ``hybrid_concept_match``: reserved for FEAT-concept-document-authority;
  raises ``NotImplementedError`` with a clear message.

Typed exceptions (``EntityAmbiguityError``, ``EntityNotFoundError``) are
raised so the Mixin can translate them to appropriate ``ContextEnvelope`` states.

**Default-deny on ambiguity**: when ``ambiguity_strategy=ask_user`` or ``fail``,
multiple candidates always raise ``EntityAmbiguityError``.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from .graph_store import OntologyGraphStore
from .schema import EntityExtractionRule, MergedOntology, TraversalPattern


# ---------------------------------------------------------------------------
# Typed exceptions
# ---------------------------------------------------------------------------


class EntityAmbiguityError(Exception):
    """Raised when multiple candidates match and the strategy is ``ask_user``
    or ``fail``.

    Attributes:
        rule_name: Name of the entity extraction rule that triggered this error.
        mention: The extracted mention string.
        candidates: List of candidate dicts from the graph (each has ``_id``).
    """

    def __init__(
        self,
        rule_name: str,
        mention: str,
        candidates: list[dict[str, Any]],
    ) -> None:
        super().__init__(
            f"Ambiguous entity for rule '{rule_name}': "
            f"mention='{mention}', {len(candidates)} candidates"
        )
        self.rule_name = rule_name
        self.mention = mention
        self.candidates = candidates


class EntityNotFoundError(Exception):
    """Raised when no candidates match a required entity extraction rule.

    Attributes:
        rule_name: Name of the entity extraction rule that triggered this error.
        mention: The extracted mention string, or ``None`` if extraction failed.
    """

    def __init__(
        self,
        rule_name: str,
        mention: str | None,
    ) -> None:
        super().__init__(
            f"Entity not found for rule '{rule_name}': mention='{mention}'"
        )
        self.rule_name = rule_name
        self.mention = mention


# ---------------------------------------------------------------------------
# EntityResolver
# ---------------------------------------------------------------------------


class EntityResolver:
    """Extracts named-entity mentions from a query and resolves them to graph
    ``_id``s using per-rule strategies.

    Designed to sit between ``OntologyIntentResolver.resolve()`` and
    ``OntologyGraphStore.execute_traversal()`` in the ``ontology_process``
    pipeline.

    Args:
        graph_store: ArangoDB wrapper for entity-lookup traversals.
        ontology: Merged ontology to discover entity collection names.
        llm_client: Optional LLM client; required for ``ai_assisted`` resolver.
    """

    def __init__(
        self,
        graph_store: OntologyGraphStore,
        ontology: MergedOntology,
        llm_client: Any | None = None,
    ) -> None:
        self._graph_store = graph_store
        self._ontology = ontology
        self._llm = llm_client
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def extract_and_resolve(
        self,
        pattern: TraversalPattern,
        query: str,
        user_context: dict[str, Any],
        tenant_id: str,
    ) -> dict[str, str]:
        """Extract entity mentions from ``query`` and resolve each to a graph ``_id``.

        For each rule in ``pattern.entity_extraction``:
        1. Extract the mention from the query (heuristic or LLM-assisted).
        2. Resolve candidates via the rule's strategy.
        3. Apply ambiguity handling or pick logic.
        4. Return the winning ``_id``.

        AQL bind-variable key convention: a rule named ``target_employee``
        produces a bind variable ``@target_employee_id`` in the Mixin's AQL.

        Args:
            pattern: The matched ``TraversalPattern`` with ``entity_extraction``.
            query: The user's natural-language query.
            user_context: Session data (``user_id``, ``department``,
                ``manager_id``, etc.).
            tenant_id: Tenant identifier for graph-store scoping.

        Returns:
            Mapping of ``rule_name`` → resolved graph ``_id``.

        Raises:
            EntityAmbiguityError: When multiple candidates match and the rule's
                ``ambiguity_strategy`` is ``ask_user`` or ``fail``, or when
                ``use_context`` re-ranking still yields multiple equally-ranked
                candidates.
            EntityNotFoundError: When no candidates match and ``rule.required``
                is ``True``.
            NotImplementedError: When ``rule.resolver == "hybrid_concept_match"``
                (reserved for FEAT-concept-document-authority).
        """
        resolved: dict[str, str] = {}

        for rule_name, rule in pattern.entity_extraction.items():
            # Step 1: mention extraction
            mention = self._extract_mention(rule_name, rule, pattern, query)

            if mention is None:
                if rule.required:
                    raise EntityNotFoundError(rule_name=rule_name, mention=None)
                self.logger.debug(
                    "No mention extracted for optional rule '%s'; skipping.",
                    rule_name,
                )
                continue

            # Step 2: candidate resolution (may raise NotImplementedError)
            candidates = await self._resolve(rule, mention, user_context, tenant_id)

            if not candidates:
                if rule.required:
                    raise EntityNotFoundError(rule_name=rule_name, mention=mention)
                self.logger.debug(
                    "No candidates for optional rule '%s' (mention='%s'); skipping.",
                    rule_name, mention,
                )
                continue

            # Step 3: pick / ambiguity handling
            chosen_id = self._pick(rule, rule_name, mention, candidates, user_context)
            resolved[rule_name] = chosen_id

        return resolved

    # ------------------------------------------------------------------
    # Mention extraction
    # ------------------------------------------------------------------

    def _extract_mention(
        self,
        rule_name: str,
        rule: EntityExtractionRule,
        pattern: TraversalPattern,
        query: str,
    ) -> str | None:
        """Heuristic mention extractor.

        Strips any matched trigger phrase from the query, then picks the first
        run of capitalized tokens in the residual as the mention candidate.

        Args:
            rule_name: Name of the current rule (for logging).
            rule: The entity extraction rule.
            pattern: The traversal pattern (for trigger_intents).
            query: The user's query string.

        Returns:
            Extracted mention string, or ``None`` if nothing found.
        """
        residual = query
        for trigger in (pattern.trigger_intents or []):
            pattern_re = re.compile(re.escape(trigger), re.IGNORECASE)
            residual = pattern_re.sub("", residual).strip()

        # Pick the first run of capitalized tokens (proper nouns)
        cap_tokens = re.findall(r"\b[A-ZÁÉÍÓÚÑ][a-záéíóúñA-ZÁÉÍÓÚÑ]*(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñA-ZÁÉÍÓÚÑ]*)*", residual)
        if cap_tokens:
            return cap_tokens[0].strip()

        # Fallback: if residual is non-empty after stripping punctuation/spaces,
        # try the whole residual as the mention
        residual_clean = re.sub(r"[^\w\s]", "", residual).strip()
        if residual_clean:
            return residual_clean

        self.logger.debug("Could not extract mention for rule '%s'", rule_name)
        return None

    # ------------------------------------------------------------------
    # Strategy dispatch
    # ------------------------------------------------------------------

    async def _resolve(
        self,
        rule: EntityExtractionRule,
        mention: str,
        user_context: dict[str, Any],
        tenant_id: str,
    ) -> list[dict[str, Any]]:
        """Dispatch to the appropriate resolution strategy.

        Args:
            rule: The entity extraction rule.
            mention: Extracted mention string.
            user_context: Session data.
            tenant_id: Tenant identifier.

        Returns:
            List of candidate dicts from the graph.

        Raises:
            NotImplementedError: For ``hybrid_concept_match``.
        """
        if rule.resolver == "hybrid_concept_match":
            raise NotImplementedError(
                "hybrid_concept_match is reserved for FEAT-concept-document-authority "
                "and is not yet implemented. Configure a different resolver strategy "
                "until that feature is merged."
            )

        if rule.resolver == "exact_id_match":
            return await self._exact_id_match(rule, mention, user_context, tenant_id)
        if rule.resolver == "fuzzy_name_match":
            return await self._fuzzy_name_match(rule, mention, user_context, tenant_id)
        if rule.resolver == "ai_assisted":
            return await self._ai_assisted(rule, mention, user_context, tenant_id)

        # Should never reach here — Pydantic guards the resolver literal
        raise ValueError(f"Unknown resolver strategy: {rule.resolver!r}")  # pragma: no cover

    # ------------------------------------------------------------------
    # Individual strategies
    # ------------------------------------------------------------------

    def _collection_for_type(self, entity_type: str) -> str:
        """Resolve an entity type name to its ArangoDB collection name.

        Falls back to the lower-cased type name if not found in the ontology.

        Args:
            entity_type: Ontology entity type (e.g. ``"Employee"``).

        Returns:
            ArangoDB collection name.
        """
        entity_def = self._ontology.entities.get(entity_type)
        if entity_def and entity_def.collection:
            return entity_def.collection
        return entity_type.lower()

    def _scope_filter(
        self,
        rule: EntityExtractionRule,
        user_context: dict[str, Any],
        bind_vars: dict[str, Any],
    ) -> str:
        """Build an additional AQL FILTER clause for scope filtering.

        Args:
            rule: The entity extraction rule.
            user_context: Session data containing ``department``.
            bind_vars: AQL bind-variable dict to extend in-place.

        Returns:
            AQL FILTER clause string (empty if no filter applies).
        """
        if rule.scope == "same_department":
            dept = user_context.get("department")
            if dept:
                bind_vars["user_department"] = dept
                return "FILTER e.department == @user_department"
            else:
                self.logger.debug(
                    "scope=same_department but user_context has no 'department'; "
                    "skipping scope filter."
                )
        return ""

    async def _exact_id_match(
        self,
        rule: EntityExtractionRule,
        mention: str,
        user_context: dict[str, Any],
        tenant_id: str,
    ) -> list[dict[str, Any]]:
        """Exact AQL match on the entity's key field.

        Args:
            rule: Entity extraction rule.
            mention: Mention string.
            user_context: Session data.
            tenant_id: Tenant identifier.

        Returns:
            List of matching candidate dicts (max 2 to detect accidental dupes).
        """
        from .schema import TenantContext

        collection = self._collection_for_type(rule.type)
        entity_def = self._ontology.entities.get(rule.type)
        key_field = (entity_def.key_field if entity_def else None) or "name"

        bind_vars: dict[str, Any] = {"mention": mention}
        scope_filter = self._scope_filter(rule, user_context, bind_vars)

        aql = (
            f"FOR e IN @@collection "
            f"FILTER e.{key_field} == @mention "
            f"{scope_filter} "
            f"LIMIT 2 RETURN e"
        )
        collection_binds = {"@collection": collection}

        ctx = TenantContext(
            tenant_id=tenant_id,
            arango_db=f"{tenant_id}_ontology",
            pgvector_schema=tenant_id,
            ontology=self._ontology,
        )
        return await self._graph_store.execute_traversal(
            ctx=ctx, aql=aql, bind_vars=bind_vars, collection_binds=collection_binds
        )

    async def _fuzzy_name_match(
        self,
        rule: EntityExtractionRule,
        mention: str,
        user_context: dict[str, Any],
        tenant_id: str,
    ) -> list[dict[str, Any]]:
        """Case-insensitive LIKE AQL match on the ``name`` field.

        Args:
            rule: Entity extraction rule.
            mention: Mention string.
            user_context: Session data.
            tenant_id: Tenant identifier.

        Returns:
            Up to 10 candidate dicts sorted by name length (shortest first).
        """
        from .schema import TenantContext

        collection = self._collection_for_type(rule.type)
        bind_vars: dict[str, Any] = {"mention": mention.lower()}
        scope_filter = self._scope_filter(rule, user_context, bind_vars)

        aql = (
            f"FOR e IN @@collection "
            f"FILTER LIKE(LOWER(e.name), CONCAT('%', @mention, '%')) "
            f"{scope_filter} "
            f"SORT LENGTH(e.name) ASC "
            f"LIMIT 10 RETURN e"
        )
        collection_binds = {"@collection": collection}

        ctx = TenantContext(
            tenant_id=tenant_id,
            arango_db=f"{tenant_id}_ontology",
            pgvector_schema=tenant_id,
            ontology=self._ontology,
        )
        return await self._graph_store.execute_traversal(
            ctx=ctx, aql=aql, bind_vars=bind_vars, collection_binds=collection_binds
        )

    async def _ai_assisted(
        self,
        rule: EntityExtractionRule,
        mention: str,
        user_context: dict[str, Any],
        tenant_id: str,
    ) -> list[dict[str, Any]]:
        """Fuzzy shortlist + LLM ranking.

        Runs ``_fuzzy_name_match`` to get up to 10 candidates, then asks the
        LLM to pick the most likely single match.

        Args:
            rule: Entity extraction rule.
            mention: Mention string.
            user_context: Session data.
            tenant_id: Tenant identifier.

        Returns:
            A single-element list with the LLM-chosen candidate, or the fuzzy
            shortlist if no LLM client is configured.
        """
        candidates = await self._fuzzy_name_match(rule, mention, user_context, tenant_id)
        if len(candidates) <= 1 or self._llm is None:
            return candidates

        # Ask LLM to pick the best match
        names = [c.get("name", c.get("_id", "?")) for c in candidates]
        prompt = (
            f"Given the mention '{mention}', which of the following is the most "
            f"likely match? Answer with ONLY the exact name from the list, nothing "
            f"else.\n\n" + "\n".join(f"- {n}" for n in names)
        )
        try:
            response = await self._llm.ask(prompt)
            chosen_name = str(response).strip()
            for candidate in candidates:
                if candidate.get("name", "") == chosen_name:
                    return [candidate]
        except Exception as exc:
            self.logger.warning(
                "LLM-assisted entity resolution failed for '%s': %s; "
                "falling back to full shortlist.",
                mention, exc
            )

        return candidates

    # ------------------------------------------------------------------
    # Ambiguity handling / pick logic
    # ------------------------------------------------------------------

    def _pick(
        self,
        rule: EntityExtractionRule,
        rule_name: str,
        mention: str,
        candidates: list[dict[str, Any]],
        user_context: dict[str, Any],
    ) -> str:
        """Select the winning candidate according to ``rule.ambiguity_strategy``.

        Args:
            rule: The entity extraction rule.
            rule_name: Rule name (for error messages).
            mention: The extracted mention string.
            candidates: Non-empty list of candidate dicts.
            user_context: Session data for context-based re-ranking.

        Returns:
            The ``_id`` of the selected candidate.

        Raises:
            EntityAmbiguityError: When ``ambiguity_strategy`` is ``ask_user``
                or ``fail`` and there are multiple candidates; or when
                ``use_context`` cannot narrow to a unique winner.
            NotImplementedError: For ``rerank_by_authority``.
        """
        if len(candidates) == 1:
            return candidates[0]["_id"]

        strategy = rule.ambiguity_strategy

        if strategy in ("ask_user", "fail"):
            raise EntityAmbiguityError(
                rule_name=rule_name,
                mention=mention,
                candidates=candidates,
            )

        if strategy == "pick_first":
            return candidates[0]["_id"]

        if strategy == "use_context":
            return self._use_context_pick(rule_name, mention, candidates, user_context)

        if strategy == "rerank_by_authority":
            raise NotImplementedError(
                "rerank_by_authority is reserved for FEAT-concept-document-authority "
                "and is not yet implemented."
            )

        raise ValueError(f"Unknown ambiguity_strategy: {strategy!r}")  # pragma: no cover

    def _use_context_pick(
        self,
        rule_name: str,
        mention: str,
        candidates: list[dict[str, Any]],
        user_context: dict[str, Any],
    ) -> str:
        """Re-rank candidates by context proximity (same dept → others).

        Args:
            rule_name: Rule name (for error messages).
            mention: The extracted mention string.
            candidates: Multiple candidate dicts.
            user_context: Session data with optional ``department``,
                ``manager_id``.

        Returns:
            ``_id`` of the unique context-preferred candidate.

        Raises:
            EntityAmbiguityError: When context re-ranking still yields multiple
                equally-ranked candidates (falls through to ``ask_user``
                semantics).
        """
        user_dept = user_context.get("department")
        user_mgr = user_context.get("manager_id")

        dept_matches = [
            c for c in candidates
            if user_dept and c.get("department") == user_dept
        ]
        if len(dept_matches) == 1:
            return dept_matches[0]["_id"]

        mgr_matches = [
            c for c in candidates
            if user_mgr and (c.get("_id") == user_mgr or c.get("manager_id") == user_mgr)
        ]
        if len(mgr_matches) == 1:
            return mgr_matches[0]["_id"]

        # Still ambiguous — fall through to ask_user semantics
        raise EntityAmbiguityError(
            rule_name=rule_name,
            mention=mention,
            candidates=candidates,
        )
