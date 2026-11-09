"""FEAT-860 regression tests for crew definition documentation."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
DOCUMENTATION_PAGES = (
    REPO_ROOT / "wiki/bots/orchestration/crew-definition-storage.md",
    REPO_ROOT / "wiki/bots/crew_handler.md",
)


@pytest.mark.parametrize("page", DOCUMENTATION_PAGES)
def test_required_crew_page_has_title_and_summary(page: Path) -> None:
    """Require each declared page to expose techwiki title and summary metadata."""
    content = page.read_text(encoding="utf-8")
    frontmatter = content.split("---", maxsplit=2)

    assert len(frontmatter) == 3, f"{page} has no YAML frontmatter"
    assert frontmatter[0] == ""
    assert "\ntitle:" in frontmatter[1]
    assert "\nsummary:" in frontmatter[1]


def test_required_crew_documentation() -> None:
    """Run the advisory spec check and reject any missing-page diagnostic."""
    result = subprocess.run(
        [
            "parrot",
            "sdd",
            "techwiki",
            "check",
            "--spec",
            "sdd/specs/postgres-crew-storage.spec.md",
            "--root",
            ".",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    output = f"{result.stdout}\n{result.stderr}".lower()

    assert result.returncode == 0, output
    assert "missing:" not in output, output
    assert "docs_required_missing_pages" not in output, output
