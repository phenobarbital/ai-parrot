"""Portable PreToolUse guard that blocks destructive actions and names the safe alternative (FEAT-633 C32).

A stdlib port of ai-parrot's ``.claude/hooks/dangerous-actions-blocker.sh`` that needs neither ``bash``, ``jq``,
``python3`` on PATH, GNU ``grep`` nor ``pgrep``, so it behaves the same on Linux, macOS and Windows. It is served
through the ``parrot`` launcher (``parrot sdd hooks dangerous-actions --hook``) and registered in a repository's
``.claude/settings.json`` by ``parrot sdd install``.

The decision travels in the JSON written to stdout (``main`` always exits 0), like the worktree guard:
``{"hookSpecificOutput": {... "permissionDecision": "deny" ...}}`` blocks, ``{"systemMessage": ...}`` warns and
``{}`` allows. ``PARROT_ALLOW_DANGEROUS=1`` disables every check. This module imports nothing from ``parrot`` at
import time (a hook runs on every tool call); ``parrot.sdd.config`` is loaded lazily and guarded.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Sequence

ESCAPE_ENV = "PARROT_ALLOW_DANGEROUS"
_RECOVERY = (
    "(If this is a deliberate recovery, ask the user to re-run with PARROT_ALLOW_DANGEROUS=1 — "
    "do not work around this hook.)"
)
_DEFAULT_PROTECTED = ("dev", "main", "master", "staging")


@dataclass(frozen=True)
class Verdict:
    """Outcome of :func:`evaluate`."""

    decision: Literal["allow", "deny", "warn"]
    reason: str = ""


_ALLOW = Verdict("allow")


def _deny(what: str, *alternatives: str) -> Verdict:
    lines = [f"BLOCKED: {what}"]
    if alternatives:
        lines += ["", "Safe alternative:", *(f"  {a}" for a in alternatives)]
    lines += ["", _RECOVERY]
    return Verdict("deny", "\n".join(lines))


# --------------------------------------------------------------------------
# context (root, protected branches)
# --------------------------------------------------------------------------


def find_root(cwd: str | Path | None) -> Path | None:
    """Walk up from ``cwd`` to the directory holding a ``.git`` entry (no subprocess); ``cwd`` when none."""
    if not cwd:
        return None
    start = Path(cwd)
    try:
        start = start.resolve()
    except OSError:
        pass
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return start


def protected_branches(root: Path | None) -> tuple[str, ...]:
    """The protected branches: ``dev``, ``main``, ``master``, ``staging`` always, plus ``base_branch``,
    ``staging_branch`` and ``hotfix_base`` from ``sdd/config.json`` when it is present and valid.

    The defaults stay protected even when the config names other lanes (FEAT-792 D2): over-protecting is the
    safe direction, and a repo whose base branch is ``trunk`` usually still cares about ``dev`` or ``staging``.
    """
    names: set[str] = set(_DEFAULT_PROTECTED)
    if root is not None and (root / "sdd" / "config.json").is_file():
        try:
            from parrot.sdd.config import load_sdd_config  # lazy + guarded: only when the repo has a config

            config = load_sdd_config(root)
            names.update(n for n in (config.base_branch, config.staging_branch, config.hotfix_base) if n)
        except Exception:  # noqa: BLE001 — an invalid config falls back to the defaults
            pass
    return tuple(sorted(names))


# --------------------------------------------------------------------------
# quoted-text stripping
# --------------------------------------------------------------------------

_SHELL_EXEC = (
    re.compile(r"(^|[;&|]|\s)(bash|sh|zsh|dash|eval|ssh)\s+([^;&|]*\s)?-c\b"),
    re.compile(r"(^|[;&|]|\s)eval\s"),
    re.compile(r"(^|[;&|]|\s)ssh\s"),
    re.compile(r"(^|[;&|]|\s)(pwsh|powershell)(\.exe)?\s+([^;&|]*\s)?-(command|c)\b", re.IGNORECASE),
    re.compile(r"(^|[;&|]|\s)cmd(\.exe)?\s+/c\b", re.IGNORECASE),
)


def strip_quoted(raw: str) -> str:
    """Blank out quoted spans so text *about* a command is not mistaken for the command.

    When the line hands a quoted string to something that executes it (``bash -c``, ``eval``, ``ssh``,
    ``pwsh -Command``, ``cmd /c``) the quoted content IS the command: only the quote characters are neutralized.
    """
    if any(p.search(raw) for p in _SHELL_EXEC):
        return raw.replace('"', " ").replace("'", " ")
    return re.sub(r'"[^"]*"', " ", re.sub(r"'[^']*'", " ", raw))


# --------------------------------------------------------------------------
# Bash rules
# --------------------------------------------------------------------------

_SEP = r"(^|[;&|]|\s)"
_RM_ROOT = re.compile(
    r"(^|[;&|(]|\s)\s*(sudo\s+)?rm(\s+(-[a-zA-Z]+|--[a-zA-Z-]+))*\s+(-[a-zA-Z]*[rR][a-zA-Z]*|--recursive)"
    r"(\s+(-[a-zA-Z]+|--[a-zA-Z-]+))*\s+['\"]?(/|~|\$\{?HOME\}?)[*/]*['\"]?\s*($|[;&|])"
)
_RM_CRITICAL = re.compile(
    r"rm\s+(-[a-zA-Z]+\s+)*-?[a-zA-Z]*[rR][a-zA-Z]*\s+[^;&|]*(\.venv|\.git(/|\s|$)|\.(claude|parrot)/worktrees)"
)
_WIN_CRITICAL = re.compile(r"(\.venv|\.git([\\/]|\s|$)|\.(claude|parrot)[\\/]worktrees)", re.IGNORECASE)
_WIN_ROOT_TOKEN = re.compile(
    r"(?:^|[\s'\"])(?:[A-Za-z]:[\\/]?\*?|~|\$home|\$env:userprofile)[\\/*]*(?=\s|$|['\"])", re.IGNORECASE
)
_WIN_DRIVE_TOKEN = re.compile(r"(?:^|[\s'\"])[A-Za-z]:[\\/]?\*?[\\/*]*(?=\s|$|['\"])")
_DESTROYERS = ("mkfs", "dd if=", ":(){:|:&};:", "> /dev/sd", "--no-preserve-root", "chmod -R 777 /")
_SQL_STMT = re.compile(r"\b(DROP\s+(DATABASE|TABLE|SCHEMA)|TRUNCATE\s+TABLE)\b", re.IGNORECASE)
_SQL_CLIENT = re.compile(
    r"\b(psql|mysql|mariadb|sqlite3|clickhouse-client|mongosh|influx|bq\s+query|duckdb)\b", re.IGNORECASE
)
_PUBLISH = re.compile(r"(twine\s+upload|uv\s+publish|python\s+-m\s+twine|poetry\s+publish|npm\s+publish)")
_PIP = re.compile(r"(^|[;&|]\s*)(sudo\s+)?pip\s+install")
_PIP_OK = re.compile(r"(uv\s+pip|cibuildwheel|python\s+-m\s+pip\s+install\s+--upgrade\s+pip)")
_SECRET = re.compile(
    r"(sk-ant-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{32,}|ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{50,}"
    r"|AKIA[A-Z0-9]{16}|xox[bpsa]-[A-Za-z0-9-]{20,})"
)
_PLACEHOLDER = re.compile(r"EXAMPLE|PLACEHOLDER|REDACTED|YOUR[_-]|<your|xxxxxxxx|0{8,}|DUMMY|FAKE_", re.IGNORECASE)
_FORCE_FLAG = re.compile(r"(\s|^)(-f|--force)(\s|$|=)")


def _branch_re(branches: Sequence[str]) -> str:
    """Match a protected branch name as a whole token, optionally as ``refs/heads/<name>``.

    A letter, digit, ``_``, ``.``, ``/`` or ``-`` on either side means the name is only part of a longer branch
    name (``feat-x-dev-loop``, ``feat/dev``), so it does not match (issue:a682edf559a5).
    """
    names = "|".join(re.escape(b) for b in branches)
    return r"(?<![\w./-])(?:refs/heads/)?(" + names + r")(?![\w./-])"


def _forced_refspec_targets(scan: str) -> list[str]:
    """Destination branches of ``+<refspec>`` arguments in every ``git … push`` segment of ``scan``.

    A leading ``+`` forces the update exactly like ``--force`` (issue:047c5435b564). The destination is the part
    after ``:`` when present, else the whole refspec; a ``refs/heads/`` prefix is stripped.
    """
    targets: list[str] = []
    for segment in re.split(r"[;&|]", scan):
        tokens = segment.split()
        if "git" not in tokens or "push" not in tokens[tokens.index("git") :]:
            continue
        start = tokens.index("push", tokens.index("git")) + 1
        for token in tokens[start:]:
            if not token.startswith("+") or len(token) == 1:
                continue
            refspec = token[1:]
            destination = refspec.split(":", 1)[1] if ":" in refspec else refspec
            targets.append(destination.removeprefix("refs/heads/"))
    return targets


_WRAPPER = re.compile(r"^(?:(?:pwsh|powershell)(?:\.exe)?\s+(?:-\w+\s+)*|cmd(?:\.exe)?\s+/[ck]\s+)", re.IGNORECASE)


def _windows_segments(scan: str) -> list[str]:
    return [s.strip() for s in re.split(r"[;&|]", scan) if s.strip()]


def _windows_destroyer(scan: str) -> str | None:
    """Name the Windows/macOS destroyer found in ``scan``, or None."""
    for seg in _windows_segments(scan):
        seg = _WRAPPER.sub("", seg)
        low = seg.lower()
        head = re.match(r"(?:sudo\s+)?(\S+)", low)
        cmd = (head.group(1) if head else "").replace(".exe", "")
        if cmd in {"remove-item", "ri"} and re.search(r"-r(ecurse)?\b", seg, re.IGNORECASE):
            if _WIN_ROOT_TOKEN.search(seg):
                return "Remove-Item -Recurse on a drive root or the home directory"
        if cmd in {"rd", "rmdir", "del", "erase"} and re.search(r"(^|\s)/s\b", seg, re.IGNORECASE):
            if _WIN_DRIVE_TOKEN.search(seg):
                return f"{cmd} /s on a drive root"
        if re.fullmatch(r"format(\.com)?", cmd) and re.match(r"\S+\s+[A-Za-z]:", seg):
            return "format of a drive"
        if cmd == "diskutil" and re.match(
            r"\S+\s+(eraseDisk|eraseVolume|partitionDisk|zeroDisk|randomDisk)\b", seg, re.IGNORECASE
        ):
            return "diskutil erase/partition"
        if cmd in {"remove-item", "ri", "rd", "rmdir", "del", "erase"}:
            recursive = re.search(r"(-r(ecurse)?\b|(^|\s)/s\b)", seg, re.IGNORECASE)
            if recursive and _WIN_CRITICAL.search(seg):
                return "recursive delete of a repo-critical path"
    return None


def _bash(cmd: str, root: Path | None, protected: Sequence[str]) -> Verdict:  # noqa: C901 — one flat rule table
    scan = strip_quoted(cmd)

    if re.search(_SEP + r"git\s+([^;&|]*\s)?reset\s+([^;&|]*\s)?--hard", scan):
        return _deny(
            "`git reset --hard` discards committed local work that is not on origin.",
            "git fetch origin",
            "git log --oneline origin/<branch>..HEAD   # commits only you have",
            "# If that list is non-empty, PUSH them before resetting.",
            "# To just catch up with origin without destroying anything:",
            "git merge --ff-only origin/<branch>",
            "# Already lost commits? They are unreferenced, not gone:",
            "git reflog  &&  git tag -f recover/<name> <sha>  &&  git cherry-pick <sha>",
        )
    if re.search(_SEP + r"git\s+([^;&|]*\s)?clean\s+[^;&|]*-[a-zA-Z]*[dx]", scan):
        return _deny(
            "`git clean -fd/-fdx` deletes untracked files (.env, local configs, scratch work).",
            "git clean -nd          # dry run — list what WOULD be deleted, first",
            "git stash -u           # keep untracked work recoverable instead",
        )
    forced_flag = bool(
        re.search(r"git\s+push\b", scan)
        and _FORCE_FLAG.search(scan)
        and "--force-with-lease" not in scan
        and re.search(_branch_re(protected), scan)
    )
    if forced_flag or any(target in protected for target in _forced_refspec_targets(scan)):
        return _deny(
            f"Force-push to a protected branch ({'/'.join(protected)}) rewrites history other worktrees and CI "
            "depend on.",
            "git push origin <feature-branch>        # push your own branch",
            "# open a pull request against the base branch to land it",
            "# Genuinely need to overwrite your OWN feature branch?",
            "git push --force-with-lease origin <feature-branch>",
        )
    if re.search(_SEP + r"git\s+(checkout|restore)\s+(--\s+)?\.\s*($|[;&|])", scan) or re.search(
        _SEP + r"git\s+checkout\s+--force\b", scan
    ):
        return _deny(
            "`git checkout .` / `git restore .` discards every uncommitted change in the tree — including another "
            "agent's in-flight edits.",
            "git status                     # see what would be lost",
            "git stash -u                   # reversible",
            "git restore -- <specific-file> # scope it to the file you mean",
        )
    if re.search(r"git\s+branch\s+[^;&|]*-[dD]\b[^;&|]*" + _branch_re(protected), scan):
        return _deny(
            f"Deleting a protected branch ({'/'.join(protected)}).",
            "# There is no safe variant. Delete a feature branch instead:",
            "git branch -d <feature-branch>",
        )
    if re.search(r"git\s+worktree\s+remove\s+[^;&|]*--force", scan):
        return _deny(
            "the `--force` flag on `git worktree remove` is refused outright (the worktree's state was NOT "
            "inspected — it may well be clean). --force would bypass git's dirty check and could kill a live "
            "worker's checkout.",
            "git worktree remove <path>                  # try without --force first: git refuses only if it is dirty",
            "parrot sdd worktree status                  # see live / dirty / unpushed worktrees",
            "# or use the /remove-worktree command, which gates on all three.",
        )
    if _RM_ROOT.search(scan):
        return _deny(
            "Recursive delete of a root target (/, /*, ~, $HOME).",
            "# Scope the delete to an explicit subdirectory and list it first:",
            "ls <dir> && rm -rf <dir>",
        )
    if _RM_CRITICAL.search(scan):
        return _deny(
            "Recursive delete of a repo-critical path (.venv, .git, .parrot/worktrees, .claude/worktrees).",
            "# .venv:     recreate it with your package manager (for example `uv sync`) instead of deleting by hand",
            "# a worktree: git worktree remove <path>  (see `parrot sdd worktree status` first)",
            "# build artefacts: delete the specific build directory, not a repository root",
        )
    for pattern in _DESTROYERS:
        if pattern in scan:
            return _deny(f"Destructive system command: '{pattern}'")
    found = _windows_destroyer(scan)
    if found:
        return _deny(
            f"Destructive system command: {found}.",
            "# Scope the delete or format to an explicit, non-root directory and list it first.",
        )
    if _SQL_STMT.search(cmd) and _SQL_CLIENT.search(cmd):
        return _deny(
            "Destructive SQL (DROP/TRUNCATE) against a live database.",
            "# Run it against a disposable test database, or write a migration",
            "# the team can review and roll back.",
        )
    if _PUBLISH.search(scan):
        return _deny(
            "Direct package publication. Registries never allow re-uploading a version, so a mistake here is "
            "permanent.",
            "# Publish through your release workflow (CI release job / tagged release), not from a shell.",
        )
    if root is not None and (root / "uv.lock").is_file() and _PIP.search(scan) and not _PIP_OK.search(scan):
        return _deny(
            "Bare `pip install` — this repository is uv-managed; pip writes state uv will not track.",
            "uv pip install <package>",
            "# For a permanent dependency, add it to pyproject.toml:",
            "uv add <package>",
        )
    if _SECRET.search(cmd) and not _PLACEHOLDER.search(cmd):
        return _deny(
            "A literal API key or token appears in this command — it would land in shell history and the "
            "transcript.",
            "# Read it from the environment instead:",
            "export MY_TOKEN=...     # in your own shell, not through the agent",
            '<command> --token "$MY_TOKEN"',
        )
    if re.search(r"git\s+(merge|pull)\b", scan) and root is not None and _worktrees_dir_exists(root):
        if _live_worker():
            return Verdict(
                "warn",
                "A sdd-worker process is live. A merge/pull on a shared branch can check out files over its "
                "uncommitted edits — verify with `git status` before proceeding.",
            )
    return _ALLOW


def _worktrees_dir_exists(root: Path) -> bool:
    """True when the repository's resolved worktree root exists (FEAT-802); never raises."""
    try:
        from parrot.sdd.config import worktree_root  # lazy + guarded, like load_sdd_config above

        return worktree_root(root).is_dir()
    except Exception:  # noqa: BLE001 — a hook must not fail on an optional capability
        return (root / ".parrot" / "worktrees").is_dir()


