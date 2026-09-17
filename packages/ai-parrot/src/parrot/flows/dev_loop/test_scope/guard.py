"""Over-broad pytest guard for sdd-coder attempts (FEAT-563, spec Module 3)."""
from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .context import read_attempt_context
from .contract import is_broad_pytest, parse_validation_commands
from .datatypes import ScopePlan
from .select import changed_files, plan_tests

BLOCK_MESSAGE: str = (
    "no scoped tests for this attempt — add test paths to the task's `## Validation Commands` "
    "or run a specific test file"
)
_ALLOW_SEPARATORS: frozenset[str] = frozenset({"&&", "||", ";", "|"})


@dataclass(frozen=True)
class GuardOutcome:
    """Guard decision for one command."""

    action: str  # "allow" | "rewrite" | "block"
    argvs: tuple[tuple[str, ...], ...] = ()
    message: str = ""


def _is_pytest_argv(argv: Sequence[str]) -> bool:
    """True for pytest / python -m pytest / python3 -m pytest (basename match on argv[0])."""
    if not argv:
        return False
    head = Path(argv[0]).name
    if head == "pytest":
        return True
    return head in {"python", "python3"} and list(argv[1:3]) == ["-m", "pytest"]


def _task_plan(worktree: Path) -> ScopePlan | None:
    """Task-tier plan for the active attempt, or None when no attempt context exists."""
    ctx = read_attempt_context(worktree)
    if ctx is None:
        return None
    try:
        task_text = (worktree / ctx.task_file).read_text(encoding="utf-8")
    except OSError:
        task_text = ""
    declared = parse_validation_commands(task_text) if task_text else []
    return plan_tests(
        worktree=worktree,
        changed_files=changed_files(worktree, ctx.base_ref),
        tier="task",
        declared=declared,
    )


def guard_argv(argv: Sequence[str], *, worktree: Path) -> GuardOutcome:
    """allow when no attempt context or not broad; else rewrite to the task-tier plan, or block when empty."""
    try:
        if not _is_pytest_argv(argv) or not is_broad_pytest(argv):
            return GuardOutcome(action="allow")
        plan = _task_plan(worktree)
        if plan is None:
            return GuardOutcome(action="allow")
        if not plan.invocations:
            return GuardOutcome(action="block", message=BLOCK_MESSAGE)
        argvs = tuple(inv.argv for inv in plan.invocations)
        rendered = " ; ".join(shlex.join(a) for a in argvs)
        return GuardOutcome(action="rewrite", argvs=argvs,
                            message=f"rewritten `{shlex.join(argv)}` → `{rendered}` (tier=task)")
    except Exception:  # noqa: BLE001 — a broken guard must never break a seat
        return GuardOutcome(action="allow")


def _subshell(argvs: Sequence[tuple[str, ...]]) -> str:
    """`( a; r=$?; b; r=$((r|$?)); ...; exit $r )` — every invocation runs, exit is the OR of all codes."""
    pieces = [shlex.join(argv) for argv in argvs]
    body = f"{pieces[0]}; r=$?"
    for piece in pieces[1:]:
        body += f"; {piece}; r=$((r|$?))"
    return f"( {body}; exit $r )"


def guard_bash(command: str, *, worktree: Path) -> tuple[GuardOutcome, str | None]:
    """Same decision for a bash string; returns (outcome, rewritten command or None)."""
    try:
        if "$(" in command or "`" in command or "<<" in command:
            return GuardOutcome(action="allow", message="compound command outside the supported subset"), None

        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        try:
            tokens = list(lexer)
        except ValueError:
            return GuardOutcome(action="allow", message="could not parse the command"), None

        punctuation = set(lexer.punctuation_chars)
        segments: list[list[str]] = [[]]
        separators: list[str] = []
        for token in tokens:
            if token in _ALLOW_SEPARATORS:
                separators.append(token)
                segments.append([])
            elif set(token) and set(token) <= punctuation:
                # a punctuation construct outside the supported separator subset
                # (redirection, subshell parens, background `&`, …)
                return GuardOutcome(action="allow", message="compound command outside the supported subset"), None
            else:
                segments[-1].append(token)

        broad_index = next(
            (i for i, seg in enumerate(segments) if seg and _is_pytest_argv(seg) and is_broad_pytest(seg)),
            None,
        )
        if broad_index is None:
            return GuardOutcome(action="allow"), None

        plan = _task_plan(worktree)
        if plan is None:
            return GuardOutcome(action="allow"), None
        if not plan.invocations:
            return GuardOutcome(action="block", message=BLOCK_MESSAGE), None

        argvs = tuple(inv.argv for inv in plan.invocations)
        pieces_out: list[str] = []
        for i, seg in enumerate(segments):
            pieces_out.append(_subshell(argvs) if i == broad_index else shlex.join(seg))
            if i < len(separators):
                pieces_out.append(separators[i])
        rewritten = " ".join(pieces_out)
        return GuardOutcome(action="rewrite", argvs=argvs, message="rewritten pytest segment (tier=task)"), rewritten
    except Exception:  # noqa: BLE001 — a broken guard must never break a seat
        return GuardOutcome(action="allow"), None
