"""Unit tests for hybrid_concept_match resolver (FEAT-159 TASK-1088).

All vector store and LLM calls are mocked — no real DB or LLM used.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.knowledge.ontology.entity_resolver import EntityResolver
from parrot.stores.models import SearchResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_concept(concept_id: str, label: str, synonyms=None):
    """Return a SimpleNamespace concept."""
    return SimpleNamespace(
        concept_id=concept_id,
        label=label,
        synonyms=synonyms or [],
        description="",
    )


def make_search_result(concept_id: str, label: str, score: float) -> SearchResult:
    """Return a SearchResult with concept metadata."""
    return SearchResult(
        id=concept_id,
        content=label,
        metadata={"concept_id": concept_id, "label": label, "tenant_id": "acme"},
        score=score,
    )


def make_resolver(
    *,
    concept_instances=None,
    vector_store=None,
    llm_client=None,
) -> EntityResolver:
    """Return an EntityResolver with mock graph store and ontology."""
    from parrot.knowledge.ontology.schema import MergedOntology

    mock_ontology = MagicMock(spec=MergedOntology)
    mock_ontology.version = "1.0"
    mock_ontology.entities = {}

    mock_graph = MagicMock()

    return EntityResolver(
        graph_store=mock_graph,
        ontology=mock_ontology,
        llm_client=llm_client,
        vector_store=vector_store,
        concept_instances=concept_instances,
    )


# ---------------------------------------------------------------------------
# _split_mentions
# ---------------------------------------------------------------------------


class TestSplitMentions:
    def test_single_term_returned_unchanged(self):
        resolver = make_resolver()
        assert resolver._split_mentions("commissions") == ["commissions"]

    def test_and_conjunction_en(self):
        resolver = make_resolver()
        parts = resolver._split_mentions("commissions and bonuses")
        assert parts == ["commissions", "bonuses"]

    def test_vs_conjunction(self):
        resolver = make_resolver()
        parts = resolver._split_mentions("commissions vs bonuses")
        assert parts == ["commissions", "bonuses"]

    def test_v_conjunction(self):
        resolver = make_resolver()
        parts = resolver._split_mentions("commissions v bonuses")
        assert parts == ["commissions", "bonuses"]

    def test_y_conjunction_es(self):
        resolver = make_resolver()
        parts = resolver._split_mentions("comisiones y bonos")
        assert parts == ["comisiones", "bonos"]

    def test_e_conjunction_es(self):
        resolver = make_resolver()
        parts = resolver._split_mentions("becas e incentivos")
        assert parts == ["becas", "incentivos"]

    def test_frente_a_conjunction_es(self):
        resolver = make_resolver()
        parts = resolver._split_mentions("comisiones frente a bonos")
        assert parts == ["comisiones", "bonos"]

    def test_frente_a_multiword(self):
        resolver = make_resolver()
        parts = resolver._split_mentions("A frente a B")
        assert parts == ["A", "B"]

    def test_empty_parts_stripped(self):
        resolver = make_resolver()
        parts = resolver._split_mentions("  and  bonuses  ")
        assert "bonuses" in parts

    def test_case_insensitive(self):
        resolver = make_resolver()
        parts = resolver._split_mentions("commissions AND bonuses")
        assert parts == ["commissions", "bonuses"]


# ---------------------------------------------------------------------------
# Stage 1: Synonym/label exact match
# ---------------------------------------------------------------------------


class TestStage1SynonymMatch:
    @pytest.mark.asyncio
    async def test_label_exact_match_returns_immediately(self):
        """Exact label match → returns without vector or LLM call."""
        concepts = [make_concept("c1", "Commissions", ["comisiones"])]
        vs = MagicMock()
        vs.similarity_search = AsyncMock()
        resolver = make_resolver(concept_instances=concepts, vector_store=vs)

        result = await resolver._resolve_single_concept_term("Commissions", "acme")

        assert result == ["c1"]
        vs.similarity_search.assert_not_called()

    @pytest.mark.asyncio
    async def test_synonym_exact_match_returns_immediately(self):
        """Exact synonym match → returns without vector call."""
        concepts = [make_concept("c1", "Commissions", ["comisiones", "bonos"])]
        vs = MagicMock()
        vs.similarity_search = AsyncMock()
        resolver = make_resolver(concept_instances=concepts, vector_store=vs)

        result = await resolver._resolve_single_concept_term("comisiones", "acme")

        assert result == ["c1"]
        vs.similarity_search.assert_not_called()

    @pytest.mark.asyncio
    async def test_case_insensitive_synonym_match(self):
        """Synonym match is case-insensitive."""
        concepts = [make_concept("c1", "Commissions", ["COMISIONES"])]
        vs = MagicMock()
        vs.similarity_search = AsyncMock()
        resolver = make_resolver(concept_instances=concepts, vector_store=vs)

        result = await resolver._resolve_single_concept_term("comisiones", "acme")
        assert result == ["c1"]

    @pytest.mark.asyncio
    async def test_no_synonym_match_falls_through_to_vector(self):
        """No synonym match → vector search is called."""
        concepts = [make_concept("c1", "Commissions", ["comisiones"])]
        vs = MagicMock()
        vs.similarity_search = AsyncMock(return_value=[
            make_search_result("c2", "Bonuses", 0.1)
        ])
        resolver = make_resolver(concept_instances=concepts, vector_store=vs)

        result = await resolver._resolve_single_concept_term("xyz_unknown", "acme")

        vs.similarity_search.assert_called_once()
        assert "c2" in result


# ---------------------------------------------------------------------------
# Stage 2: Vector search
# ---------------------------------------------------------------------------


class TestStage2VectorSearch:
    @pytest.mark.asyncio
    async def test_vector_clearly_dominant_no_llm(self):
        """top-1 score << top-2 → returns top-1 without LLM call."""
        llm = MagicMock()
        llm.ask = AsyncMock()
        vs = MagicMock()
        vs.similarity_search = AsyncMock(return_value=[
            make_search_result("c1", "Commissions", 0.1),   # much closer
            make_search_result("c2", "Bonuses", 0.5),        # further
        ])
        resolver = make_resolver(vector_store=vs, llm_client=llm)

        result = await resolver._resolve_single_concept_term("commissions", "acme")

        assert result == ["c1"]
        llm.ask.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_vector_store_returns_empty(self):
        """No vector_store configured → returns [] after synonym miss."""
        resolver = make_resolver(concept_instances=[], vector_store=None)
        result = await resolver._resolve_single_concept_term("commissions", "acme")
        assert result == []

    @pytest.mark.asyncio
    async def test_vector_search_passes_tenant_filter(self):
        """similarity_search is called with tenant_id in metadata_filters."""
        vs = MagicMock()
        vs.similarity_search = AsyncMock(return_value=[])
        resolver = make_resolver(vector_store=vs)

        await resolver._resolve_single_concept_term("commissions", "acme_corp")

        call_kwargs = vs.similarity_search.call_args.kwargs
        assert call_kwargs.get("metadata_filters", {}).get("tenant_id") == "acme_corp"

    @pytest.mark.asyncio
    async def test_single_result_returned_directly(self):
        """One vector result → returned without LLM."""
        vs = MagicMock()
        vs.similarity_search = AsyncMock(return_value=[
            make_search_result("c1", "Commissions", 0.2),
        ])
        resolver = make_resolver(vector_store=vs)
        result = await resolver._resolve_single_concept_term("x", "acme")
        assert result == ["c1"]

    @pytest.mark.asyncio
    async def test_empty_vector_results_returns_empty(self):
        """No vector results → [] returned."""
        vs = MagicMock()
        vs.similarity_search = AsyncMock(return_value=[])
        resolver = make_resolver(vector_store=vs)
        result = await resolver._resolve_single_concept_term("x", "acme")
        assert result == []


# ---------------------------------------------------------------------------
# Stage 3: LLM tie-breaker
# ---------------------------------------------------------------------------


class TestStage3LLMTieBreaker:
    @pytest.mark.asyncio
    async def test_llm_tiebreaker_invoked_when_ambiguous(self):
        """Ambiguous vector scores → LLM ask() is called."""
        llm = MagicMock()
        llm.ask = AsyncMock(return_value='["c1"]')
        vs = MagicMock()
        # Both results equally distant — ambiguous
        vs.similarity_search = AsyncMock(return_value=[
            make_search_result("c1", "Commissions", 0.3),
            make_search_result("c2", "Bonuses", 0.3),
        ])
        resolver = make_resolver(vector_store=vs, llm_client=llm)

        result = await resolver._resolve_single_concept_term("pay", "acme")

        llm.ask.assert_called_once()
        assert "c1" in result

    @pytest.mark.asyncio
    async def test_llm_tiebreaker_validates_against_pool(self):
        """LLM response with unknown ID → that ID is dropped."""
        llm = MagicMock()
        llm.ask = AsyncMock(return_value='["c_unknown", "c1"]')
        vs = MagicMock()
        vs.similarity_search = AsyncMock(return_value=[
            make_search_result("c1", "Commissions", 0.3),
            make_search_result("c2", "Bonuses", 0.35),
        ])
        resolver = make_resolver(vector_store=vs, llm_client=llm)

        result = await resolver._resolve_single_concept_term("pay", "acme")

        assert "c_unknown" not in result
        assert "c1" in result

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back_to_all_candidates(self):
        """LLM raises → fallback to returning all candidate IDs."""
        llm = MagicMock()
        llm.ask = AsyncMock(side_effect=RuntimeError("LLM error"))
        vs = MagicMock()
        vs.similarity_search = AsyncMock(return_value=[
            make_search_result("c1", "Commissions", 0.3),
            make_search_result("c2", "Bonuses", 0.32),
        ])
        resolver = make_resolver(vector_store=vs, llm_client=llm)

        result = await resolver._resolve_single_concept_term("pay", "acme")

        assert "c1" in result
        assert "c2" in result

    @pytest.mark.asyncio
    async def test_no_llm_returns_all_top_five(self):
        """No LLM configured → top-5 candidate IDs returned directly."""
        vs = MagicMock()
        vs.similarity_search = AsyncMock(return_value=[
            make_search_result(f"c{i}", f"Label{i}", 0.3)
            for i in range(7)
        ])
        resolver = make_resolver(vector_store=vs, llm_client=None)

        result = await resolver._resolve_single_concept_term("pay", "acme")

        # No LLM → top-5 returned
        assert len(result) == 5


# ---------------------------------------------------------------------------
# Multi-concept conjunction
# ---------------------------------------------------------------------------


class TestMultiConceptConjunction:
    @pytest.mark.asyncio
    async def test_conjunction_en_union_both(self):
        """'commissions and bonuses' → union of both concept IDs."""
        concepts = [
            make_concept("c1", "Commissions"),
            make_concept("c2", "Bonuses"),
        ]
        vs = MagicMock()
        vs.similarity_search = AsyncMock(return_value=[])
        resolver = make_resolver(concept_instances=concepts, vector_store=vs)

        result = await resolver._resolve_hybrid_concept_match(
            MagicMock(), "Commissions and Bonuses", {}, "acme"
        )

        assert "c1" in result
        assert "c2" in result

    @pytest.mark.asyncio
    async def test_conjunction_es_union_both(self):
        """'comisiones y bonos' → union of both concept IDs."""
        concepts = [
            make_concept("c1", "Commissions", ["comisiones"]),
            make_concept("c2", "Bonuses", ["bonos"]),
        ]
        vs = MagicMock()
        vs.similarity_search = AsyncMock(return_value=[])
        resolver = make_resolver(concept_instances=concepts, vector_store=vs)

        result = await resolver._resolve_hybrid_concept_match(
            MagicMock(), "comisiones y bonos", {}, "acme"
        )

        assert "c1" in result
        assert "c2" in result

    @pytest.mark.asyncio
    async def test_deduplication_across_terms(self):
        """Same concept matched from two terms → appears once in results."""
        concepts = [make_concept("c1", "Commissions", ["pay", "salary"])]
        vs = MagicMock()
        vs.similarity_search = AsyncMock(return_value=[])
        resolver = make_resolver(concept_instances=concepts, vector_store=vs)

        result = await resolver._resolve_hybrid_concept_match(
            MagicMock(), "pay and salary", {}, "acme"
        )

        assert result.count("c1") == 1

    @pytest.mark.asyncio
    async def test_cap_at_five_concepts(self):
        """Query resolving 7 concepts → only first 5 returned."""
        vs = MagicMock()
        # Return 7 distinct results per query call
        vs.similarity_search = AsyncMock(return_value=[
            make_search_result(f"c{i}", f"Label{i}", 0.1 * i)
            for i in range(1, 8)
        ])
        resolver = make_resolver(vector_store=vs, llm_client=None)

        # "a and b and c and d and e and f and g" → 7 terms
        result = await resolver._resolve_hybrid_concept_match(
            MagicMock(),
            "a and b and c and d and e and f and g",
            {},
            "acme",
        )

        assert len(result) <= 5


# ---------------------------------------------------------------------------
# Result caching
# ---------------------------------------------------------------------------


class TestResultCaching:
    @pytest.mark.asyncio
    async def test_cache_hit_skips_vector_call(self):
        """Same query+version+tenant → no vector call on second invocation."""
        vs = MagicMock()
        vs.similarity_search = AsyncMock(return_value=[
            make_search_result("c1", "Commissions", 0.1),
        ])
        resolver = make_resolver(vector_store=vs)

        await resolver._resolve_hybrid_concept_match(
            MagicMock(), "commissions", {}, "acme"
        )
        vs.reset_mock()

        result = await resolver._resolve_hybrid_concept_match(
            MagicMock(), "commissions", {}, "acme"
        )

        vs.similarity_search.assert_not_called()
        assert result  # same result as before

    @pytest.mark.asyncio
    async def test_cache_miss_on_version_bump(self):
        """Different ontology version → fresh resolution (cache miss)."""
        vs = MagicMock()
        vs.similarity_search = AsyncMock(return_value=[
            make_search_result("c1", "Commissions", 0.1),
        ])
        resolver = make_resolver(vector_store=vs)

        await resolver._resolve_hybrid_concept_match(
            MagicMock(), "commissions", {}, "acme"
        )

        # Bump version
        resolver._ontology.version = "2.0"
        vs.reset_mock()

        await resolver._resolve_hybrid_concept_match(
            MagicMock(), "commissions", {}, "acme"
        )

        vs.similarity_search.assert_called()

    @pytest.mark.asyncio
    async def test_cache_miss_on_different_tenant(self):
        """Different tenant_id → separate cache entry (fresh resolution)."""
        vs = MagicMock()
        vs.similarity_search = AsyncMock(return_value=[
            make_search_result("c1", "Commissions", 0.1),
        ])
        resolver = make_resolver(vector_store=vs)

        await resolver._resolve_hybrid_concept_match(
            MagicMock(), "commissions", {}, "tenant_a"
        )
        call_count_after_first = vs.similarity_search.call_count

        await resolver._resolve_hybrid_concept_match(
            MagicMock(), "commissions", {}, "tenant_b"
        )

        assert vs.similarity_search.call_count > call_count_after_first


# ---------------------------------------------------------------------------
# Tenant filtering
# ---------------------------------------------------------------------------


class TestTenantFiltering:
    @pytest.mark.asyncio
    async def test_tenant_filter_passed_to_vector_store(self):
        """Vector search is scoped to tenant_id='acme', not 'globex'."""
        vs = MagicMock()
        vs.similarity_search = AsyncMock(return_value=[])
        resolver = make_resolver(vector_store=vs)

        await resolver._resolve_hybrid_concept_match(
            MagicMock(), "commissions", {}, "acme"
        )

        call_kwargs = vs.similarity_search.call_args.kwargs
        assert call_kwargs.get("metadata_filters", {}).get("tenant_id") == "acme"

    @pytest.mark.asyncio
    async def test_different_tenants_get_different_searches(self):
        """Resolver with tenant_id='acme' does not use 'globex' tenant filter."""
        calls = []

        async def capture_search(**kwargs):
            calls.append(kwargs.get("metadata_filters", {}).get("tenant_id"))
            return []

        vs = MagicMock()
        vs.similarity_search = capture_search
        resolver = make_resolver(vector_store=vs)

        await resolver._resolve_hybrid_concept_match(
            MagicMock(), "commissions", {}, "acme"
        )
        await resolver._resolve_hybrid_concept_match(
            MagicMock(), "commissions", {}, "globex"
        )

        assert "acme" in calls
        assert "globex" in calls
