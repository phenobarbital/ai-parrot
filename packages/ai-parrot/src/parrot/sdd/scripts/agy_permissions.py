"""Antigravity (agy) PreToolUse permission policy for the SDD command surface (brief agy-permission-hook).

agy (1.4.12) runs a shell command without asking only when a ``permissions.allow`` rule in the user's
settings matches it. A PreToolUse hook can ``deny`` a command, ``force_ask`` (prompt even though a rule
matches) or ``ask`` (leave the decision to the rules); a hook ``allow`` is accepted but ignored. This module
therefore carries both halves of the policy:

* :data:`SDD_ALLOW_RULES` — the managed agy rules that ``parrot sdd install --host google`` merges into
  the user's agy settings, broad enough for ``/sdd-spec``, ``/sdd-task``, ``/sdd-brief`` and ``/sdd-fix``;
* :func:`evaluate` — the hook that narrows those rules: ``deny`` for destructive commands (the C32
  dangerous-actions rules plus a push to the hotfix branch), ``force_ask`` for anything a managed rule would
  approve that the policy cannot positively classify as routine, ``ask`` otherwise. A command no managed rule
  covers is never escalated: agy prompts for it anyway.

High-risk commands (``git push|switch|merge|config|remote|worktree|checkout``, ``parrot sdd``,
``wikitoolkit``) are judged against **positive** allowlists of options and verbs, so short-option clusters,
long-option abbreviations and unknown flags fall to ``force_ask``. Read-only tools are judged by where their
path arguments resolve (attached option values, brace expansion and symlinks included). Heredocs and
newlines are parsed quote-aware.

It is a narrowing layer on top of agy's own matching, not a sandbox: an approved ``pytest`` runs repository
code by design. Served as ``parrot sdd hooks agy-permissions --hook``; :func:`main` always exits 0 and writes
one JSON object. Only the stdlib and the sibling ``dangerous_actions`` guard are imported at module level;
``parrot.sdd.config`` is loaded lazily and guarded.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Sequence

from parrot.sdd.scripts import dangerous_actions
from parrot.sdd.scripts import worktree_environment

UNATTENDED_ENV = "PARROT_SDD_AGY_UNATTENDED"
_RANK = {"ask": 0, "force_ask": 1, "deny": 2}

# --------------------------------------------------------------------------
# managed rules
# --------------------------------------------------------------------------

_READ_ONLY: tuple[str, ...] = (
    "ls", "cat", "head", "tail", "wc", "grep", "rg", "find", "sed", "jq", "sort", "uniq", "cut", "tr",
    "diff", "file", "stat", "tree", "pwd", "echo", "printf", "basename", "dirname", "realpath", "readlink",
    "test", "which", "nl", "comm", "du", "date", "mkdir",
)  # fmt: skip
_GIT_READ: tuple[str, ...] = (
    "status", "log", "diff", "show", "rev-parse", "ls-files", "ls-tree", "blame", "grep", "describe",
    "merge-base", "rev-list", "show-ref", "for-each-ref", "cat-file",
)  # fmt: skip
_GIT_OTHER: tuple[str, ...] = (
    "branch", "remote", "config", "fetch", "add", "commit", "pull", "push", "checkout", "switch", "merge",
)  # fmt: skip
#: every git subcommand the policy knows how to judge (``git -C <path> <sub>`` outside this set is risky)
GIT_SUBCOMMANDS: frozenset[str] = frozenset((*_GIT_READ, *_GIT_OTHER, "worktree"))
_GH: tuple[str, ...] = (
    "pr create", "pr view", "pr list", "pr checks", "pr diff", "pr status", "issue view", "issue list",
    "api", "run list", "run view", "repo view",
)  # fmt: skip

RULE_WORDS: tuple[tuple[str, ...], ...] = (
    *((name,) for name in _READ_ONLY),
    *(("git", sub) for sub in (*_GIT_READ, *_GIT_OTHER)),
    ("git", "worktree", "list"),
    ("git", "-C"),
    *(("gh", *sub.split()) for sub in _GH),
    ("parrot", "sdd"),
    ("parrot", "wiki"),
    ("wikitoolkit",),
    ("pytest",),
    ("python", "-m", "pytest"),
    ("python3", "-m", "pytest"),
    ("ruff", "check"),
    ("ruff", "format"),
    ("black",),
    ("source", ".venv/bin/activate"),
    (".", ".venv/bin/activate"),
)
#: The agy ``permissions.allow`` rules ``parrot sdd install --host google`` manages, in a stable order.
SDD_ALLOW_RULES: tuple[str, ...] = tuple(f"command({' '.join(words)})" for words in RULE_WORDS)

_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
#: environment overrides a covered command may carry; PYTHONPATH entries must also stay inside the workspace
_SAFE_ENV = frozenset({"PYTHONDONTWRITEBYTECODE", "GIT_TERMINAL_PROMPT", "NO_COLOR", "TERM", "LANG", "LC_ALL", "TZ"})
_PATH_ENV = frozenset({"PYTHONPATH"})


def _strip_assignments(words: Sequence[str]) -> list[str]:
    """Drop leading ``NAME=value`` words, as agy does before matching a rule."""
    index = 0
    while index < len(words) and _ASSIGNMENT.match(words[index]):
        index += 1
    return list(words[index:])


def rule_covers(words: Sequence[str]) -> bool:
    """Whether a managed rule matches one simple command, using agy's word-prefix matching.

    Args:
        words: The command's words (leading ``NAME=value`` assignments are ignored, like agy does).

    Returns:
        True when the words of some rule in :data:`RULE_WORDS` are a prefix of ``words``.
    """
    argv = _strip_assignments(words)
    return any(tuple(argv[: len(rule)]) == rule for rule in RULE_WORDS)


# --------------------------------------------------------------------------
# decisions and state
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Decision:
    """Outcome of :func:`evaluate`, in agy's hook vocabulary."""

    decision: Literal["deny", "force_ask", "ask"]
    reason: str = ""
    overwrite: dict[str, str] | None = None


_ASK = Decision("ask")
_PLACEHOLDER = "__PARROT_SUBST__"
_SEPARATORS = frozenset({";", "&&", "||", "|", "|&", "&", "(", ")", ";;", ";&", "{", "}", "!"})
_WRITE_REDIRECTS = frozenset({">", ">>", ">|", "&>", "&>>", "<>"})
_FD_REDIRECTS = frozenset({">&", "<&"})
_WRAPPERS = frozenset({"time", "nohup", "command", "builtin"})
#: directories whose files configure agents, hooks or git: never rewritten through a redirect unprompted
_CONTROL_DIRS = frozenset({".agents", ".agent", ".git", ".claude", ".codex", ".gemini", ".parrot"})


@dataclass
class _Context:
    """Per-command evaluation state."""

    roots: list[Path]
    real_roots: list[str]
    cwd: Path | None
    root: Path | None
    hotfix: frozenset[str]
    protected: tuple[str, ...]
    deny: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    subst_trusted: bool = True


@dataclass
class _Segment:
    """One simple command: its words, leading assignments and redirections."""

    argv: list[str]
    env: list[str]
    redirects: list[tuple[str, str]]


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------


