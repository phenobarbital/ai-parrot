"""Tests for the domain-expert governance rules chain (FEAT-778 M8)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from parrot.experts.models import (
    ExpertBundle,
    ExpertManifest,
    KnowledgeSourceKind,
    KnowledgeSourceSpec,
    RuleSet,
    RuleSyntaxError,
)
from parrot.experts.rules import parse_rules, resolve_chain, rules_to_layer


class CharacterCounter:
    """Deterministic token counter for rules-layer tests."""

    name = "characters"

    def count(self, text: str) -> int:
        """Return the number of characters in text."""
        return len(text)


def _bundle(root: Path, rules: RuleSet | None = None) -> ExpertBundle:
    """Build the smallest valid expert bundle for resolving governance rules."""
    manifest = ExpertManifest(
        name="sample-expert",
        display_name="Sample Expert",
        description="Rules test bundle",
        knowledge=[KnowledgeSourceSpec(source=KnowledgeSourceKind.WIKI, mode="retrieval")],
    )
    return ExpertBundle(manifest=manifest, root=root, identity_dir=root / "identity", rules=rules)


def test_rules_grammar_rejects_prose(tmp_path: Path) -> None:
    """A prose line outside the strict grammar reports its file and line."""
    path = tmp_path / "rules.md"
    path.write_text("## Mandated\nALWAYS cite sources\nThis is prose\n", encoding="utf-8")

    with pytest.raises(RuleSyntaxError, match=rf"{path}:3"):
        parse_rules(path, layer="org")


def test_rules_grammar_rejects_wrong_section(tmp_path: Path) -> None:
    """An ALWAYS rule is invalid in the forbidden section."""
    path = tmp_path / "rules.md"
    path.write_text("## Forbidden\nALWAYS cite sources\n", encoding="utf-8")

    with pytest.raises(RuleSyntaxError, match=rf"{path}:2"):
        parse_rules(path, layer="org")


def test_rules_chain_is_additive_and_deduped(governance_dir: Path) -> None:
    """Wider duplicate rules are retained and the rendered layer preserves scope order."""
    expert_rules = RuleSet(
        layer="expert",
        source=governance_dir / "experts" / "sample-expert" / "rules" / "governance.md",
        revision="expert-revision",
        mandated=["ALWAYS review evidence", "ALWAYS document decisions"],
        forbidden=["NEVER disclose secrets", "NEVER delegate"],
    )

    chain = resolve_chain(governance_dir, _bundle(governance_dir, expert_rules))
    layer = rules_to_layer(chain, CharacterCounter())

    assert [rules.layer for rules in chain] == ["org", "team", "project", "expert"]
    assert chain[2].mandated == []
    assert chain[3].mandated == ["ALWAYS document decisions"]
    assert chain[3].forbidden == ["NEVER delegate"]
    assert layer.content is not None
    assert layer.content.index("## org") < layer.content.index("## team") < layer.content.index("## project")
    assert layer.content.count("ALWAYS cite sources") == 1
    assert layer.content.count("ALWAYS review evidence") == 1
    assert layer.tokens == len(layer.content)


def test_chain_without_bundle_rules(governance_dir: Path) -> None:
    """Optional bundle rules leave the three workspace layers intact."""
    chain = resolve_chain(governance_dir, _bundle(governance_dir))

    assert [rules.layer for rules in chain] == ["org", "team", "project"]


def test_chain_with_no_governance_dir(tmp_path: Path) -> None:
    """An absent governance directory yields an empty but stable inline layer."""
    chain = resolve_chain(tmp_path, _bundle(tmp_path))
    layer = rules_to_layer(chain, CharacterCounter())

    assert chain == []
    assert layer.content == ""
    assert layer.tokens == 0
    assert layer.revision == hashlib.sha256(b"").hexdigest()


def test_revision_is_sha256(tmp_path: Path) -> None:
    """A ruleset revision is the SHA-256 digest of its exact file bytes."""
    path = tmp_path / "rules.md"
    data = b"<!-- comment -->\n## Mandated\nALWAYS cite sources\n"
    path.write_bytes(data)

    rules = parse_rules(path, layer="org")

    assert rules.revision == hashlib.sha256(data).hexdigest()
