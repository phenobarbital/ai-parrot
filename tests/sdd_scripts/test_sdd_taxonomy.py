"""Unit tests for the FEAT-576 SDD taxonomy parser."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.sdd.sdd_meta import KNOWN_PROJECTS, DocTaxonomy, normalize_tag, parse, parse_taxonomy

REPO_ROOT = Path(__file__).resolve().parents[2]


def _doc(tmp_path: Path, front: str) -> Path:
    p = tmp_path / "x.spec.md"
    p.write_text(f"---\n{front}---\n# X\n", encoding="utf-8")
    return p


def test_parse_taxonomy_absent_returns_empty(tmp_path: Path) -> None:
    p = tmp_path / "plain.md"
    p.write_text("# no frontmatter\n", encoding="utf-8")
    assert parse_taxonomy(p) == DocTaxonomy()


def test_parse_taxonomy_scalar_coerced(tmp_path: Path) -> None:
    assert parse_taxonomy(_doc(tmp_path, "tags: memory\n")).tags == ["memory"]


def test_normalize_tag() -> None:
    assert normalize_tag("Tool Output_Pruning") == "tool-output-pruning"
    with pytest.raises(ValueError):
        normalize_tag("!!")


def test_project_alias(tmp_path: Path) -> None:
    t = parse_taxonomy(_doc(tmp_path, "projects: [parrot-core, formdesigner]\n"))
    assert t.projects == ["ai-parrot", "parrot-formdesigner"]


def test_unknown_project_warns_not_fails(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        t = parse_taxonomy(_doc(tmp_path, "projects: [mystery-area]\n"))
    assert t.projects == ["mystery-area"]
    assert "mystery-area" in caplog.text


def test_dedupe_preserves_order(tmp_path: Path) -> None:
    assert parse_taxonomy(_doc(tmp_path, "tags: [b, a, B]\n")).tags == ["b", "a"]


def test_malformed_tag_raises(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        parse_taxonomy(_doc(tmp_path, "tags: ['!!']\n"))


def test_parse_unchanged_with_taxonomy_keys(tmp_path: Path) -> None:
    meta = parse(_doc(tmp_path, "type: feature\nbase_branch: dev\nprojects: [ai-parrot]\ntags: [x]\n"))
    assert (meta.type, meta.base_branch) == ("feature", "dev")


def test_parse_empty_block_still_raises(tmp_path: Path) -> None:
    p = tmp_path / "empty.md"
    p.write_text("---\n---\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        parse(p)


def test_known_projects_covers_packages_dir() -> None:
    dists = {p.parent.name for p in (REPO_ROOT / "packages").glob("*/pyproject.toml")}
    assert dists, "packages/*/pyproject.toml not found"
    assert dists <= KNOWN_PROJECTS, f"missing from KNOWN_PROJECTS: {sorted(dists - KNOWN_PROJECTS)}"