def _live_worker() -> bool:
    """True when a process whose command line mentions ``sdd-worker`` is running (``psutil`` only; else False)."""
    try:
        import psutil  # type: ignore[import-not-found]

        for proc in psutil.process_iter(["cmdline"]):
            if any("sdd-worker" in part for part in (proc.info.get("cmdline") or [])):
                return True
    except Exception:  # noqa: BLE001 — optional capability
        return False
    return False


# --------------------------------------------------------------------------
# Edit / Write rules
# --------------------------------------------------------------------------

_TEMPLATES = {".env.example", ".env.sample", ".env.template", ".env.dist", ".env.test"}
_SECRET_NAMES = (
    ".env",
    ".env.*",
    "credentials.json",
    "serviceAccountKey.json",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    ".pypirc",
    ".npmrc",
    "secrets.yml",
    "secrets.yaml",
)


def _file_tool(file_path: str) -> Verdict:
    norm = file_path.replace("\\", "/")
    name = PurePosixPath(norm).name
    if name not in _TEMPLATES and any(fnmatch.fnmatchcase(name, p) for p in _SECRET_NAMES):
        return _deny(
            f"Writing to the secrets file '{name}'.",
            "# Secrets are set outside the repo. Document the variable instead:",
            "# add its NAME (never its value) to .env.example or docs/",
        )
    slashed = "/" + norm.lstrip("/")
    if norm.endswith((".pem", ".key")) or "/.ssh/" in slashed:
        return _deny(f"Writing to a credential file: {file_path}")
    if "/.venv/" in slashed:
        return _deny(
            "Writing inside .venv/ — it is generated and will be overwritten.",
            "# Change the dependency instead:",
            "uv add <package>       # then: uv sync",
        )
    if "/node_modules/" in slashed or "/.git/objects/" in slashed:
        return _deny(f"Writing inside a generated/internal directory: {file_path}")
    return _ALLOW


