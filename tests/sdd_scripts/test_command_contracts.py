"""Convention guards for SDD worktree ownership — FEAT-552 / TASK-3160.

Worktree creation belongs to whoever writes code in the worktree
(`/sdd-start`, `sdd-worker`) and to the dev-loop orchestrators that plan and
dispatch in one run (`sdd-planner`, `sdd-research`, `sdd-autopilot`). Planning
alone (`/sdd-task`) creates none. All of them go through
`parrot sdd worktree ensure`, so exactly one naming rule exists.

Live worktrees (under the resolved worktree root, and legacy ones under `.claude/worktrees/`) are never inspected: those are
separate checkouts of older branches and legitimately hold the old text.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Files that must not hand-roll a worktree, and whether they must instead
#: name the shared CLI.
_CREATORS: dict[str, bool] = {
    ".claude/commands/sdd-task.md": False,
    ".claude/commands/sdd-start.md": True,
    ".claude/commands/sdd-brief.md": True,
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
        f"{rel} hand-rolls a worktree; call " "`parrot sdd worktree ensure` instead"
    )


@pytest.mark.parametrize("rel", sorted(r for r, needs_cli in _CREATORS.items() if needs_cli))
def test_every_creator_calls_ensure_worktree(rel: str) -> None:
    """Each lane that provisions a worktree goes through the shared CLI."""
    assert "parrot sdd worktree ensure" in _read(
        rel
    ), f"{rel} must call `parrot sdd worktree ensure` to provision worktrees"


#: Agent prompts that run /sdd-spec unattended — they must never enter intake mode (FEAT-577).
_UNATTENDED_SPEC_CALLERS = (
    ".claude/agents/sdd-research.md",
    ".claude/agents/sdd-planner.md",
    "packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-research.md",
    "packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-planner.md",
)


@pytest.mark.parametrize("rel", _UNATTENDED_SPEC_CALLERS)
def test_unattended_callers_pass_no_interview(rel: str) -> None:
    """Every /sdd-spec invocation in an unattended agent carries --no-interview (FEAT-577)."""
    content = _read(rel)
    lines = content.splitlines()
    spec_lines = [line for line in lines if "/sdd-spec " in line and "<slug>" in line]
    assert spec_lines, f"No /sdd-spec <slug> invocation found in {rel}"
    for line in spec_lines:
        assert "--no-interview" in line, f"Line in {rel} missing --no-interview: {line}"


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

_LEGACY_ROOT = ".claude/worktrees"
_GUARD_DIRS = (".claude", ".agent", ".agents", "packages/ai-parrot/src/parrot/sdd/_assets")
_GUARD_SUFFIXES = {".md", ".toml", ".sh"}


def test_no_legacy_worktree_root_remains() -> None:
    """No .md/.toml/.sh under .claude/, .agent/, .agents/, parrot/sdd/_assets/ and CLAUDE.md names
    `.claude/worktrees` except lines that also contain `git worktree repair` (the migration recipe).
    Files under a live worktree are skipped exactly as the sibling test does."""
    if not (_REPO_ROOT / ".claude").is_dir():
        pytest.skip(".claude/ directory not found at this checkout")
    offenders: list[str] = []
    candidates: list[Path] = []
    for guard_dir in _GUARD_DIRS:
        dir_path = _REPO_ROOT / guard_dir
        if dir_path.is_dir():
            candidates.extend(p for p in dir_path.rglob("*") if p.is_file() and p.suffix in _GUARD_SUFFIXES)
    claude_md = _REPO_ROOT / "CLAUDE.md"
    if claude_md.is_file():
        candidates.append(claude_md)

    for path in candidates:
        if "worktrees" in path.parts or path.name == "settings.local.json":
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(content.splitlines(), start=1):
            if _LEGACY_ROOT in line:
                if "git worktree repair" in line or "(claude|parrot)" in line:
                    continue
                rel = path.relative_to(_REPO_ROOT)
                offenders.append(f"{rel}:{lineno}")

    assert not offenders, "Legacy worktree root still named in: " + ", ".join(offenders)


_SHIPPED_WITH_INLINE_PYTHON_BAN = (
    ".claude/commands/sdd-spec.md",
    ".agent/workflows/sdd-spec.md",
    ".claude/commands/sdd-task.md",
    ".agent/workflows/sdd-task.md",
    ".agents/skills/sdd-task/SKILL.md",
    ".claude/agents/sdd-worker.md",
    ".agents/agents/sdd-worker/agent.md",
    # rev 0.5 C22 E: the navconfig one-liners became an env-var precondition, so after rules 6 + E these
    # twins carry no inline Python either:
    ".claude/commands/sdd-done.md",
    ".agent/workflows/sdd-done.md",
    ".claude/commands/sdd-tojira.md",
    ".agent/workflows/sdd-tojira.md",
)
# `python -c "` one-liners and `python - … <<` heredocs; prose mentions of `python -c` in
# backticks without an opening quote are not invocations and are not matched.
_INLINE_PY = re.compile(r'python3?\s+(?:-c\s+"|-\s+(?:"\$\w+"\s+)?<<)')


@pytest.mark.parametrize("rel", _SHIPPED_WITH_INLINE_PYTHON_BAN)
def test_shipped_commands_have_no_inline_python(rel: str) -> None:
    """FEAT-633 Q1 (TASK-4334): a shipped command never embeds Python — only the ``sdd_meta``
    one-liners remain, and TASK-4089 rule 6 retires those (then the allowance below is
    exercised zero times and this test still passes)."""
    lines = (_REPO_ROOT / rel).read_text(encoding="utf-8").splitlines()
    offenders = []
    for i, line in enumerate(lines):
        if not _INLINE_PY.search(line):
            continue
        window = "\n".join(lines[i : i + 4])
        if "scripts.sdd.sdd_meta" in window:
            continue  # TASK-4299 gives sdd_meta a CLI; TASK-4089 rewrites these by hand
        offenders.append(f"{rel}:{i + 1}: {line.strip()[:80]}")
    assert not offenders, offenders
