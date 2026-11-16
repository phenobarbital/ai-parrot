"""The operator page for the procedure graph exists and covers what the spec requires (FEAT-891)."""

from pathlib import Path

import pytest

PAGE = Path(__file__).resolve().parents[6] / "wiki" / "sdd-tooling" / "sdd" / "procedure-graph.md"

REQUIRED = (
    "parrot sdd procedure build",
    "parrot sdd procedure next",
    "parrot sdd procedure check",
    "parrot sdd procedure brief",
    "wiki_procedure_next",
    "PARROT_ALLOW_PROCEDURE",
    "PARROT_ALLOW_DANGEROUS",
    "enforce",
    "wikitoolkit ns add procedure",
    "## Pilot activation",
    "parrot sdd install --portable",
    "## Pilot baseline",
    "parrot sdd task state",
)


def test_docs_present() -> None:
    """The page exists and names the CLI verbs, the three escape switches and the pilot steps."""
    if not PAGE.parent.is_dir():
        pytest.skip("not running from the monorepo checkout")
    text = PAGE.read_text(encoding="utf-8")
    missing = [needle for needle in REQUIRED if needle not in text]
    assert not missing, f"procedure-graph.md lacks: {missing}"
