"""Antigravity (agy) PreToolUse permission policy for the SDD command surface (brief agy-permission-hook).

agy (1.4.12) runs a shell command without asking only when a ``permissions.allow`` rule in the user's
settings matches it. A PreToolUse hook can ``deny`` a command, ``force_ask`` (prompt even though a rule
matches) or ``ask`` (leave the decision to the rules); a hook ``allow`` is accepted but ignored. This module
therefore carries both halves of the policy:

* :data:`SDD_ALLOW_RULES` — the managed agy rules that ``parrot sdd install --host google`` merges into
  the user's agy settings, broad enough for ``/sdd-spec``, ``/sdd-task``, ``/sdd-brief`` and ``/sdd-fix``;
* :func:`evaluate` — the hook that narrows those rules: ``deny`` for destructive commands (the C32
  dangerous-actions rules plus a push to the hotfix branch), ``force_ask`` for risky variants a broad rule
  would approve (``find -delete``, ``sed -i``, reads outside the workspace, a bare ``pytest`` …), ``ask``
  otherwise. A command no managed rule covers is never escalated: agy prompts for it anyway.

It is a narrowing layer on top of agy's own matching, not a sandbox. Served as
``parrot sdd hooks agy-permissions --hook``; :func:`main` always exits 0 and writes one JSON object. Only
the stdlib and the sibling ``dangerous_actions`` guard are imported at module level; ``parrot.sdd.config``
is loaded lazily and guarded.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Sequence

from parrot.sdd.scripts import dangerous_actions

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
_SAFE_ENV = frozenset(
    {"PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "GIT_TERMINAL_PROMPT", "GIT_PAGER", "PAGER", "NO_COLOR", "TERM",
     "LANG", "LC_ALL", "TZ"}
)  # fmt: skip


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
# decisions
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Decision:
    """Outcome of :func:`evaluate`, in agy's hook vocabulary."""

    decision: Literal["deny", "force_ask", "ask"]
    reason: str = ""


