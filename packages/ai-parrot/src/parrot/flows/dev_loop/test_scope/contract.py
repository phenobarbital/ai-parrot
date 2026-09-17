"""`## Validation Commands` parsing and over-broad pytest detection (FEAT-563 M1/M9)."""

from __future__ import annotations

import re
import shlex
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

VALIDATION_HEADING: str = "## Validation Commands"
_HEADING_RE = re.compile(r"^## Validation Commands\s*$", re.M)
_NEXT_HEADING_RE = re.compile(r"^## ", re.M)
_BULLET_CMD_RE = re.compile(r"^\s*[-*]\s+`([^`]+)`")
_PYTEST_MODULE_FORMS = (("python", "-m", "pytest"), ("python3", "-m", "pytest"))
_OPTIONS_WITH_VALUE = frozenset(
    {"-m", "-k", "-c", "-p", "-o", "-n", "--rootdir", "--confcutdir", "--tb", "--ignore", "--maxfail"}
)
_ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def env_prefix_of(argv: Sequence[str]) -> list[str]:
    """The leading POSIX simple-command `NAME=value` assignment tokens of `argv`, in order ([] if none)."""
    prefix: list[str] = []
    for token in argv:
        if not _ENV_ASSIGNMENT_RE.match(token):
            break
        prefix.append(token)
    return prefix


def strip_env_prefix(argv: Sequence[str]) -> list[str]:
    """Drop leading POSIX simple-command `NAME=value` assignment tokens (e.g. `PYTHONPATH=x pytest ...`).

    `.claude/rules/worktree-management.md` documents exactly this idiom for running pytest inside a
    worktree (`PYTHONPATH=packages/ai-parrot/src pytest ...`) — without this strip, the guard's
    `argv[0]`/`seg[0]` check never recognizes the command as pytest and silently allows it unscoped.
    """
    argv = list(argv)
    return argv[len(env_prefix_of(argv)) :]


def _strip_uv_run_prefix(argv: list[str]) -> list[str]:
    """Drop a leading `uv run [-FLAG ...]` launcher prefix (e.g. `uv run --no-sync pytest ...`).

    `.claude/rules/worktree-management.md` documents `uv run --no-sync` as the sanctioned way to
    invoke tools in a worktree without mutating the shared environment — pytest run this way must
    be recognized just like a bare `pytest` invocation.
    """
    if len(argv) < 2 or PurePosixPath(argv[0]).name != "uv" or argv[1] != "run":
        return argv
    rest = argv[2:]
    i = 0
    while i < len(rest) and rest[i].startswith("-"):
        i += 1
    return rest[i:]


def normalize_pytest_argv(argv: Sequence[str]) -> list[str]:
    """`argv` past any leading env-assignment and/or `uv run [flags]` launcher prefix."""
    return _strip_uv_run_prefix(strip_env_prefix(argv))


def parse_validation_commands(task_md: str) -> list[list[str]]:
    """Backticked commands under '## Validation Commands' (bullets), shlex-split; [] when absent."""
    match = _HEADING_RE.search(task_md)
    if not match:
        return []
    body = task_md[match.end() :]
    nxt = _NEXT_HEADING_RE.search(body)
    body = body[: nxt.start()] if nxt else body
    commands: list[list[str]] = []
    for line in body.splitlines():
        bullet = _BULLET_CMD_RE.match(line)
        if not bullet:
            continue
        try:
            commands.append(shlex.split(bullet.group(1)))
        except ValueError:
            continue
    return commands


def _pytest_operands(argv: Sequence[str]) -> list[str] | None:
    """Positional operands of a pytest argv, or None when argv is not a pytest invocation."""
    argv = normalize_pytest_argv(argv)
    if not argv:
        return None
    head = PurePosixPath(argv[0]).name
    if head == "pytest":
        rest = argv[1:]
    elif len(argv) >= 3 and (head, argv[1], argv[2]) in _PYTEST_MODULE_FORMS:
        rest = argv[3:]
    else:
        return None

    operands: list[str] = []
    i = 0
    while i < len(rest):
        token = rest[i]
        if token.startswith("-"):
            if "=" in token:
                # e.g. --rootdir=/path — the value is embedded, no extra token to skip.
                i += 1
                continue
            if token in _OPTIONS_WITH_VALUE:
                i += 2  # skip the option and its separate value token
                continue
            i += 1  # a bare flag, e.g. -q, --co
            continue
        operands.append(token)
        i += 1
    return operands


def _relativize(op_path: str, worktree: Path | None) -> str:
    """Best-effort: rewrite an absolute `op_path` relative to `worktree`; unchanged otherwise.

    An absolute operand pointing at the exact same broad directory as its relative form (e.g.
    `/abs/repo/packages/ai-parrot/tests` vs. `packages/ai-parrot/tests`) must be recognized the
    same way — `is_broad_pytest` only ever inspects the relative shape, so without this the guard
    silently treats an absolute-path broad run as narrow. `worktree=None` (no worktree known, e.g.
    a worktree-agnostic caller/unit test) leaves any absolute operand untouched, same as before
    this parameter existed.
    """
    if worktree is None or not PurePosixPath(op_path).is_absolute():
        return op_path
    try:
        return str(Path(op_path).resolve().relative_to(Path(worktree).resolve()).as_posix())
    except (OSError, ValueError):
        return op_path


def is_pytest_invocation(argv: Sequence[str]) -> bool:
    """True when `argv` is `pytest ...` / `python[3] -m pytest ...` (past env/`uv run` prefixes).

    A declared `## Validation Commands` entry that is NOT a pytest invocation at all (e.g. `true`
    or `ruff check .`) is silently invisible to `plan_tests`/`is_broad_pytest` — this lets a task
    (or a lint) tell the two apart from a command that IS pytest but simply narrow.
    """
    return _pytest_operands(argv) is not None


def is_broad_pytest(argv: Sequence[str], *, worktree: Path | None = None) -> bool:
    """True for pytest with no path operand or an operand in {., tests, packages/<dist>/tests} or a
    parent. Pass `worktree` so an absolute operand pointing at one of those same directories is
    also recognized (see `_relativize`)."""
    operands = _pytest_operands(argv)
    if operands is None:
        return False
    if not operands:
        return True
    for op in operands:
        raw = _relativize(op.split("::", 1)[0].rstrip("/") or ".", worktree)
        path = PurePosixPath(raw)
        parts = path.parts
        if parts in ((), (".",), ("tests",), ("packages",)):
            return True
        if len(parts) == 2 and parts[0] == "packages":
            return True
        if len(parts) == 3 and parts[0] == "packages" and parts[2] == "tests":
            return True
    return False