# --------------------------------------------------------------------------
# entry points
# --------------------------------------------------------------------------


def evaluate(payload: dict[str, Any], *, root: Path | None) -> Verdict:
    """Pure decision for one PreToolUse payload. ``PARROT_ALLOW_DANGEROUS=1`` allows everything."""
    if os.environ.get(ESCAPE_ENV) == "1":
        return _ALLOW
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return _ALLOW
    if tool == "Bash":
        cmd = tool_input.get("command")
        if not isinstance(cmd, str) or not cmd:
            return _ALLOW
        return _bash(cmd, root, protected_branches(root))
    if tool in {"Edit", "Write", "MultiEdit"}:
        path = tool_input.get("file_path")
        return _file_tool(path) if isinstance(path, str) and path else _ALLOW
    return _ALLOW


def _render(verdict: Verdict) -> dict[str, Any]:
    if verdict.decision == "deny":
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": verdict.reason,
            }
        }
    if verdict.decision == "warn":
        return {"systemMessage": verdict.reason}
    return {}


def main(argv: Sequence[str] | None = None) -> None:
    """Serve a PreToolUse hook: read the payload on stdin, write one JSON line, always exit 0."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hook", action="store_true", required=True)
    parser.parse_args(argv)
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("payload is not a JSON object")
        root = find_root(payload.get("cwd") or os.getcwd())
        result = _render(evaluate(payload, root=root))
    except Exception as exc:  # noqa: BLE001 — documented fail-open, now visible
        result = {"systemMessage": f"dangerous-actions guard: checks skipped ({type(exc).__name__}: {exc})"}
    sys.stdout.write(json.dumps(result) + "\n")


if __name__ == "__main__":
    main()
