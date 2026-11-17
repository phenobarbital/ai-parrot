"""Regression contract: Model policy validation and role grants (M3)."""

from pathlib import Path

import pytest

from parrot.semantic.errors import SemanticPolicyError
from parrot.semantic.models import ModelMember
from parrot.semantic.policy import load_policy


def _members() -> list[ModelMember]:
    """Return the fixed semantic catalog used by policy tests."""
    return [
        ModelMember(name="revenue", kind="metric"),
        ModelMember(name="region", kind="dimension"),
        ModelMember(name="order_date", kind="time_dimension"),
        ModelMember(name="email", kind="dimension", sensitive=True),
    ]


def _write_policy(tmp_path: Path, content: str) -> Path:
    """Write a model-local policy side-file."""
    path = tmp_path / "orders.policy.yaml"
    path.write_text(content)
    return path


def test_governed_defaults_and_unknown_bindings(tmp_path: Path) -> None:
    """Verify governed defaults and fail-closed unknown bindings."""
    policy = load_policy(
        _write_policy(tmp_path, "connection: warehouse\nroles: {analyst: {metrics: [revenue]}}\n"),
        _members(),
        {"sales.orders"},
    )
    assert policy.governed is True
    assert policy.allowed_members(frozenset({"analyst"}), _members()) == {"revenue"}

    with pytest.raises(SemanticPolicyError, match="unknown") as error:
        load_policy(
            _write_policy(tmp_path, "connection: warehouse\nroles: {analyst: {metrics: [missing]}}\n"),
            _members(),
            {"sales.orders"},
        )
    assert error.value.code == "unknown_member"

    with pytest.raises(SemanticPolicyError) as error:
        load_policy(_write_policy(tmp_path, "connection: warehouse\nengine: native\n"), _members(), {"sales.orders"})
    assert error.value.code == "invalid_policy"


def test_role_usage_and_mask_permissions(tmp_path: Path) -> None:
    """Verify projection masking and independent usage permissions."""
    policy = load_policy(
        _write_policy(
            tmp_path,
            """connection: warehouse
roles:
  analyst: {dimensions: [email], usage: [sales.orders.region]}
masks:
  sales.orders.email: {strategy: hash, projection_roles: [auditor], usage_roles: [steward]}
""",
        ),
        _members(),
        {"sales.orders"},
    )
    assert policy.mask_for(frozenset({"analyst"}), "sales.orders.email") is not None
    assert policy.mask_for(frozenset({"auditor"}), "sales.orders.email") is None
    assert policy.usage_allowed(frozenset({"analyst"}), "sales.orders.region")
    assert not policy.usage_allowed(frozenset({"analyst"}), "sales.orders.email")
    assert policy.usage_allowed(frozenset({"steward"}), "sales.orders.email")


def test_typed_rls_template_and_additive_functions(tmp_path: Path) -> None:
    """Verify RLS parsing, function normalization, and saved-query expansion."""
    policy = load_policy(
        _write_policy(
            tmp_path,
            """connection: warehouse
allowed_functions: [regexp_replace]
rls:
  - driver: pg
    table: sales.orders
    predicate_template: "region IN (:subject.programs)"
    subject_attribute: programs
saved_queries:
  - name: monthly_revenue
    verified_by: reviewer@example.test
    verified_at: 2026-10-19
    query:
      metrics: [revenue]
      time_dimensions: [{name: order_date, grain: month}]
""",
        ),
        _members(),
        {"sales.orders"},
    )
    assert policy.allowed_functions == ["REGEXP_REPLACE"]
    assert policy.saved_queries[0].query.model == "orders"
    assert len(policy.digest()) == 64

    with pytest.raises(SemanticPolicyError) as error:
        load_policy(
            _write_policy(
                tmp_path,
                """connection: warehouse
rls:
  - driver: pg
    table: sales.orders
    predicate_template: "EXISTS (SELECT 1)"
    subject_attribute: programs
""",
            ),
            _members(),
            {"sales.orders"},
        )
    assert error.value.code == "invalid_policy"


def test_mask_targets_column_exposed_only_through_metric(tmp_path: Path) -> None:
    """A mask may bind to a physical column behind a metric (issue:7e1d9700c5c1)."""
    content = "connection: warehouse\nmasks:\n  sales.orders.amount: {strategy: \"null\"}\n"
    with pytest.raises(SemanticPolicyError) as error:
        load_policy(_write_policy(tmp_path, content), _members(), {"sales.orders"})
    assert error.value.code == "unknown_member"
    columns = {"sales.orders": {"id", "region", "amount"}}
    policy = load_policy(_write_policy(tmp_path, content), _members(), {"sales.orders"}, columns)
    assert policy.mask_for(frozenset({"analyst"}), "sales.orders.amount") is not None
    with pytest.raises(SemanticPolicyError) as error:
        load_policy(
            _write_policy(tmp_path, "connection: warehouse\nmasks:\n  sales.orders.nope: {strategy: \"null\"}\n"),
            _members(),
            {"sales.orders"},
            columns,
        )
    assert error.value.code == "unknown_member"
