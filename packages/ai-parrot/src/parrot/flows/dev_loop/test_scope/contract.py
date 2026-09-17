"""`## Validation Commands` parsing and over-broad pytest detection (FEAT-563 M1/M9)."""
from __future__ import annotations

import re
import shlex
from collections.abc import Sequence
from pathlib import PurePosixPath

VALIDATION_HEADING: str = "## Validation Commands"
_HEADING_RE = re.compile(r"^## Validation Commands\s*$", re.M)
_NEXT_HEADING_RE = re.compile(r"^## ", re.M)
_BULLET_CMD_RE = re.compile(r"^\s*[-*]\s+`([^`]+)`")
_PYTEST_MODULE_FORMS = (("python", "-m", "pytest"), ("python3", "-m", "pytest"))
_OPTIONS_WITH_VALUE = frozenset({"-m", "-k", "-c", "-p", "-o", "-n", "--rootdir", "--confcutdir", "--tb", "--ignore"})


def parse_validation_commands(task_md: str) -> list[list[str]]:
    """Backticked commands under '## Validation Commands' (bullets), shlex-split; [] when absent."""
    match = _HEADING_RE.search(task_md)
    if not match:
        return []
    body = task_md[match.end():]
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
    argv = list(argv)
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


def is_broad_pytest(argv: Sequence[str]) -> bool:
    """True for pytest with no path operand or an operand in {., tests, packages/<dist>/tests} or a parent."""
    operands = _pytest_operands(argv)
    if operands is None:
        return False
    if not operands:
        return True
    for op in operands:
        path = PurePosixPath(op.split("::", 1)[0].rstrip("/") or ".")
        parts = path.parts
        if parts in ((), (".",), ("tests",), ("packages",)):
            return True
        if len(parts) == 2 and parts[0] == "packages":
            return True
        if len(parts) == 3 and parts[0] == "packages" and parts[2] == "tests":
            return True
    return False
