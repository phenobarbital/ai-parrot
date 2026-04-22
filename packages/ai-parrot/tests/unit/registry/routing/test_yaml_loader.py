"""Unit tests for parrot.registry.routing.yaml_loader (TASK-786)."""
import pytest
from pathlib import Path
from parrot.registry.routing import (
    StoreRouterConfig,
    StoreFallbackPolicy,
    load_store_router_config,
)
from parrot.tools.multistoresearch import StoreType


def test_loads_valid_yaml(tmp_path):
    p = tmp_path / "router.yaml"
    p.write_text(
        "margin_threshold: 0.25\n"
        "fallback_policy: fan_out\n"
        "custom_rules:\n"
        "  - pattern: graph\n"
        "    store: arango\n"
    )
    cfg = load_store_router_config(p)
    assert cfg.margin_threshold == 0.25
    assert cfg.fallback_policy == StoreFallbackPolicy.FAN_OUT
    assert len(cfg.custom_rules) == 1
    assert cfg.custom_rules[0].store == StoreType.ARANGO


def test_missing_file_returns_defaults(caplog):
    cfg = load_store_router_config("/does/not/exist.yaml")
    assert isinstance(cfg, StoreRouterConfig)
    assert cfg.margin_threshold == 0.15


def test_malformed_yaml_returns_defaults(tmp_path, caplog):
    p = tmp_path / "bad.yaml"
    p.write_text("::: not: valid: yaml :::")
    cfg = load_store_router_config(p)
    assert cfg.margin_threshold == 0.15  # defaults


def test_invalid_schema_returns_defaults(tmp_path, caplog):
    p = tmp_path / "bad_schema.yaml"
    p.write_text("margin_threshold: not_a_float\n")
    cfg = load_store_router_config(p)
    assert cfg.margin_threshold == 0.15


def test_dict_input():
    cfg = load_store_router_config({"top_n": 3})
    assert cfg.top_n == 3


def test_dict_with_rules():
    cfg = load_store_router_config({
        "margin_threshold": 0.10,
        "custom_rules": [
            {"pattern": "graph", "store": "arango", "weight": 0.9},
        ],
    })
    assert cfg.margin_threshold == 0.10
    assert cfg.custom_rules[0].store == StoreType.ARANGO
    assert cfg.custom_rules[0].weight == 0.9


def test_non_mapping_yaml_returns_defaults(tmp_path, caplog):
    p = tmp_path / "list.yaml"
    p.write_text("- item1\n- item2\n")
    cfg = load_store_router_config(p)
    assert cfg.margin_threshold == 0.15


def test_fallback_policy_raise(tmp_path):
    p = tmp_path / "router.yaml"
    p.write_text("fallback_policy: raise\n")
    cfg = load_store_router_config(p)
    assert cfg.fallback_policy == StoreFallbackPolicy.RAISE


def test_str_path(tmp_path):
    p = tmp_path / "router.yaml"
    p.write_text("top_n: 2\n")
    cfg = load_store_router_config(str(p))
    assert cfg.top_n == 2


def test_empty_dict_returns_defaults():
    cfg = load_store_router_config({})
    assert cfg.margin_threshold == 0.15
    assert cfg.top_n == 1
