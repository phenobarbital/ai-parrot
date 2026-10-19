"""FEAT-707 — mixin consumer wiring (TASK-4503).

Covers the SkillRegistryMixin side of the per-tenant skills feature: the
view/prompt-layer/active-skill wiring, learned-skill refresh and tenant reload.
"""

import asyncio
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from parrot.bots.prompts import PromptBuilder, RenderPhase
from parrot.skills import middleware as middleware_module
from parrot.skills import tools as tools_module
from parrot.skills.mixin import SkillRegistryMixin
from parrot.skills.models import SkillDefinition
from parrot.skills.prompt import render_skills_prompt_layer
from parrot.skills.tenancy import bind_skill_tenant, reset_skill_tenant


def _skill(path: Path, name: str, trigger: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nname: {name}\ndescription: {name} desc\ntriggers:\n  - /{trigger}\n---\n\nBody of {name}\n")


@pytest.fixture
def agent_tree(tmp_path):
    root = tmp_path / "troc_finance"
    _skill(root / "skills" / "glob.md", "glob", "glob")
    _skill(root / "tenants" / "pokemon" / "skills" / "poke.md", "poke", "poke")
    _skill(root / "tenants" / "epson" / "skills" / "eps.md", "eps", "eps")
    return tmp_path


def make_host(tmp_path, *, tenant_based=False, **kw):
    class Host(SkillRegistryMixin):
        name = "troc_finance"
        enable_skill_registry = False

    host = Host(tenant_based=tenant_based, **kw)
    host._agents_dir = tmp_path
    host._prompt_builder = PromptBuilder()
    return host


def _rendered(host, tenant=None) -> str:
    """Build the system prompt for ``tenant`` (bound for the duration of the call)."""
    token = bind_skill_tenant(tenant) if tenant is not None else None
    try:
        return host._prompt_builder.build({})
    finally:
        if token is not None:
            reset_skill_tenant(token)


@pytest.mark.asyncio
async def test_flag_off_installs_exactly_todays_layer(agent_tree):
    host = make_host(agent_tree, tenant_based=False)
    await host._configure_skill_file_registry()

    layer = host._prompt_builder.get("available_skills")
    expected = render_skills_prompt_layer(host._skill_file_registry)
    assert layer is not None
    assert layer.name == expected.name
    assert layer.phase == expected.phase == RenderPhase.CONFIGURE
    assert layer.template == expected.template
    assert layer.cacheable == expected.cacheable
    assert host._prompt_builder.get("available_skills:pokemon") is None
    assert host._prompt_builder.get("available_skills:epson") is None


@pytest.mark.asyncio
async def test_tenant_layers_installed_per_view(agent_tree):
    host = make_host(agent_tree, tenant_based=True)
    await host._configure_skill_file_registry()

    builder = host._prompt_builder
    assert builder.get("available_skills") is not None
    for tenant in ("pokemon", "epson"):
        layer = builder.get(f"available_skills:{tenant}")
        assert layer is not None
        assert layer.phase == RenderPhase.REQUEST
        assert layer.cacheable is True
    assert builder.get("available_skills").phase == RenderPhase.REQUEST
    assert builder.get("available_skills").cacheable is True

    # Idempotent: re-installing replaces by name instead of duplicating.
    before = sorted(builder.layer_names)
    host._install_skill_prompt_layers()
    assert sorted(builder.layer_names) == before


@pytest.mark.asyncio
async def test_only_bound_tenant_layer_renders(agent_tree):
    host = make_host(agent_tree, tenant_based=True)
    await host._configure_skill_file_registry()

    prompt = _rendered(host, tenant="pokemon")
    assert 'name="poke"' in prompt
    assert 'name="glob"' in prompt
    assert 'name="eps"' not in prompt


@pytest.mark.asyncio
async def test_unknown_tenant_renders_global_layer(agent_tree):
    host = make_host(agent_tree, tenant_based=True)
    await host._configure_skill_file_registry()

    prompt = _rendered(host, tenant="unknown")
    assert 'name="glob"' in prompt
    assert 'name="poke"' not in prompt
    assert 'name="eps"' not in prompt


@pytest.mark.asyncio
async def test_toolkit_and_middleware_receive_view_provider(agent_tree, monkeypatch):
    seen = {}

    def fake_middleware(**kwargs):
        seen["middleware"] = kwargs
        return MagicMock()

    class FakeToolkit:
        def __init__(self, **kwargs):
            seen["toolkit"] = kwargs

        def get_tools(self):
            return []

    monkeypatch.setattr(middleware_module, "create_skill_trigger_middleware", fake_middleware)
    monkeypatch.setattr(tools_module, "SkillFileToolkit", FakeToolkit)

    host = make_host(agent_tree, tenant_based=True)
    host._prompt_pipeline = MagicMock()
    await host._configure_skill_file_registry()
    assert seen["middleware"]["view_provider"] == host.current_skill_view
    assert seen["toolkit"]["view_provider"] == host.current_skill_view

    seen.clear()
    flag_off = make_host(agent_tree, tenant_based=False)
    flag_off._prompt_pipeline = MagicMock()
    await flag_off._configure_skill_file_registry()
    assert "view_provider" not in seen["middleware"]
    assert "view_provider" not in seen["toolkit"]


@pytest.mark.asyncio
async def test_active_skill_property_is_request_local(agent_tree):
    host = make_host(agent_tree, tenant_based=True)
    await host._configure_skill_file_registry()
    skill_a = host.current_skill_view("pokemon").get("/poke")
    skill_b = host.current_skill_view("pokemon").get("/glob")
    assert skill_a is not None and skill_b is not None
    assert host._active_skill is None

    async def run(skill: SkillDefinition) -> SkillDefinition | None:
        host._active_skill = skill
        await asyncio.sleep(0)
        return host._active_skill

    seen_a, seen_b = await asyncio.gather(
        asyncio.create_task(run(skill_a)),
        asyncio.create_task(run(skill_b)),
    )
    assert seen_a is skill_a
    assert seen_b is skill_b
    # The main task context was never written by the child tasks.
    assert host._active_skill is None


@pytest.mark.asyncio
async def test_save_learned_skill_refreshes_layers_and_views(agent_tree):
    host = make_host(agent_tree, tenant_based=True)
    await host._configure_skill_file_registry()

    skill = await host.save_learned_skill(
        name="learned_x",
        content="Learned body",
        description="learned desc",
        triggers=["/lx"],
    )
    assert skill is not None
    # Learned skills are global: visible through every tenant view and the global view.
    assert host._global_view.get("/lx") is not None
    assert host.current_skill_view("pokemon").get("/lx") is not None
    assert host.current_skill_view("epson").get("/lx") is not None
    # And every installed layer now lists it.
    assert 'name="learned_x"' in _rendered(host, tenant="pokemon")
    assert 'name="learned_x"' in _rendered(host, tenant="epson")
    assert 'name="learned_x"' in _rendered(host)


@pytest.mark.asyncio
async def test_reload_removes_layer_of_deleted_tenant(agent_tree):
    host = make_host(agent_tree, tenant_based=True)
    await host._configure_skill_file_registry()
    assert host._prompt_builder.get("available_skills:epson") is not None

    shutil.rmtree(agent_tree / "troc_finance" / "tenants" / "epson")
    await host.reload_tenant_skills("epson")

    assert "epson" not in host.known_tenants()
    assert host._prompt_builder.get("available_skills:epson") is None
    assert host._prompt_builder.get("available_skills:pokemon") is not None
