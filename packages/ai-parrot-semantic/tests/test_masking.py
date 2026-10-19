"""Projection masking strategy tests."""

from __future__ import annotations

import pytest
import sqlglot
from sqlglot.optimizer.qualify import qualify

from parrot.semantic.governance.lineage import resolve_column_uses
from parrot.semantic.governance.masking import apply_masks
from parrot.semantic.loader import PhysicalSchema
from parrot.semantic.policy import ModelPolicy

SCHEMA = PhysicalSchema(driver="duckdb", tables={"sales.customers": {"email": "TEXT"}})


@pytest.mark.parametrize(
    ("strategy", "expected"),
    [
        ("null", "CAST(NULL AS"),
        ("hash", "MD5(CAST"),
        ("partial", "REPEAT('*', LENGTH"),
    ],
)
@pytest.mark.parametrize("dialect", ["postgres", "bigquery", "duckdb"])
def test_masking_strategies(strategy: str, expected: str, dialect: str) -> None:
    """Rewrite each strategy and preserve the original output name."""
    tree = qualify(
        sqlglot.parse_one("SELECT email AS contact FROM sales.customers", dialect=dialect),
        schema=SCHEMA.sqlglot_schema(),
        dialect=dialect,
    )
    uses = resolve_column_uses(tree, SCHEMA)
    policy = ModelPolicy(
        connection="warehouse",
        masks={"customers.email": {"strategy": strategy, "projection_roles": [], "usage_roles": []}},
    )

    masked, columns, trusted = apply_masks(tree, uses, policy, frozenset({"analyst"}), dialect)
    rendered = masked.sql(dialect=dialect)

    assert expected in rendered
    assert masked.expressions[0].alias_or_name == "contact"
    assert columns == ("sales.customers.email",)
    assert trusted == {id(node) for node in masked.expressions[0].walk()}


def test_projection_role_bypasses_mask() -> None:
    """Leave the projection unchanged for a role permitted to see cleartext."""
    tree = qualify(
        sqlglot.parse_one("SELECT email FROM sales.customers", dialect="duckdb"),
        schema=SCHEMA.sqlglot_schema(),
        dialect="duckdb",
    )
    uses = resolve_column_uses(tree, SCHEMA)
    policy = ModelPolicy(
        connection="warehouse",
        masks={"customers.email": {"strategy": "hash", "projection_roles": ["admin"]}},
    )

    original = tree.sql()
    masked, columns, trusted = apply_masks(tree, uses, policy, frozenset({"admin"}), "duckdb")

    assert masked.sql() == original
    assert columns == ()
    assert trusted == set()


def test_repeated_projection_is_fully_masked() -> None:
    """Mask every projected occurrence even when lineage deduplicates the physical use."""
    tree = qualify(
        sqlglot.parse_one("SELECT email AS primary_email, email AS backup_email FROM sales.customers"),
        schema=SCHEMA.sqlglot_schema(),
        dialect="duckdb",
    )
    policy = ModelPolicy(connection="warehouse", masks={"customers.email": {"strategy": "hash"}})

    masked, columns, _ = apply_masks(
        tree,
        resolve_column_uses(tree, SCHEMA),
        policy,
        frozenset({"analyst"}),
        "duckdb",
    )

    assert masked.sql().count("MD5") == 2
    assert columns == ("sales.customers.email",)