def _heredoc_word(text: str, start: int) -> tuple[str, bool, int]:
    """Read a heredoc delimiter at ``start``: its unquoted text, whether any part was quoted, and the end index."""
    index = start
    if index < len(text) and text[index] == "-":
        index += 1
    while index < len(text) and text[index] in " \t":
        index += 1
    word: list[str] = []
    quoted = False
    quote: str | None = None
    while index < len(text):
        char = text[index]
        if quote:
            if char == quote:
                quote = None
            else:
                word.append(char)
        elif char in "'\"":
            quote = char
            quoted = True
        elif char == "\\":
            quoted = True
        elif char.isspace() or char in ";&|<>()":
            break
        else:
            word.append(char)
        index += 1
    return "".join(word), quoted, index


def _normalize(command: str, ctx: _Context) -> str:
    """Drop heredoc bodies and turn unquoted newlines into ``;`` (quote-aware).

    Raises:
        ValueError: an unterminated quote or heredoc.
    """
    text = command.replace("\\\n", "")
    out: list[str] = []
    pending: list[tuple[str, bool]] = []
    quote: str | None = None
    index = 0
    while index < len(text):
        char = text[index]
        if quote:
            out.append(char)
            if char == "\\" and quote == '"' and index + 1 < len(text):
                out.append(text[index + 1])
                index += 2
                continue
            if char == quote:
                quote = None
            index += 1
            continue
        if char in "'\"":
            quote = char
        elif char == "\\" and index + 1 < len(text):
            out.append(text[index : index + 2])
            index += 2
            continue
        elif text.startswith("<<", index) and not text.startswith("<<<", index) and text[index - 1 : index] != "<":
            delimiter, quoted, end = _heredoc_word(text, index + 2)
            if not delimiter:
                raise ValueError("heredoc without a delimiter")
            pending.append((delimiter, quoted))
            out.append(" ")
            index = end
            continue
        elif char == "\n":
            out.append(" ; ")
            index += 1
            for delimiter, quoted in pending:
                body: list[str] = []
                while True:
                    if index >= len(text):
                        raise ValueError("unterminated heredoc")
                    newline = text.find("\n", index)
                    line = text[index : newline if newline != -1 else len(text)]
                    index = newline + 1 if newline != -1 else len(text)
                    if line.strip() == delimiter:
                        break
                    body.append(line)
                joined = "\n".join(body)
                if not quoted and ("$(" in joined or "`" in joined):
                    ctx.risks.append("an unquoted heredoc body runs a command substitution")
            pending = []
            continue
        out.append(char)
        index += 1
    if quote:
        raise ValueError("unterminated quote")
    if pending:
        raise ValueError("unterminated heredoc")
    return "".join(out)


def _closing_paren(text: str, start: int) -> int:
    """Index of the ``)`` closing the ``(`` at ``start``, honouring quotes and nesting."""
    depth = 0
    quote: str | None = None
    index = start
    while index < len(text):
        char = text[index]
        if quote:
            if char == "\\" and quote == '"':
                index += 2
                continue
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        elif char == "\\":
            index += 2
            continue
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise ValueError("unterminated substitution")


def _extract_substitutions(text: str) -> tuple[str, list[str]]:
    """Replace ``$(…)``, backticks and ``<(…)``/``>(…)`` outside single quotes with a placeholder.

    Returns:
        The rewritten text and the substitution bodies (each still a full command string).
    """
    out: list[str] = []
    bodies: list[str] = []
    in_single = in_double = False
    index = 0
    while index < len(text):
        char = text[index]
        if in_single:
            out.append(char)
            in_single = char != "'"
            index += 1
            continue
        if char == "\\" and index + 1 < len(text):
            out.append(text[index : index + 2])
            index += 2
            continue
        if char == "'" and not in_double:
            in_single = True
        elif char == '"':
            in_double = not in_double
        elif char == "`":
            end = text.find("`", index + 1)
            if end == -1:
                raise ValueError("unterminated backtick")
            bodies.append(text[index + 1 : end])
            out.append(_PLACEHOLDER)
            index = end + 1
            continue
        elif text.startswith("$(", index) or (
            not in_double and text[index : index + 2] in {"<(", ">("} and (index == 0 or text[index - 1].isspace())
        ):
            end = _closing_paren(text, index + 1)
            bodies.append(text[index + 2 : end])
            out.append(_PLACEHOLDER)
            index = end + 1
            continue
        out.append(char)
        index += 1
    return "".join(out), bodies


def _segments(text: str) -> list[_Segment]:
    """Split a substitution-free, single-line command into simple commands."""
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    tokens = list(lexer)
    segments: list[_Segment] = []
    current = _Segment([], [], [])
    index = 0
    while index < len(tokens):
        token = tokens[index]
        nxt = tokens[index + 1] if index + 1 < len(tokens) else ""
        if token in _SEPARATORS:
            if current.argv or current.env or current.redirects:
                segments.append(current)
            current = _Segment([], [], [])
        elif token.isdigit() and (nxt in _WRITE_REDIRECTS or nxt in _FD_REDIRECTS or nxt == "<"):
            pass  # a file descriptor number (`2>`), not an argument
        elif token in _WRITE_REDIRECTS or token in _FD_REDIRECTS or token in {"<", "<<<"}:
            current.redirects.append((token, nxt))
            index += 1
        elif not current.argv and _ASSIGNMENT.match(token):
            current.env.append(token)
        else:
            current.argv.append(token)
        index += 1
    if current.argv or current.env or current.redirects:
        segments.append(current)
    return segments


def _unwrap(segment: _Segment) -> _Segment:
    """See through ``time``/``nohup``/``command``/``timeout <d>``/``nice``/``env`` wrappers."""
    argv = list(segment.argv)
    env = list(segment.env)
    while argv:
        head = argv[0]
        if head in _WRAPPERS:
            argv = argv[1:]
        elif head == "timeout" and len(argv) > 2:
            rest = argv[1:]
            while rest and rest[0].startswith("-"):
                rest = rest[1:]
            argv = rest[1:]
        elif head == "nice":
            rest = argv[1:]
            if rest[:1] == ["-n"]:
                rest = rest[2:]
            elif rest and rest[0].startswith("-"):
                rest = rest[1:]
            argv = rest
        elif head == "env":
            rest = argv[1:]
            while rest and _ASSIGNMENT.match(rest[0]):
                env.append(rest[0])
                rest = rest[1:]
            argv = rest
        else:
            break
    return _Segment(argv, env, segment.redirects)


# --------------------------------------------------------------------------
# options
# --------------------------------------------------------------------------


def _long_name(token: str) -> str:
    """``--name`` of a long option token (``--name=value`` included), else ``""``."""
    return token.split("=", 1)[0] if token.startswith("--") and len(token) > 2 else ""


def _short_letters(token: str) -> str:
    """Everything after the dash of a short-option token or cluster (``-Df`` → ``Df``, ``-o.x`` → ``o.x``).

    Attached values are included on purpose: a risky letter anywhere in the token counts, which over-matches
    rather than letting ``-o.agents/hooks.json`` slip through.
    """
    return token[1:] if len(token) > 1 and token[0] == "-" and token[1] != "-" else ""


