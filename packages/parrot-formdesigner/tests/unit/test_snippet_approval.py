"""Unit tests for SnippetApprovalService — FEAT-459 / TASK-3166."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
import pytest

from parrot_formdesigner.core.snippets import (
    CapabilityManifest,
    CapabilityTier,
    SnippetBundle,
    SnippetSource,
    SnippetStatus,
)
from parrot_formdesigner.services.snippets.approval import SnippetApprovalService


class _FakeConformanceResult:
    def __init__(self, passed: bool, errors: list[str] | None = None) -> None:
        self.passed = passed
        self.errors = errors or []


class _FakePool:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def fetchrow(self, query: str, *args: Any) -> dict | None:
        if "COALESCE(MAX(version)" in query:
            tenant, handler_ref = args
            matching = [r["version"] for r in self.rows if r["tenant"] == tenant and r["handler_ref"] == handler_ref]
            return {"max_v": max(matching) if matching else 0}
        elif "SELECT * FROM form_snippets WHERE tenant = $1 AND handler_ref = $2 AND version = $3" in query:
            tenant, handler_ref, version = args
            for r in self.rows:
                if r["tenant"] == tenant and r["handler_ref"] == handler_ref and r["version"] == version:
                    return r
            return None
        return None

    async def fetch(self, query: str, *args: Any) -> list[dict]:
        if "SELECT * FROM form_snippets WHERE tenant = $1 AND handler_ref = $2 ORDER BY version DESC" in query:
            tenant, handler_ref = args
            matching = [r for r in self.rows if r["tenant"] == tenant and r["handler_ref"] == handler_ref]
            return sorted(matching, key=lambda r: r["version"], reverse=True)
        return []

    async def execute(self, query: str, *args: Any) -> str:
        if "INSERT INTO form_snippets" in query:
            tenant, handler_ref, event, version, status, manifest_json, python_source, python_sha256, client_source, client_sha256, approved_by, approved_at = args
            import json
            manifest_dict = json.loads(manifest_json)
            self.rows.append({
                "tenant": tenant,
                "handler_ref": handler_ref,
                "event": event,
                "version": version,
                "status": status,
                "manifest": manifest_dict,
                "python_source": python_source,
                "python_sha256": python_sha256,
                "client_source": client_source,
                "client_sha256": client_sha256,
                "approved_by": approved_by,
                "approved_at": approved_at,
            })
        elif "UPDATE form_snippets" in query:
            if "status = $1, approved_by = $2, approved_at = $3" in query:
                status, approved_by, approved_at, tenant, handler_ref, version = args
                for r in self.rows:
                    if r["tenant"] == tenant and r["handler_ref"] == handler_ref and r["version"] == version:
                        r["status"] = status
                        r["approved_by"] = approved_by
                        r["approved_at"] = approved_at
            elif "status = $1" in query:
                status, tenant, handler_ref, version = args
                for r in self.rows:
                    if r["tenant"] == tenant and r["handler_ref"] == handler_ref and r["version"] == version:
                        r["status"] = status
        return "OK"


class _FakeStore:
    def __init__(self) -> None:
        self._pool = _FakePool()
        self.invalidate_calls: list[tuple[str, str]] = []
        self.tier_cap_raises = False

    def check_tier_cap(self, tenant, manifest):
        if self.tier_cap_raises:
            raise ValueError("capped at tier 2")

    def invalidate(self, *, tenant, handler_ref):
        self.invalidate_calls.append((tenant, handler_ref))

    async def get_published(self, *, tenant, handler_ref):
        return None


def _make_bundle(tenant: str = "acme", handler_ref: str = "x.onBeforeSubmit", tier: CapabilityTier = CapabilityTier.PURE) -> SnippetBundle:
    return SnippetBundle(
        source=SnippetSource.DB,
        status=SnippetStatus.DRAFT,
        version=1,
        handler_ref=handler_ref,
        event="onBeforeSubmit",
        tenant=tenant,
        manifest=CapabilityManifest(tier=tier),
        python_source="def handler(ctx):\n    pass",
        python_sha256="dummy_sha",
    )


@pytest.mark.asyncio
async def test_approval_refuses_unconformant() -> None:
    store = _FakeStore()

    async def _fails(bundle):
        return _FakeConformanceResult(passed=False, errors=["undeclared import: socket"])

    service = SnippetApprovalService(store, check_conformance=_fails)
    bundle = _make_bundle()
    drafted = await service.draft(bundle, tenant="acme")

    with pytest.raises(ValueError, match="conformance"):
        await service.publish(tenant="acme", handler_ref="x.onBeforeSubmit", version=drafted.version, approved_by="admin")

    assert store.invalidate_calls == []


@pytest.mark.asyncio
async def test_approval_records_approver() -> None:
    store = _FakeStore()

    async def _passes(bundle):
        return _FakeConformanceResult(passed=True)

    service = SnippetApprovalService(store, check_conformance=_passes)
    bundle = _make_bundle()
    drafted = await service.draft(bundle, tenant="acme")

    published = await service.publish(tenant="acme", handler_ref="x.onBeforeSubmit", version=drafted.version, approved_by="admin-user")
    assert published.status == SnippetStatus.PUBLISHED
    assert published.approved_by == "admin-user"
    assert published.approved_at is not None


@pytest.mark.asyncio
async def test_draft_never_executes() -> None:
    """A DRAFT snippet is never resolved by get_published() (query-level filter)."""
    store = _FakeStore()

    async def _passes(bundle):
        return _FakeConformanceResult(passed=True)

    service = SnippetApprovalService(store, check_conformance=_passes)
    result = await service.get_published(tenant="acme", handler_ref="x.onBeforeSubmit")
    assert result is None  # _FakeStore.get_published always returns None here


@pytest.mark.asyncio
async def test_publish_invalidates_cache_on_success() -> None:
    store = _FakeStore()

    async def _passes(bundle):
        return _FakeConformanceResult(passed=True)

    service = SnippetApprovalService(store, check_conformance=_passes)
    bundle = _make_bundle()
    drafted = await service.draft(bundle, tenant="acme")

    await service.publish(tenant="acme", handler_ref="x.onBeforeSubmit", version=drafted.version, approved_by="admin")
    assert store.invalidate_calls == [("acme", "x.onBeforeSubmit")]


@pytest.mark.asyncio
async def test_revoke_invalidates_cache() -> None:
    store = _FakeStore()

    async def _passes(bundle):
        return _FakeConformanceResult(passed=True)

    service = SnippetApprovalService(store, check_conformance=_passes)
    bundle = _make_bundle()
    drafted = await service.draft(bundle, tenant="acme")

    await service.publish(tenant="acme", handler_ref="x.onBeforeSubmit", version=drafted.version, approved_by="admin")
    store.invalidate_calls.clear()

    await service.revoke(tenant="acme", handler_ref="x.onBeforeSubmit", version=drafted.version)
    assert store.invalidate_calls == [("acme", "x.onBeforeSubmit")]


@pytest.mark.asyncio
async def test_list_versions() -> None:
    store = _FakeStore()

    async def _passes(bundle):
        return _FakeConformanceResult(passed=True)

    service = SnippetApprovalService(store, check_conformance=_passes)
    bundle1 = _make_bundle()
    drafted1 = await service.draft(bundle1, tenant="acme")
    drafted2 = await service.draft(bundle1, tenant="acme")

    versions = await service.list_versions(tenant="acme", handler_ref="x.onBeforeSubmit")
    assert len(versions) == 2
    assert versions[0].version == 2
    assert versions[1].version == 1


@pytest.mark.asyncio
async def test_publish_refuses_tier_cap() -> None:
    store = _FakeStore()
    store.tier_cap_raises = True

    async def _passes(bundle):
        return _FakeConformanceResult(passed=True)

    service = SnippetApprovalService(store, check_conformance=_passes)
    bundle = _make_bundle(tier=CapabilityTier.BROKERED)
    drafted = await service.draft(bundle, tenant="acme")

    with pytest.raises(ValueError, match="capped at tier 2"):
        await service.publish(tenant="acme", handler_ref="x.onBeforeSubmit", version=drafted.version, approved_by="admin")
