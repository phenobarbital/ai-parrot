"""FEAT-784 M10: the committed taxonomy and seed rules are valid (AC16, AC20)."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.knowledge.wiki.decisions.parser import parse_frontmatter
from parrot.knowledge.wiki.decisions.spec_entries import SEED_HEADING, parse_spec_decisions
from parrot.knowledge.wiki.decisions.taxonomy import Taxonomy

_REPO_ROOT = Path(__file__).resolve().parents[6]
SEEDS = sorted((_REPO_ROOT / "docs/decisions").glob("*.md"))
EXPECTED = {
    "clients-memoryless",
    "history-single-writer",
    "non-blocking-async-stack",
    "http-stack-aiohttp",
    "config-core-navconfig",
    "auth-platform-navigator-auth",
    "tools-live-in-parrot-tools",
    "no-langchain",
    "clients-base-protected",
}


def test_taxonomy_loads() -> None:
    taxonomy = Taxonomy.load(_REPO_ROOT / "sdd/taxonomy/subsystems.yaml")
    assert len(taxonomy.ids()) == 14


def test_all_nine_seeds_present() -> None:
    assert {path.stem for path in SEEDS} >= EXPECTED


@pytest.mark.parametrize("path", SEEDS, ids=lambda path: path.stem)
def test_seed_parses_and_resolves(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    frontmatter, _, frontmatter_diagnostics = parse_frontmatter(text.splitlines())
    assert frontmatter_diagnostics == []
    assert frontmatter["status"] == "accepted"

    block, waivers, diagnostics = parse_spec_decisions(
        text,
        source_path=path.relative_to(_REPO_ROOT).as_posix(),
        heading=SEED_HEADING,
    )
    assert diagnostics == []
    assert waivers == []
    assert block is not None
    assert block.document_id == f"seed-{path.stem}"

    taxonomy = Taxonomy.load(_REPO_ROOT / "sdd/taxonomy/subsystems.yaml")
    for entry in block.entries:
        assert set(entry.about) <= taxonomy.ids()
        for target in entry.targets:
            prefix, separator, value = target.partition(":")
            assert separator == ":"
            assert prefix in {"sym", "file", "dir"}
            if prefix == "sym":
                target_path, symbol_separator, symbol = value.partition("#")
                assert symbol_separator == "#" and target_path and symbol
            else:
                target_path = value
                assert target_path
            assert (_REPO_ROOT / target_path).exists()


def test_rule3_rationale_states_stack_consistency() -> None:
    text = (_REPO_ROOT / "docs/decisions/non-blocking-async-stack.md").read_text(encoding="utf-8")
    assert "stack consistency" in text and "httpx" in text