def _risky_flag(
    args: Sequence[str], short: str = "", long: Sequence[str] = (), benign: Sequence[str] = ()
) -> str | None:
    """First option that sets a risky short letter (clusters included) or a risky long option.

    Long options also match any prefix of four characters or more (git and GNU tools accept unambiguous
    abbreviations such as ``--amen`` or ``--del``); a complete option listed in ``benign`` (``--prune``, a
    prefix of ``--prune-tags``) is never treated as an abbreviation.
    """
    for token in args:
        if token == "--":
            break
        name = _long_name(token)
        if name:
            if name in benign:
                continue
            if any(full == name or (len(name) >= 4 and full.startswith(name)) for full in long):
                return token
        elif short and set(_short_letters(token)) & set(short):
            return token
    return None


def _unknown_flag(
    args: Sequence[str],
    short: str = "",
    long: frozenset[str] = frozenset(),
    valued_short: str = "",
    valued_long: frozenset[str] = frozenset(),
) -> str | None:
    """First option outside a positive allowlist; a cluster may only use allowed letters.

    A letter in ``valued_short`` ends its cluster (the rest, or the next token, is its value).
    """
    skip = False
    for token in args:
        if skip:
            skip = False
            continue
        if token == "--":
            break
        name = _long_name(token)
        if name:
            if name in long:
                continue
            if name in valued_long:
                skip = "=" not in token
                continue
            return token
        letters = _short_letters(token)
        if letters:
            for position, char in enumerate(letters):
                if char in valued_short:
                    skip = position == len(letters) - 1
                    break
                if char not in short:
                    return token
            continue
        if token.startswith("-") and token != "-":
            return token
    return None


def _positionals(args: Sequence[str], valued: frozenset[str] = frozenset()) -> list[str]:
    out: list[str] = []
    skip = False
    after_dashes = False
    for token in args:
        if skip:
            skip = False
            continue
        if after_dashes:
            out.append(token)
        elif token == "--":
            after_dashes = True
        elif token in valued:
            skip = True
        elif not token.startswith("-") or token == "-":
            out.append(token)
    return out


# --------------------------------------------------------------------------
# paths
# --------------------------------------------------------------------------


def _main_checkout(root: Path) -> Path | None:
    """The primary checkout of a linked worktree (``<root>/.git`` is a ``gitdir:`` file), else None."""
    git = root / ".git"
    try:
        if not git.is_file():
            return None
        line = git.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not line.startswith("gitdir:"):
        return None
    gitdir = Path(line.split(":", 1)[1].strip())
    if not gitdir.is_absolute():
        gitdir = (root / gitdir).resolve()
    return gitdir.parents[2] if len(gitdir.parents) > 2 and gitdir.parent.name == "worktrees" else None


def workspace_roots(workspace_paths: Sequence[str], fallback: Path | None) -> list[Path]:
    """The directories a command may touch: the workspace paths and each one's main checkout.

    Args:
        workspace_paths: ``workspacePaths`` from the agy payload.
        fallback: Used when the payload names no workspace (the hook's repository root).

    Returns:
        Normalized absolute roots, in order, without duplicates.
    """
    candidates = [Path(p) for p in workspace_paths if isinstance(p, str) and p]
    if not candidates and fallback is not None:
        candidates = [fallback]
    roots: list[Path] = []
    for candidate in candidates:
        norm = Path(os.path.normpath(os.path.abspath(candidate)))
        for path in (norm, _main_checkout(norm)):
            if path is not None and path not in roots:
                roots.append(path)
    return roots


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _inside(ctx: _Context, path: Path | None) -> bool:
    return path is not None and any(_under(str(path), str(root)) for root in ctx.roots)


def _expand(token: str) -> str | None:
    """Expand ``~``/``$HOME``/``${HOME}``; None for any other variable (opaque)."""
    home = str(Path.home())
    if token == "~" or token.startswith("~/"):
        return home + token[1:]
    if token.startswith("~"):
        return "/"  # another user's home: outside by construction
    for prefix in ("${HOME}", "$HOME"):
        if token.startswith(prefix):
            return home + token[len(prefix) :]
    return None if "$" in token else token


def _path_like(token: str) -> bool:
    return (
        "/" in token or token.startswith("~") or "$" in token or "{" in token or token == ".." or _PLACEHOLDER in token
    )


def _resolve(ctx: _Context, token: str) -> tuple[str | None, str | None]:
    """Resolve a path-like token: ``(normalized absolute path, None)`` or ``(None, problem)``."""
    if "{" in token and "}" in token and ("," in token or ".." in token):
        return None, "uses brace expansion"
    if _PLACEHOLDER in token:
        if not ctx.subst_trusted:
            return None, "is built from a command substitution"
        base = ctx.cwd or (ctx.roots[0] if ctx.roots else None)
        if base is None:
            return None, "is built from a command substitution"
        token = token.replace(_PLACEHOLDER, str(base))
    expanded = _expand(token)
    if expanded is None:
        return None, "is built from a shell variable"
    if not os.path.isabs(expanded):
        if ctx.cwd is None:
            return None, "is relative to an unknown directory"
        expanded = os.path.join(str(ctx.cwd), expanded)
    return os.path.normpath(expanded), None


_GLOB_CHARS = frozenset("*?[")
_GLOB_LIMIT = 500


def _path_problem(ctx: _Context, token: str) -> str | None:
    """Why a path-like token may point outside the workspace, or None when it stays inside.

    Symlinks are resolved, and a glob pattern is expanded so every match is checked (the shell, not the
    command, sees the expanded names).
    """
    norm, problem = _resolve(ctx, token)
    if problem or norm is None:
        return problem
    if norm == "/dev/null" or norm.startswith("/dev/fd/") or norm in {"/dev/stdout", "/dev/stderr", "/dev/stdin"}:
        return None
    if not any(_under(norm, str(root)) for root in ctx.roots):
        return "is outside the workspace"
    candidates = [norm]
    if _GLOB_CHARS & set(token):
        candidates = glob.glob(norm)[: _GLOB_LIMIT + 1]
        if len(candidates) > _GLOB_LIMIT:
            return "matches too many paths to check"
    for candidate in candidates:
        if not any(_under(os.path.realpath(candidate), root) for root in ctx.real_roots):
            return "resolves outside the workspace through a symlink"
    return None


def _check_paths(
    ctx: _Context, tokens: Sequence[str], what: str, *, attached: bool = False, bare: bool = False
) -> str | None:
    """First token (or option value) that may point outside the workspace.

    Args:
        ctx: Evaluation state.
        tokens: Arguments to inspect; ``--opt=value`` values are inspected too.
        what: Label for the reason.
        attached: Also inspect values attached to short options (``-f/etc/passwd``).
        bare: Also inspect plain names (``outside``, ``*``) — they can be symlinks or globs leaving the workspace.
    """
    for token in tokens:
        if token == "--":
            continue
        if token.startswith("--"):
            if "=" not in token:
                continue
            value = token.split("=", 1)[1]
        elif token.startswith("-") and token != "-":
            if not (attached and len(token) > 2):
                continue
            value = token[2:]
        else:
            value = token
        if not value or not (_path_like(value) or bare):
            continue
        problem = _path_problem(ctx, value)
        if problem:
            return f"{what} `{value.replace(_PLACEHOLDER, '$(…)')}` {problem}"
    return None


