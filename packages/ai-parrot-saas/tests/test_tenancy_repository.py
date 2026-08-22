"""Tenant models, the tenant repository, and the isolation guardrail."""
from __future__ import annotations

import inspect
import re

import pytest
from asyncdb import AsyncDB

from parrot_saas.db.repository import BaseRepository, TenantScopeError
from parrot_saas.db.schema import ensure_schema
from parrot_saas.tenancy.context import TenantStatus
from parrot_saas.tenancy.models import Tenant, TenantCreate, TenantUpdate
from parrot_saas.tenancy.repository import (
    TenantAlreadyExists,
    TenantRepository,
)

# ---------------------------------------------------------------------------
# Models — no database
# ---------------------------------------------------------------------------


def test_tenant_to_context_drops_audit_fields() -> None:
    """The runtime view carries identity and settings, not timestamps."""
    tenant = Tenant(
        tenant_id="bar-pepe",
        name="Bar Pepe",
        timezone="Europe/Madrid",
        settings={"max_revise_rounds": 3},
    )

    ctx = tenant.to_context()

    assert ctx.tenant_id == "bar-pepe"
    assert ctx.timezone == "Europe/Madrid"
    assert ctx.setting("max_revise_rounds") == 3
    assert not hasattr(ctx, "created_at")


@pytest.mark.parametrize(
    "slug", ["Bar-Pepe", "1bar", "b", "bar_pepe", "bar pepe", "", "a" * 64]
)
def test_invalid_slugs_are_rejected(slug: str) -> None:
    """The slug pattern is enforced on the stored model too, not just context."""
    with pytest.raises(ValueError, match="invalid tenant_id"):
        Tenant(tenant_id=slug, name="x")


def test_tenant_from_row_parses_json_settings() -> None:
    """Settings survive arriving as a JSON string from the driver."""
    tenant = Tenant.from_row(
        {"tenant_id": "bar-pepe", "name": "Bar Pepe", "settings": '{"a": 1}'}
    )

    assert tenant.settings == {"a": 1}


def test_tenant_from_row_tolerates_null_settings() -> None:
    """A NULL settings column becomes an empty mapping, not None."""
    tenant = Tenant.from_row(
        {"tenant_id": "bar-pepe", "name": "Bar Pepe", "settings": None}
    )

    assert tenant.settings == {}


def test_update_changes_only_reports_set_fields() -> None:
    """An unset field means 'leave alone', not 'set to null'."""
    assert TenantUpdate().changes() == {}
    assert TenantUpdate(name="New").changes() == {"name": "New"}


def test_update_cannot_rename_a_tenant() -> None:
    """`tenant_id` is absent from the update payload by design.

    A slug appears in provisioned stack names, Docker object names and the AAD
    of every stored secret, so renaming is a migration rather than an edit.
    """
    assert "tenant_id" not in TenantUpdate.model_fields


# ---------------------------------------------------------------------------
# The isolation guardrail — no database
# ---------------------------------------------------------------------------


async def test_tenant_scoped_helper_rejects_sql_without_predicate() -> None:
    """Passing the right argument to a query that ignores it must fail."""
    repo = BaseRepository("postgres://unused", schema="saas")

    with pytest.raises(TenantScopeError, match="does not reference tenant_id"):
        await repo.fetch_all("bar-pepe", "SELECT * FROM saas.tenants")


async def test_all_three_scoped_helpers_are_guarded() -> None:
    """The guard is on every data helper, not just the one that was tested."""
    repo = BaseRepository("postgres://unused", schema="saas")

    for call in (
        repo.fetch_one("t", "SELECT 1"),
        repo.fetch_all("t", "SELECT 1"),
        repo.execute("t", "DELETE FROM saas.tenants"),
    ):
        with pytest.raises(TenantScopeError):
            await call


def test_scoped_helpers_take_tenant_id_first_and_without_default() -> None:
    """A caller must not be able to forget the tenant.

    Enforced structurally rather than by review: if someone gives ``tenant_id``
    a default, or moves it after another parameter, this fails.
    """
    for name in ("fetch_one", "fetch_all", "execute"):
        params = list(inspect.signature(getattr(BaseRepository, name)).parameters)
        assert params[1] == "tenant_id", name
        default = inspect.signature(
            getattr(BaseRepository, name)
        ).parameters["tenant_id"].default
        assert default is inspect.Parameter.empty, name


