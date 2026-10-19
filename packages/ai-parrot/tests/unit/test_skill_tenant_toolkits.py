"""FEAT-707 tenant providers for the skill toolkits (TASK-4495)."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.skills.file_registry import SkillFileRegistry
from parrot.skills.models import SkillDefinition, SkillSource
from parrot.skills.tools import SkillFileToolkit, SkillRegistryToolkit, create_skill_tools


def _skill(name: str, body: str, root: Path, *, composite: bool = False) -> SkillDefinition:
    """Build a small file skill for provider tests."""
    skill_dir = root / name
    if composite:
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(body)
        (skill_dir / "example.txt").write_text("asset")
        file_path = skill_dir / "SKILL.md"
        assets_dir = skill_dir
    else:
        file_path = root / f"{name}.md"
        assets_dir = None
    return SkillDefinition(
        name=name,
        description=f"{name} description",
        triggers=[f"/{name}"],
        source=SkillSource.AUTHORED,
        template_body=body,
        token_count=1,
        file_path=file_path,
        assets_dir=assets_dir,
    )


@pytest.mark.asyncio
async def test_file_toolkit_without_provider_unchanged(tmp_path: Path) -> None:
    """Without a provider, file tools continue using their constructor registry."""
    registry = SkillFileRegistry(tmp_path)
    registry.add(_skill("global", "global body", tmp_path))
    toolkit = SkillFileToolkit(file_registry=registry)

    listed = await toolkit.list_skill_commands()
    loaded = await toolkit.load_skill("global")

    assert listed.metadata["count"] == 1
    assert loaded.result == "global body"


@pytest.mark.asyncio
async def test_file_toolkit_uses_view_provider_each_invocation(tmp_path: Path) -> None:
    """Every read invocation resolves the current view and uses its contents."""
    global_registry = SkillFileRegistry(tmp_path / "global")
    provider_registry = SkillFileRegistry(tmp_path / "tenant")
    provider_registry.add(_skill("tenant", "tenant body", tmp_path / "tenant"))
    provider = MagicMock(return_value=provider_registry)
    toolkit = SkillFileToolkit(file_registry=global_registry, view_provider=provider)

    assert (await toolkit.list_skill_commands()).metadata["count"] == 1
    assert (await toolkit.load_skill("tenant")).result == "tenant body"
    assert provider.call_count == 2


@pytest.mark.asyncio
async def test_file_toolkit_provider_none_falls_back(tmp_path: Path) -> None:
    """A provider returning None falls back to the constructor registry."""
    registry = SkillFileRegistry(tmp_path)
    registry.add(_skill("global", "global body", tmp_path))
    toolkit = SkillFileToolkit(file_registry=registry, view_provider=lambda: None)

    result = await toolkit.load_skill("global")

    assert result.status == "done"
    assert result.result == "global body"


@pytest.mark.asyncio
async def test_read_skill_asset_uses_view(tmp_path: Path) -> None:
    """Composite skills only present in the provider view are readable."""
    global_registry = SkillFileRegistry(tmp_path / "global")
    tenant_root = tmp_path / "tenant"
    tenant_registry = SkillFileRegistry(tenant_root)
    tenant_registry.add(_skill("composite", "tenant body", tenant_root, composite=True))
    toolkit = SkillFileToolkit(file_registry=global_registry, view_provider=lambda: tenant_registry)

    result = await toolkit.read_skill_asset("composite", "example.txt")

    assert result.status == "done"
    assert result.result == "asset"


@pytest.mark.asyncio
async def test_save_learned_skill_writes_global(tmp_path: Path) -> None:
    """Learned saves check and hot-add only the constructor registry."""
    global_registry = SkillFileRegistry(tmp_path / "global")
    tenant_registry = SkillFileRegistry(tmp_path / "tenant")
    toolkit = SkillFileToolkit(
        file_registry=global_registry,
        learned_dir=tmp_path / "global" / "learned",
        view_provider=lambda: tenant_registry,
    )

    result = await toolkit.save_learned_skill(
        name="learned",
        description="Learned globally",
        content="global instructions",
        triggers=["/learned"],
    )

    assert result.status == "done"
    assert global_registry.get("/learned") is not None
    assert tenant_registry.get("/learned") is None


def _registry_mock(*, skills=None, content="content") -> MagicMock:
    """Create a registry mock with awaitable methods used by the toolkit."""
    registry = MagicMock()
    registry.search_skills = AsyncMock(return_value=[])
    registry.read_skill = AsyncMock(return_value=content)
    registry.list_skills = AsyncMock(return_value=skills or [])
    registry.upload_skill = AsyncMock(
        return_value=(
            SimpleNamespace(skill_id="skill-id", metadata=SimpleNamespace(name="skill")),
            SimpleNamespace(version_number=2),
        )
    )
    return registry


@pytest.mark.asyncio
async def test_registry_toolkit_uses_registry_provider() -> None:
    """Search, list, read, document, and update use the current registry."""
    global_registry = _registry_mock()
    tenant_registry = _registry_mock(
        skills=[
            {
                "skill_id": "skill-id",
                "name": "skill",
                "description": "description",
                "category": "general",
                "tags": [],
                "current_version": 1,
            }
        ]
    )
    provider = MagicMock(return_value=tenant_registry)
    toolkit = SkillRegistryToolkit(
        registry=global_registry,
        agent_id="agent",
        registry_provider=provider,
    )

    await toolkit.search_skills("query")
    await toolkit.list_skills()
    await toolkit.read_skill("skill-id")
    await toolkit.document_skill("name", "description", "content")
    await toolkit.update_skill("skill-id", "updated")

    assert provider.call_count == 5
    tenant_registry.search_skills.assert_awaited_once()
    assert tenant_registry.list_skills.await_count == 3
    tenant_registry.read_skill.assert_awaited_once()
    assert tenant_registry.upload_skill.await_count == 2
    global_registry.search_skills.assert_not_awaited()
    global_registry.list_skills.assert_not_awaited()


def test_create_skill_tools_forwards_providers(tmp_path: Path) -> None:
    """The factory passes both providers to the toolkit constructors."""
    registry = MagicMock()
    file_registry = SkillFileRegistry(tmp_path)
    view_provider = MagicMock()
    registry_provider = MagicMock()

    tools = create_skill_tools(
        registry=registry,
        agent_id="agent",
        file_registry=file_registry,
        view_provider=view_provider,
        registry_provider=registry_provider,
    )

    registry_toolkit = next(
        tool.bound_method.__self__ for tool in tools if tool.name == "search_skills"
    )
    file_toolkit = next(
        tool.bound_method.__self__ for tool in tools if tool.name == "list_skill_commands"
    )
    assert registry_toolkit._registry_provider is registry_provider
    assert file_toolkit._view_provider is view_provider
