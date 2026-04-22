"""Unit tests for parrot.registry.routing models (TASK-785)."""
import pytest
from pydantic import ValidationError

from parrot.registry.routing import (
    StoreFallbackPolicy,
    StoreRule,
    StoreRouterConfig,
    StoreScore,
    StoreRoutingDecision,
)
from parrot.tools.multistoresearch import StoreType


class TestStoreRouterConfig:
    def test_defaults(self):
        cfg = StoreRouterConfig()
        assert cfg.margin_threshold == 0.15
        assert cfg.confidence_floor == 0.2
        assert cfg.llm_timeout_s == 1.0
        assert cfg.top_n == 1
        assert cfg.fallback_policy == StoreFallbackPolicy.FAN_OUT
        assert cfg.cache_size == 256
        assert cfg.enable_ontology_signal is True
        assert cfg.custom_rules == []

    def test_cache_disabled_when_zero(self):
        cfg = StoreRouterConfig(cache_size=0)
        assert cfg.cache_size == 0

    def test_custom_policy(self):
        cfg = StoreRouterConfig(fallback_policy=StoreFallbackPolicy.RAISE)
        assert cfg.fallback_policy == StoreFallbackPolicy.RAISE

    def test_margin_threshold_bounds(self):
        with pytest.raises(ValidationError):
            StoreRouterConfig(margin_threshold=-0.1)
        with pytest.raises(ValidationError):
            StoreRouterConfig(margin_threshold=1.1)

    def test_llm_timeout_must_be_positive(self):
        with pytest.raises(ValidationError):
            StoreRouterConfig(llm_timeout_s=0.0)
        with pytest.raises(ValidationError):
            StoreRouterConfig(llm_timeout_s=-1.0)

    def test_top_n_ge1(self):
        with pytest.raises(ValidationError):
            StoreRouterConfig(top_n=0)


class TestStoreRule:
    def test_regex_flag(self):
        rule = StoreRule(pattern=".*graph.*", store=StoreType.ARANGO, regex=True)
        assert rule.regex is True
        assert rule.store == StoreType.ARANGO

    def test_default_weight(self):
        rule = StoreRule(pattern="exact", store=StoreType.PGVECTOR)
        assert rule.weight == 1.0

    def test_weight_bounds(self):
        with pytest.raises(ValidationError):
            StoreRule(pattern="x", store=StoreType.PGVECTOR, weight=-0.1)
        with pytest.raises(ValidationError):
            StoreRule(pattern="x", store=StoreType.PGVECTOR, weight=1.1)

    def test_roundtrip(self):
        rule = StoreRule(pattern=".*graph.*", store=StoreType.ARANGO, regex=True)
        restored = StoreRule.model_validate(rule.model_dump())
        assert restored.pattern == ".*graph.*"
        assert restored.store == StoreType.ARANGO
        assert restored.regex is True


class TestStoreFallbackPolicy:
    def test_values(self):
        assert StoreFallbackPolicy.FAN_OUT == "fan_out"
        assert StoreFallbackPolicy.FIRST_AVAILABLE == "first_available"
        assert StoreFallbackPolicy.EMPTY == "empty"
        assert StoreFallbackPolicy.RAISE == "raise"

    def test_is_str_enum(self):
        assert isinstance(StoreFallbackPolicy.FAN_OUT, str)


class TestStoreScore:
    def test_confidence_bounds(self):
        with pytest.raises(ValidationError):
            StoreScore(store=StoreType.PGVECTOR, confidence=1.5)
        with pytest.raises(ValidationError):
            StoreScore(store=StoreType.PGVECTOR, confidence=-0.1)

    def test_valid_score(self):
        s = StoreScore(store=StoreType.PGVECTOR, confidence=0.85, reason="keyword match")
        assert s.store == StoreType.PGVECTOR
        assert s.confidence == 0.85
        assert s.reason == "keyword match"

    def test_default_reason_empty(self):
        s = StoreScore(store=StoreType.FAISS, confidence=0.5)
        assert s.reason == ""


class TestStoreRoutingDecision:
    def test_roundtrip(self):
        d = StoreRoutingDecision(
            rankings=[StoreScore(store=StoreType.PGVECTOR, confidence=0.9)],
            path="fast",
        )
        restored = StoreRoutingDecision.model_validate(d.model_dump())
        assert restored.rankings[0].store == StoreType.PGVECTOR
        assert restored.path == "fast"

    def test_defaults(self):
        d = StoreRoutingDecision(path="cache")
        assert d.rankings == []
        assert d.fallback_used is False
        assert d.cache_hit is False
        assert d.ontology_annotations is None
        assert d.elapsed_ms == 0.0

    def test_cache_hit_flag(self):
        d = StoreRoutingDecision(path="cache", cache_hit=True)
        assert d.cache_hit is True

    def test_fallback_with_annotations(self):
        d = StoreRoutingDecision(
            path="fallback",
            fallback_used=True,
            ontology_annotations={"action": "graph_query"},
        )
        assert d.fallback_used is True
        assert d.ontology_annotations["action"] == "graph_query"
