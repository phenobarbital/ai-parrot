"""FEAT-707 — per-tenant DB-like store (TASK-4504)."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.skills.mixin import SkillRegistryMixin


class FakeRegistry:
    """Async registry fake that records tenant-store interactions."""

    def __init__(self, namespace: str, persistence_path: Path | None) -> None:
        self.namespace = namespace
        self.persistence_path = persistence_path
        self._embedding_model = object()
        self.configure = AsyncMock()
        self.search_skills = AsyncMock(return_value=[])
        self.get_relevant_skills = AsyncMock(return_value="")
        self.upload_skill = AsyncMock(return_value=(SimpleNamespace(skill_id="id"), SimpleNamespace()))
        self.extract_skill_from_conversation = AsyncMock(return_value=None)
        self.cleanup = AsyncMock()


def _result(name: str, score: float, content: str | None = None) -> SimpleNamespace:
    """Build a store-shaped search result."""
    return SimpleNamespace(
        skill=SimpleNamespace(skill_id=f"{name}-id", metadata=SimpleNamespace(name=name, description=f"{name} desc")),
        content=content or f"{name} content",
        relevance_score=score,
    )


@pytest.fixture
def host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[SkillRegistryMixin, list[FakeRegistry]]:
    """Build a tenant-enabled mixin host with registry factory fakes."""
    registries: list[FakeRegistry] = []

    def factory(namespace: str, persistence_path: Path | None = None, **_: object) -> FakeRegistry:
        registry = FakeRegistry(namespace, persistence_path)
        registries.append(registry)
        return registry

    monkeypatch.setattr("parrot.skills.mixin.create_skill_registry", factory)

    class Host(SkillRegistryMixin):
        name = "agent"
        org_id = "org"

    instance = Host(tenant_based=True)
    instance._agents_dir = tmp_path
    for tenant in ("acme", "beta"):
        (tmp_path / "agent" / "tenants" / tenant / "skills").mkdir(parents=True)
    return instance, registries


@pytest.mark.asyncio
async def test_store_namespace_and_persistence_per_tenant(host: tuple[SkillRegistryMixin, list[FakeRegistry]]) -> None:
    """Tenant stores use the tenant namespace and skills directory."""
    instance, registries = host
    await instance._configure_skill_registry()
    assert [registry.namespace for registry in registries] == ["org/agent", "org/agent/acme", "org/agent/beta"]
    assert registries[1].persistence_path == instance._agents_dir / "agent" / "tenants" / "acme" / "skills"


@pytest.mark.asyncio
async def test_store_shares_embedding_model(host: tuple[SkillRegistryMixin, list[FakeRegistry]]) -> None:
    """Every tenant configure call receives the already-loaded global model."""
    instance, registries = host
    await instance._configure_skill_registry()
    global_model = registries[0]._embedding_model
    assert registries[1].configure.await_args.kwargs["embedding_model"] is global_model
    assert registries[2].configure.await_args.kwargs["embedding_model"] is global_model


@pytest.mark.asyncio
async def test_search_skills_merge_before_limit(host: tuple[SkillRegistryMixin, list[FakeRegistry]]) -> None:
    """Tenant search shadows names, is ranked globally, then limited."""
    instance, registries = host
    await instance._configure_skill_registry()
    registries[0].search_skills.return_value = [_result("shared", 0.9, "global shared"), _result("global", 0.7)]
    registries[1].search_skills.return_value = [_result("shared", 0.8, "tenant shared"), _result("tenant", 0.95)]
    results = await instance.search_skills("q", max_results=2, tenant="acme")
    assert [item["name"] for item in results] == ["tenant", "shared"]
    assert results[1]["content"] == "tenant shared"
    assert [item["namespace"] for item in results] == ["org/agent/acme", "org/agent/acme"]


@pytest.mark.asyncio
async def test_get_skill_context_tenant_then_global(host: tuple[SkillRegistryMixin, list[FakeRegistry]]) -> None:
    """Tenant context is preferred and falls back only when empty."""
    instance, registries = host
    await instance._configure_skill_registry()
    registries[1].get_relevant_skills.return_value = "tenant"
    assert await instance.get_skill_context("q", tenant="acme") == "tenant"
    registries[1].get_relevant_skills.return_value = "  "
    registries[0].get_relevant_skills.return_value = "global"
    assert await instance.get_skill_context("q", tenant="acme") == "global"


@pytest.mark.asyncio
async def test_document_skill_routes_to_tenant(host: tuple[SkillRegistryMixin, list[FakeRegistry]]) -> None:
    """An explicit known tenant writes to its local registry."""
    instance, registries = host
    await instance._configure_skill_registry()
    await instance.document_skill("tenant", "content", tenant="acme")
    registries[1].upload_skill.assert_awaited_once()


@pytest.mark.asyncio
async def test_document_skill_global_without_tenant(host: tuple[SkillRegistryMixin, list[FakeRegistry]]) -> None:
    """An unresolved tenant writes to the global registry."""
    instance, registries = host
    await instance._configure_skill_registry()
    await instance.document_skill("global", "content")
    registries[0].upload_skill.assert_awaited_once()


@pytest.mark.asyncio
async def test_extract_skills_stays_global(host: tuple[SkillRegistryMixin, list[FakeRegistry]]) -> None:
    """Conversation extraction always remains owned by the global store."""
    instance, registries = host
    await instance._configure_skill_registry()
    instance.skill_registry_auto_extract = True
    await instance.extract_skills_from_conversation("conversation")
    registries[0].extract_skill_from_conversation.assert_awaited_once()
    registries[1].extract_skill_from_conversation.assert_not_awaited()


@pytest.mark.asyncio
async def test_cleanup_closes_tenant_stores(host: tuple[SkillRegistryMixin, list[FakeRegistry]]) -> None:
    """Cleanup closes all tenant registries before dropping them."""
    instance, registries = host
    await instance._configure_skill_registry()
    await instance._cleanup_skill_registry()
    assert instance._tenant_store_registries == {}
    registries[1].cleanup.assert_awaited_once()
    registries[2].cleanup.assert_awaited_once()


@pytest.mark.asyncio
async def test_flag_off_no_tenant_stores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The disabled flag preserves a global-only registry."""
    factory = MagicMock(
        side_effect=lambda namespace, persistence_path=None, **_: FakeRegistry(namespace, persistence_path)
    )
    monkeypatch.setattr("parrot.skills.mixin.create_skill_registry", factory)

    class Host(SkillRegistryMixin):
        name = "agent"

    instance = Host()
    instance._agents_dir = tmp_path
    await instance._configure_skill_registry()
    assert instance._tenant_store_registries == {}
    assert factory.call_count == 1
