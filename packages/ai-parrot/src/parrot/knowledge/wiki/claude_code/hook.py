"""PreToolUse hook runtime for the Claude Code wiki integration.

Invoked by Claude Code as ``wikitoolkit claude-hook`` before
search-style tool calls (``Grep``/``Glob``/``Read``).  Reads the hook
payload from stdin and — when the repository has a built wiki plane —
emits a non-blocking JSON nudge (``hookSpecificOutput.additionalContext``)
steering the assistant toward ``wikitoolkit query "<question>"``
instead of scanning raw files.

Design constraints:

- **Never blocks**: no ``permissionDecision`` is emitted, so the
  normal permission flow is untouched; the nudge is context only.
- **Never breaks the session**: any error exits 0 silently.
- **Throttled**: at most one nudge per cooldown window (default 300 s,
  configurable via ``claude.nudge_cooldown_seconds`` in
  ``.parrot/wiki.json``) so search-heavy turns are not spammed.
- **Fast**: imports are dependency-light (stdlib + pydantic).
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path, PurePosixPath
from typing import Any, Optional, TextIO

from parrot.knowledge.wiki.claude_code.assets import NUDGE_TEXT
from parrot.knowledge.wiki.project import (
    WikiProjectConfig,
    find_project_root,
    load_project_config,
)
from parrot.knowledge.wiki.repo_scan import CODE_SUFFIXES, DOC_SUFFIXES

#: Prefix of the throttle stamp files, inside the wiki storage directory.
STATE_FILENAME = "claude_hook_nudge"

#: File suffixes for which a Read nudge makes sense — the same
#: source/doc set the scanner turns into wiki pages.
_READ_NUDGE_SUFFIXES = CODE_SUFFIXES | DOC_SUFFIXES


def _should_nudge_read(tool_input: dict[str, Any]) -> bool:
    """Only nudge Read calls that target source/doc files."""
    file_path = str(tool_input.get("file_path") or "")
    if not file_path:
        return False
    return PurePosixPath(file_path).suffix.lower() in _READ_NUDGE_SUFFIXES


#: Shell executables that *search* the repository — an unambiguous signal
#: that the assistant is scanning source instead of querying the wiki.
_BASH_SEARCH_TOOLS = frozenset({
    "grep", "egrep", "fgrep", "rg", "ag", "ack", "ripgrep", "find",
})

#: Shell executables that *read* files — nudged only when an argument
#: looks like a source/doc file (so ``cat wiki.db`` or ``cat /etc/hosts``
#: stays silent).
_BASH_READ_TOOLS = frozenset({"cat", "head", "tail", "sed", "awk", "bat", "less"})

#: Command wrappers to skip when finding a segment's real executable.
_BASH_WRAPPERS = frozenset({"sudo", "command", "time", "nice", "xargs", "env"})


def _leading_exe(tokens: list[str]) -> Optional[str]:
    """First real executable basename in a command segment.

    Skips leading ``VAR=value`` environment assignments and common
    wrappers (``sudo``/``xargs``/``env`` …) so ``FOO=1 grep`` and
    ``xargs rg`` are recognised.
    """
    for tok in tokens:
        if "=" in tok and not tok.startswith("-") and "/" not in tok.split("=", 1)[0]:
            continue  # environment assignment
        if tok in _BASH_WRAPPERS:
            continue
        return PurePosixPath(tok).name
    return None


def _should_nudge_bash(tool_input: dict[str, Any]) -> bool:
    """Whether a Bash command is searching/reading the repo.

    Fires for code-search tools (``grep``/``rg``/``find`` …) anywhere in
    the command, and for file readers (``cat``/``head`` …) only when an
    argument targets a source/doc file. Every other shell command
    (``git``, ``ls``, ``pytest``, ``uv`` …) is left alone so the nudge
    never spams unrelated Bash calls.
    """
    command = str(tool_input.get("command") or "")
    if not command:
        return False
    for segment in re.split(r"[|&;\n]+", command):
        tokens = segment.split()
        exe = _leading_exe(tokens)
        if exe is None:
            continue
        if exe in _BASH_SEARCH_TOOLS:
            return True
        if exe in _BASH_READ_TOOLS and any(
            PurePosixPath(tok).suffix.lower() in _READ_NUDGE_SUFFIXES
            for tok in tokens[1:]
        ):
            return True
    return False


def _throttled(storage: Path, cooldown_seconds: int, now: float) -> bool:
    """Atomically claim the nudge slot for the current cooldown window.

    Claude Code fans out tool calls (and therefore hook processes) in
    parallel, so a read-modify-write state file would let several
    concurrent hooks all nudge at once. Instead, each cooldown window
    is claimed by creating a per-window stamp file with
    ``O_CREAT | O_EXCL`` — exactly one process wins the window.

    Args:
        storage: Wiki storage directory (holds the stamp files).
        cooldown_seconds: Window length; ``0`` disables throttling.
        now: Current time (injectable for tests).

    Returns:
        ``True`` when another nudge already claimed this window.
    """
    if cooldown_seconds <= 0:
        return False
    bucket = int(now // cooldown_seconds)
    stamp = storage / f"{STATE_FILENAME}.{bucket}.stamp"
    try:
        storage.mkdir(parents=True, exist_ok=True)
        fd = os.open(stamp, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        return True
    except OSError:
        # Cannot persist throttle state — stay quiet rather than spam.
        return True
    # Best-effort cleanup of stale window stamps.
    for old in storage.glob(f"{STATE_FILENAME}.*.stamp"):
        if old != stamp:
            try:
                old.unlink()
            except OSError:
                pass
    return False


def build_nudge(
    payload: dict[str, Any],
    root: Optional[Path] = None,
    config: Optional[WikiProjectConfig] = None,
    now: Optional[float] = None,
) -> Optional[dict[str, Any]]:
    """Decide whether the hook payload deserves a wiki nudge.

    Args:
        payload: Parsed PreToolUse hook payload (``tool_name``,
            ``tool_input``, ``cwd``...).
        root: Repository root override (resolved from ``cwd`` when
            omitted).
        config: Project config override (loaded from ``root`` when
            omitted).
        now: Clock override for tests.

    Returns:
        The hook response JSON object, or ``None`` when no nudge
        should be emitted.
    """
    if payload.get("hook_event_name") not in (None, "PreToolUse"):
        return None
    tool_name = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}

    if root is None:
        cwd = Path(str(payload.get("cwd") or Path.cwd()))
        root = find_project_root(cwd)
    if root is None:
        return None
    config = config or load_project_config(root)

    if tool_name not in config.claude.nudge_tools:
        return None
    if not config.is_built(root):
        return None
    if tool_name == "Read" and not _should_nudge_read(tool_input):
        return None
    if tool_name == "Bash" and not _should_nudge_bash(tool_input):
        return None

    storage = config.storage_path(root)
    if _throttled(
        storage,
        config.claude.nudge_cooldown_seconds,
        time.time() if now is None else now,
    ):
        return None

    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": NUDGE_TEXT,
        },
        "suppressOutput": True,
    }


def run_pre_tool_use_hook(
    stdin: Optional[TextIO] = None,
    stdout: Optional[TextIO] = None,
) -> int:
    """Entry point for ``wikitoolkit claude-hook`` / ``parrot claude hook``.

    Reads the hook payload from stdin, prints the nudge JSON (if any)
    to stdout, and always returns 0 so a misconfigured hook can never
    block the assistant.

    Args:
        stdin: Input stream override for tests.
        stdout: Output stream override for tests.

    Returns:
        Process exit code (always 0).
    """
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    try:
        payload = json.load(stdin)
        if not isinstance(payload, dict):
            return 0
        response = build_nudge(payload)
        if response is not None:
            json.dump(response, stdout)
            stdout.write("\n")
    except Exception:  # noqa: BLE001 — a hook must never break the session
        return 0
    return 0