# --------------------------------------------------------------------------
# read-only tools
# --------------------------------------------------------------------------

_FIND_ACTIONS = frozenset({"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fprintf", "-fls"})
_FIND_PATH_VALUED = frozenset({"-newer", "-anewer", "-cnewer", "-samefile", "-files0-from"})
_SED_PRINT = (
    re.compile(r"^\s*(\d+|\$)(\s*,\s*(\d+|\$))?\s*p\s*$"),
    re.compile(r"^\s*/[^/]*/(\s*,\s*/[^/]*/)?\s*p\s*$"),
    re.compile(r"^\s*s(.)(?:(?!\1)[^\\]|\\.)*\1(?:(?!\1)[^\\]|\\.)*\1[gpiI0-9]*\s*$"),
)
_GREP_VALUED = frozenset(
    {"-m", "--max-count", "-A", "-B", "-C", "--context", "--after-context", "--before-context", "--include",
     "--exclude", "--exclude-dir", "-g", "--glob", "-t", "--type", "-T", "--type-not", "--color", "--colour",
     "-M", "--max-columns", "-j", "--threads", "--max-depth", "-d", "--sort", "--sortr"}
)  # fmt: skip
#: tools whose arguments are text, not paths (their redirects are still checked)
_TEXT_ONLY = frozenset({"echo", "printf", "test", "basename", "dirname", "realpath", "readlink", "which", "pwd"})


def _find(ctx: _Context, args: list[str]) -> str | None:
    hit = next((a for a in args if a in _FIND_ACTIONS), None)
    if hit:
        return f"`find {hit}` runs or deletes"
    index = 0
    while index < len(args) and (args[index] in {"-H", "-L", "-P", "-D"} or args[index].startswith("-O")):
        index += 2 if args[index] == "-D" else 1
    starts: list[str] = []
    while index < len(args) and not (args[index].startswith("-") or args[index] in {"(", "!", ")"}):
        starts.append(args[index])
        index += 1
    values = [args[i + 1] for i in range(len(args) - 1) if args[i] in _FIND_PATH_VALUED or args[i].startswith("-newer")]
    return _check_paths(ctx, [*(starts or ["."]), *values], "find path", bare=True)


def _sed(ctx: _Context, args: list[str]) -> str | None:
    scripts: list[str] = []
    files: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--in-place" or token.startswith(("--in-place=", "-i")):
            return "`sed -i` edits files in place"
        if token in {"-f", "--file"} or token.startswith("--file="):
            return "`sed -f` runs a script file"
        if token in {"-e", "--expression"}:
            scripts.append(args[index + 1] if index + 1 < len(args) else "")
            index += 2
            continue
        if token.startswith("--expression="):
            scripts.append(token.split("=", 1)[1])
        elif token.startswith("--"):
            if token not in {"--quiet", "--silent", "--regexp-extended", "--debug", "--posix", "--null-data"}:
                return f"`sed {token}` is not on the read-only list"
        elif token.startswith("-") and token != "-":
            cluster = token[1:]
            for position, char in enumerate(cluster):
                if char == "i":
                    return "`sed -i` edits files in place"
                if char == "f":
                    return "`sed -f` runs a script file"
                if char == "e":
                    rest = cluster[position + 1 :]
                    if rest:
                        scripts.append(rest)
                    else:
                        scripts.append(args[index + 1] if index + 1 < len(args) else "")
                        index += 1
                    break
                if char not in "nErsuz":
                    return f"`sed -{char}` is not on the read-only list"
        else:
            files.append(token)
        index += 1
    if not scripts and files:
        scripts.append(files.pop(0))
    if not scripts or any(not any(p.match(s) for p in _SED_PRINT) for s in scripts):
        return "the sed script is not print-only"
    return _check_paths(ctx, files, "sed input", bare=True)


def _grep(ctx: _Context, name: str, args: list[str]) -> str | None:
    if name == "rg":
        hit = _risky_flag(args, long=("--pre", "--pre-glob", "--hostname-bin"))
        if hit:
            return f"`rg {hit}` runs a program"

    def is_pattern_option(token: str) -> bool:
        return (not token.startswith("--") and token.startswith("-e")) or token.startswith("--regexp")

    explicit = (
        any(
            is_pattern_option(t) or (not t.startswith("--") and t.startswith("-f")) or t.startswith("--file")
            for t in args
        )
        or "--type-list" in args
    )
    positionals = _positionals(args, _GREP_VALUED | {"-e", "--regexp", "-f", "--file"})
    files = positionals if explicit else positionals[1:]
    pattern_files = [args[i + 1] for i in range(len(args) - 1) if args[i] in {"-f", "--file"}]
    options = [t for t in args if t.startswith("-") and not is_pattern_option(t)]
    return _check_paths(ctx, [*files, *pattern_files, *options], f"{name} path", attached=True, bare=True)


def _jq(ctx: _Context, args: list[str]) -> str | None:
    from_file = any(t in {"-f", "--from-file"} or t.startswith("--from-file=") for t in args)
    positionals: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        if token in {"--arg", "--argjson"}:
            index += 3
            continue
        if token in {"--rawfile", "--slurpfile"}:
            positionals.extend(args[index + 2 : index + 3])
            index += 3
            continue
        if token in {"--indent", "-L"}:
            positionals.extend(args[index + 1 : index + 2] if token == "-L" else [])
            index += 2
            continue
        if not token.startswith("-") or token == "-":
            positionals.append(token)
        index += 1
    files = positionals if from_file else positionals[1:]
    return _check_paths(ctx, [*files, *(t for t in args if t.startswith("--"))], "jq input", bare=True)


def _read_only(ctx: _Context, name: str, args: list[str]) -> str | None:
    if name == "find":
        return _find(ctx, args)
    if name == "sed":
        return _sed(ctx, args)
    if name in {"grep", "rg"}:
        return _grep(ctx, name, args)
    if name == "jq":
        return _jq(ctx, args)
    if name == "sort":
        hit = _risky_flag(args, short="o", long=("--output", "--compress-program"))
        if hit:
            return f"`sort {hit}` writes a file or runs a program"
    if name == "tree":
        hit = _risky_flag(args, short="o", long=("--output",))
        if hit:
            return f"`tree {hit}` writes a file"
    if name == "uniq" and len(_positionals(args, frozenset({"-f", "-s", "-w"}))) >= 2:
        return "`uniq IN OUT` writes a file"
    if name in _TEXT_ONLY:
        return None
    return _check_paths(ctx, args, f"{name} path", attached=True, bare=True)


# --------------------------------------------------------------------------
# git
# --------------------------------------------------------------------------

