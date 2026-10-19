"""Tests for semantic-model policy parsing and role answers."""

from __future__ import annotations

import pytest

from parrot.semantic.errors import SemanticPolicyError
from parrot.semantic.models import ModelMember
from parrot.semantic.policy import ModelPolicy, load_policy

MEMBERS = [
    ModelMember(name="revenue", kind="metric"),
    ModelMember(name="region", kind="dimension"),
    ModelMember(name="order_date", kind="time_dimension"),
]
TABLES = {"sales.orders", "dim.customers"}


def test_policy_unknown_member_rejected(tmp_path) -> None:
    """Reject grants referencing semantic members that the model does not declare."""
    path = tmp_path / "orders.policy.yaml"
    path.write_text("connection: wh\nroles:\n  analyst: {metrics: [revenu]}\n")
    with pytest.raises(SemanticPolicyError, match="unknown_member"):
        load_policy(path, MEMBERS, TABLES)


def test_policy_defaults_governed(tmp_path) -> None:
    """Default policies are governed and an explicit opt-out needs no connection."""
    governed = tmp_path / "governed.policy.yaml"
    governed.write_text("connection: wh\n")
    assert load_policy(governed, MEMBERS, TABLES).governed is True

    ungoverned = tmp_path / "ungoverned.policy.yaml"
    ungoverned.write_text("governed: false\n")
    assert load_policy(ungoverned, MEMBERS, TABLES).governed is False

    missing_connection = tmp_path / "missing-connection.policy.yaml"
    missing_connection.write_text("governed: true\n")
    with pytest.raises(SemanticPolicyError, match="missing_connection"):
        load_policy(missing_connection, MEMBERS, TABLES)


def test_policy_allowed_functions_additive(tmp_path) -> None:
    """Normalize additive function extensions and reject unsafe function tokens."""
    path = tmp_path / "functions.policy.yaml"
    path.write_text("connection: wh\nallowed_functions: [regexp_replace]\n")
    assert load_policy(path, MEMBERS, TABLES).allowed_functions == ["REGEXP_REPLACE"]

    invalid = tmp_path / "invalid-functions.policy.yaml"
    invalid.write_text("connection: wh\nallowed_functions: ['x; drop']\n")
    with pytest.raises(SemanticPolicyError, match="invalid_function"):
        load_policy(invalid, MEMBERS, TABLES)


def test_policy_role_answers_and_masks() -> None:
    """Apply wildcard grants and mask-specific projection and usage permissions."""
    policy = ModelPolicy.model_validate(
        {
            "roles": {"admin": {"metrics": "*", "dimensions": "*", "usage": "*"}},
            "masks": {"customers.region": {"strategy": "hash", "projection_roles": [], "usage_roles": []}},
        }
    )
    roles = frozenset({"admin"})
    assert policy.allowed_members(roles, MEMBERS) == {"revenue", "region", "order_date"}
    assert policy.mask_for(roles, "customers.region") is not None
    assert policy.usage_allowed(roles, "customers.region") is False


def test_policy_rejects_multi_statement_rls_and_digest_is_stable(tmp_path) -> None:
    """Reject executable RLS text and produce canonical policy digests."""
    valid_path = tmp_path / "valid-rls.policy.yaml"
    valid_path.write_text(
        "connection: wh\nrls:\n"
        "  - driver: pg\n"
        "    table: sales.orders\n"
        "    predicate_template: 'region IN (:subject.programs)'\n"
        "    subject_attribute: programs\n"
    )
    assert load_policy(valid_path, MEMBERS, TABLES).rls[0].table == "sales.orders"

    path = tmp_path / "rls.policy.yaml"
    path.write_text(
        "connection: wh\nrls:\n"
        "  - driver: pg\n"
        "    table: sales.orders\n"
        "    predicate_template: 'region IN (:subject.programs); DROP TABLE x'\n"
        "    subject_attribute: programs\n"
    )
    with pytest.raises(SemanticPolicyError, match="invalid_rls_predicate"):
        load_policy(path, MEMBERS, TABLES)

    first = ModelPolicy.model_validate({"connection": "wh", "roles": {"analyst": {"metrics": ["revenue"]}}})
    second = ModelPolicy.model_validate({"roles": {"analyst": {"metrics": ["revenue"]}}, "connection": "wh"})
    assert first.digest() == second.digest()
