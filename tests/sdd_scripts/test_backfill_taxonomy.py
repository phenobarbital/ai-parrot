# tests/sdd_scripts/test_backfill_taxonomy.py
"""Tests for scripts.sdd.backfill_taxonomy (FEAT-576)."""
from __future__ import annotations

from pathlib import Path

from scripts.sdd.backfill_taxonomy import infer_projects, main, plan_edit

FRONT = "---\n# a comment that must survive\ntype: feature\nbase_branch: dev\n---\n"


def test_infer_projects() -> None:
    text = (
        "see packages/parrot-formdesigner/src/x.py and parrot_tools.jira, "
        "scripts/sdd/reserve_ids.py, packages/ai-parrot-server/ui/src/App.svelte, parrot/bots/abstract.py"
    )
    assert infer_projects(text) == [
        "parrot-formdesigner", "ai-parrot-tools", "sdd-tooling", "ai-parrot-server", "admin-ui", "ai-parrot",
    ]


def test_plan_edit_preserves_bytes(tmp_path: Path) -> None:
    p = tmp_path / "a.spec.md"
    body = "# A\nuses packages/ai-parrot-server/src/parrot/handlers/x.py\n"
    p.write_text(FRONT + body, encoding="utf-8")
    new = plan_edit(p)
    assert new is not None
    assert new.startswith("---\n# a comment that must survive\ntype: feature\nbase_branch: dev\n")
    assert "projects: [ai-parrot-server]\n" in new and "tags: []\n" in new
    assert new.endswith("---\n" + body)


def test_plan_edit_never_overwrites(tmp_path: Path) -> None:
    p = tmp_path / "b.spec.md"
    p.write_text("---\ntype: feature\nbase_branch: dev\nprojects: [docs]\n---\npackages/ai-parrot/x\n", encoding="utf-8")
    assert plan_edit(p) is None


def test_backfill_dry_run_writes_nothing(tmp_path: Path) -> None:
    spec = tmp_path / "sdd" / "specs" / "c.spec.md"
    spec.parent.mkdir(parents=True)
    original = FRONT + "packages/ai-parrot-tools/src/parrot_tools/x.py\n"
    spec.write_text(original, encoding="utf-8")
    assert main(["--root", str(tmp_path)]) == 0
    assert spec.read_text(encoding="utf-8") == original
    assert main(["--root", str(tmp_path), "--apply"]) == 0
    assert "projects: [ai-parrot-tools]" in spec.read_text(encoding="utf-8")
