"""Body parity between `.claude/commands/<name>.md` and its `.agent/workflows/<name>.md` twin (FEAT-545).

The twin may differ ONLY by a leading YAML frontmatter block and by exactly
ONE documented per-command substitution line (each references
`AGENTS.md`/`sdd/WORKFLOW.md` where the `.claude/commands/` original
references `CLAUDE.md`). Rather than dropping whatever is on the tolerated
line (which would hide unrelated drift appended to it), this test applies
the specific expected substitution to the original and asserts the result
is byte-identical to the twin — any other difference, anywhere, still fails.
Pattern: packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TWINNED = ("sdd-spec", "sdd-task")

# name -> (exact original substring, exact twin substring). Each pair must
# appear exactly once in its respective file today; see TASK-3098's
# Completion Note for how these were re-verified against a stale assumption.
_SUBSTITUTIONS: dict[str, tuple[str, str]] = {
    "sdd-spec": (
        '- Worktree policy: `CLAUDE.md` (section "Worktree Policy")',
        "- Worktree policy: `AGENTS.md` and `sdd/WORKFLOW.md`",
    ),
    "sdd-task": (
        "(sub-features extend a parent feature branch — see `CLAUDE.md`).",
        "(sub-features extend a parent feature branch — see `AGENTS.md`).",
    ),
}


def _strip_frontmatter(text: str) -> str:
    """Drop a leading ``---`` … ``---`` YAML block, if present."""
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 4)
    return text if end == -1 else text[end + len("\n---\n") :].lstrip("\n")


def _apply_expected_substitution(name: str, original_text: str) -> str:
    """Apply the ONE documented twin-only substitution for `name`.

    Asserts the substitution anchor is present exactly once, so a future
    edit that changes or removes that line causes this test to fail loudly
    (pointing at the stale anchor) rather than silently pass.
    """
    original_line, twin_line = _SUBSTITUTIONS[name]
    count = original_text.count(original_line)
    assert count == 1, (
        f"{name}: expected exactly one occurrence of the tolerated-delta anchor "
        f"{original_line!r} in .claude/commands/{name}.md, found {count}"
    )
    return original_text.replace(original_line, twin_line)


@pytest.mark.parametrize("name", _TWINNED)
def test_command_twin_parity(name: str) -> None:
    """`.agent/workflows/<name>.md` body == `.claude/commands/<name>.md` body,
    modulo frontmatter and the one documented substitution."""
    original = _REPO_ROOT / ".claude" / "commands" / f"{name}.md"
    twin = _REPO_ROOT / ".agent" / "workflows" / f"{name}.md"
    if not original.is_file() or not twin.is_file():
        pytest.skip(f"{name}: command or twin missing at this checkout")
    got = _strip_frontmatter(twin.read_text(encoding="utf-8")).strip()
    want = _apply_expected_substitution(name, original.read_text(encoding="utf-8")).strip()
    assert got == want, f"{name}.md drifted between .claude/commands/ and .agent/workflows/"
