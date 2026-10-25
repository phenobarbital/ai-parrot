"""Regression contract: Governance composition and subject/provenance digest (M6d)."""

from pathlib import Path

import pytest

from parrot.auth import PermissionContext, RlsRegistry, RlsRule, UserSession
from parrot.auth.exceptions import AuthorizationRequired
from parrot.semantic.errors import SemanticAccessError, SemanticValidationError
from parrot.semantic.governance import pbac
from parrot.semantic.governance.pbac import PbacGate
from parrot.semantic.governance.pipeline import GovernancePipeline, subject_digest
from parrot.semantic.governance.rls import RlsPushdown
from parrot.semantic.loader import SemanticModelLoader
from parrot.tools.dataset_manager.sources.resolver import PhysicalResources

from ._models import models_dir  # noqa: F401  (pytest fixture)

SQL = (
    "SELECT orders.region AS region, SUM(orders.amount) AS revenue "
    "FROM sales.orders AS orders GROUP BY orders.region"
)


class _Guard:
    """Deterministic PBAC double recording every authorization."""

    def __init__(self, *, deny: bool = False) -> None:
        self._evaluator = object()
        self.deny = deny
        self.calls: list[PhysicalResources] = []

    async def authorize_source(self, ctx: object, resources: PhysicalResources) -> None:
        """Record or deny."""
        self.calls.append(resources)
        if self.deny:
            raise AuthorizationRequired("semantic_query", "denied")


def _ctx(roles: frozenset[str] = frozenset({"admin"}), **metadata: object) -> PermissionContext:
    """Build a trusted subject."""
    return PermissionContext(
        session=UserSession(user_id="u1", tenant_id="t1", roles=roles, metadata=dict(metadata or {"programs": ["eu"]}))
    )


def _pipeline(monkeypatch: pytest.MonkeyPatch, guard: _Guard) -> GovernancePipeline:
    """Build a pipeline with the fixture RLS rule and an available PBAC gate."""
    monkeypatch.setattr(pbac.importlib.util, "find_spec", lambda module: object())
    registry = RlsRegistry()
    registry.register(
        RlsRule(
            driver="duckdb",
            table="sales.orders",
            predicate_template="region IN (:subject.programs)",
            subject_attribute="programs",
            description="orders by program",
        )
    )
    return GovernancePipeline(pbac=PbacGate(guard), rls=RlsPushdown(registry), allowed_functions=frozenset())


@pytest.mark.asyncio
async def test_fixed_order_and_input_immutability(
    tmp_path: Path, models_dir: Path, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    """Verify fixed order and input immutability."""
    model = SemanticModelLoader(models_dir, driver="duckdb").load()["orders"]
    before = model.model_dump(mode="json")
    guard = _Guard()
    pipeline = _pipeline(monkeypatch, guard)
    sql = str(SQL)
    first = await pipeline.govern(sql, model=model, ctx=_ctx(), roles=frozenset({"admin"}))
    second = await pipeline.govern(sql, model=model, ctx=_ctx(), roles=frozenset({"admin"}))
    assert sql == SQL
    assert model.model_dump(mode="json") == before
    assert len(guard.calls) == 2  # PBAC awaited on every request
    assert first == second
    assert first.rls_applied == ("orders by program",)
    assert "'eu'" in first.sql and "LIMIT 1000" in first.sql
    assert first.limit == 1000
    assert first.tables == ("sales.orders",)


@pytest.mark.asyncio
async def test_typed_subject_digest_and_provenance(
    tmp_path: Path, models_dir: Path, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    """Verify typed subject digest and provenance."""
    a = _ctx(frozenset({"b", "a"}), level=1)
    b = _ctx(frozenset({"a", "b"}), level=1)
    c = _ctx(frozenset({"a", "b"}), level="1")
    assert subject_digest(a) == subject_digest(b)
    assert subject_digest(a) != subject_digest(c)
    assert subject_digest(None) != subject_digest(a)
    with pytest.raises(SemanticAccessError) as error:
        subject_digest(_ctx(level=object()))
    assert error.value.code == "unstable_subject"

    model = SemanticModelLoader(models_dir, driver="duckdb").load()["orders"]
    pipeline = _pipeline(monkeypatch, _Guard())
    governed = await pipeline.govern(
        "SELECT orders.region AS r, SUM(orders.amount) AS x FROM sales.orders AS orders "
        "WHERE orders.region = 'eu' GROUP BY orders.region",
        model=model,
        ctx=_ctx(),
        roles=frozenset({"admin"}),
    )
    assert governed.members == ("region", "revenue")
    assert governed.physical_columns == ("sales.orders.amount", "sales.orders.region")
    assert governed.subject_digest == subject_digest(_ctx())


@pytest.mark.asyncio
async def test_denials_never_return_partial_sql(
    tmp_path: Path, models_dir: Path, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    """Verify denials never return partial sql."""
    model = SemanticModelLoader(models_dir, driver="duckdb").load()["orders"]
    pipeline = _pipeline(monkeypatch, _Guard(deny=True))
    with pytest.raises(SemanticAccessError) as error:
        await pipeline.govern(SQL, model=model, ctx=_ctx(), roles=frozenset({"admin"}))
    assert error.value.code == "pbac_denied"

    pipeline = _pipeline(monkeypatch, _Guard())
    with pytest.raises(SemanticAccessError) as error:
        await pipeline.govern(SQL, model=model, ctx=None, roles=frozenset())
    assert error.value.code == "no_subject"
    with pytest.raises(SemanticAccessError) as error:
        await pipeline.govern(
            "SELECT SUM(orders.amount) AS x FROM sales.orders AS orders WHERE orders.amount > 5",
            model=model,
            ctx=_ctx(frozenset({"analyst"})),
            roles=frozenset({"analyst"}),
        )
    assert error.value.code == "usage_denied"
    with pytest.raises(SemanticValidationError):
        await pipeline.govern("DELETE FROM sales.orders", model=model, ctx=_ctx(), roles=frozenset({"admin"}))
    with pytest.raises(SemanticValidationError) as error:
        await pipeline.govern(
            "SELECT MD5(orders.region) AS h FROM sales.orders AS orders",
            model=model,
            ctx=_ctx(),
            roles=frozenset({"admin"}),
        )
    assert error.value.code == "function_not_allowed"
