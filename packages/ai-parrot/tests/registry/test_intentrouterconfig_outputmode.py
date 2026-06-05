"""Tests for IntentRouterConfig output-mode routing fields (FEAT-224, TASK-1485)."""
from __future__ import annotations

from parrot.registry.capabilities.models import IntentRouterConfig


def test_new_outputmode_defaults():
    c = IntentRouterConfig()
    assert c.enable_output_mode_routing is False
    assert c.embedding_model == "intfloat/multilingual-e5-small"
    assert c.output_mode_routes == {}
    # Calibrated default for multilingual-e5-small (review fix: 0.55 accepted
    # every query; 0.85 separates on-topic from off-topic).
    assert c.output_mode_threshold == 0.85
    assert c.discrepancy_margin == 0.05


def test_existing_fields_intact():
    c = IntentRouterConfig()
    assert c.confidence_threshold == 0.7
    assert c.hitl_threshold == 0.3
    assert c.strategy_timeout_s == 30.0
    assert c.exhaustive_mode is False
    assert c.max_cascades == 3
    assert c.custom_keywords == {}


def test_output_mode_routes_roundtrip():
    routes = {"structured_chart": ["create a pie chart"]}
    c = IntentRouterConfig(
        enable_output_mode_routing=True,
        output_mode_routes=routes,
        output_mode_threshold=0.8,
    )
    assert c.enable_output_mode_routing is True
    assert c.output_mode_routes == routes
    assert c.output_mode_threshold == 0.8