#: options whose value is free text (messages, formats, search strings): never path-checked
_GIT_TEXT_VALUED = frozenset(
    {"-m", "--message", "--author", "--committer", "--date", "--grep", "-S", "-G", "--format", "--pretty",
     "--trailer", "--since", "--until", "--before", "--after", "--subject-prefix"}
)  # fmt: skip
_BRANCH_NAME = re.compile(r"^[A-Za-z0-9._/-]+$")
_REMOTE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def _gitdir(start: Path | None) -> Path | None:
    """The git directory of the repository holding ``start`` (a worktree's own gitdir), no subprocess."""
    root = dangerous_actions.find_root(start) if start is not None else None
    if root is None:
        return None
    git = root / ".git"
    try:
        if git.is_file():
            gitdir = Path(git.read_text(encoding="utf-8").split(":", 1)[1].strip())
            return gitdir if gitdir.is_absolute() else root / gitdir
    except (OSError, IndexError):
        return None
    return git if git.is_dir() else None


def _current_branch(start: Path | None) -> str | None:
    """The checked-out branch of the repository holding ``start``, read from ``HEAD``."""
    gitdir = _gitdir(start)
    try:
        head = (gitdir / "HEAD").read_text(encoding="utf-8").strip() if gitdir else ""
    except OSError:
        return None
    return head.removeprefix("ref: refs/heads/") if head.startswith("ref: refs/heads/") else None


_CONFIG_SECTION = re.compile(r'^\[([A-Za-z0-9.-]+)(?:\s+"(.*)")?\]$')


def _git_config(start: Path | None) -> dict[str, list[str]]:
    """``section[.subsection].key`` → values from the repository's shared ``config`` file (no subprocess)."""
    gitdir = _gitdir(start)
    if gitdir is None:
        return {}
    try:
        common = gitdir
        if (gitdir / "commondir").is_file():
            common = (gitdir / (gitdir / "commondir").read_text(encoding="utf-8").strip()).resolve()
        lines = (common / "config").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    out: dict[str, list[str]] = {}
    section = ""
    for raw in lines:
        line = raw.strip()
        if not line or line[0] in "#;":
            continue
        match = _CONFIG_SECTION.match(line)
        if match:
            section = match.group(1).lower() + (f".{match.group(2)}" if match.group(2) is not None else "")
            continue
        key, _, value = line.partition("=")
        out.setdefault(f"{section}.{key.strip().lower()}", []).append(value.strip().strip('"'))
    return out


def _git_paths(ctx: _Context, args: list[str], cwd: Path | None) -> str | None:
    """Path-check git arguments (free-text option values excluded) relative to the git working directory."""
    tokens: list[str] = []
    skip = False
    for token in args:
        if skip:
            skip = False
            continue
        name = _long_name(token) or token
        if name in _GIT_TEXT_VALUED:
            skip = "=" not in token
            continue
        if token.startswith(("-m", "-S", "-G")) and not token.startswith("--"):
            continue
        tokens.append(token)
    outer = ctx.cwd
    ctx.cwd = cwd
    try:
        return _check_paths(ctx, tokens, "git path", attached=True)
    finally:
        ctx.cwd = outer


def _push(ctx: _Context, args: list[str], cwd: Path | None) -> str | None:
    unknown = _unknown_flag(
        args,
        short="uqvn",
        long=frozenset(
            {"--set-upstream", "--quiet", "--verbose", "--porcelain", "--dry-run", "--progress", "--no-progress",
             "--atomic"}
        ),  # fmt: skip
    )
    if unknown:
        return f"`git push {unknown}` is not a plain push"
    positionals = _positionals(args)
    if positionals and not _REMOTE_NAME.match(positionals[0]):
        return f"`git push {positionals[0]}` pushes to a URL or path, not a configured remote"
    refspecs = positionals[1:]
    if not refspecs:
        # No refspec: git pushes what the repository configuration says — read it instead of assuming HEAD.
        config = _git_config(cwd)
        branch = _current_branch(cwd) or ""
        remote = positionals[0] if positionals else (config.get(f"branch.{branch}.remote") or ["origin"])[-1]
        if config.get(f"remote.{remote}.push"):
            return f"`git push` would push the refspecs configured for remote {remote}"
        mode = (config.get("push.default") or ["simple"])[-1].lower()
        if mode == "matching":
            return "`git push` with push.default=matching pushes every matching branch"
        upstream = (config.get(f"branch.{branch}.merge") or [""])[-1]
        refspecs = [f"HEAD:{upstream}"] if mode in {"upstream", "tracking"} and upstream else ["HEAD"]
    destinations: list[str] = []
    for spec in refspecs:
        if spec.startswith(":"):
            return f"refspec {spec} deletes a branch"
        if spec.startswith("+"):
            return f"refspec {spec} forces the update"
        if "*" in spec:
            return f"refspec {spec} pushes a pattern"
        dest = spec.split(":", 1)[1] if ":" in spec else spec
        if dest == "HEAD" or (":" not in spec and spec == "HEAD"):
            dest = _current_branch(cwd) or ""
        for prefix in ("refs/heads/", "heads/"):
            dest = dest.removeprefix(prefix)
        destinations.append(dest)
    blocked = sorted({d for d in destinations if d in ctx.hotfix})
    if blocked:
        ctx.deny.append(
            f"BLOCKED: push to {', '.join(blocked)} — that branch changes only through a pull request. "
            f"Push your own branch and open a PR against {blocked[0]}."
        )
    return None


def _commit(ctx: _Context, args: list[str], cwd: Path | None) -> str | None:
    hit = _risky_flag(args, long=("--amend", "--no-verify"))
    if hit:
        return f"`git commit {hit}` rewrites history or skips hooks"
    valued = {"-m", "-F", "-C", "-c", "-t", "--message", "--file", "--author", "--date", "--reuse-message",
              "--reedit-message", "--fixup", "--squash", "--trailer", "--cleanup", "--template"}  # fmt: skip
    files: list[str] = []
    skip: str | None = None
    for token in args:
        if skip is not None:
            if skip in {"-F", "--file", "-t", "--template"}:
                files.append(token)
            skip = None
            continue
        name = _long_name(token)
        if name in {"--file", "--template"} and "=" in token:
            files.append(token.split("=", 1)[1])
        if token in valued:
            skip = token
        elif _short_letters(token):
            for position, char in enumerate(token[1:]):
                if char == "n":
                    return "`git commit -n` skips hooks"
                if char in "mFCct":
                    rest = token[position + 2 :]
                    if char in "Ft":
                        if rest:
                            files.append(rest)
                        else:
                            skip = f"-{char}"
                    elif not rest:
                        skip = f"-{char}"
                    break
    outer = ctx.cwd
    ctx.cwd = cwd
    try:
        return _check_paths(ctx, files, "git commit message file")
    finally:
        ctx.cwd = outer


