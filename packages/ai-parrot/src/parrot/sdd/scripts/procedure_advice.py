"""Hook-side procedure advice (FEAT-891): stdlib only, no parrot import, never raises.

Loads both as ``parrot.sdd.scripts.procedure_advice`` and as a script sibling of the guards.
"""

from __future__ import annotations

import fnmatch
import json
import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping

INDEX_SCHEMA_VERSION = 1
ESCAPE_ENV = "PARROT_ALLOW_PROCEDURE"
LAUNCHER_MARKERS = ("PARROT_SDD_SANDBOX_ROOTS", "PARROT_SDD_CACHE_DIR")
PLANE_DIR = Path(".parrot") / "procedure"
INDEX_FILE = "procedures.json"
MAX_INDEX_BYTES = 262144
_OPERATORS = frozenset({"&&", "||", ";", "|", "&", "\n"})


@dataclass(frozen=True)
class Advice:
    """Outcome of the procedure check for one command."""

    decision: Literal["none", "advise", "deny"]
    text: str = ""


def checkout_root(cwd: Path) -> Path | None:
    """Return the nearest ancestor of ``cwd`` holding a ``.git`` entry."""
    try:
        if cwd is None:
            return None
        start = Path(cwd).resolve()
        for candidate in (start, *start.parents):
            if (candidate / ".git").exists():
                return candidate
    except (OSError, RuntimeError, TypeError, ValueError):
        pass
    return None


def shared_root(cwd: Path) -> Path | None:
    """Return the primary checkout for ``cwd`` without invoking a subprocess.

    A linked worktree's ``.git`` file points at an administrative worktree directory. Its
    ``commondir`` file points back to the primary checkout's ``.git`` directory.
    """
    try:
        root = checkout_root(cwd)
        if root is None:
            return None

        git_entry = root / ".git"
        if git_entry.is_dir():
            return root
        if not git_entry.is_file():
            return None

        first_line = git_entry.read_text(encoding="utf-8").splitlines()[0]
        marker = "gitdir:"
        if not first_line.lower().startswith(marker):
            return None
        gitdir_text = first_line[len(marker) :].strip()
        if not gitdir_text:
            return None
        gitdir = Path(gitdir_text)
        if not gitdir.is_absolute():
            gitdir = root / gitdir
        gitdir = gitdir.resolve()

        common_text = (gitdir / "commondir").read_text(encoding="utf-8").strip()
        if not common_text:
            return None
        common_dir = Path(common_text)
        if not common_dir.is_absolute():
            common_dir = gitdir / common_dir
        return common_dir.resolve().parent
    except (OSError, IndexError, RuntimeError, TypeError, ValueError):
        return None


def load_index(root: Path) -> dict[str, Any] | None:
    """Load a valid compiled procedure index from ``root`` without raising."""
    try:
        index_path = root / PLANE_DIR / INDEX_FILE
        if index_path.stat().st_size > MAX_INDEX_BYTES:
            return None
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != INDEX_SCHEMA_VERSION:
            return None
        return payload
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _replace_unquoted_newlines(command: str) -> str:
    """Turn unquoted newlines into shell segment separators for ``shlex``."""
    result: list[str] = []
    quote = ""
    escaped = False
    for character in command:
        if escaped:
            result.append(character)
            escaped = False
            continue
        if character == "\\" and quote != "'":
            result.append(character)
            escaped = True
            continue
        if character in {"'", '"'}:
            if not quote:
                quote = character
            elif quote == character:
                quote = ""
            result.append(character)
            continue
        if character == "\n" and not quote:
            result.append(" ; ")
        else:
            result.append(character)
    return "".join(result)


def command_segments(command: str) -> list[list[str]]:
    """Split a shell command into token lists, one per simple command."""
    try:
        line = _replace_unquoted_newlines(command)
        lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        segments: list[list[str]] = []
        current: list[str] = []
        for token in lexer:
            if token in _OPERATORS:
                if current:
                    segments.append(current)
                    current = []
            else:
                current.append(token)
        if current:
            segments.append(current)
        return segments
    except (TypeError, ValueError, OSError):
        return []


def _assignment(token: str) -> bool:
    """Return whether ``token`` is a shell-style leading environment assignment."""
    name, separator, _ = token.partition("=")
    return bool(separator and name and (name[0].isalpha() or name[0] == "_") and name.isidentifier())


def _skip_options(tokens: list[str], index: int) -> int:
    """Skip option tokens in a wrapper prefix."""
    while index < len(tokens) and tokens[index].startswith("-") and tokens[index] != "-":
        index += 1
    return index


def _clean(tokens: list[str]) -> tuple[str, list[str]]:
    """Return the executable basename and its arguments after known wrappers are removed."""
    try:
        index = 0
        while index < len(tokens) and _assignment(tokens[index]):
            index += 1

        while index < len(tokens):
            wrapper = os.path.basename(tokens[index])
            if wrapper == "rtk":
                index += 1
                continue
            if wrapper == "sudo":
                index = _skip_options(tokens, index + 1)
                continue
            if wrapper == "timeout":
                index = _skip_options(tokens, index + 1)
                if index < len(tokens):
                    index += 1
                continue
            if wrapper == "uv" and index + 1 < len(tokens) and tokens[index + 1] == "run":
                index = _skip_options(tokens, index + 2)
                continue
            if wrapper == "cd":
                return "", []
            return wrapper, tokens[index + 1 :]
        return "", []
    except (IndexError, TypeError, ValueError, OSError):
        return "", []


def leading_command(command: str) -> tuple[str, list[str]]:
    """Return the executable and arguments from the first real command segment."""
    try:
        for tokens in command_segments(command):
            executable, argv = _clean(tokens)
            if executable:
                return executable, argv
    except (TypeError, ValueError, OSError):
        pass
    return "", []


def _normalise_path(value: str) -> str:
    """Normalize a guard argument to a POSIX-style repository-relative path."""
    normalized = os.path.normpath(value).replace(os.sep, "/").replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def match_guards(index: Mapping[str, Any], command: str) -> list[dict[str, Any]]:
    """Return index guards matching any command segment, preserving index order."""
    try:
        guards = index.get("guards", [])
        if not isinstance(guards, list):
            return []
        segments = command_segments(command)
        matches: list[dict[str, Any]] = []
        for guard in guards:
            if not isinstance(guard, Mapping):
                continue
            executable = guard.get("executable")
            argv_prefix = guard.get("argv_prefix", [])
            path_globs = guard.get("path_globs", [])
            if not isinstance(executable, str) or not isinstance(argv_prefix, list) or not all(
                isinstance(item, str) for item in argv_prefix
            ):
                continue
            if not isinstance(path_globs, list) or not all(isinstance(item, str) for item in path_globs):
                continue
            for tokens in segments:
                actual_executable, argv = _clean(tokens)
                if actual_executable != executable or argv[: len(argv_prefix)] != argv_prefix:
                    continue
                remaining = argv[len(argv_prefix) :]
                if path_globs and not any(
                    fnmatch.fnmatchcase(_normalise_path(argument), pattern)
                    for argument in remaining
                    for pattern in path_globs
                ):
                    continue
                matched = dict(guard)
                matched["argv"] = list(remaining)
                matches.append(matched)
                break
        return matches
    except (AttributeError, IndexError, OSError, TypeError, ValueError):
        return []
