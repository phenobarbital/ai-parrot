"""FEAT-707 — tenancy primitives (TASK-4494)."""

import asyncio
from pathlib import Path

import pytest

from parrot.skills.file_registry import SkillFileRegistry
from parrot.skills.models import SkillSource
from parrot.skills.tenancy import (
    SkillView,
    bind_skill_tenant,
    current_active_skill,
    current_skill_tenant,
    discover_tenant_dirs,
    reset_skill_tenant,
    set_active_skill,
    tenant_skills_dir,
    validate_tenant_id,
)


def _skill(directory: Path, name: str, triggers: list[str], *, global_only: bool = False) -> None:
    """Write a minimal skill fixture."""
    directory.mkdir(parents=True, exist_ok=True)
    trigger_lines = "".join(f"  - {trigger}\n" for trigger in triggers)
    global_only_line = "global_only: true\n" if global_only else ""
    (directory / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: {name} skill\ntriggers:\n"
        f"{trigger_lines}{global_only_line}---\n\n{name} body\n"
    )


async def _registry(skills_dir: Path) -> SkillFileRegistry:
    """Load a registry rooted at a fixture directory."""
    registry = SkillFileRegistry(skills_dir=skills_dir, learned_dir=skills_dir / "learned")
    await registry.load()
    return registry


@pytest.mark.parametrize("value", ["pokemon", "acme-01", "Tenant.A"])
def test_validate_tenant_id_accepts_safe_segment(value: str) -> None:
    """Safe, non-reserved names are accepted unchanged."""
    assert validate_tenant_id(value) == value


@pytest.mark.parametrize("value", ["..", "a/b", "", "skills", "Learned", "TENANTS", "_shared"])
def test_validate_tenant_id_rejects(value: str) -> None:
    """Unsafe and reserved names are rejected before path access."""
    with pytest.raises(ValueError):
        validate_tenant_id(value)


def test_tenant_skills_dir_secure_path_escape(tmp_path: Path) -> None:
    """A tenant symlink escaping the root is rejected."""
    outside = tmp_path / "outside"
    outside.mkdir()
    tenants = tmp_path / "agent" / "tenants"
    tenants.mkdir(parents=True)
    (tenants / "evil").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="Path traversal"):
        tenant_skills_dir(tmp_path / "agent", "evil")


