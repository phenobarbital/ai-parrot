"""FEAT-836: ``sdd_meta.parse()`` and ``worktree_sync.resolve_base_branch`` on /sdd-brief frontmatter."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from parrot.knowledge.wiki.ledger.sdd_meta import parse
from parrot.sdd.config import SddConfig
from parrot.sdd.scripts import worktree_sync

CFG = SddConfig(base_branch="dev", hotfix_base="main")


def _brief(path: Path, body: str) -> Path:
    """Write a brief file with ``body`` as its YAML frontmatter."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{body}---\n\n# Brief\n", encoding="utf-8")
    return path


def test_parse_brief_on_hotfix_base_is_hotfix(tmp_path: Path) -> None:
    """The frontmatter shape from the issue (brief on main, with hotfix_base) parses as a hotfix."""
    doc = _brief(
        tmp_path / "b.brief.md",
        "kind: brief\nslug: x\nkey: NAV-1\nbase_branch: main\nhotfix_base: main\n",
    )
    meta = parse(doc, config=CFG)
    assert meta.type == "hotfix"
    assert meta.base_branch == "main"


def test_parse_brief_on_dev_is_feature(tmp_path: Path) -> None:
    """A ledger-sourced brief on dev parses as a feature; extra brief keys are ignored."""
    doc = _brief(
        tmp_path / "b.brief.md",
        "kind: brief\nslug: x\nkey: abc123\nbase_branch: dev\n"
        'source:\n  type: ledger\n  ref: issue:abc123\n  url: null\ncreated: "2026-11-02"\n',
    )
    meta = parse(doc, config=CFG)
    assert meta.type == "feature"
    assert meta.base_branch == "dev"


def test_parse_brief_explicit_type_kept(tmp_path: Path) -> None:
    """An explicit ``type`` is not overridden, so hotfix-on-dev still fails validation."""
    doc = _brief(tmp_path / "b.brief.md", "kind: brief\ntype: hotfix\nbase_branch: dev\n")
    with pytest.raises(ValidationError):
        parse(doc, config=CFG)


def test_parse_brief_without_base_branch_fails(tmp_path: Path) -> None:
    """``parse()`` never invents a base branch for a brief."""
    doc = _brief(tmp_path / "b.brief.md", "kind: brief\nslug: x\n")
    with pytest.raises(ValidationError):
        parse(doc, config=CFG)


def test_resolve_base_branch_reads_brief_frontmatter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A ``fix-*`` brief worktree resolves its base from the brief instead of raising SyncError."""
    wt = tmp_path / "wt"
    _brief(wt / "sdd" / "briefs" / "thing.brief.md", "kind: brief\nslug: thing\nkey: abc123\nbase_branch: dev\n")
    monkeypatch.setattr(worktree_sync, "_branch", lambda _wt: "fix-abc123-thing")
    assert worktree_sync.resolve_base_branch(wt, None) == "dev"
