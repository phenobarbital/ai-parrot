"""Over-broad pytest guard for sdd-coder attempts (FEAT-563, spec Module 3)."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .context import read_attempt_context
from .contract import parse_validation_commands
from .datatypes import ScopePlan
from .runners.registry import load_registry
from .select import changed_files, plan_tests

BLOCK_MESSAGE: str = (
    "no scoped tests for this attempt — add test paths to the task's `## Validation Commands` "
    "or run a specific test file"
)
VERDICT_ARGV: tuple[str, ...] = ("python", "scripts/sdd/select_tests.py", "--tier", "task", "--run", "--verdict")
_ALLOW_SEPARATORS: frozenset[str] = frozenset({"&&", "||", ";", "|"})


@dataclass(frozen=True)
class GuardOutcome:
    """Guard decision for one command."""

    action: str  # "allow" | "verdict" | "block"
    argvs: tuple[tuple[str, ...], ...] = ()
    message: str = ""


def _runner_for(argv: Sequence[str], *, worktree: Path) -> "RunnerAdapter | None":
    """Return the registered runner for ``argv``, or None when registry loading fails."""
    try:
        return load_registry(worktree).adapter_for_argv(argv)
    except ValueError:
        return None


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
    """Return a task-tier validation verdict for a broad registered runner command."""
    try:
        runner = _runner_for(argv, worktree=worktree)
        if runner is None or not runner.is_broad(argv, worktree=worktree):
            return GuardOutcome(action="allow")
        plan = _task_plan(worktree)
        if plan is None:
            return GuardOutcome(action="allow")
        if not plan.invocations:
            return GuardOutcome(action="block", message=BLOCK_MESSAGE)
        return GuardOutcome(
            action="verdict",
            argvs=((*VERDICT_ARGV, "--worktree", str(worktree)),),
            message=f"`{shlex.join(argv)}` runs through the validation verdict (tier=task)",
        )
    except Exception:  # noqa: BLE001 — a broken guard must never break a seat
        return GuardOutcome(action="allow")


def guard_bash(command: str, *, worktree: Path) -> tuple[GuardOutcome, str | None]:
    """Return a verdict command for one broad runner command; compounds remain allowed."""
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

        if separators or len(segments) != 1:
            return GuardOutcome(action="allow"), None
        argv = segments[0]
        runner = _runner_for(argv, worktree=worktree)
        if runner is None or not runner.is_broad(argv, worktree=worktree):
            return GuardOutcome(action="allow"), None

        plan = _task_plan(worktree)
        if plan is None:
            return GuardOutcome(action="allow"), None
        if not plan.invocations:
            return GuardOutcome(action="block", message=BLOCK_MESSAGE), None

        verdict_argv = (*VERDICT_ARGV, "--worktree", str(worktree))
        rewritten = f"cd {shlex.quote(str(worktree))} && {shlex.join(verdict_argv)}"
        return GuardOutcome(
            action="verdict", argvs=(verdict_argv,), message="runner command uses validation verdict (tier=task)"
        ), rewritten
    except Exception:  # noqa: BLE001 — a broken guard must never break a seat
        return GuardOutcome(action="allow"), None