#: Methods permitted to reach across tenants, each with the reason why.
#: Adding a name here is the deliberate act the ``admin_*`` naming exists to
#: force; the test below makes it the *only* way.
_CROSS_TENANT_METHODS = {
    # Onboarding: the row does not exist yet, so it cannot be scoped to.
    "create",
    # The control plane's own view of every tenant.
    "list_tenants",
}


def test_every_repository_method_is_scoped_or_declared_cross_tenant() -> None:
    """Isolation must be auditable, not remembered.

    For each public method of :class:`TenantRepository`, assert that it either
    goes through the tenant-scoped helpers (which bind ``tenant_id`` as ``$1``
    and reject SQL without a tenant predicate) or is listed in
    :data:`_CROSS_TENANT_METHODS`. A new method that quietly calls
    ``admin_fetch_all`` fails here rather than in production.
    """
    scoped_helpers = ("self.fetch_one(", "self.fetch_all(", "self.execute(")
    admin_helpers = (
        "self.admin_fetch_one(",
        "self.admin_fetch_all(",
        "self.admin_execute(",
    )

    checked = 0
    for name, member in vars(TenantRepository).items():
        if name.startswith("_") or not inspect.isfunction(member):
            continue
        body = inspect.getsource(member)
        uses_admin = any(helper in body for helper in admin_helpers)
        uses_scoped = any(helper in body for helper in scoped_helpers)
        delegates = re.search(r"return await self\.\w+\(", body) is not None

        if uses_admin:
            assert name in _CROSS_TENANT_METHODS, (
                f"{name}() reaches across tenants but is not declared in "
                "_CROSS_TENANT_METHODS — if that is intended, add it there "
                "with a reason"
            )
        else:
            assert uses_scoped or delegates, (
                f"{name}() touches neither a scoped helper nor another "
                "repository method; it may be issuing unscoped SQL"
            )
        checked += 1

    assert checked >= 6, "expected to inspect the repository's public methods"


def test_declared_cross_tenant_methods_still_exist() -> None:
    """Keep the allow-list honest as the repository evolves."""
    for name in _CROSS_TENANT_METHODS:
        assert hasattr(TenantRepository, name), (
            f"_CROSS_TENANT_METHODS names {name!r}, which no longer exists"
        )


# ---------------------------------------------------------------------------
# Repository — needs Postgres
# ---------------------------------------------------------------------------

integration = pytest.mark.integration


@pytest.fixture
async def tenant_repo(test_dsn: str, unique_schema: str):
    """A TenantRepository over a throwaway schema."""
    conn = AsyncDB("pg", dsn=test_dsn)
    async with await conn.connection():
        await ensure_schema(conn, schema=unique_schema)
    repo = TenantRepository(test_dsn, schema=unique_schema)
    try:
        yield repo
    finally:
        await repo.aclose()
        conn = AsyncDB("pg", dsn=test_dsn)
        async with await conn.connection():
            await conn.execute(f"DROP SCHEMA IF EXISTS {unique_schema} CASCADE")


@integration
async def test_create_and_get(tenant_repo) -> None:
    """A created tenant round-trips."""
    created = await tenant_repo.create(
        TenantCreate(
            tenant_id="bar-pepe",
            name="Bar Pepe",
            timezone="Europe/Madrid",
            settings={"max_revise_rounds": 3},
        )
    )

    assert created.tenant_id == "bar-pepe"
    fetched = await tenant_repo.get("bar-pepe")
    assert fetched is not None
    assert fetched.name == "Bar Pepe"
    assert fetched.settings == {"max_revise_rounds": 3}
    assert fetched.to_context().timezone == "Europe/Madrid"


@integration
async def test_get_unknown_returns_none(tenant_repo) -> None:
    """An unknown slug is None, not an error."""
    assert await tenant_repo.get("nobody") is None


@integration
async def test_duplicate_slug_raises(tenant_repo) -> None:
    """Onboarding the same slug twice is a domain error, not a driver error."""
    await tenant_repo.create(TenantCreate(tenant_id="bar-pepe", name="A"))

    with pytest.raises(TenantAlreadyExists, match="already exists"):
        await tenant_repo.create(TenantCreate(tenant_id="bar-pepe", name="B"))


