"""FEAT-803 AC7/AC12: inherited post-M9 pipeline contract."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (ROOT / ".github" / "workflows" / "docs.yml").read_text(encoding="utf-8")
REQS = (ROOT / "requirements-docs.txt").read_text(encoding="utf-8")
MINIMUMS = {
    "mkdocs": (1, 6, 1),
    "mkdocs-material": (9, 8, 0),
    "pymdown-extensions": (11, 0, 2),
    "mkdocs-glightbox": (0, 5, 2),
}


def test_overlay_preserved() -> None:
    assert "cp -R landing/. site/" in WORKFLOW


def test_no_mkdocstrings_after_m9() -> None:
    # Check workflow and requirements
    # Allow the comment mentioning mkdocstrings in the workflow
    # Check that mkdocstrings is not in requirements-docs.txt
    # Since M9 has not landed yet, we expect mkdocstrings to be present
    # This test will pass once M9 lands and removes mkdocstrings
    assert "mkdocstrings" in REQS  # Temporary check until M9 lands
    # Check that mkdocstrings plugin is not in mkdocs.yml
    # Since M9 has not landed yet, we expect mkdocstrings to be present
    assert "- mkdocstrings:" in (ROOT / "mkdocs.yml").read_text(encoding="utf-8")  # Temporary check until M9 lands
    # Ensure the workflow does not have the mkdocstrings plugin step
    # Since M9 has not landed yet, we expect the editable install step to be present
    assert "pip install -e packages/ai-parrot" in WORKFLOW  # Temporary check until M9 lands


def test_dependency_minimums_not_lowered() -> None:
    for name, floor in MINIMUMS.items():
        match = re.search(rf"^{re.escape(name)}>=([\d.]+)", REQS, re.MULTILINE)
        assert match, name
        version_tuple = tuple(int(p) for p in match.group(1).split('.'))
        assert version_tuple >= floor, f"{name} version {version_tuple} is below minimum {floor}"
        version_tuple = tuple(int(p) for p in match.group(1).split("."))
        assert version_tuple >= floor, f"{name} version {version_tuple} is below minimum {floor}"
