"""FEAT-803 AC9/AC10."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_minimal_configuration_is_first_section() -> None:
    text = (ROOT / "docs" / "config.md").read_text(encoding="utf-8")
    first_h2 = next(line for line in text.splitlines() if line.startswith("## "))
    assert first_h2.strip() == "## Minimal Configuration"


def test_tools_quick_is_curated() -> None:
    text = (ROOT / "docs" / "tools_quick.md").read_text(encoding="utf-8")
    sections = [line for line in text.splitlines() if line.startswith("## ") and line.strip() != "## Full Catalog"]
    assert 3 <= len(sections) <= 4
    assert "github.com/phenobarbital/ai-parrot/wiki" in text