def _git_sub(ctx: _Context, sub: str, args: list[str], cwd: Path | None) -> str | None:  # noqa: C901 — flat rule table
    if sub not in GIT_SUBCOMMANDS:
        return f"`git {sub}` is not on the SDD auto-approve list"
    if sub in _GIT_READ:
        hit = _risky_flag(
            args,
            short="O" if sub == "grep" else "",
            long=("--output", "--open-files-in-pager", "--no-index", "--contents"),
        )
        if hit:
            return f"`git {sub} {hit}` writes a file, runs a program or reads outside git"
        return _git_paths(ctx, args, cwd)
    if sub == "branch":
        hit = _risky_flag(
            args,
            short="dDmMcCfu",
            long=("--delete", "--move", "--copy", "--force", "--set-upstream-to", "--unset-upstream",
                  "--edit-description"),
        )  # fmt: skip
        return f"`git branch {hit}` changes branches" if hit else None
    if sub == "remote":
        rest = [a for a in args if a not in {"-v", "--verbose"}]
        return None if not rest or rest[0] in {"get-url", "show"} else "`git remote` changes remotes"
    if sub == "config":
        reads = {"--get", "--get-all", "--get-regexp", "--list"}
        unknown = _unknown_flag(
            args,
            short="lz",
            long=frozenset(reads | {"--show-origin", "--show-scope", "--null", "--name-only", "--includes",
                                    "--no-includes", "--local", "--worktree"}),
            valued_long=frozenset({"--type", "--default"}),
        )  # fmt: skip
        reading = any(_long_name(a) in reads for a in args) or any("l" in _short_letters(a) for a in args)
        if unknown or (not reading and len(_positionals(args)) != 1):
            return "`git config` writes configuration or reads outside the repository"
        listing = any(_long_name(a) in {"--list", "--get-regexp"} for a in args) or any(
            "l" in _short_letters(a) for a in args
        )
        if listing and not ({"--local", "--worktree"} & set(args)):
            return "`git config --list` can print credentials from the global configuration (add --local)"
        return None
    if sub == "worktree":
        ok = args[:1] == ["list"] and not _unknown_flag(
            args[1:], short="vz", long=frozenset({"--porcelain", "--verbose"})
        )
        return None if ok else "`git worktree` other than `list` (use `parrot sdd worktree`)"
    if sub == "fetch":
        hit = _risky_flag(
            args, short="f", long=("--force", "--update-head-ok", "--upload-pack", "--prune-tags"), benign=("--prune",)
        )
        if hit:
            return f"`git fetch {hit}` can rewrite local refs"
        positionals = _positionals(args, frozenset({"--depth", "-j", "--jobs"}))
        if positionals and not _REMOTE_NAME.match(positionals[0]):
            return f"`git fetch {positionals[0]}` fetches from a URL or path, not a configured remote"
        if any(":" in p or p.startswith("+") for p in positionals[1:]):
            return "a `git fetch` refspec can rewrite a local branch"
        return None
    if sub == "add":
        hit = _risky_flag(args, short="f", long=("--force",))
        return f"`git add {hit}` adds ignored files" if hit else _git_paths(ctx, args, cwd)
    if sub == "commit":
        return _commit(ctx, args, cwd)
    if sub == "pull":
        hit = _risky_flag(args, short="fr", long=("--force", "--rebase", "--upload-pack"))
        return f"`git pull {hit}` rewrites local history or refs" if hit else None
    if sub == "push":
        return _push(ctx, args, cwd)
    if sub == "checkout":
        plain = [a for a in args if a not in {"-q", "--quiet"}]
        if len(plain) == 1 and plain[0] in ctx.protected:
            return None
        if (
            plain[:1] == ["-b"]
            and len(plain) in {2, 3}
            and all(_BRANCH_NAME.match(p) and not p.startswith("-") for p in plain[1:])
        ):
            return None
        return "`git checkout` of paths or other refs can discard changes (use `git switch <branch>`)"
    if sub == "switch":
        unknown = _unknown_flag(
            args,
            short="cqt",
            long=frozenset({"--create", "--quiet", "--track", "--no-track", "--detach", "--guess", "--no-guess",
                            "--progress", "--no-progress"}),
        )  # fmt: skip
        return f"`git switch {unknown}` can discard changes" if unknown else None
    unknown = _unknown_flag(  # merge
        args,
        short="qv",
        long=frozenset({"--ff-only", "--no-ff", "--ff", "--no-edit", "--edit", "--quiet", "--verbose", "--stat",
                        "--no-stat", "--log", "--no-log", "--continue", "--progress", "--no-progress", "--signoff"}),
        valued_short="m",
        valued_long=frozenset({"--message"}),
    )  # fmt: skip
    return f"`git merge {unknown}` is not a plain merge" if unknown else None


def _git(ctx: _Context, args: list[str]) -> str | None:
    cwd = ctx.cwd
    index = 0
    while index < len(args) and args[index].startswith("-"):
        token = args[index]
        if token == "-C" or (token.startswith("-C") and len(token) > 2):
            target = args[index + 1] if token == "-C" and index + 1 < len(args) else token[2:]
            index += 2 if token == "-C" else 1
            norm, problem = _resolve(ctx, target)
            if problem or norm is None:
                return f"`git -C {target.replace(_PLACEHOLDER, '$(…)')}` {problem}"
            path = Path(norm)
            if not _inside(ctx, path) or not any(_under(os.path.realpath(norm), r) for r in ctx.real_roots):
                return f"`git -C {target.replace(_PLACEHOLDER, '$(…)')}` is outside the workspace"
            cwd = path
            continue
        if token in {"--no-pager", "--no-optional-locks", "--literal-pathspecs", "--no-replace-objects"}:
            index += 1
            continue
        return f"`git {token}` overrides repository settings"
    if index >= len(args):
        return None
    return _git_sub(ctx, args[index], args[index + 1 :], cwd)


# --------------------------------------------------------------------------
# gh, parrot, wikitoolkit, tests
# --------------------------------------------------------------------------


def _gh(ctx: _Context, args: list[str]) -> str | None:
    if args[:1] == ["api"]:
        for index, token in enumerate(args):
            method = None
            if token in {"-X", "--method"}:
                method = args[index + 1] if index + 1 < len(args) else ""
            elif token.startswith("--method="):
                method = token.split("=", 1)[1]
            elif token.startswith("-X") and len(token) > 2:
                method = token[2:]
            if method is not None and method.upper() != "GET":
                return f"`gh api` with method {method} changes GitHub state"
            if token in {"-f", "-F", "--field", "--raw-field", "--input"} or token.startswith(
                ("--field=", "--raw-field=", "--input=")
            ):
                return "`gh api` with fields sends a write request"
            if re.match(r"-[fF].", token):
                return "`gh api` with fields sends a write request"
        return None
    if args[:2] == ["pr", "create"]:
        files = [args[i + 1] for i in range(len(args) - 1) if args[i] in {"-F", "--body-file"}]
        files += [t.split("=", 1)[1] for t in args if t.startswith("--body-file=")]
        files += [t[2:] for t in args if t.startswith("-F") and len(t) > 2]
        return _check_paths(ctx, files, "gh pr create body file")
    return None


_SPEC_VERBS = frozenset(
    {"init-run", "render-brief", "stamp-run", "validate-suggestions", "check-path", "commit-intake",
     "existing-feature-id", "consequences"}
)  # fmt: skip
#: the `parrot sdd <noun> <verb>` surface the four agy SDD skills use; None = every verb
_PARROT_SDD: dict[str, frozenset[str] | None] = {
    "worktree": frozenset({"ensure", "root", "status", "list", "baseline", "sync-base"}),
    "task": frozenset({"close", "finalize", "graph", "state", "review", "heal"}),
    "ids": frozenset({"reserve", "check", "ledger"}),
    "spec": _SPEC_VERBS,
    "brief": frozenset({"plan", "write-index"}),
    "docs": frozenset({"parse", "taxonomy", "resolve-flow", "list"}),
    "tests": frozenset({"select", "report", "contract", "e2e-closeout"}),
    "techwiki": frozenset({"check", "api"}),
    "hooks": frozenset({"dangerous-actions", "agy-permissions"}),
    "ledger": None,
    "status": None,
}
_WIKITOOLKIT = frozenset(
    {"query", "page", "related", "status", "symbols", "ledger", "spec", "remember", "note", "link", "memories",
     "audit", "standup", "decisions", "adr", "lint", "entity", "communities", "ground", "schema", "usage", "ns",
     "inbox", "build"}
)  # fmt: skip


