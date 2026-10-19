"""FEAT-707 tenant-aware skill prompt layers (TASK-4498)."""

from pathlib import Path

from parrot.bots.prompts import RenderPhase
from parrot.skills.file_registry import SkillFileRegistry
from parrot.skills.models import SkillDefinition, SkillSource
from parrot.skills.prompt import (
    build_active_skill_layer,
    global_layer_condition,
    render_skills_prompt_layer,
    tenant_layer_condition,
)
from parrot.skills.tenancy import SkillView, bind_skill_tenant, reset_skill_tenant


def make_registry(tmp_path: Path, name: str = "summarize") -> SkillFileRegistry:
    """Build a registry containing one deterministic test skill."""
    registry = SkillFileRegistry(skills_dir=tmp_path)
    registry.add(
        SkillDefinition(
            name=name,
            description="Summarize text",
            triggers=["/summary"],
            source=SkillSource.AUTHORED,
            template_body="Summarize.",
            token_count=2,
            file_path=tmp_path / f"{name}.md",
        )
    )
    return registry


def test_render_layer_defaults_unchanged(tmp_path: Path) -> None:
    """Defaults preserve the original layer metadata and rendered template."""
    layer = render_skills_prompt_layer(make_registry(tmp_path))

    assert layer.name == "available_skills"
    assert layer.phase == RenderPhase.CONFIGURE
    assert layer.cacheable is True
    assert layer.condition is None
    assert layer.template == (
        '<available_skills>\n  <skill name="summarize">\n'
        '    Summarize text\n    Load with: load_skill(name="summarize")\n'
        "    Also triggerable via: /summary\n  </skill>\n</available_skills>"
    )


def test_render_layer_tenant_variant(tmp_path: Path) -> None:
    """Tenant layer metadata is passed through to all return paths."""
    condition = tenant_layer_condition("acme")
    layer = render_skills_prompt_layer(
        make_registry(tmp_path),
        name="available_skills:acme",
        phase=RenderPhase.REQUEST,
        condition=condition,
        cacheable=True,
    )

    assert layer.name == "available_skills:acme"
    assert layer.phase == RenderPhase.REQUEST
    assert layer.condition is condition
    assert layer.cacheable is True


def test_tenant_condition_matches_only_bound_tenant() -> None:
    """Tenant conditions follow the current ContextVar rather than context data."""
    condition = tenant_layer_condition("acme")
    token = bind_skill_tenant("acme")
    try:
        assert condition({}) is True
        reset_skill_tenant(token)
        token = bind_skill_tenant("other")
        assert condition({}) is False
    finally:
        reset_skill_tenant(token)


def test_global_condition_hidden_for_known_tenant_and_shown_otherwise() -> None:
    """The global layer is hidden only for tenants with a discovered view."""
    condition = global_layer_condition({"acme"})
    for tenant, expected in (("acme", False), ("unknown", True), (None, True)):
        token = bind_skill_tenant(tenant)
        try:
            assert condition({}) is expected
        finally:
            reset_skill_tenant(token)


def test_global_condition_sees_live_set_updates() -> None:
    """Newly discovered tenants affect an existing global condition."""
    known_tenants: set[str] = set()
    condition = global_layer_condition(known_tenants)
    token = bind_skill_tenant("acme")
    try:
        assert condition({}) is True
        known_tenants.add("acme")
        assert condition({}) is False
    finally:
        reset_skill_tenant(token)


def test_build_active_skill_layer_condition() -> None:
    """The active layer renders only a non-empty request body and is uncached."""
    layer = build_active_skill_layer()

    assert layer.name == "skill_active"
    assert layer.priority == 90
    assert layer.phase == RenderPhase.REQUEST
    assert layer.cacheable is False
    assert layer.render({"active_skill_body": "body with $literal"}) == "body with $literal"
    assert layer.render({"active_skill_body": ""}) is None
    assert layer.render({}) is None


def test_render_accepts_skill_view(tmp_path: Path) -> None:
    """The prompt factory accepts the read-only composite view duck type."""
    global_registry = make_registry(tmp_path / "global")
    tenant_registry = make_registry(tmp_path / "tenant", name="tenant-skill")
    view = SkillView(global_registry, tenant_registry, tenant="acme")

    layer = render_skills_prompt_layer(view)

    assert 'name="tenant-skill"' in layer.template
    assert 'name="summarize"' in layer.template
