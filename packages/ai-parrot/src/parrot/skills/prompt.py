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

from typing import Optional

from parrot.bots.prompts import PromptLayer, RenderPhase

from .file_registry import SkillFileRegistry


def render_skills_prompt_layer(
    registry: SkillFileRegistry,
    max_skills: Optional[int] = None,
    priority: int = 45,
) -> PromptLayer:
    """Build a static ``<available_skills>`` XML PromptLayer from the registry.

    Reads all skills from ``registry`` and emits an XML block listing each
    skill's name, description, and a ``load_skill(name="...")`` hint. Skills
    that declare ``triggers`` also include an "Also triggerable via: /cmd" line.

    The returned :class:`~parrot.bots.prompts.PromptLayer` uses
    ``phase=RenderPhase.CONFIGURE`` so it is resolved once at boot and cached;
    there is no per-request evaluation overhead.

    Args:
        registry: The :class:`~parrot.skills.file_registry.SkillFileRegistry`
            to read skills from.
        max_skills: If set, truncate to this many skills (first N from registry).
            ``None`` means include all.
        priority: Integer priority for the layer. Default ``45`` places the
            layer between ``USER_SESSION`` (40) and ``TOOLS`` (50).

    Returns:
        A frozen :class:`~parrot.bots.prompts.PromptLayer` with:

        - ``name="available_skills"``
        - ``template`` containing the ``<available_skills>`` XML block, or
          an empty string if the registry has no skills.
        - ``phase=RenderPhase.CONFIGURE``
    """
    if max_skills == 0:
        return PromptLayer(
            name="available_skills",
            priority=priority,
            template="",
            phase=RenderPhase.CONFIGURE,
        )

    skills = registry.list_skills()

    if not skills:
        return PromptLayer(
            name="available_skills",
            priority=priority,
            template="",
            phase=RenderPhase.CONFIGURE,
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
        name="available_skills",
        priority=priority,
        template="\n".join(lines),
        phase=RenderPhase.CONFIGURE,
    )
