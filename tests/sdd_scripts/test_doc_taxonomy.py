# tests/sdd_scripts/test_doc_taxonomy.py
"""Tests for scripts.sdd.doc_taxonomy (FEAT-576)."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.sdd.doc_taxonomy import TaxonomyRow, collect, filter_rows, main

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write(root: Path, rel: str, front: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\ntype: feature\nbase_branch: dev\n{front}---\n# x\n", encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _write(tmp_path, "sdd/specs/a.spec.md", "projects: [ai-parrot]\ntags: [memory]\n")
    _write(tmp_path, "sdd/specs/b.spec.md", "projects: [parrot-formdesigner]\ntags: [mcp]\n")
    _write(tmp_path, "sdd/proposals/c.brainstorm.md", "tags: [memory]\n")
    _write(tmp_path, "sdd/specs/bad.spec.md", "tags: ['!!']\n")
    return tmp_path


def test_collect_skips_invalid_doc(repo: Path) -> None:
    paths = [r.path for r in collect(repo)]
    assert "sdd/specs/bad.spec.md" not in paths
    assert len(paths) == 3


def test_filter_and_or_semantics(repo: Path) -> None:
    rows = collect(repo)
    assert {r.path for r in filter_rows(rows, [], ["memory"])} == {
        "sdd/specs/a.spec.md",
        "sdd/proposals/c.brainstorm.md",
    }
    assert [r.path for r in filter_rows(rows, ["ai-parrot"], ["memory"])] == ["sdd/specs/a.spec.md"]
    assert {r.path for r in filter_rows(rows, ["formdesigner", "ai-parrot"], [])} == {
        "sdd/specs/a.spec.md",
        "sdd/specs/b.spec.md",
    }


def test_cli_paths_only(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--root", str(repo), "--kind", "spec", "--paths-only", "--tag", "mcp"]) == 0
    assert capsys.readouterr().out.split() == ["sdd/specs/b.spec.md"]


def test_doc_taxonomy_on_repo() -> None:
    assert isinstance(collect(REPO_ROOT), list)
