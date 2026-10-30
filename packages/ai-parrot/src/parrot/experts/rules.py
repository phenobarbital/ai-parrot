"""Governance rules: strict ALWAYS/NEVER grammar and the additive org→team→project→expert chain (FEAT-778 M8)."""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Final, Sequence

from parrot.experts.models import ExpertBundle, KnowledgeLayer, KnowledgeMode, RuleSet, RuleSyntaxError
from parrot.memory.compaction.tokens import TokenCounter, get_default_counter

GOVERNANCE_DIRNAME: Final[str] = "governance"
RULE_LAYERS: Final[tuple[str, ...]] = ("org", "team", "project", "expert", "stage")
_LOGGER = logging.getLogger(__name__)


def parse_rules(path: Path, *, layer: str) -> RuleSet:
    """Parse one rules file.

    Args:
        path: Rules file to parse.
        layer: Scope that owns the rules.

    Returns:
        The parsed and revision-stamped rules.

    Raises:
        RuleSyntaxError: If a non-empty, non-comment line violates the rules grammar.
    """
    data = path.read_bytes()
    mandated: list[str] = []
    forbidden: list[str] = []
    section: str | None = None

    for lineno, raw_line in enumerate(data.decode().splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("<!--"):
            continue
        if line == "## Mandated":
            section = "mandated"
            continue
        if line == "## Forbidden":
            section = "forbidden"
            continue
        if section == "mandated" and line.startswith("ALWAYS "):
            mandated.append(line)
            continue
        if section == "forbidden" and line.startswith("NEVER "):
            forbidden.append(line)
            continue
        raise RuleSyntaxError(f"{path}:{lineno}: invalid governance rule")

    return RuleSet(
        layer=layer,
        source=path,
        revision=hashlib.sha256(data).hexdigest(),
        mandated=mandated,
        forbidden=forbidden,
    )


def resolve_chain(workspace: Path | None, bundle: ExpertBundle, *, stage_rules: RuleSet | None = None) -> list[RuleSet]:
    """Build the additive governance chain in widest-to-narrowest order.

    Args:
        workspace: The AGENTS_DIR root, if one is available.
        bundle: Expert bundle whose optional rules form the expert layer.
        stage_rules: Optional future stage-specific rules.

    Returns:
        Rule sets in :data:`RULE_LAYERS` order, with wider duplicate rules retained.
    """
    chain: list[RuleSet] = []
    if workspace is not None:
        for layer in ("org", "team", "project"):
            candidate = workspace / GOVERNANCE_DIRNAME / f"{layer}.md"
            if candidate.is_file():
                chain.append(parse_rules(candidate, layer=layer))
    if bundle.rules is not None:
        chain.append(bundle.rules)
    if stage_rules is not None:
        chain.append(stage_rules)

    seen: set[str] = set()
    deduplicated: list[RuleSet] = []
    for rules in chain:
        mandated: list[str] = []
        forbidden: list[str] = []
        for line in rules.mandated:
            normalized = line.strip()
            if normalized not in seen:
                seen.add(normalized)
                mandated.append(line)
        for line in rules.forbidden:
            normalized = line.strip()
            if normalized not in seen:
                seen.add(normalized)
                forbidden.append(line)
        deduplicated.append(rules.model_copy(update={"mandated": mandated, "forbidden": forbidden}))
    return deduplicated


def rules_to_layer(chain: Sequence[RuleSet], counter: TokenCounter | None = None) -> KnowledgeLayer:
    """Return the single inline rules layer for a resolved governance chain.

    Args:
        chain: Deduplicated governance rule sets in scope order.
        counter: Token counter to use; the default counter is used when omitted.

    Returns:
        An inline ``rules`` layer, including when the chain is empty.
    """
    counter = counter or get_default_counter()
    blocks: list[str] = []
    for rules in chain:
        lines = [f"## {rules.layer}"]
        if rules.mandated:
            lines.extend(("### Mandated", *rules.mandated))
        if rules.forbidden:
            lines.extend(("### Forbidden", *rules.forbidden))
        blocks.append("\n".join(lines))
    content = "\n\n".join(blocks)
    revision = hashlib.sha256("|".join(rules.revision for rules in chain).encode()).hexdigest()
    return KnowledgeLayer(
        layer="rules",
        source="governance-chain",
        mode=KnowledgeMode.INLINE,
        revision=revision,
        tokens=counter.count(content),
        content=content,
    )
