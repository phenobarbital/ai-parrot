"""Render a KnowledgeContext into literal prompt layers (FEAT-778 M6)."""

from __future__ import annotations

import dataclasses

from parrot.bots.prompts.builder import PromptBuilder
from parrot.bots.prompts.layers import EXPERT_KNOWLEDGE_LAYER, EXPERT_RULES_LAYER
from parrot.experts.models import KnowledgeContext, KnowledgeMode


def render_rules(ctx: KnowledgeContext) -> str:
    """Render the 'rules' layer as ``<governance_rules>``.

    Args:
        ctx: Resolved knowledge context.

    Returns:
        The wrapped rule text, or ``''`` when there is no rule text.
    """
    text = ctx.inline_text("rules").strip()
    return f"<governance_rules>\n{text}\n</governance_rules>" if text else ""


def render_knowledge(ctx: KnowledgeContext) -> str:
    """Render INLINE non-rules layers as ``<expert_knowledge>`` sections, in ctx order.

    Args:
        ctx: Resolved knowledge context.

    Returns:
        The wrapped knowledge text, or ``''`` when no inline non-rules content exists.
    """
    sections: list[str] = []
    for item in ctx.layers:
        if item.layer == "rules" or item.mode is not KnowledgeMode.INLINE or item.content is None:
            continue
        content = item.content.strip()
        if not content:
            continue
        sections.append(
            f'<section layer="{item.layer}" source="{item.source}" revision="{item.revision}">\n'
            f"{content}\n</section>"
        )
    if not sections:
        return ""
    return "<expert_knowledge>\n" + "\n".join(sections) + "\n</expert_knowledge>"


def install_layers(builder: PromptBuilder, ctx: KnowledgeContext) -> PromptBuilder:
    """Return a clone of ``builder`` with expert layers added and 'knowledge' removed (S2).

    Args:
        builder: Source builder; never mutated.
        ctx: Resolved knowledge context.

    Returns:
        A new PromptBuilder.
    """
    new_builder = builder.clone()
    new_builder.remove("knowledge")
    rules = render_rules(ctx)
    knowledge = render_knowledge(ctx)
    if rules:
        new_builder.add(dataclasses.replace(EXPERT_RULES_LAYER, template=rules))
    if knowledge:
        new_builder.add(dataclasses.replace(EXPERT_KNOWLEDGE_LAYER, template=knowledge))
    return new_builder
