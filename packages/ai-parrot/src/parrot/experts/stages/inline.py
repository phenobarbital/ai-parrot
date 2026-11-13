"""Inline multi-expert composition into a conductor (FEAT-890 M4)."""

from __future__ import annotations

import dataclasses
from typing import Mapping

from parrot.bots.prompts.builder import PromptBuilder
from parrot.experts.knowledge.render import install_layers
from parrot.experts.models import KnowledgeContext

_RULE_PREFIXES = ("ALWAYS ", "NEVER ")


class InlineCompositionError(Exception):
    """Two inlined experts declare the same rule id."""


def _rule_ids(ctx: KnowledgeContext) -> set[str]:
    """Return the rule lines (ALWAYS/NEVER statements) an expert's rules layer carries."""
    return {line.strip() for line in ctx.inline_text("rules").splitlines() if line.strip().startswith(_RULE_PREFIXES)}


def build_inline_conductor(builder: PromptBuilder, contexts: Mapping[str, KnowledgeContext]) -> PromptBuilder:
    """Return a clone of ``builder`` with every expert's layers under per-expert names.

    The conductor keeps its identity: expert identity layers are never copied. Each
    expert's rules and knowledge land as ``expert_rules:<slug>`` and
    ``expert_knowledge:<slug>``. ``builder`` is never mutated.

    Args:
        builder: The conductor's prompt builder.
        contexts: Mapping of expert slug to its resolved knowledge context.

    Returns:
        A new PromptBuilder carrying the conductor plus all expert layers.

    Raises:
        InlineCompositionError: If two experts declare the same rule id.
    """
    owners: dict[str, str] = {}
    for slug, ctx in contexts.items():
        for rule in _rule_ids(ctx):
            other = owners.setdefault(rule, slug)
            if other != slug:
                raise InlineCompositionError(f"rule {rule!r} declared by both {other!r} and {slug!r}")

    composed = builder.clone()
    for slug, ctx in contexts.items():
        scratch = install_layers(builder, ctx)
        for base in ("expert_rules", "expert_knowledge"):
            layer = scratch.get(base)
            if layer is not None:
                composed.add(dataclasses.replace(layer, name=f"{base}:{slug}"))
    return composed
