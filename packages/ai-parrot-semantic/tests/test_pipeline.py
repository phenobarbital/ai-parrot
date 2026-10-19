"""Tests for the fixed-order semantic governance pipeline."""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.auth import PermissionContext, RlsRegistry, RlsRule
from parrot.semantic.errors import SemanticAccessError, SemanticValidationError
from parrot.semantic.governance.pbac import PbacGate
from parrot.semantic.governance.pipeline import GovernancePipeline, subject_digest
from parrot.semantic.governance.rls import RlsPushdown
from parrot.semantic.loader import LoadedModel, PhysicalSchema
from parrot.semantic.models import Limits, ModelMember
from parrot.semantic.policy import ModelPolicy, RoleGrant


def _model(*, governed: bool = True) -> LoadedModel:
    """Build a minimal physical model suitable for pipeline-level tests."""
    return LoadedModel(
        name="orders",
        layer=object(),
        policy=ModelPolicy(
            governed=governed,
            connection="warehouse" if governed else None,
            limits=Limits(default=25, max=100),
            roles={"analyst": RoleGrant(dimensions=["region"], usage=["region", "amount", "tenant_id"])},
        ),
        members=[ModelMember(name="region", kind="dimension")],
        schema=PhysicalSchema(
            driver="duckdb",
            tables={"sales.orders": {"region": "TEXT", "amount": "DOUBLE", "tenant_id": "TEXT"}},
        ),
        model_digest="model",
        policy_digest="policy",
        engine_version="test",
    )


def _pipeline(*, registry: RlsRegistry | None = None) -> tuple[GovernancePipeline, MagicMock]:
    """Build a pipeline whose PBAC dependency authorizes every request."""
    guard = MagicMock()
    guard.authorize_source = AsyncMock()
    pbac = PbacGate(guard)
    pbac.available = True
    return (
        GovernancePipeline(pbac=pbac, rls=RlsPushdown(registry or RlsRegistry()), allowed_functions=frozenset()),
        guard,
    )


def test_subject_digest_includes_metadata(pctx_factory: Callable[..., PermissionContext]) -> None:
    """Metadata excluded from UserSession hashing remains part of the subject digest."""
    first = pctx_factory(programs=["n"])
    second = pctx_factory(programs=["s"])

    assert subject_digest(first) != subject_digest(second)


