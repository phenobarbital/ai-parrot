"""Convention guards for SDD worktree ownership — FEAT-552 / TASK-3160.

Worktree creation belongs to whoever writes code in the worktree
(`/sdd-start`, `sdd-worker`) and to the dev-loop orchestrators that plan and
dispatch in one run (`sdd-planner`, `sdd-research`, `sdd-autopilot`). Planning
alone (`/sdd-task`) creates none. All of them go through
`scripts.sdd.ensure_worktree`, so exactly one naming rule exists.

These tests keep that true. `.claude/worktrees/` is never inspected: those are
separate checkouts of older branches and legitimately hold the old text.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Files that must not hand-roll a worktree, and whether they must instead
#: name the shared CLI.
_CREATORS: dict[str, bool] = {
    ".claude/commands/sdd-task.md": False,
    ".claude/commands/sdd-start.md": True,
    ".claude/agents/sdd-worker.md": True,
    ".claude/agents/sdd-planner.md": True,
    ".claude/agents/sdd-research.md": True,
    ".claude/agents/sdd-autopilot.md": True,
}

_LEGACY_TEMPLATE = "feat-<id>-<slug>"


def _read(rel: str) -> str:
    path = _REPO_ROOT / rel
    if not path.is_file():
        pytest.skip(f"{rel} missing at this checkout")
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("rel", sorted(_CREATORS))
def test_no_command_hand_rolls_a_worktree(rel: str) -> None:
    """No SDD command or agent runs `git worktree add` itself (FEAT-552)."""
    assert "git worktree add" not in _read(rel), (
        f"{rel} hand-rolls a worktree; call " "`python -m scripts.sdd.ensure_worktree` instead"
    )


@pytest.mark.parametrize("rel", sorted(r for r, needs_cli in _CREATORS.items() if needs_cli))
def test_every_creator_calls_ensure_worktree(rel: str) -> None:
    """Each lane that provisions a worktree goes through the shared CLI."""
    assert "scripts.sdd.ensure_worktree" in _read(
        rel
    ), f"{rel} must call `python -m scripts.sdd.ensure_worktree` to provision worktrees"


def test_no_legacy_naming_template_remains() -> None:
    """`feat-<id>-<slug>` is gone: one template, owned by plan_worktree."""
    claude_dir = _REPO_ROOT / ".claude"
    if not claude_dir.is_dir():
        pytest.skip(".claude/ directory not found at this checkout")

    offenders = []
    for md_file in claude_dir.rglob("*.md"):
        # Skip files under .claude/worktrees/ (separate checkouts)
        if "worktrees" in md_file.parts:
            continue
        # Skip CLAUDE.md (examples are allowed there)
        if md_file.name == "CLAUDE.md":
            continue

        content = md_file.read_text(encoding="utf-8")
        if _LEGACY_TEMPLATE in content:
            offenders.append(md_file.relative_to(_REPO_ROOT))

    assert not offenders, f"Legacy template `{_LEGACY_TEMPLATE}` found in: " + ", ".join(str(p) for p in offenders)
