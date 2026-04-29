"""Unit tests for FEAT-133 BotModel field additions.

Tests cover:
- Default values are empty dicts for both new fields.
- Default dicts are independent across instances (not shared mutable).
- ``to_bot_config()`` includes both new keys.
- Payload roundtrip works with and without the new keys.
"""

from __future__ import annotations

from parrot.handlers.models.bots import BotModel


def test_default_empty_dicts() -> None:
    """Both new fields must default to empty dict."""
    m = BotModel(name="t1")
    assert m.reranker_config == {}
    assert m.parent_searcher_config == {}


def test_independent_default_dicts() -> None:
    """Mutating one instance's field must not affect another instance."""
    m1 = BotModel(name="t1")
    m2 = BotModel(name="t2")
    m1.reranker_config["type"] = "llm"
    assert m2.reranker_config == {}


def test_to_bot_config_contains_new_keys() -> None:
    """to_bot_config() must include both 'reranker_config' and 'parent_searcher_config'."""
    cfg = BotModel(name="t1").to_bot_config()
    assert "reranker_config" in cfg
    assert "parent_searcher_config" in cfg
    assert cfg["reranker_config"] == {}
    assert cfg["parent_searcher_config"] == {}


def test_to_bot_config_reflects_set_values() -> None:
    """to_bot_config() must reflect non-default values in both keys."""
    m = BotModel(
        name="t1",
        reranker_config={"type": "llm"},
        parent_searcher_config={"type": "in_table", "expand_to_parent": True},
    )
    cfg = m.to_bot_config()
    assert cfg["reranker_config"] == {"type": "llm"}
    assert cfg["parent_searcher_config"] == {"type": "in_table", "expand_to_parent": True}


def test_payload_with_configs_roundtrips() -> None:
    """BotModel(**payload) must accept and preserve both new fields."""
    payload = {
        "name": "t1",
        "reranker_config": {"type": "llm"},
        "parent_searcher_config": {"type": "in_table", "expand_to_parent": True},
    }
    m = BotModel(**payload)
    assert m.reranker_config == {"type": "llm"}
    assert m.parent_searcher_config["expand_to_parent"] is True


def test_payload_without_new_keys_still_works() -> None:
    """BotModel without the new fields must succeed (back-compat)."""
    m = BotModel(name="bare")
    assert m.reranker_config == {}
    assert m.parent_searcher_config == {}
