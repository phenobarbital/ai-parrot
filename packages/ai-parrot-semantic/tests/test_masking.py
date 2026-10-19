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


# --- FEAT-704 review fixes: masks bound to physical columns (C1) and alias + RLS masking (C2) ---------------

_PEOPLE_MODEL = """version: 1
models:
  - name: people
    table: dim.people
    primary_key: id
    dimensions:
      - {{name: email, type: categorical, sql: {email_sql}, metadata: {{data_type: TEXT}}}}
      - {{name: region, type: categorical, metadata: {{data_type: TEXT}}}}
    metrics:
      - {{name: n, agg: count, sql: "*"}}
"""

_PEOPLE_POLICY = """governed: true
connection: c
roles:
  analyst: {{metrics: [n], dimensions: [email, region], usage: [region]}}
masks:
  {mask_key}: {{strategy: hash, projection_roles: [admin], usage_roles: [admin]}}
rls:
  - driver: duckdb
    table: dim.people
    predicate_template: "region IN (:subject.programs)"
    subject_attribute: programs
    description: r
"""


def _people_pipeline(tmp_path, *, email_sql: str = "email", mask_key: str = "people.email"):
    """Load a one-table model with an RLS rule and a hashed email mask; return (model, pipeline, ctx)."""
    from unittest.mock import AsyncMock, MagicMock

    from parrot.auth import PermissionContext, RlsRegistry, UserSession
    from parrot.semantic.governance.pbac import PbacGate
    from parrot.semantic.governance.pipeline import GovernancePipeline
    from parrot.semantic.governance.rls import RlsPushdown
    from parrot.semantic.loader import SemanticModelLoader

    (tmp_path / "people.yml").write_text(_PEOPLE_MODEL.format(email_sql=email_sql))
    (tmp_path / "people.policy.yaml").write_text(_PEOPLE_POLICY.format(mask_key=mask_key))
    model = SemanticModelLoader(tmp_path, driver="duckdb").load()["people"]
    registry = RlsRegistry()
    for rule in model.policy.rls:
        registry.register(rule)
    guard = MagicMock()
    guard.authorize_source = AsyncMock()
    pbac = PbacGate(guard)
    pbac.available = True
    pipeline = GovernancePipeline(pbac=pbac, rls=RlsPushdown(registry), allowed_functions=frozenset())
    ctx = PermissionContext(
        session=UserSession(user_id="u", tenant_id="t", roles=frozenset({"analyst"}), metadata={"programs": ["EU"]})
    )
    return model, pipeline, ctx


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT p.email FROM dim.people AS p",
        "SELECT p.email FROM dim.people p",
        "WITH c AS (SELECT p.email AS e FROM dim.people p) SELECT e FROM c",
        "SELECT x FROM (SELECT p.email AS x FROM dim.people p) q",
    ],
)
async def test_mask_applies_to_aliased_table_wrapped_by_rls(tmp_path, sql: str) -> None:
    """C2: an alias that RLS moved onto its wrapper subquery must still be masked."""
    model, pipeline, ctx = _people_pipeline(tmp_path)
    governed = await pipeline.govern(sql, model=model, ctx=ctx, roles=frozenset({"analyst"}))
    assert governed.masked_columns == ("dim.people.email",)
    assert "MD5(" in governed.sql


@pytest.mark.asyncio
async def test_mask_binds_to_member_sql_column(tmp_path) -> None:
    """C1: a member whose sql differs from its name is masked and usage-restricted on the physical column."""
    from parrot.semantic.errors import SemanticAccessError

    model, pipeline, ctx = _people_pipeline(tmp_path, email_sql="email_address")
    governed = await pipeline.govern(
        "SELECT email_address FROM dim.people", model=model, ctx=ctx, roles=frozenset({"analyst"})
    )
    assert governed.masked_columns == ("dim.people.email_address",)
    with pytest.raises(SemanticAccessError, match="usage_denied"):
        await pipeline.govern(
            "SELECT region FROM dim.people WHERE email_address = 'a@b.c'",
            model=model,
            ctx=ctx,
            roles=frozenset({"analyst"}),
        )


def test_mask_with_unknown_table_is_rejected_at_load(tmp_path) -> None:
    """C1: a mistyped mask table must reject the policy instead of masking nothing."""
    from parrot.semantic.errors import SemanticPolicyError

    with pytest.raises(SemanticPolicyError, match="unknown_member"):
        _people_pipeline(tmp_path, mask_key="custmers.email")