@integration
async def test_update_applies_only_given_fields(tenant_repo) -> None:
    """A partial patch leaves everything else alone."""
    await tenant_repo.create(
        TenantCreate(
            tenant_id="bar-pepe", name="Bar Pepe", settings={"keep": True}
        )
    )

    updated = await tenant_repo.update(
        "bar-pepe", TenantUpdate(name="Bar Pepe II")
    )

    assert updated is not None
    assert updated.name == "Bar Pepe II"
    assert updated.settings == {"keep": True}
    assert updated.timezone == "UTC"


@integration
async def test_update_settings_replaces_the_document(tenant_repo) -> None:
    """Settings are replaced wholesale, not merged — stated and tested."""
    await tenant_repo.create(
        TenantCreate(tenant_id="bar-pepe", name="x", settings={"a": 1})
    )

    updated = await tenant_repo.update(
        "bar-pepe", TenantUpdate(settings={"b": 2})
    )

    assert updated is not None
    assert updated.settings == {"b": 2}


@integration
async def test_empty_patch_is_a_noop(tenant_repo) -> None:
    """An empty patch returns the tenant unchanged rather than failing."""
    await tenant_repo.create(TenantCreate(tenant_id="bar-pepe", name="x"))

    assert (await tenant_repo.update("bar-pepe", TenantUpdate())).name == "x"


@integration
async def test_update_unknown_returns_none(tenant_repo) -> None:
    """Patching a missing tenant is None, not a silent create."""
    assert await tenant_repo.update("nobody", TenantUpdate(name="x")) is None


@integration
async def test_delete_is_a_soft_suspend(tenant_repo) -> None:
    """Retiring a tenant must not orphan its coupons, replies or stacks."""
    await tenant_repo.create(TenantCreate(tenant_id="bar-pepe", name="x"))

    suspended = await tenant_repo.delete("bar-pepe")

    assert suspended is not None
    assert suspended.status == TenantStatus.SUSPENDED.value
    still_there = await tenant_repo.get("bar-pepe")
    assert still_there is not None
    assert still_there.to_context().is_active is False


@integration
async def test_list_tenants_and_status_filter(tenant_repo) -> None:
    """The control-plane listing spans tenants and can filter by lifecycle."""
    await tenant_repo.create(TenantCreate(tenant_id="aaa-bar", name="A"))
    await tenant_repo.create(TenantCreate(tenant_id="zzz-hotel", name="Z"))
    await tenant_repo.delete("zzz-hotel")

    everyone = await tenant_repo.list_tenants()
    active = await tenant_repo.list_tenants(status=TenantStatus.ACTIVE)

    assert [t.tenant_id for t in everyone] == ["aaa-bar", "zzz-hotel"]
    assert [t.tenant_id for t in active] == ["aaa-bar"]


@integration
async def test_get_cannot_see_another_tenant(tenant_repo) -> None:
    """The scoped read really is scoped."""
    await tenant_repo.create(TenantCreate(tenant_id="bar-pepe", name="A"))
    await tenant_repo.create(TenantCreate(tenant_id="hotel-x", name="B"))

    assert (await tenant_repo.get("bar-pepe")).name == "A"
    assert (await tenant_repo.get("hotel-x")).name == "B"


@integration
async def test_ensure_schema_is_idempotent(test_dsn: str, unique_schema: str) -> None:
    """Running the DDL twice is free, which is what makes boot-time safe."""
    conn = AsyncDB("pg", dsn=test_dsn)
    try:
        async with await conn.connection():
            await ensure_schema(conn, schema=unique_schema)
            await ensure_schema(conn, schema=unique_schema)
            row = await conn.fetch_one(
                "SELECT count(*) AS n FROM information_schema.tables "
                "WHERE table_schema = $1 AND table_name = 'tenants'",
                unique_schema,
            )
        assert int(row["n"]) == 1
    finally:
        conn = AsyncDB("pg", dsn=test_dsn)
        async with await conn.connection():
            await conn.execute(f"DROP SCHEMA IF EXISTS {unique_schema} CASCADE")


def test_ensure_schema_rejects_unsafe_schema_name() -> None:
    """Schema names are interpolated, so they are validated."""
    import asyncio

    with pytest.raises(ValueError, match="unsafe schema name"):
        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            ensure_schema(object(), schema="saas; DROP TABLE x")  # type: ignore[arg-type]
        )