def _parrot(args: list[str]) -> str | None:
    if args[:1] == ["wiki"]:
        return _wikitoolkit(args[1:])
    noun = args[1] if len(args) > 1 else ""
    verb = args[2] if len(args) > 2 else ""
    if noun in _PARROT_SDD and (_PARROT_SDD[noun] is None or verb in (_PARROT_SDD[noun] or ())):
        return None
    if not noun or noun in {"--help", "-h"}:
        return None
    return f"`parrot sdd {noun}{' ' + verb if verb else ''}` is not on the SDD auto-approve list"


def _wikitoolkit(args: list[str]) -> str | None:
    if not args or args[0] in _WIKITOOLKIT or args[0] in {"--help", "-h"}:
        return None
    return f"`wikitoolkit {args[0]}` is not on the SDD auto-approve list"


_TEST_OUTPUTS = ("--junitxml", "--junit-xml", "--basetemp", "--html", "--report-log", "--log-file", "--resultlog")
_PYTEST_VALUED = frozenset(
    {"-k", "-m", "-p", "-c", "-o", "-n", "-W", "-r", "--tb", "--maxfail", "--rootdir", "--deselect", "--ignore",
     "--ignore-glob", "--confcutdir", "--durations", "--log-level", "--cov", "--cov-report", "--dist", "--color",
     "--import-mode", "--timeout", "--override-ini", "--config-file"}
)  # fmt: skip


def _tests(ctx: _Context, args: list[str], name: str) -> str | None:
    hit = _risky_flag(args, long=_TEST_OUTPUTS)
    if hit:
        return f"`{name} {hit}` writes output files"
    override = next((a for a in args if a.startswith("-o") or _long_name(a) == "--override-ini"), None)
    if override is not None:
        return f"`{name} {override}` overrides the test configuration"
    positionals = _positionals(args, _PYTEST_VALUED)
    paths = [p for p in positionals if "/" in p or p.endswith(".py") or "::" in p or p == "."]
    if not paths:
        return f"`{name}` without an explicit path runs on the whole repository"
    return _check_paths(ctx, args, f"{name} path", attached=True)


# --------------------------------------------------------------------------
# segments
# --------------------------------------------------------------------------


def _env_risk(ctx: _Context, segment: _Segment) -> str | None:
    for assignment in segment.env:
        name, _, value = assignment.partition("=")
        if name in _PATH_ENV:
            for entry in filter(None, value.split(os.pathsep)):
                problem = _path_problem(ctx, entry)
                if problem:
                    return f"{name} entry `{entry}` {problem}"
        elif name not in _SAFE_ENV:
            return f"environment override {name}"
    return None


def _segment_risk(ctx: _Context, segment: _Segment) -> str | None:
    """The risk of one covered simple command, or None."""
    env = _env_risk(ctx, segment)
    if env:
        return env
    if not _inside(ctx, ctx.cwd):
        return "the working directory is outside the workspace"
    argv = segment.argv
    name, args = argv[0], argv[1:]
    if name in _READ_ONLY:
        return _read_only(ctx, name, args)
    if name == "git":
        return _git(ctx, args)
    if name == "gh":
        return _gh(ctx, args)
    if name == "parrot":
        return _parrot(args)
    if name == "wikitoolkit":
        return _wikitoolkit(args)
    if name in {"pytest", "black"}:
        return _tests(ctx, args, name)
    if name in {"python", "python3"}:
        return _tests(ctx, args[2:], "pytest")
    if name == "ruff":
        return _tests(ctx, args[1:], f"ruff {args[0]}")
    return None  # source/. .venv/bin/activate


def _control_path(ctx: _Context, norm: str) -> bool:
    """Whether an absolute path lies in a control directory (``.agents``, ``.git`` …) of a workspace root."""
    for root in ctx.roots:
        if _under(norm, str(root)) and norm != str(root):
            first = Path(os.path.relpath(norm, root)).parts[0]
            if first in _CONTROL_DIRS:
                return True
    return False


def _redirect_risk(ctx: _Context, segment: _Segment) -> None:
    """Record denies/risks for one segment's redirections (applies to every command)."""
    for op, target in segment.redirects:
        if op == "<<<" or not target:
            continue
        if op in _FD_REDIRECTS and (target.isdigit() or target == "-"):
            continue
        writes = op in _WRITE_REDIRECTS or op in _FD_REDIRECTS
        shown = target.replace(_PLACEHOLDER, "$(…)")
        problem = _path_problem(ctx, target) if _path_like(target) or ctx.cwd is None else None
        if problem:
            ctx.risks.append(f"redirect {op} `{shown}` {problem}")
            continue
        if not writes or target == "/dev/null":
            continue
        norm, _ = _resolve(ctx, target)
        if norm is not None and _control_path(ctx, norm):
            ctx.risks.append(f"redirect {op} `{shown}` rewrites agent, hook or git configuration")
            continue
        verdict = dangerous_actions.evaluate({"tool_name": "Write", "tool_input": {"file_path": target}}, root=ctx.root)
        if verdict.decision == "deny":
            ctx.deny.append(verdict.reason)


_TRUSTED_SUBSTITUTIONS: tuple[tuple[str, ...], ...] = (
    ("git", "rev-parse"),
    ("git", "branch", "--show-current"),
    ("pwd",),
    ("parrot", "sdd", "worktree", "root"),
)


def _trusted_substitution(body: str) -> bool:
    """Whether a substitution only prints a path or name inside the repository (its value is then path-checked)."""
    if "\n" in body or "$(" in body or "`" in body:
        return False
    try:
        segments = _segments(body)
    except ValueError:
        return False
    if len(segments) != 1 or segments[0].redirects or segments[0].env:
        return False
    argv = segments[0].argv
    if argv[:2] == ["git", "-C"]:
        argv = ["git", *argv[3:]]
    return any(tuple(argv[: len(prefix)]) == prefix for prefix in _TRUSTED_SUBSTITUTIONS)


def _evaluate_segments(ctx: _Context, text: str) -> None:
    """Classify the simple commands of one substitution-free command line."""
    for raw in _segments(text):
        segment = _unwrap(raw)
        argv = segment.argv
        if argv and argv[0] in {"cd", "pushd"}:
            target = argv[1] if len(argv) > 1 else "~"
            norm, problem = _resolve(ctx, target) if target != "-" else (None, "previous directory")
            ctx.cwd = None if problem or norm is None else Path(norm)
            continue
        if argv and argv[0] == "popd":
            ctx.cwd = None
            continue
        _redirect_risk(ctx, segment)
        if argv and rule_covers([*segment.env, *argv]):
            risk = _segment_risk(ctx, segment)
            if risk:
                ctx.risks.append(risk)


