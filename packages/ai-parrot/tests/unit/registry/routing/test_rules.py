"""Unit tests for parrot.registry.routing.rules (TASK-788)."""
import pytest
from parrot.registry.routing import (
    StoreRule,
    StoreScore,
    apply_rules,
    DEFAULT_STORE_RULES,
)
from parrot.tools.multistoresearch import StoreType


ALL_STORES = [StoreType.PGVECTOR, StoreType.FAISS, StoreType.ARANGO]


def test_keyword_rule_selects_pgvector():
    scores = apply_rules("what is an endcap?", DEFAULT_STORE_RULES, ALL_STORES, None)
    assert scores
    assert scores[0].store == StoreType.PGVECTOR


def test_graph_keyword_selects_arango():
    scores = apply_rules(
        "show the relationship between suppliers and warehouses",
        DEFAULT_STORE_RULES,
        ALL_STORES,
        None,
    )
    assert scores[0].store == StoreType.ARANGO


def test_ontology_hint_boosts_arango():
    scores = apply_rules(
        "supplier warehouse",
        DEFAULT_STORE_RULES,
        ALL_STORES,
        {"action": "graph_query"},
    )
    arango_scores = [s for s in scores if s.store == StoreType.ARANGO]
    assert arango_scores
    assert arango_scores[0].confidence >= 0.15  # at minimum the boost itself


def test_ontology_hint_boosts_pgvector():
    scores = apply_rules(
        "some random query",
        DEFAULT_STORE_RULES,
        ALL_STORES,
        {"action": "vector_only"},
    )
    pv_scores = [s for s in scores if s.store == StoreType.PGVECTOR]
    assert pv_scores
    assert pv_scores[0].confidence >= 0.15


def test_unavailable_store_is_filtered():
    scores = apply_rules(
        "relationship",
        DEFAULT_STORE_RULES,
        [StoreType.PGVECTOR],  # ARANGO NOT available
        None,
    )
    assert all(s.store != StoreType.ARANGO for s in scores)


def test_regex_rule():
    custom = [StoreRule(pattern=r"^find\s+\d+", store=StoreType.FAISS, regex=True)]
    scores = apply_rules("find 10 similar products", custom, ALL_STORES, None)
    assert scores and scores[0].store == StoreType.FAISS


def test_no_match_returns_empty():
    scores = apply_rules("zzzz completely unmatched", [], ALL_STORES, None)
    assert scores == []


def test_max_weight_wins_over_sum():
    custom = [
        StoreRule(pattern="foo", store=StoreType.PGVECTOR, weight=0.5),
        StoreRule(pattern="foo", store=StoreType.PGVECTOR, weight=0.9),
    ]
    scores = apply_rules("foo foo foo", custom, ALL_STORES, None)
    assert scores[0].confidence == 0.9  # MAX, not sum


def test_scores_descending():
    scores = apply_rules(
        "relationship graph what is",
        DEFAULT_STORE_RULES,
        ALL_STORES,
        None,
    )
    for i in range(len(scores) - 1):
        assert scores[i].confidence >= scores[i + 1].confidence


def test_empty_ontology_no_crash():
    scores = apply_rules("x", DEFAULT_STORE_RULES, ALL_STORES, {})
    assert isinstance(scores, list)


def test_none_ontology_no_crash():
    scores = apply_rules("x", DEFAULT_STORE_RULES, ALL_STORES, None)
    assert isinstance(scores, list)


def test_ontology_boost_capped_at_one():
    # Start with max weight 0.95; boost of 0.15 would exceed 1.0
    custom = [StoreRule(pattern="q", store=StoreType.ARANGO, weight=0.95)]
    scores = apply_rules(
        "q",
        custom,
        ALL_STORES,
        {"action": "graph_query"},
    )
    arango = next(s for s in scores if s.store == StoreType.ARANGO)
    assert arango.confidence <= 1.0


def test_faiss_similarity_rule():
    scores = apply_rules("similar to cats", DEFAULT_STORE_RULES, ALL_STORES, None)
    faiss_scores = [s for s in scores if s.store == StoreType.FAISS]
    assert faiss_scores


def test_custom_rules_take_effect():
    custom = [StoreRule(pattern="supplier", store=StoreType.PGVECTOR, weight=0.95)]
    scores = apply_rules("supplier data", custom, ALL_STORES, None)
    assert scores[0].store == StoreType.PGVECTOR
    assert scores[0].confidence == 0.95
