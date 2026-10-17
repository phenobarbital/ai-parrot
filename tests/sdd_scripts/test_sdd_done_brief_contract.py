"""/sdd-done opens PRs (main included), never merges main; brief lane present — FEAT-698 / TASK-4435."""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_DOC = _ROOT / ".claude/commands/sdd-done.md"
_TWIN = _ROOT / ".agents/skills/sdd-done/SKILL.md"


def _doc() -> str:
    return _DOC.read_text(encoding="utf-8")


def test_old_never_open_pr_rule_gone() -> None:
    doc = _doc()
    assert "NEVER opens a PR against `main`" not in doc
    assert "NEVER merges into `main`" in doc


def test_pr_created_with_base_branch_variable() -> None:
    doc = _doc()
    assert 'gh pr create \\\n  --base "$BASE_BRANCH" \\\n  --head "$BRANCH"' in doc
    assert '--head "feat-<FEAT-ID>-<slug>"' not in doc
    assert "fail closed" in doc


def test_merge_into_main_refused_before_push() -> None:
    doc = _doc()
    refusal = doc.index('"$BASE_BRANCH" == "main" && "$MERGE_FLAG" == "--merge"')
    assert doc.index("### 8.") < refusal < doc.index("git -C <worktree-path> push origin \"$BRANCH\"")
    assert refusal < doc.index("### 9.")


def test_brief_lane_present_and_never_checks_out_main() -> None:
    doc = _doc()
    assert "### 2b. Brief Lane (FEAT-698)" in doc
    lane = doc[doc.index("### 2b."): doc.index("### 3. Locate the Worktree")]
    assert "never runs `git checkout`" in lane
    assert "sdd/briefs/<slug>.index.json" in lane
    assert not re.search(r"^\s*git checkout", lane, re.M)


def test_ledger_close_only_after_confirmed_merge() -> None:
    doc = _doc()
    assert "wikitoolkit ledger close <ledger_issue>" in doc
    assert "only once the fix is confirmed merged" in doc


def test_twin_no_longer_prints_manual_main_pr() -> None:
    twin = _TWIN.read_text(encoding="utf-8")
    assert "print a manual `gh pr create --base main`" not in twin
    assert "refuse automatic merge or PR creation" not in twin
    assert "never merge into `main`" in twin
    assert "brief" in twin