def _evaluate_command(ctx: _Context, command: str, depth: int = 0) -> None:
    """Classify one command string (recursing into substitutions), recording into ``ctx``."""
    if depth > 8:
        ctx.risks.append("substitutions nested too deeply")
        return
    text, bodies = _extract_substitutions(_normalize(command, ctx))
    for body in bodies:
        _evaluate_command(ctx, body, depth + 1)
    outer_trusted = ctx.subst_trusted
    ctx.subst_trusted = all(_trusted_substitution(body) for body in bodies)
    try:
        _evaluate_segments(ctx, text)
    finally:
        ctx.subst_trusted = outer_trusted


def _hotfix_branches(root: Path | None) -> frozenset[str]:
    names = {"main", "master"}
    if root is not None and (root / "sdd" / "config.json").is_file():
        try:
            from parrot.sdd.config import load_sdd_config  # lazy + guarded, like dangerous_actions

            hotfix = load_sdd_config(root).hotfix_base
            if hotfix:
                names.add(hotfix)
        except Exception:  # noqa: BLE001 — an invalid config falls back to the defaults
            pass
    return frozenset(names)


def evaluate(payload: dict[str, Any], *, root: Path | None) -> Decision:
    """Combine command policy and worktree verdict for one agy PreToolUse payload."""
    unattended = os.environ.get(UNATTENDED_ENV) == "1"
    call = payload.get("toolCall")
    name = call.get("name") if isinstance(call, dict) else None
    # The escape hatch is for an operator at the keyboard. An unattended worker runs without one and under
    # --dangerously-skip-permissions, so a variable inherited from the launching shell must never lift the guard.
    if not unattended and os.environ.get(dangerous_actions.ESCAPE_ENV) == "1":
        return _ASK
    if name in worktree_environment.AGY_FILE_TOOLS:
        decision = _verdict(payload, root=root, unattended=unattended)
    else:
        decision = _policy(payload, root=root)
        args = call.get("args") if isinstance(call, dict) else None
        command = args.get("CommandLine") if isinstance(args, dict) else None
        if name == "run_command" and isinstance(command, str) and command.strip():
            decision = _merge(decision, _verdict(payload, root=root, unattended=unattended))
    return _unattended(decision) if unattended else decision


def _verdict(payload: dict[str, Any], *, root: Path | None, unattended: bool) -> Decision:
    """Return the worktree-environment verdict as a :class:`Decision`."""
    if root is None:
        return Decision("deny", "agy-permissions: no checkout root for this workspace")
    backend = os.environ.get("PARROT_SDD_SANDBOX_BACKEND", "")
    decision, reason, overwrite = worktree_environment.agy_verdict(
        payload, root=root, backend=backend, unattended=unattended
    )
    return Decision(decision, reason, overwrite)


def _merge(policy: Decision, verdict: Decision) -> Decision:
    """Merge decisions with deny > force_ask > ask precedence."""
    winner, other = (verdict, policy) if _RANK[verdict.decision] > _RANK[policy.decision] else (policy, verdict)
    reason = winner.reason or other.reason
    overwrite = None if winner.decision == "deny" else verdict.overwrite
    return Decision(winner.decision, reason, overwrite)


def _unattended(decision: Decision) -> Decision:
    """Map a non-interactive confirmation to a denial."""
    if decision.decision != "force_ask":
        return decision
    return Decision("deny", f"unattended: {decision.reason}".rstrip())


def _policy(payload: dict[str, Any], *, root: Path | None) -> Decision:
    """PR #2040 command policy for one run_command payload.

    Args:
        payload: The agy hook payload (``toolCall.name``, ``toolCall.args.CommandLine``, ``workspacePaths``).
        root: The repository root used for ``sdd/config.json`` and the dangerous-actions rules.

    Returns:
        ``deny`` for a destructive command, ``force_ask`` for a covered command the policy cannot positively
        classify as routine, else ``ask``.
    """
    if os.environ.get(UNATTENDED_ENV) != "1" and os.environ.get(dangerous_actions.ESCAPE_ENV) == "1":
        return _ASK
    call = payload.get("toolCall")
    if not isinstance(call, dict) or call.get("name") != "run_command":
        return _ASK
    raw_args = call.get("args")
    args: dict[str, Any] = raw_args if isinstance(raw_args, dict) else {}
    command = args.get("CommandLine", args.get("commandLine"))
    if not isinstance(command, str) or not command.strip():
        return _ASK
    paths = payload.get("workspacePaths")
    roots = workspace_roots(paths if isinstance(paths, list) else [], root)
    cwd_arg = args.get("Cwd") or args.get("cwd")
    if isinstance(cwd_arg, str) and cwd_arg:
        base = str(roots[0]) if roots else os.getcwd()
        cwd: Path | None = Path(os.path.normpath(os.path.join(base, os.path.expanduser(cwd_arg))))
    else:
        cwd = roots[0] if roots else Path(os.getcwd())
    verdict = dangerous_actions.evaluate(
        {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}, root=root
    )
    if verdict.decision == "deny":
        return Decision("deny", verdict.reason)
    ctx = _Context(
        roots=roots,
        real_roots=[os.path.realpath(r) for r in roots],
        cwd=cwd,
        root=root,
        hotfix=_hotfix_branches(root),
        protected=dangerous_actions.protected_branches(root),
    )
    try:
        _evaluate_command(ctx, command)
    except ValueError as exc:
        return Decision("force_ask", f"agy-permissions: could not parse the command ({exc})")
    if ctx.deny:
        return Decision("deny", ctx.deny[0])
    reasons = list(dict.fromkeys(ctx.risks))
    if verdict.decision == "warn":
        reasons.insert(0, verdict.reason)
    if reasons:
        return Decision("force_ask", "; ".join(reasons))
    return _ASK


def _render(decision: Decision) -> dict[str, Any]:
    out: dict[str, Any] = {"decision": decision.decision}
    if decision.reason:
        out["reason"] = decision.reason
    if decision.overwrite and decision.decision != "deny":
        out["overwrite"] = dict(decision.overwrite)
    return out


def main(argv: Sequence[str] | None = None) -> None:
    """Serve the agy PreToolUse hook: read the payload on stdin, write one JSON object, always exit 0."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hook", action="store_true", required=True)
    parser.parse_args(argv)
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("payload is not a JSON object")
        paths = payload.get("workspacePaths")
        first = paths[0] if isinstance(paths, list) and paths and isinstance(paths[0], str) else os.getcwd()
        result = _render(evaluate(payload, root=dangerous_actions.find_root(first)))
    except Exception as exc:  # noqa: BLE001 — never neutral on failure: the broad agy rules would apply unnarrowed
        reason = f"agy-permissions: checks failed ({type(exc).__name__}: {exc}); confirm this command"
        if os.environ.get(UNATTENDED_ENV) == "1":
            result = {"decision": "deny", "reason": f"unattended: {reason}"}
        else:
            result = {"decision": "force_ask", "reason": reason}
    sys.stdout.write(json.dumps(result) + "\n")


if __name__ == "__main__":
    main()
