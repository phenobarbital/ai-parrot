"""Body parity between `.claude/commands/<name>.md` and its `.agent/workflows/<name>.md` twin (FEAT-545).

The twin may differ ONLY by a leading YAML frontmatter block and by the
`- Worktree policy:` reference line; every other line must be identical.
Pattern: packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TWINNED = ("sdd-spec", "sdd-task")


def _strip_frontmatter(text: str) -> str:
    """Drop a leading ``---`` … ``---`` YAML block, if present."""
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 4)
    return text if end == -1 else text[end + len("\n---\n"):].lstrip("\n")


def _normalize(text: str) -> str:
    """Remove the tolerated delta lines and trailing whitespace noise.

    Two twin-only substitutions exist today, one per command (each references
    `AGENTS.md`/`sdd/WORKFLOW.md` where the `.claude/commands/` original
    references `CLAUDE.md`): `sdd-spec.md`'s "- Worktree policy:" line, and
    `sdd-task.md`'s "sub-features extend a parent feature branch" line. Both
    are stripped so the remaining body must match exactly.
    """
    lines = [
        ln
        for ln in text.splitlines()
        if not ln.startswith("- Worktree policy:")
        and "sub-features extend a parent feature branch — see `" not in ln
    ]
    return "\n".join(lines).strip()


@pytest.mark.parametrize("name", _TWINNED)
def test_command_twin_parity(name: str) -> None:
    """`.agent/workflows/<name>.md` body == `.claude/commands/<name>.md` body."""
    original = _REPO_ROOT / ".claude" / "commands" / f"{name}.md"
    twin = _REPO_ROOT / ".agent" / "workflows" / f"{name}.md"
    if not original.is_file() or not twin.is_file():
        pytest.skip(f"{name}: command or twin missing at this checkout")
    got = _normalize(_strip_frontmatter(twin.read_text(encoding="utf-8")))
    want = _normalize(original.read_text(encoding="utf-8"))
    assert got == want, f"{name}.md drifted between .claude/commands/ and .agent/workflows/"
