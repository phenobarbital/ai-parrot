"""Contract: sdd/templates/brief.md stays parseable as BriefMeta — FEAT-698 / TASK-4428."""

from __future__ import annotations

from pathlib import Path

from scripts.sdd.brief_meta import parse_brief

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATE = _REPO_ROOT / "sdd/templates/brief.md"
_SECTIONS = (
    "## Problem",
    "## Root cause",
    "## Research findings",
    "## Decisions",
    "## Fix plan",
    "## Validation commands",
)


def test_template_sections_present() -> None:
    """The brief template retains every implementer-facing section."""
    text = _TEMPLATE.read_text(encoding="utf-8")
    for heading in _SECTIONS:
        assert heading in text, f"brief template lost section {heading!r}"


def test_filled_template_parses(tmp_path: Path) -> None:
    """Replacing every template token produces valid brief metadata."""
    replacements = {
        "<slug>": "demo-fix",
        "<key>": "cs-224",
        "<base_branch>": "main",
        "<source_type>": "code-scanning",
        "<source_ref>": '"224"',
        "<source_url>": "null",
        "<created>": '"2026-10-17T00:00:00+00:00"',
        "<Title>": "Demo fix",
        "<KEY>": "cs-224",
    }
    text = _TEMPLATE.read_text(encoding="utf-8")
    for placeholder, value in replacements.items():
        text = text.replace(placeholder, value)

    document = tmp_path / "demo-fix.brief.md"
    document.write_text(text, encoding="utf-8")

    assert parse_brief(document).feature_id == "BRIEF-cs-224"


def test_template_has_no_type_key() -> None:
    """Brief frontmatter never uses FlowMeta's top-level ``type`` key."""
    text = _TEMPLATE.read_text(encoding="utf-8")
    frontmatter = text.split("---", 2)[1]

    assert not any(line.startswith("type:") for line in frontmatter.splitlines())