def test_discover_tenant_dirs_sorted_and_filtered(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Discovery returns only contained directories and preserves sorted order."""
    root = tmp_path / "agent"
    _skill(root / "tenants" / "zeta" / "skills", "zeta", ["/zeta"])
    _skill(root / "tenants" / "alpha" / "skills", "alpha", ["/alpha"])
    (root / "tenants" / "skills").mkdir(parents=True)
    (root / "tenants" / "empty").mkdir()
    (root / "tenants" / "file").write_text("not a directory")
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "tenants" / "evil").symlink_to(outside, target_is_directory=True)

    found = discover_tenant_dirs(root)

    assert list(found) == ["alpha", "zeta"]
    assert "Skipping tenant dir" in caplog.text


@pytest.mark.asyncio
async def test_skill_view_c1_shadow_by_name(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """C1: a tenant name shadows a non-locked global name."""
    _skill(tmp_path / "global", "shared", ["/global"])
    _skill(tmp_path / "tenant", "shared", ["/tenant"])
    view = SkillView(await _registry(tmp_path / "global"), await _registry(tmp_path / "tenant"), tenant="a")

    assert view.get_by_name("shared").triggers == ["/tenant"]
    assert [skill.name for skill in view.list_skills()] == ["shared"]
    assert "shadows global" in caplog.text


@pytest.mark.asyncio
async def test_skill_view_c2_shadow_by_trigger(tmp_path: Path) -> None:
    """C2: a tenant trigger wins while the global name remains reachable."""
    _skill(tmp_path / "global", "global", ["/same"])
    _skill(tmp_path / "tenant", "tenant", ["/same"])
    view = SkillView(await _registry(tmp_path / "global"), await _registry(tmp_path / "tenant"), tenant="a")

    assert view.get("/same").name == "tenant"
    assert view.get_by_name("global").name == "global"
    assert [skill.name for skill in view.list_skills()] == ["tenant", "global"]


@pytest.mark.asyncio
async def test_skill_view_c3_global_only_name_drops_tenant(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """C3: a global-only name drops the tenant collision."""
    _skill(tmp_path / "global", "locked", ["/locked"], global_only=True)
    _skill(tmp_path / "tenant", "locked", ["/tenant"])
    view = SkillView(await _registry(tmp_path / "global"), await _registry(tmp_path / "tenant"), tenant="a")

    assert view.get_by_name("locked").file_path == tmp_path / "global" / "locked.md"
    assert view.report.dropped == ("locked",)
    assert str(tmp_path / "global" / "locked.md") in caplog.text
    assert str(tmp_path / "tenant" / "locked.md") in caplog.text


@pytest.mark.asyncio
async def test_skill_view_c4_global_only_trigger_drops_trigger(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """C4: a global-only trigger remains global and is removed from tenant skill."""
    _skill(tmp_path / "global", "locked", ["/same"], global_only=True)
    _skill(tmp_path / "tenant", "tenant", ["/same", "/free"])
    view = SkillView(await _registry(tmp_path / "global"), await _registry(tmp_path / "tenant"), tenant="a")

    assert view.get("/same").name == "locked"
    assert view.get_by_name("tenant").triggers == ["/free"]
    assert str(tmp_path / "global" / "locked.md") in caplog.text
    assert str(tmp_path / "tenant" / "tenant.md") in caplog.text


@pytest.mark.asyncio
async def test_skill_view_c5_tenant_only(tmp_path: Path) -> None:
    """C5: tenant-only skills pass through."""
    _skill(tmp_path / "tenant", "tenant", ["/tenant"])
    view = SkillView(await _registry(tmp_path / "global"), await _registry(tmp_path / "tenant"), tenant="a")

    assert view.get("/tenant").name == "tenant"


@pytest.mark.asyncio
async def test_skill_view_c6_global_only(tmp_path: Path) -> None:
    """C6: global-only views fall back to global skills."""
    _skill(tmp_path / "global", "global", ["/global"])
    view = SkillView(await _registry(tmp_path / "global"), await _registry(tmp_path / "tenant"), tenant="a")

    assert view.get("/global").name == "global"


@pytest.mark.asyncio
async def test_skill_view_c8_learned_global(tmp_path: Path) -> None:
    """C8: learned global skills are visible and may be shadowed by tenant names."""
    _skill(tmp_path / "global" / "learned", "learned", ["/learned"])
    _skill(tmp_path / "tenant", "learned", ["/tenant"])
    view = SkillView(await _registry(tmp_path / "global"), await _registry(tmp_path / "tenant"), tenant="a")

    assert view.get_by_name("learned").source is SkillSource.AUTHORED
    assert view.get("/learned").source is SkillSource.LEARNED
    assert view.get("/tenant").name == "learned"


@pytest.mark.asyncio
async def test_skill_view_global_view_equals_registry(tmp_path: Path) -> None:
    """A view without a tenant registry mirrors the global registry."""
    _skill(tmp_path / "global", "global", ["/global"])
    registry = await _registry(tmp_path / "global")
    view = SkillView(registry)

    assert view.list_skills() == registry.list_skills()
    assert view.get("/global") == registry.get("/global")
    assert view.report is None


@pytest.mark.asyncio
async def test_skill_view_learned_dir_is_global(tmp_path: Path) -> None:
    """The learned directory is always the global registry location."""
    global_registry = await _registry(tmp_path / "global")
    tenant_registry = await _registry(tmp_path / "tenant")

    assert SkillView(global_registry, tenant_registry, tenant="a").learned_dir == global_registry.learned_dir


@pytest.mark.asyncio
async def test_list_skills_order_deterministic(tmp_path: Path) -> None:
    """Tenant registry order precedes unshadowed global registry order."""
    _skill(tmp_path / "global", "alpha", ["/alpha"])
    _skill(tmp_path / "global", "beta", ["/beta"])
    _skill(tmp_path / "tenant", "delta", ["/delta"])
    _skill(tmp_path / "tenant", "alpha", ["/tenant-alpha"])
    view = SkillView(await _registry(tmp_path / "global"), await _registry(tmp_path / "tenant"), tenant="a")

    assert [skill.name for skill in view.list_skills()] == ["alpha", "delta", "beta"]


@pytest.mark.asyncio
async def test_contextvars_default_none_and_reset(tmp_path: Path) -> None:
    """Tenant and active-skill ContextVars default to none and restore values."""
    assert current_skill_tenant() is None
    assert current_active_skill() is None
    token = bind_skill_tenant("tenant-a")
    assert current_skill_tenant() == "tenant-a"
    reset_skill_tenant(token)
    assert current_skill_tenant() is None
    _skill(tmp_path / "skills", "active", ["/active"])
    active = (await _registry(tmp_path / "skills")).get("/active")
    set_active_skill(active)
    assert current_active_skill() == active
    set_active_skill(None)


@pytest.mark.asyncio
async def test_contextvars_isolated_between_tasks() -> None:
    """Separate asyncio tasks retain their own tenant bindings."""

    async def bound(tenant: str) -> str:
        token = bind_skill_tenant(tenant)
        try:
            await asyncio.sleep(0)
            return current_skill_tenant()
        finally:
            reset_skill_tenant(token)

    assert await asyncio.gather(bound("a"), bound("b")) == ["a", "b"]
