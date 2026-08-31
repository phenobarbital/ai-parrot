"""Local git history helpers: ref validation, argv builders, output parsers.

This module backs `git_log` / `git_show` / `git_blame` on
`ReadOnlyRepoToolkit` (spec §3 Module 3). Everything here is module-level
so it is unit-testable without a toolkit instance, and so `_generate_tools()`
(`tools/toolkit.py:537`) never mistakes a helper for a tool.

Ref validation (`validate_ref`) is the security control this module exists
for: a ref such as ``--upload-pack=/bin/sh`` handed to a git command that
does not terminate its options is remote code execution (spec §7). Every
git invocation below validates the ref *and* terminates options with
``--``, belt and braces.
"""

from __future__ import annotations

import re

#: Deliberately conservative: shas, branch/tag names, HEAD~3, a..b, a...b, ^ref.
_REF_OK = re.compile(r"^[A-Za-z0-9._/~^@{}-]{1,255}$")

_US = "\x1f"  # unit separator — cannot appear in a commit message
_RS = "\x1e"  # record separator
LOG_FORMAT = _US.join(["%H", "%an", "%aI", "%s"]) + _RS
SHOW_FORMAT = _US.join(["%H", "%an", "%aI", "%s"]) + _RS


class InvalidRefError(ValueError):
    """Raised when a caller-supplied git ref is not safe to pass to argv."""


def validate_ref(ref: str) -> str:
    """Validate a git ref before it reaches an argv list.

    Rejects option-shaped refs — a ref such as ``--upload-pack=/bin/sh``
    handed to a git command that does not terminate its options is remote
    code execution (spec §7).

    Args:
        ref: Caller-supplied ref: a sha, branch, tag, or range.

    Returns:
        The ref, unchanged, when it is safe.

    Raises:
        InvalidRefError: The ref is empty, option-shaped, or contains a
            character outside the conservative allow-list.
    """
    candidate = ref.strip()
    if not candidate:
        raise InvalidRefError("ref must not be empty")
    if candidate.startswith("-"):
        raise InvalidRefError(f"option-shaped ref rejected: {ref!r}")
    if not _REF_OK.match(candidate):
        raise InvalidRefError(f"ref contains unsupported characters: {ref!r}")
    if ".." in candidate and candidate.count(".") > 3:
        raise InvalidRefError(f"malformed ref range: {ref!r}")
    return candidate


def parse_log(stdout: str) -> list[dict[str, str]]:
    """Parse `git log --format=<LOG_FORMAT>` output into records.

    Splits on the unit/record separators used by `LOG_FORMAT` rather than
    whitespace, since commit subjects may contain anything.

    Args:
        stdout: Raw stdout from a `git log` invocation using `LOG_FORMAT`.

    Returns:
        A list of `{sha, author, date, subject}` dicts, in the order git
        emitted them.
    """
    out: list[dict[str, str]] = []
    for record in stdout.split(_RS):
        record = record.strip("\n")
        if not record:
            continue
        parts = record.split(_US)
        if len(parts) != 4:
            continue
        sha, author, date, subject = parts
        out.append({"sha": sha, "author": author, "date": date, "subject": subject})
    return out


def split_show_output(stdout: str) -> tuple[dict[str, str], str]:
    """Split `git show --format=<SHOW_FORMAT> --stat` stdout into parts.

    Args:
        stdout: Raw stdout from the `git show` invocation.

    Returns:
        A `(header, stat_text)` tuple: `header` is the parsed
        `{sha, author, date, subject}` mapping (empty if unparsable), and
        `stat_text` is everything after it (the `--stat` diffstat).
    """
    if _RS in stdout:
        header_part, _, rest = stdout.partition(_RS)
        parts = header_part.split(_US)
        header = {"sha": parts[0], "author": parts[1], "date": parts[2], "subject": parts[3]} if len(parts) == 4 else {}
    else:
        header, rest = {}, stdout
    return header, rest.lstrip("\n")


_BLAME_HEADER = re.compile(r"^([0-9a-f]{40}) (\d+) (\d+)(?: (\d+))?$")


def parse_blame(stdout: str) -> list[dict[str, object]]:
    """Parse `git blame --porcelain` output into per-line attribution.

    Args:
        stdout: Raw stdout from a `git blame --porcelain` invocation.

    Returns:
        A list of `{line, sha, author, content}` dicts, one per blamed
        line, in final-file line order.
    """
    authors: dict[str, str] = {}
    summaries: dict[str, str] = {}
    lines: list[dict[str, object]] = []
    current_sha = ""
    current_final = 0
    for raw_line in stdout.splitlines():
        header = _BLAME_HEADER.match(raw_line)
        if header:
            current_sha = header.group(1)
            current_final = int(header.group(3))
            continue
        if raw_line.startswith("author "):
            authors[current_sha] = raw_line[len("author ") :]
            continue
        if raw_line.startswith("summary "):
            summaries[current_sha] = raw_line[len("summary ") :]
            continue
        if raw_line.startswith("\t"):
            lines.append(
                {
                    "line": current_final,
                    "sha": current_sha,
                    "author": authors.get(current_sha, ""),
                    "summary": summaries.get(current_sha, ""),
                    "content": raw_line[1:],
                }
            )
    return lines
