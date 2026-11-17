"""FEAT-803 AC6/AC7/AC12: post-M9 pipeline contract."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (ROOT / ".github" / "workflows" / "docs.yml").read_text(encoding="utf-8")
REQS = (ROOT / "requirements-docs.txt").read_text(encoding="utf-8")
MKDOCS = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
MINIMUMS = {
    "mkdocs": (1, 6, 1),
    "mkdocs-material": (9, 8, 0),
    "pymdown-extensions": (11, 0, 2),
    "mkdocs-glightbox": (0, 5, 2),
}


def test_overlay_preserved() -> None:
    assert "cp -R landing/. site/" in WORKFLOW


def test_no_mkdocstrings_after_m9() -> None:
    assert "mkdocstrings" not in REQS
    assert "mkdocstrings" not in MKDOCS
    assert "pip install -e packages/ai-parrot" not in WORKFLOW
    assert not (ROOT / "docs" / "api-reference").exists()


def test_ci_build_is_strict() -> None:
    assert "mkdocs build --strict" in WORKFLOW


def test_tools_quick_in_nav() -> None:
    assert "tools_quick.md" in MKDOCS


def test_dependency_minimums_not_lowered() -> None:
    for name, floor in MINIMUMS.items():
        match = re.search(rf"^{re.escape(name)}>=([\d.]+)", REQS, re.MULTILINE)
        assert match, name
        version_tuple = tuple(int(p) for p in match.group(1).split("."))
        assert version_tuple >= floor, f"{name} version {version_tuple} is below minimum {floor}"


def test_wiki_links_resolve_to_published_pages() -> None:
    """Every wiki link in the site docs names a real page (migration map) or Home."""
    from urllib.parse import unquote

    names = {"Home"}
    for line in (ROOT / "sdd" / "state" / "FEAT-801" / "migration-map.md").read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.split("|")]
        if len(cells) > 4 and cells[1].startswith("`docs/"):
            names.add(unquote(cells[3]))
    pattern = re.compile(r"github\.com/phenobarbital/ai-parrot/wiki/([^)\s\"'>]+)")
    bad = []
    for path in [
        *(ROOT / "docs").glob("*.md"),
        *(ROOT / "docs" / "chapters").glob("*.md"),
        *(ROOT / "docs" / "tutorials").glob("*.md"),
    ]:
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            if unquote(match.group(1)) not in names:
                bad.append((path.name, match.group(1)))
    assert not bad, bad
