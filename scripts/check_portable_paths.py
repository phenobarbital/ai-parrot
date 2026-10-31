#!/usr/bin/env python3
"""Fail when a tracked path cannot be checked out on Windows (issue:7e03742cc29b).

``actions/checkout`` on a Windows runner — and any developer clone on Windows — aborts with
``error: invalid path`` when a tracked file name contains a character Windows forbids, is a
reserved device name, or ends with a dot or a space. One such path is enough to break every
Windows leg of ``release.yml``.

Usage:
    python scripts/check_portable_paths.py            # every path in ``git ls-files``
    python scripts/check_portable_paths.py PATH ...   # only the given paths

Exit codes: 0 every path is portable; 1 at least one is not.

Stdlib only: runs in CI before the workspace is synced.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Sequence

#: Characters Windows forbids in a file or directory name, plus ASCII control characters.
FORBIDDEN_CHARS = re.compile(r'[<>:"|?*\\\x00-\x1f]')
#: Device names Windows reserves, with or without an extension (``aux.py`` is as invalid as ``AUX``).
RESERVED_NAMES: frozenset[str] = frozenset(
    {"CON", "PRN", "AUX", "NUL"} | {f"COM{n}" for n in range(1, 10)} | {f"LPT{n}" for n in range(1, 10)}
)


def path_problems(path: str) -> list[str]:
    """Return why ``path`` (repo-relative, ``/``-separated) cannot exist on Windows; empty when it can.

    Args:
        path: A path as ``git ls-files`` prints it.

    Returns:
        One human-readable reason per offending path component.
    """
    problems: list[str] = []
    for part in path.split("/"):
        bad = sorted(set(FORBIDDEN_CHARS.findall(part)))
        if bad:
            problems.append(f"{part!r} contains {', '.join(repr(c) for c in bad)}")
        if part.split(".", 1)[0].upper() in RESERVED_NAMES:
            problems.append(f"{part!r} is a reserved Windows device name")
        if part not in (".", "..") and part.endswith((".", " ")):
            problems.append(f"{part!r} ends with a dot or a space")
    return problems


def tracked_paths() -> list[str]:
    """Every path git tracks in the current repository (``git ls-files -z``, so no quoting)."""
    output = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True).stdout
    return [p for p in output.decode("utf-8", errors="surrogateescape").split("\0") if p]


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point: report every non-portable path; exit 1 when there is one."""
    args = list(sys.argv[1:] if argv is None else argv)
    paths = args or tracked_paths()
    offenders = [(path, problems) for path in paths if (problems := path_problems(path))]
    for path, problems in offenders:
        sys.stdout.write(f"{path}: {'; '.join(problems)}\n")
    if offenders:
        sys.stdout.write(
            f"\n{len(offenders)} path(s) cannot be checked out on Windows. Rename them to [a-z0-9._-] "
            "(no : * ? \" < > | \\, no reserved device names, no trailing dot or space).\n"
        )
        return 1
    sys.stdout.write(f"All {len(paths)} paths are portable to Windows.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
