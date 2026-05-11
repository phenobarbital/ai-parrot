"""Tests for EntityResolver — all four strategies, scope filters, and ambiguity handling.

Covers FEAT-158 Module 2 acceptance criteria.
"""
from datetime import datetime, timezone

import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.knowledge.ontology.entity_resolver import (
    EntityAmbiguityError,
    EntityNotFoundError,
    EntityResolver,
)
from parrot.knowledge.ontology.schema import (
    EntityDef,
    EntityExtractionRule,
    MergedOntology,
    PropertyDef,
    TraversalPattern,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def graph_store():
    """Mocked OntologyGraphStore."""
    gs = MagicMock()
    gs.execute_traversal = AsyncMock()
    return gs


@pytest.fixture
def ontology() -> MergedOntology:
    """Real MergedOntology with an Employee entity (Pydantic-valid)."""
    return MergedOntology(
        name="test",
        version="1.0",
        entities={
            "Employee": EntityDef(
                collection="employees",
                key_field="employee_id",
                properties=[{"employee_id": PropertyDef(type="string")}],
            ),
        },
        relations={},
        traversal_patterns={},
        layers=["test"],
        merge_timestamp=datetime.now(timezone.utc),
    )


@pytest.fixture
def resolver(graph_store, ontology) -> EntityResolver:
    """EntityResolver with no LLM client."""
    return EntityResolver(graph_store=graph_store, ontology=ontology, llm_client=None)


def _pattern_with_rule(rule: EntityExtractionRule) -> TraversalPattern:
    """Helper: build a minimal TraversalPattern with one entity_extraction rule."""
    return TraversalPattern(
        description="t",
        trigger_intents=["el equipo de"],
        query_template="FOR e IN Employee RETURN e",
        post_action="vector_search",
        post_query=None,
        entity_extraction={"target": rule},
    )


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


class TestEntityResolver:
    """Core entity resolver behaviour."""

    @pytest.mark.asyncio
    async def test_exact_match_no_llm(self, resolver, graph_store):
        """Unambiguous name resolves to a single _id without LLM call."""
        graph_store.execute_traversal.return_value = [
            {"_id": "Employee/123", "name": "Jesús Lara"}
        ]
        pattern = _pattern_with_rule(
            EntityExtractionRule(type="Employee", resolver="fuzzy_name_match")
        )
        out = await resolver.extract_and_resolve(
            pattern,
            "el equipo de Jesús",
            user_context={"user_id": "u1"},
            tenant_id="t1",
        )
        assert out == {"target": "Employee/123"}

    @pytest.mark.asyncio
    async def test_ambiguous_raises(self, resolver, graph_store):
        """Multiple matches with ambiguity_strategy=ask_user raise EntityAmbiguityError."""
        graph_store.execute_traversal.return_value = [
            {"_id": "Employee/1", "name": "Jesús Lara"},
            {"_id": "Employee/2", "name": "Jesús Pérez"},
        ]
        pattern = _pattern_with_rule(
            EntityExtractionRule(
                type="Employee",
                resolver="fuzzy_name_match",
                ambiguity_strategy="ask_user",
            )
        )
        with pytest.raises(EntityAmbiguityError) as exc_info:
            await resolver.extract_and_resolve(
                pattern,
                "el equipo de Jesús",
                user_context={"user_id": "u1"},
                tenant_id="t1",
            )
        err = exc_info.value
        assert err.rule_name == "target"
        assert err.mention is not None
        assert len(err.candidates) == 2

    @pytest.mark.asyncio
    async def test_use_context_picks_same_dept(self, resolver, graph_store):
        """use_context picks the candidate in the requesting user's department."""
        graph_store.execute_traversal.return_value = [
            {"_id": "Employee/1", "name": "Jesús Lara", "department": "Engineering"},
            {"_id": "Employee/2", "name": "Jesús Pérez", "department": "Sales"},
        ]
        pattern = _pattern_with_rule(
            EntityExtractionRule(
                type="Employee",
                resolver="fuzzy_name_match",
                ambiguity_strategy="use_context",
            )
        )
        out = await resolver.extract_and_resolve(
            pattern,
            "el equipo de Jesús",
            user_context={"user_id": "u1", "department": "Engineering"},
            tenant_id="t1",
        )
        assert out == {"target": "Employee/1"}

    @pytest.mark.asyncio
    async def test_not_found_required_raises(self, resolver, graph_store):
        """required=True and no match raises EntityNotFoundError."""
        graph_store.execute_traversal.return_value = []
        pattern = _pattern_with_rule(
            EntityExtractionRule(
                type="Employee",
                resolver="fuzzy_name_match",
                required=True,
            )
        )
        with pytest.raises(EntityNotFoundError) as exc_info:
            await resolver.extract_and_resolve(
                pattern,
                "el equipo de Jesús",
                user_context={"user_id": "u1"},
                tenant_id="t1",
            )
        assert exc_info.value.rule_name == "target"

    @pytest.mark.asyncio
    async def test_not_found_optional_silent(self, resolver, graph_store):
        """required=False and no match returns empty dict without raising."""
        graph_store.execute_traversal.return_value = []
        pattern = _pattern_with_rule(
            EntityExtractionRule(
                type="Employee",
                resolver="fuzzy_name_match",
                required=False,
            )
        )
        out = await resolver.extract_and_resolve(
            pattern,
            "el equipo de Jesús",
            user_context={"user_id": "u1"},
            tenant_id="t1",
        )
        assert out == {}

    @pytest.mark.asyncio
    async def test_pick_first_takes_first_candidate(self, resolver, graph_store):
        """pick_first returns the first candidate from the sorted list."""
        graph_store.execute_traversal.return_value = [
            {"_id": "Employee/1", "name": "Jesús A"},
            {"_id": "Employee/2", "name": "Jesús B"},
        ]
        pattern = _pattern_with_rule(
            EntityExtractionRule(
                type="Employee",
                resolver="fuzzy_name_match",
                ambiguity_strategy="pick_first",
            )
        )
        out = await resolver.extract_and_resolve(
            pattern,
            "el equipo de Jesús",
            user_context={"user_id": "u1"},
            tenant_id="t1",
        )
        assert out == {"target": "Employee/1"}

    # ------------------------------------------------------------------
    # Scope filter tests
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_scope_same_department_filters(self, resolver, graph_store):
        """scope=same_department adds a department filter to the AQL call."""
        graph_store.execute_traversal.return_value = [
            {"_id": "Employee/1", "name": "Jesús Lara", "department": "Engineering"},
        ]
        pattern = _pattern_with_rule(
            EntityExtractionRule(
                type="Employee",
                resolver="fuzzy_name_match",
                scope="same_department",
            )
        )
        out = await resolver.extract_and_resolve(
            pattern,
            "el equipo de Jesús",
            user_context={"user_id": "u1", "department": "Engineering"},
            tenant_id="t1",
        )
        assert out == {"target": "Employee/1"}
        # Verify department was bound in the AQL call
        call_kwargs = graph_store.execute_traversal.call_args
        bind_vars = call_kwargs.kwargs.get("bind_vars") or call_kwargs.args[2] if len(call_kwargs.args) > 2 else {}
        assert "user_department" in bind_vars or "Engineering" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_scope_same_department_no_user_dept_skips_filter(self, resolver, graph_store):
        """scope=same_department without user department gracefully skips filter."""
        graph_store.execute_traversal.return_value = [
            {"_id": "Employee/1", "name": "Jesús Lara"},
        ]
        pattern = _pattern_with_rule(
            EntityExtractionRule(
                type="Employee",
                resolver="fuzzy_name_match",
                scope="same_department",
            )
        )
        # No 'department' in user_context — should not raise
        out = await resolver.extract_and_resolve(
            pattern,
            "el equipo de Jesús",
            user_context={"user_id": "u1"},
            tenant_id="t1",
        )
        assert out == {"target": "Employee/1"}

    # ------------------------------------------------------------------
    # Reserved / unimplemented strategies
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_hybrid_raises_not_implemented(self, resolver):
        """hybrid_concept_match raises NotImplementedError referencing parent feature."""
        pattern = _pattern_with_rule(
            EntityExtractionRule(
                type="Employee",
                resolver="hybrid_concept_match",
            )
        )
        with pytest.raises(NotImplementedError, match="FEAT-concept-document-authority"):
            await resolver.extract_and_resolve(
                pattern,
                "X",
                user_context={"user_id": "u1"},
                tenant_id="t1",
            )

    # ------------------------------------------------------------------
    # use_context still ambiguous → raises
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_use_context_still_ambiguous_raises(self, resolver, graph_store):
        """use_context with two same-dept candidates still raises EntityAmbiguityError."""
        graph_store.execute_traversal.return_value = [
            {"_id": "Employee/1", "name": "Jesús Lara", "department": "Engineering"},
            {"_id": "Employee/2", "name": "Jesús Pérez", "department": "Engineering"},
        ]
        pattern = _pattern_with_rule(
            EntityExtractionRule(
                type="Employee",
                resolver="fuzzy_name_match",
                ambiguity_strategy="use_context",
            )
        )
        with pytest.raises(EntityAmbiguityError):
            await resolver.extract_and_resolve(
                pattern,
                "el equipo de Jesús",
                user_context={"user_id": "u1", "department": "Engineering"},
                tenant_id="t1",
            )

    # ------------------------------------------------------------------
    # fail strategy behaves like ask_user
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_fail_strategy_raises_on_ambiguity(self, resolver, graph_store):
        """ambiguity_strategy=fail raises EntityAmbiguityError on multiple candidates."""
        graph_store.execute_traversal.return_value = [
            {"_id": "Employee/1", "name": "Jesús Lara"},
            {"_id": "Employee/2", "name": "Jesús Pérez"},
        ]
        pattern = _pattern_with_rule(
            EntityExtractionRule(
                type="Employee",
                resolver="fuzzy_name_match",
                ambiguity_strategy="fail",
            )
        )
        with pytest.raises(EntityAmbiguityError):
            await resolver.extract_and_resolve(
                pattern,
                "el equipo de Jesús",
                user_context={"user_id": "u1"},
                tenant_id="t1",
            )