_ASK = Decision("ask")
_PLACEHOLDER = "__PARROT_SUBST__"
_SEPARATORS = frozenset({";", "&&", "||", "|", "|&", "&", "(", ")", ";;", ";&", "{", "}", "!"})
_WRITE_REDIRECTS = frozenset({">", ">>", ">|", "&>", "&>>", "<>"})
_FD_REDIRECTS = frozenset({">&", "<&"})
_HERE_REDIRECTS = frozenset({"<<", "<<-", "<<<"})
_HEREDOC = re.compile(r"(?<!<)<<-?(?!<)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
_WRAPPERS = frozenset({"time", "nohup", "command", "builtin"})


@dataclass
class _Context:
    """Per-command evaluation state."""

    roots: list[Path]
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


def _strip_heredocs(command: str) -> str:
    """Remove heredoc bodies and join the remaining lines as ``;``-separated commands."""
    lines = command.replace("\\\n", " ").split("\n")
    kept: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        kept.append(line)
        index += 1
        for match in _HEREDOC.finditer(line):
            while index < len(lines) and lines[index].strip() != match.group(2):
                index += 1
            index += 1
    return " ; ".join(line for line in kept if line.strip())


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
    """Split a substitution-free command into simple commands."""
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
        elif token in _WRITE_REDIRECTS or token in _FD_REDIRECTS or token in _HERE_REDIRECTS or token == "<":
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


def _under(path: str, root: Path) -> bool:
    text = str(root)
    return path == text or path.startswith(text.rstrip(os.sep) + os.sep)


def _inside(ctx: _Context, path: Path | None) -> bool:
    return path is not None and any(_under(str(path), root) for root in ctx.roots)


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
    return "/" in token or token.startswith("~") or "$" in token or token == ".." or _PLACEHOLDER in token


def _path_problem(ctx: _Context, token: str) -> str | None:
    """Why a path-like token may point outside the workspace, or None when it stays inside."""
    if _PLACEHOLDER in token:
        return None if ctx.subst_trusted else "is built from a command substitution"
    expanded = _expand(token)
    if expanded is None:
        return "is built from a shell variable"
    if expanded == "/dev/null" or expanded.startswith("/dev/fd/") or expanded in {"/dev/stdout", "/dev/stderr"}:
        return None
    if not os.path.isabs(expanded):
        if ctx.cwd is None:
            return "is relative to an unknown directory"
        expanded = os.path.join(str(ctx.cwd), expanded)
    if any(_under(os.path.normpath(expanded), root) for root in ctx.roots):
        return None
    return "is outside the workspace"


def _check_paths(ctx: _Context, tokens: Sequence[str], what: str) -> str | None:
    for token in tokens:
        value = token.split("=", 1)[1] if token.startswith("--") and "=" in token else token
        if value.startswith("-") and value != token:
            continue
        if (value is token and token.startswith("-")) or not _path_like(value):
            continue
        problem = _path_problem(ctx, value)
        if problem:
            return f"{what} `{value.replace(_PLACEHOLDER, '$(…)')}` {problem}"
    return None


# --------------------------------------------------------------------------
# per-command rules
# --------------------------------------------------------------------------

_FIND_ACTIONS = frozenset({"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fprintf", "-fls"})
_SED_PRINT = (
    re.compile(r"^\s*(\d+|\$)(\s*,\s*(\d+|\$))?\s*p\s*$"),
    re.compile(r"^\s*/[^/]*/(\s*,\s*/[^/]*/)?\s*p\s*$"),
    re.compile(r"^\s*s(.)(?:(?!\1)[^\\]|\\.)*\1(?:(?!\1)[^\\]|\\.)*\1[gpiI0-9]*\s*$"),
)
_GREP_VALUED = frozenset(
    {"-e", "--regexp", "-f", "--file", "-m", "--max-count", "-A", "-B", "-C", "--context", "--after-context",
     "--before-context", "--include", "--exclude", "--exclude-dir", "-g", "--glob", "-t", "--type", "-T",
     "--type-not", "--color", "--colour", "-M", "--max-columns", "-j", "--threads", "--max-depth", "-d"}
)  # fmt: skip
_NO_PATH_CHECK = frozenset({"echo", "printf", "test", "date", "basename", "dirname", "realpath", "readlink", "which",
                            "pwd"})  # fmt: skip
_PYTEST_VALUED = frozenset(
    {"-k", "-m", "-p", "-c", "-o", "-n", "-W", "-r", "--tb", "--maxfail", "--rootdir", "--basetemp", "--deselect",
     "--ignore", "--ignore-glob", "--confcutdir", "--durations", "--junitxml", "--log-level", "--cov",
     "--cov-report", "--dist", "--color", "--import-mode", "--timeout", "-x"}
)  # fmt: skip


def _positionals(args: Sequence[str], valued: frozenset[str]) -> list[str]:
    out: list[str] = []
    skip = False
    for token in args:
        if skip:
            skip = False
            continue
        if token in valued and token != "-x":
            skip = True
        elif not token.startswith("-") or token == "-":
            out.append(token)
    return out


def _find(ctx: _Context, args: list[str]) -> str | None:
    hit = next((a for a in args if a in _FIND_ACTIONS), None)
    if hit:
        return f"`find {hit}` runs or deletes"
    starts: list[str] = []
    index = 0
    while index < len(args) and not (args[index].startswith("-") or args[index] in {"(", "!", ")"}):
        starts.append(args[index])
        index += 1
    values = [args[i + 1] for i in range(len(args) - 1) if args[i] in {"-newer", "-samefile"}]
    return _check_paths(ctx, [*(starts or ["."]), *values], "find path")


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
            for pos, char in enumerate(cluster):
                if char == "i":
                    return "`sed -i` edits files in place"
                if char == "f":
                    return "`sed -f` runs a script file"
                if char == "e":
                    rest = cluster[pos + 1 :]
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
    return _check_paths(ctx, files, "sed input")


def _read_only(ctx: _Context, name: str, args: list[str]) -> str | None:
    if name == "find":
        return _find(ctx, args)
    if name == "sed":
        return _sed(ctx, args)
    if name == "sort" and any(a == "--output" or a.startswith(("--output=", "-o")) for a in args):
        return "`sort -o` writes a file"
    if name == "tree" and "-o" in args:
        return "`tree -o` writes a file"
    if name == "uniq" and len(_positionals(args, frozenset({"-f", "-s", "-w"}))) >= 2:
        return "`uniq IN OUT` writes a file"
    if name == "rg" and any(a in {"--pre", "--pre-glob"} or a.startswith("--pre=") for a in args):
        return "`rg --pre` runs a command"
    if name in _NO_PATH_CHECK:
        return None
    if name in {"grep", "rg"}:
        explicit = any(a in {"-e", "--regexp", "-f", "--file"} or a.startswith("--regexp=") for a in args)
        positionals = _positionals(args, _GREP_VALUED)
        files = positionals if explicit else positionals[1:]
        valued = [args[i + 1] for i in range(len(args) - 1) if args[i] in {"-f", "--file"}]
        return _check_paths(ctx, [*files, *valued], f"{name} path")
    if name == "jq":
        return _check_paths(ctx, _positionals(args, frozenset({"--arg", "--argjson"}))[1:], "jq input")
    return _check_paths(ctx, args, f"{name} path")


def _current_branch(start: Path | None) -> str | None:
    """The checked-out branch of the repository holding ``start``, read from ``HEAD`` (no subprocess)."""
    root = dangerous_actions.find_root(start) if start is not None else None
    if root is None:
        return None
    git = root / ".git"
    try:
        gitdir = git
        if git.is_file():
            gitdir = Path(git.read_text(encoding="utf-8").split(":", 1)[1].strip())
            if not gitdir.is_absolute():
                gitdir = root / gitdir
        head = (gitdir / "HEAD").read_text(encoding="utf-8").strip()
    except (OSError, IndexError):
        return None
    return head.removeprefix("ref: refs/heads/") if head.startswith("ref: refs/heads/") else None


def _push(ctx: _Context, args: list[str], cwd: Path | None) -> str | None:
    risky = {"-f", "--force", "--force-with-lease", "--force-if-includes", "-d", "--delete", "--mirror", "--all",
             "--prune", "--no-verify", "--receive-pack", "--exec"}  # fmt: skip
    hit = next((a for a in args if a.split("=", 1)[0] in risky), None)
    positionals = _positionals(args, frozenset({"-o", "--push-option", "--repo"}))
    refspecs = positionals[1:]
    destinations: list[str] = []
    for spec in refspecs or ["HEAD"]:
        if spec.startswith(":"):
            hit = hit or f"refspec {spec} deletes a branch"
            continue
        if spec.startswith("+"):
            hit = hit or f"refspec {spec} forces the update"
            spec = spec[1:]
        dest = spec.split(":", 1)[1] if ":" in spec else spec
        if dest == "HEAD":
            dest = _current_branch(cwd) or ""
        destinations.append(dest.removeprefix("refs/heads/"))
    blocked = sorted({d for d in destinations if d in ctx.hotfix})
    if blocked:
        ctx.deny.append(
            f"BLOCKED: push to {', '.join(blocked)} — that branch changes only through a pull request. "
            f"Push your own branch and open a PR against {blocked[0]}."
        )
    return f"`git push {hit}`" + (" is risky" if not hit.startswith("refspec") else "") if hit else None


def _git_sub(ctx: _Context, sub: str, args: list[str], cwd: Path | None) -> str | None:  # noqa: C901 — flat rule table
    if sub not in GIT_SUBCOMMANDS:
        return f"`git {sub}` is not on the SDD auto-approve list"
    if sub in _GIT_READ:
        if any(a == "--output" or a.startswith("--output=") or a in {"-O", "--open-files-in-pager"} for a in args):
            return f"`git {sub}` writes a file or opens a pager"
        return None
    if sub == "branch":
        risky = {"-d", "-D", "--delete", "-m", "-M", "--move", "-c", "-C", "--copy", "-f", "--force", "-u",
                 "--set-upstream-to", "--unset-upstream", "--edit-description"}  # fmt: skip
        hit = next((a for a in args if a.split("=", 1)[0] in risky), None)
        return f"`git branch {hit}` changes branches" if hit else None
    if sub == "remote":
        return None if not args or args[0] in {"-v", "--verbose", "get-url", "show"} else "`git remote` changes remotes"
    if sub == "config":
        writes = {"--unset", "--unset-all", "--add", "--replace-all", "--edit", "-e", "--rename-section",
                  "--remove-section", "--file", "-f", "--blob"}  # fmt: skip
        if any(a.split("=", 1)[0] in writes for a in args) or len(_positionals(args, frozenset())) >= 2:
            return "`git config` writes configuration"
        return None
    if sub == "worktree":
        return None if args[:1] == ["list"] else "`git worktree` other than `list` (use `parrot sdd worktree`)"
    if sub == "fetch":
        if any(a in {"-f", "--force", "--update-head-ok"} or a.startswith("--upload-pack") for a in args):
            return "`git fetch --force` can rewrite local branches"
        if any(":" in p or p.startswith("+") for p in _positionals(args, frozenset({"--depth", "-j", "--jobs"}))[1:]):
            return "a `git fetch` refspec can rewrite a local branch"
        return None
    if sub == "commit":
        valued = {"-m", "-F", "-C", "-c", "-t", "--message", "--file", "--author", "--date", "--reuse-message",
                  "--reedit-message", "--fixup", "--squash", "--trailer", "--cleanup", "--template"}  # fmt: skip
        skip = False
        for token in args:
            if skip:
                skip = False
                continue
            if token.split("=", 1)[0] in {"--amend", "--no-verify"}:
                return f"`git commit {token}` rewrites history or skips hooks"
            if token in valued:
                skip = True
            elif re.fullmatch(r"-[a-zA-Z]+", token):
                for char in token[1:]:
                    if char == "n":
                        return "`git commit -n` skips hooks"
                    if char in "mFCct":
                        break
        return None
    if sub == "pull":
        return (
            "`git pull --force`" if any(a in {"-f", "--force"} or a.startswith("--upload-pack") for a in args) else None
        )
    if sub == "push":
        return _push(ctx, args, cwd)
    if sub == "checkout":
        plain = [a for a in args if a not in {"-q", "--quiet"}]
        if len(plain) == 1 and plain[0] in ctx.protected:
            return None
        if plain[:1] == ["-b"] and len(plain) in {2, 3} and not any(p.startswith("-") for p in plain[1:]):
            return None
        return "`git checkout` of paths or other refs can discard changes (use `git switch <branch>`)"
    if sub == "switch":
        risky = {"-f", "--force", "--discard-changes", "-C", "--force-create"}
        hit = next((a for a in args if a in risky), None)
        return f"`git switch {hit}` can discard changes" if hit else None
    return None  # merge, add


def _git(ctx: _Context, args: list[str]) -> str | None:
    cwd = ctx.cwd
    index = 0
    while index < len(args) and args[index].startswith("-"):
        token = args[index]
        if token == "-C" or (token.startswith("-C") and len(token) > 2):
            target = args[index + 1] if token == "-C" and index + 1 < len(args) else token[2:]
            index += 2 if token == "-C" else 1
            expanded = _expand(target) if _PLACEHOLDER not in target else None
            if expanded is None:
                cwd = None
                continue
            path = Path(os.path.normpath(os.path.join(str(cwd) if cwd else "/", expanded)))
            if not _inside(ctx, path):
                return f"`git -C {target}` is outside the workspace"
            cwd = path
            continue
        if token in {"--no-pager", "--no-optional-locks", "--literal-pathspecs", "--no-replace-objects"}:
            index += 1
            continue
        return f"`git {token}` overrides repository settings"
    if index >= len(args):
        return None
    return _git_sub(ctx, args[index], args[index + 1 :], cwd)


def _gh(args: list[str]) -> str | None:
    if args[:1] != ["api"]:
        return None
    for index, token in enumerate(args):
        if token in {"-X", "--method"}:
            method = args[index + 1] if index + 1 < len(args) else ""
            if method.upper() != "GET":
                return f"`gh api {token} {method}` changes GitHub state"
        if token.startswith("--method=") and token.split("=", 1)[1].upper() != "GET":
            return "`gh api --method` changes GitHub state"
        if token.split("=", 1)[0] in {"-f", "-F", "--field", "--raw-field", "--input"} or re.match(r"-[fF]\w", token):
            return "`gh api` with fields sends a write request"
    return None


_PARROT_RISKY_NOUNS = frozenset({"install", "uninstall", "launch", "closeout"})
_PARROT_RISKY_VERBS = frozenset({("worktree", "remove"), ("worktree", "push-protection"), ("hooks", "install")})
_WIKI_RISKY = frozenset({"claude", "codex", "gemini", "google", "mcp", "serve"})


def _parrot(args: list[str]) -> str | None:
    if args[:1] == ["wiki"]:
        return _wikitoolkit(args[1:])
    noun = args[1] if len(args) > 1 else ""
    verb = args[2] if len(args) > 2 else ""
    if noun in _PARROT_RISKY_NOUNS or (noun, verb) in _PARROT_RISKY_VERBS:
        return f"`parrot sdd {noun}{' ' + verb if verb else ''}` changes the environment"
    return None


def _wikitoolkit(args: list[str]) -> str | None:
    return f"`wikitoolkit {args[0]}` installs or serves" if args[:1] and args[0] in _WIKI_RISKY else None


def _tests(ctx: _Context, args: list[str], name: str) -> str | None:
    positionals = _positionals(args, _PYTEST_VALUED)
    paths = [p for p in positionals if "/" in p or p.endswith(".py") or "::" in p or p == "."]
    if not paths:
        return f"`{name}` without an explicit path runs on the whole repository"
    valued = [args[i + 1] for i in range(len(args) - 1) if args[i] in {"--basetemp", "--rootdir", "-c"}]
    return _check_paths(ctx, [*paths, *valued, *(a for a in args if a.startswith("--"))], f"{name} path")


def _segment_risk(ctx: _Context, segment: _Segment) -> str | None:
    """The risk of one covered simple command, or None."""
    bad_env = [e.split("=", 1)[0] for e in segment.env if e.split("=", 1)[0] not in _SAFE_ENV]
    if bad_env:
        return f"environment override {', '.join(bad_env)}"
    if not _inside(ctx, ctx.cwd):
        return "the working directory is outside the workspace"
    argv = segment.argv
    name, args = argv[0], argv[1:]
    if name in _READ_ONLY:
        return _read_only(ctx, name, args)
    if name == "git":
        return _git(ctx, args)
    if name == "gh":
        return _gh(args)
    if name == "parrot":
        return _parrot(args)
    if name == "wikitoolkit":
        return _wikitoolkit(args)
    if name == "pytest" or name in {"black"}:
        return _tests(ctx, args, name)
    if name in {"python", "python3"}:
        return _tests(ctx, args[2:], "pytest")
    if name == "ruff":
        return _tests(ctx, args[1:], f"ruff {args[0]}")
    return None  # source/. .venv/bin/activate


def _redirect_risk(ctx: _Context, segment: _Segment) -> None:
    """Record denies/risks for one segment's redirections (applies to every command)."""
    for op, target in segment.redirects:
        if op in _HERE_REDIRECTS or not target:
            continue
        if op in _FD_REDIRECTS and (target.isdigit() or target == "-"):
            continue
        writes = op in _WRITE_REDIRECTS or op in _FD_REDIRECTS
        problem = _path_problem(ctx, target) if _path_like(target) or ctx.cwd is None else None
        if problem:
            ctx.risks.append(f"redirect {op} `{target.replace(_PLACEHOLDER, '$(…)')}` {problem}")
        elif writes and target != "/dev/null":
            verdict = dangerous_actions.evaluate(
                {"tool_name": "Write", "tool_input": {"file_path": target}}, root=ctx.root
            )
            if verdict.decision == "deny":
                ctx.deny.append(verdict.reason)


def _evaluate_command(ctx: _Context, command: str, depth: int = 0) -> None:
    """Classify one command string (recursing into substitutions), recording into ``ctx``."""
    if depth > 8:
        ctx.risks.append("substitutions nested too deeply")
        return
    text, bodies = _extract_substitutions(_strip_heredocs(command))
    for body in bodies:
        _evaluate_command(ctx, body, depth + 1)
    outer_trusted = ctx.subst_trusted
    ctx.subst_trusted = all(_trusted_substitution(body) for body in bodies)
    try:
        _evaluate_segments(ctx, text)
    finally:
        ctx.subst_trusted = outer_trusted


_TRUSTED_SUBSTITUTIONS: tuple[tuple[str, ...], ...] = (
    ("git", "rev-parse"),
    ("git", "branch", "--show-current"),
    ("pwd",),
    ("parrot", "sdd", "worktree", "root"),
)


def _trusted_substitution(body: str) -> bool:
    """Whether a substitution only prints a path or name derived from the repository itself."""
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
            expanded = _expand(target) if _PLACEHOLDER not in target and target != "-" else None
            ctx.cwd = (
                None
                if expanded is None or ctx.cwd is None and not os.path.isabs(expanded)
                else Path(os.path.normpath(os.path.join(str(ctx.cwd or "/"), expanded)))
            )
            continue
        if argv and argv[0] == "popd":
            ctx.cwd = None
            continue
        _redirect_risk(ctx, segment)
        if argv and rule_covers([*segment.env, *argv]):
            risk = _segment_risk(ctx, segment)
            if risk:
                ctx.risks.append(risk)


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
    """Pure decision for one agy PreToolUse payload.

    Args:
        payload: The agy hook payload (``toolCall.name``, ``toolCall.args.CommandLine``, ``workspacePaths``).
        root: The repository root used for ``sdd/config.json`` and the dangerous-actions rules.

    Returns:
        ``deny`` for a destructive command, ``force_ask`` for a risky variant of a managed rule, else ``ask``.
    """
    if os.environ.get(dangerous_actions.ESCAPE_ENV) == "1":
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


def _render(decision: Decision) -> dict[str, str]:
    out = {"decision": decision.decision}
    if decision.reason:
        out["reason"] = decision.reason
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
    except Exception as exc:  # noqa: BLE001 — fail neutral: agy's own rules still decide
        result = {"decision": "ask", "reason": f"agy-permissions: checks skipped ({type(exc).__name__}: {exc})"}
    sys.stdout.write(json.dumps(result) + "\n")


if __name__ == "__main__":
    main()
