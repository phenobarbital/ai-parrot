"""FEAT-598 TASK-3783 — SlugCatalog resolves tenant slugs through DefinitionRepository."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from parrot_tools.querysource import _qs
from parrot_tools.querysource.catalog import SlugCatalog, TenantGuard
from parrot_tools.querysource.errors import SlugNotFoundError, TenantDeniedError


class _TenantError(Exception):
    def __init__(self, message: str, *, error_code: str) -> None:
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True)
class _Identity:
    store: object
    slug: str


class FakeRepo:
    """Records identities; stores = {schema: {slug: runtime}}."""

    def __init__(self, stores: dict[str, dict[str, object]]) -> None:
        self.stores = stores
        self.identities: list[_Identity] = []
        self.registry = SimpleNamespace(resolve=self._resolve)

    def _resolve(self, tenant):
        if tenant in self.stores:
            return SimpleNamespace(schema=tenant, table="queries", contract="tenant")
        raise _TenantError(f"Tenant not found: {tenant}", error_code="tenant_not_available")

    async def get(self, identity):
        self.identities.append(identity)
        runtime = self.stores.get(identity.store.schema, {}).get(identity.slug)
        if runtime is None:
            raise _TenantError(f"Query not found: {identity.slug!r}", error_code="query_not_found")
        return SimpleNamespace(runtime=runtime)

    async def list(self, store, params):
        rows = tuple(
            {
                "query_slug": slug,
                "description": getattr(runtime, "description", None),
                "provider": getattr(runtime, "provider", "db"),
                "is_cached": getattr(runtime, "is_cached", True),
                "cache_timeout": getattr(runtime, "cache_timeout", 3600),
                "conditions": {},
                "cond_definition": {},
                "filtering": {},
                "fields": [],
                "ordering": [],
                "grouping": [],
                "query_raw": getattr(runtime, "query_raw", None),
            }
            for slug, runtime in self.stores.get(store.schema, {}).items()
        )
        return SimpleNamespace(rows=rows, total=len(rows))


@pytest.fixture
def fake_repo(monkeypatch):
    runtime = SimpleNamespace(
        query_slug="epson_field_activity",
        description="Field activity",
        provider="db",
        is_cached=True,
        cache_timeout=3600,
        conditions={},
        cond_definition={},
        filtering={},
        fields=[],
        ordering=[],
        grouping=[],
        query_raw=None,
    )
    repo = FakeRepo({"acme": {"epson_field_activity": runtime}})
    monkeypatch.setattr(_qs, "get_tenants", lambda: SimpleNamespace(QueryIdentity=_Identity, TenantError=_TenantError))

    async def _get_definition_repository():
        return repo

    monkeypatch.setattr(_qs, "get_definition_repository", _get_definition_repository)
    return repo


async def test_catalog_get_tenant_uses_definition_repository(fake_repo):
    catalog = SlugCatalog("postgres://fake", TenantGuard(None))
    rec = await catalog.get("epson_field_activity", tenant="acme")
    assert fake_repo.identities[-1].slug == "epson_field_activity"
    assert rec.program_slug == "acme"  # program_slug == schema for tenant stores


async def test_catalog_tenant_allowlist_applies(fake_repo):
    catalog = SlugCatalog("postgres://fake", TenantGuard(["epson"]))
    with pytest.raises(TenantDeniedError):
        await catalog.get_allowed("epson_field_activity", tenant="acme")


async def test_catalog_tenant_errors_map_to_slug_not_found(fake_repo):
    catalog = SlugCatalog("postgres://fake", TenantGuard(None))
    with pytest.raises(SlugNotFoundError):
        await catalog.get("epson_field_activity", tenant="unknown-tenant")
    with pytest.raises(SlugNotFoundError):
        await catalog.get("no-such-slug", tenant="acme")


async def test_catalog_list_tenant(fake_repo):
    catalog = SlugCatalog("postgres://fake", TenantGuard(None))
    records = await catalog.list(search=None, program=None, limit=10, tenant="acme")
    assert [r.slug for r in records] == sorted(r.slug for r in records)
    assert all(r.program_slug == "acme" for r in records)


async def test_catalog_tenant_none_keeps_query_model_path(patched_qs):
    rec = await SlugCatalog("postgres://fake", TenantGuard(None)).get("epson_field_activity")
    assert rec.program_slug == "epson" and patched_qs["get"]
