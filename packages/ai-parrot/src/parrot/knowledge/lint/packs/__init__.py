"""Lint rule packs (FEAT-625)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from parrot.knowledge.lint.models import LintOptions
    from parrot.knowledge.lint.rule import LintRule


def default_rules(options: "LintOptions") -> list["LintRule"]:
    """Instantiate every deterministic rule; add the LLM rule only when ``options.llm``."""
    from parrot.knowledge.lint.packs.adr import ADR_RULES
    from parrot.knowledge.lint.packs.export import EXPORT_RULES
    from parrot.knowledge.lint.packs.memory import MEMORY_RULES
    from parrot.knowledge.lint.packs.plane import PLANE_RULES
    from parrot.knowledge.lint.packs.plane_fix import PLANE_FIX_RULES

    rules: list[LintRule] = [
        cls() for cls in (*PLANE_RULES, *PLANE_FIX_RULES, *EXPORT_RULES, *ADR_RULES, *MEMORY_RULES)
    ]
    if options.llm:
        from parrot.knowledge.lint.packs.llm import build_llm_rule

        llm_rule = build_llm_rule(options)
        if llm_rule is not None:
            rules.append(llm_rule)
    return rules