@pytest.mark.asyncio
async def test_govern_order_and_clone(
    pctx_factory: Callable[..., PermissionContext], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Apply all governed stages to a fresh AST and preserve the source SQL string."""
    import parrot.semantic.governance.pipeline as pipeline_module

    pipeline, guard = _pipeline()
    order: list[str] = []
    original_validate = pipeline_module.QueryValidator.validate_sql_ast
    original_qualify = pipeline_module.qualify
    original_resources = pipeline_module.resources_from_ast
    original_resolve = pipeline_module.resolve_column_uses
    original_enforce = pipeline_module.enforce_usage_rights
    original_apply = pipeline.rls.apply
    original_masks = pipeline_module.apply_masks
    original_guard = pipeline_module.PositiveGuard.check_and_limit

    def validate(*args: object, **kwargs: object) -> dict[str, object]:
        order.append("validate")
        return original_validate(*args, **kwargs)

    def qualified(*args: object, **kwargs: object):
        order.append("qualify")
        return original_qualify(*args, **kwargs)

    def resources(*args: object, **kwargs: object):
        order.append("resources")
        return original_resources(*args, **kwargs)

    def resolve(*args: object, **kwargs: object):
        order.append("lineage")
        return original_resolve(*args, **kwargs)

    def enforce(*args: object, **kwargs: object) -> None:
        order.append("usage")
        original_enforce(*args, **kwargs)

    def apply(*args: object, **kwargs: object):
        order.append("rls")
        return original_apply(*args, **kwargs)

    def masks(*args: object, **kwargs: object):
        order.append("masks")
        return original_masks(*args, **kwargs)

    def positive_guard(*args: object, **kwargs: object):
        order.append("guard")
        return original_guard(*args, **kwargs)

    monkeypatch.setattr(pipeline_module.QueryValidator, "validate_sql_ast", validate)
    monkeypatch.setattr(pipeline_module, "qualify", qualified)
    monkeypatch.setattr(pipeline_module, "resources_from_ast", resources)
    monkeypatch.setattr(pipeline_module, "resolve_column_uses", resolve)
    monkeypatch.setattr(pipeline_module, "enforce_usage_rights", enforce)
    monkeypatch.setattr(pipeline.rls, "apply", apply)
    monkeypatch.setattr(pipeline_module, "apply_masks", masks)
    monkeypatch.setattr(pipeline_module.PositiveGuard, "check_and_limit", positive_guard)

    sql = "SELECT region, SUM(amount) AS total FROM sales.orders GROUP BY region"
    governed = await pipeline.govern(sql, model=_model(), ctx=pctx_factory(), roles=frozenset({"analyst"}))

    assert sql == "SELECT region, SUM(amount) AS total FROM sales.orders GROUP BY region"
    assert order == ["validate", "qualify", "resources", "lineage", "usage", "rls", "masks", "guard"]
    assert governed.sql.endswith("LIMIT 25")
    assert governed.tables == ("sales.orders",)
    guard.authorize_source.assert_awaited()


@pytest.mark.asyncio
async def test_govern_denies_without_ctx() -> None:
    """Governed models fail closed before PBAC can authorize an anonymous subject."""
    pipeline, guard = _pipeline()

    with pytest.raises(SemanticAccessError, match="no_subject"):
        await pipeline.govern("SELECT region FROM sales.orders", model=_model(), ctx=None, roles=frozenset({"analyst"}))

    guard.authorize_source.assert_not_awaited()


@pytest.mark.asyncio
async def test_ungoverned_still_guarded(pctx_factory: Callable[..., PermissionContext]) -> None:
    """Ungoverned models skip PBAC/RLS/lineage but remain subject to the positive guard."""
    pipeline, guard = _pipeline()

    governed = await pipeline.govern(
        "SELECT region FROM sales.orders", model=_model(governed=False), ctx=pctx_factory(), roles=frozenset()
    )
    assert governed.rls_applied == ()
    assert governed.sql.endswith("LIMIT 25")
    guard.authorize_source.assert_not_awaited()

    with pytest.raises(SemanticValidationError, match="function_not_allowed"):
        await pipeline.govern(
            "SELECT RANDOM() FROM sales.orders", model=_model(governed=False), ctx=None, roles=frozenset()
        )


@pytest.mark.asyncio
async def test_cache_hit_re_governs_for_each_subject(pctx_factory: Callable[..., PermissionContext]) -> None:
    """The same pre-governance SQL receives fresh RLS literals for each subject."""
    registry = RlsRegistry()
    registry.register(
        RlsRule(
            driver="duckdb",
            table="sales.orders",
            predicate_template="region = :subject.programs",
            subject_attribute="programs",
            description="regional orders",
        )
    )
    pipeline, _ = _pipeline(registry=registry)
    sql = "SELECT region, SUM(amount) AS total FROM sales.orders GROUP BY region"

    europe = await pipeline.govern(sql, model=_model(), ctx=pctx_factory(programs=["EU"]), roles=frozenset({"analyst"}))
    united_states = await pipeline.govern(
        sql, model=_model(), ctx=pctx_factory(programs=["US"]), roles=frozenset({"analyst"})
    )

    assert sql == "SELECT region, SUM(amount) AS total FROM sales.orders GROUP BY region"
    assert "'EU'" in europe.sql
    assert "'US'" in united_states.sql
    assert europe.subject_digest != united_states.subject_digest


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sql", "raw_sql", "denied"),
    [
        ("SELECT tenant_id FROM sales.orders", False, True),
        ("SELECT tenant_id FROM sales.orders", True, True),
        ("SELECT UPPER(tenant_id) AS t FROM sales.orders", True, True),
        ("SELECT region FROM sales.orders", True, False),
        ("SELECT region FROM sales.orders WHERE tenant_id = 't1'", True, False),
    ],
)
async def test_projection_requires_granted_member(
    pctx_factory: Callable[..., PermissionContext], sql: str, raw_sql: bool, denied: bool
) -> None:
    """issue:4adcfffcd99a: returned columns must back a granted member; raw SQL also gates derived outputs."""
    pipeline, _ = _pipeline()
    model = _model()
    model.members.append(ModelMember(name="tenant_id", kind="dimension"))
    call = pipeline.govern(sql, model=model, ctx=pctx_factory(), roles=frozenset({"analyst"}), raw_sql=raw_sql)
    if denied:
        with pytest.raises(SemanticAccessError, match="member_not_granted"):
            await call
    else:
        assert (await call).sql
