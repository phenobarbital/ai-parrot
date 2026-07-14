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


# ---------------------------------------------------------------------------
# Legacy LLM-tuning column tolerance + folding (schema drift).
# Older navigator.ai_bots tables still carry model_name/temperature/
# max_tokens/top_k/top_p/embedding_model as standalone columns. Under
# Meta.strict=True these are passed as kwargs during row hydration; the model
# must accept them and fold them into the canonical JSONB.
# ---------------------------------------------------------------------------


def test_legacy_columns_do_not_raise_under_strict() -> None:
    """Passing the legacy columns as kwargs must not raise (strict=True)."""
    m = BotModel(
        name="legacy",
        model_name="gemini-2.5-pro",
        temperature=0.1,
        max_tokens=8192,
        top_k=41,
        top_p=0.9,
    )
    assert m.name == "legacy"


def test_legacy_columns_fold_into_model_config() -> None:
    """Legacy scalar columns backfill model_config when the JSONB is empty."""
    m = BotModel(name="legacy", model_name="gemini-2.5-pro", temperature=0.1)
    assert m.model_config["model_name"] == "gemini-2.5-pro"
    assert m.model_config["temperature"] == 0.1
    # model_name is mirrored to the 'model' key (callers read either).
    assert m.model_config["model"] == "gemini-2.5-pro"


def test_explicit_model_config_wins_over_legacy_column() -> None:
    """An explicit model_config value must not be overwritten by the column."""
    m = BotModel(
        name="legacy",
        model_name="gpt-4.5",
        model_config={"model_name": "gemini-2.5-flash"},
    )
    assert m.model_config["model_name"] == "gemini-2.5-flash"


def test_legacy_embedding_model_folds_into_vector_store_config() -> None:
    """Legacy embedding_model column backfills vector_store_config."""
    emb = {"model_name": "sentence-transformers/all-mpnet-base-v2"}
    m = BotModel(name="legacy", embedding_model=emb)
    assert m.vector_store_config["embedding_model"] == emb


def test_no_legacy_columns_leaves_model_config_untouched() -> None:
    """Without legacy columns, model_config stays as provided (no spurious keys)."""
    m = BotModel(name="plain")
    assert m.model_config == {}
