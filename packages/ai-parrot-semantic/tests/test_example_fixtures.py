"""Regression contract: the committed example model/policy fixtures load (FEAT-769 AC11)."""

from __future__ import annotations

from pathlib import Path

from parrot.semantic.loader import SemanticModelLoader

_MODELS = Path(__file__).resolve().parents[3] / "examples" / "agents" / "semantic" / "models"
_UNGOVERNED = Path(__file__).resolve().parents[3] / "examples" / "agents" / "semantic" / "models_ungoverned"


def test_governed_fixture_loads_with_one_policy_per_model() -> None:
    """Both models load; neither raises ``missing_policy`` (spec AC11)."""
    loaded = SemanticModelLoader(_MODELS, driver="duckdb").load()
    assert set(loaded) == {"orders", "customers"}
    assert all(model.policy.governed for model in loaded.values())


def test_the_two_models_use_distinct_named_connections() -> None:
    """Q3: the connection is a per-model property, resolved from the root model's policy."""
    loaded = SemanticModelLoader(_MODELS, driver="duckdb").load()
    assert loaded["orders"].policy.connection == "semantic_example"
    assert loaded["customers"].policy.connection == "semantic_dim"


def test_mask_and_saved_query_validate_through_the_real_loader() -> None:
    """The masks and saved queries demonstrated by TASK-4882 are loader-valid."""
    policy = SemanticModelLoader(_MODELS, driver="duckdb").load()["orders"].policy
    mask = policy.masks["sales.orders.region"]
    assert mask.strategy == "null"
    assert policy.mask_for(frozenset({"analyst"}), "sales.orders.region") is mask
    assert policy.mask_for(frozenset({"admin"}), "sales.orders.region") is None
    assert policy.saved_queries[0].name == "monthly_revenue"
    assert policy.saved_queries[0].query.model == "orders"


def test_ungoverned_fixture_loads_and_is_not_governed() -> None:
    """TASK-4883's compile surface has the same graph with ungoverned policies."""
    loaded = SemanticModelLoader(_UNGOVERNED, driver="duckdb").load()
    assert set(loaded) == {"orders", "customers"}
    assert not any(model.policy.governed for model in loaded.values())


def test_the_two_graphs_are_identical() -> None:
    """Only governance differs between the two directories (spec AC12)."""
    assert (_MODELS / "orders.yml").read_text(encoding="utf-8").splitlines()[3:] == (
        _UNGOVERNED / "orders.yml"
    ).read_text(encoding="utf-8").splitlines()[4:]
