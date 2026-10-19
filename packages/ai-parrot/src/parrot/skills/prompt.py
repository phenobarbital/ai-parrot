"""
Skills Prompt Layer Factory.

Provides :func:`render_skills_prompt_layer` — a factory function that builds
a static ``<available_skills>`` XML block from a
:class:`~parrot.skills.file_registry.SkillFileRegistry` and returns it as an
immutable :class:`~parrot.bots.prompts.PromptLayer` with
``phase=RenderPhase.CONFIGURE``.

The layer is resolved once at ``configure()`` time and cached, incurring zero
per-turn cost (Tier 1 of the two-tier skills system).

Usage::

    from parrot.skills.prompt import render_skills_prompt_layer

    layer = render_skills_prompt_layer(registry)
    self._prompt_builder.add(layer)
"""
from __future__ import annotations

from typing import Any, Callable, Collection, Dict, Optional

from parrot.bots.prompts import PromptLayer, RenderPhase

from .tenancy import current_skill_tenant


def render_skills_prompt_layer(
    registry: Any,
    max_skills: Optional[int] = None,
    priority: int = 45,
    *,
    name: str = "available_skills",
    phase: RenderPhase = RenderPhase.CONFIGURE,
    condition: Optional[Callable[[Dict[str, Any]], bool]] = None,
    cacheable: Optional[bool] = None,
) -> PromptLayer:
    """Build a static ``<available_skills>`` XML PromptLayer from the registry.

    Reads all skills from ``registry`` and emits an XML block listing each
    skill's name, description, and a ``load_skill(name="...")`` hint. Skills
    that declare ``triggers`` also include an "Also triggerable via: /cmd" line.

    The returned :class:`~parrot.bots.prompts.PromptLayer` uses
    ``phase=RenderPhase.CONFIGURE`` so it is resolved once at boot and cached;
    there is no per-request evaluation overhead.

    Args:
        registry: Any object exposing ``list_skills()``, such as a
            :class:`~parrot.skills.file_registry.SkillFileRegistry` or
            :class:`~parrot.skills.tenancy.SkillView`.
        max_skills: If set, truncate to this many skills (first N from registry).
            ``None`` means include all.
        priority: Integer priority for the layer. Default ``45`` places the
            layer between ``USER_SESSION`` (40) and ``TOOLS`` (50).
        name: Name for the returned prompt layer. Defaults to
            ``"available_skills"``.
        phase: Rendering phase for the layer. Defaults to
            ``RenderPhase.CONFIGURE``.
        condition: Optional callable that controls whether the layer renders.
        cacheable: Optional explicit provider-cache eligibility override.

    Returns:
        A frozen :class:`~parrot.bots.prompts.PromptLayer` with:

        - ``name="available_skills"`` by default
        - ``template`` containing the ``<available_skills>`` XML block, or
          an empty string if the registry has no skills.
        - ``phase=RenderPhase.CONFIGURE`` by default
    """
    if max_skills == 0:
        return PromptLayer(
            name=name,
            priority=priority,
            template="",
            phase=phase,
            condition=condition,
            cacheable=cacheable,
        )

    skills = registry.list_skills()

    if not skills:
        return PromptLayer(
            name=name,
            priority=priority,
            template="",
            phase=phase,
            condition=condition,
            cacheable=cacheable,
        )

    if max_skills is not None and len(skills) > max_skills:
        skills = skills[:max_skills]

    lines = ["<available_skills>"]
    for skill in skills:
        lines.append(f'  <skill name="{skill.name}">')
        lines.append(f"    {skill.description}")
        lines.append(f'    Load with: load_skill(name="{skill.name}")')
        if skill.triggers:
            lines.append(
                f"    Also triggerable via: {', '.join(skill.triggers)}"
            )
        lines.append("  </skill>")
    lines.append("</available_skills>")

    return PromptLayer(
        name=name,
        priority=priority,
        template="\n".join(lines),
        phase=phase,
        condition=condition,
        cacheable=cacheable,
    )


def tenant_layer_condition(tenant: str) -> Callable[[Dict[str, Any]], bool]:
    """Return a condition true only while ``tenant`` is bound."""
    return lambda _ctx: current_skill_tenant() == tenant


def global_layer_condition(known_tenants: Collection[str]) -> Callable[[Dict[str, Any]], bool]:
    """Return a condition true when no known tenant is currently bound."""
    return lambda _ctx: current_skill_tenant() not in known_tenants


def build_active_skill_layer(priority: int = 90) -> PromptLayer:
    """Build the permanent conditional layer for the active skill body."""
    return PromptLayer(
        name="skill_active",
        priority=priority,
        template="$active_skill_body",
        phase=RenderPhase.REQUEST,
        condition=lambda ctx: bool(ctx.get("active_skill_body")),
        cacheable=False,
    )
