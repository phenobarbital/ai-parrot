"""Stdlib-only launch-time venv resolution for parrot console scripts (FEAT-633 M1).

HARD RULE: import nothing but the standard library here — this module fronts every
``wikitoolkit claude-hook`` call. Enforced by tests/launcher/test_launcher_stdlib_only.py (TASK-4072).
"""
from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

PARROT_HOME_ENV = "PARROT_HOME"            # existing convention: knowledge/wiki/project.py:1382
PARROT_VENV_ENV = "PARROT_VENV"            # new explicit override
PARROT_PROJECT_ENV = "PARROT_PROJECT"      # new project-root pin
LOOP_GUARD_ENV = "PARROT_LAUNCHER_RESOLVED"
MANAGED_PYTHON = "3.12"                    # owner decision (spec §8)
_DEFAULT_HOME = "~/.parrot"
_WARNED: set[str] = set()                  # warn-once-per-process registry (keys: "project:<venv>", "PARROT_VENV")


def parrot_home(env: Mapping[str, str] | None = None) -> Path:
    """``$PARROT_HOME`` or ``~/.parrot``, ``~``-expanded, NOT resolved; read on every call."""
    source = os.environ if env is None else env
    return Path(source.get(PARROT_HOME_ENV) or _DEFAULT_HOME).expanduser()


def is_managed(prefix: str | None = None, *, env: Mapping[str, str] | None = None) -> bool:
    """True iff ``prefix`` (default ``sys.prefix``) is inside ``parrot_home()/'venv'`` (realpaths)."""
    managed = os.path.realpath(parrot_home(env) / "venv")
    current = os.path.realpath(prefix if prefix is not None else sys.prefix)
    return current == managed or current.startswith(managed + os.sep)


def _is_temp_root(candidate: Path) -> bool:
    """True when ``candidate`` is the system temp dir or one of its ancestors (rev 0.5 C24).

    Mirrors ``wiki.project._is_temp_root`` (project.py:1011-1031); the ``.git`` walk-ups stop there.
    """
    try:
        temp_root = Path(tempfile.gettempdir()).resolve()
    except (OSError, RuntimeError):
        return False
    return candidate == temp_root or candidate in temp_root.parents


def _existing_directory(path: Path) -> Path:
    """Port of worktree_environment.existing_directory (:27): nearest existing ancestor, resolved."""
    candidate = Path(os.path.abspath(path))
    for parent in (candidate, *candidate.parents):
        if parent.is_dir():
            return parent.resolve()
    return Path(candidate.anchor or os.sep)


def repository_paths(cwd: Path) -> tuple[Path, Path | None]:
    """(repo_root, common_git_dir_or_None). Port of worktree_environment.py:53-71.

    Deviation: a malformed ``.git`` file yields ``(cwd, None)`` instead of raising.
    The walk stops at ``_is_temp_root`` (rev 0.5 C24) → ``(cwd, None)``.
    The main checkout of a linked worktree is ``common_git_dir.parent``.
    """
    cwd = _existing_directory(cwd)
    for root in (cwd, *cwd.parents):
        if _is_temp_root(root):
            break
        marker = root / ".git"
        try:
            if marker.is_dir():
                return root, marker.resolve()
            if marker.is_file():
                content = marker.read_text(encoding="utf-8").strip()
                if not content.startswith("gitdir: "):
                    return cwd, None
                git_dir = Path(os.path.abspath(root / content.removeprefix("gitdir: ")))
                common = git_dir / "commondir"
                if common.is_file():
                    git_dir = Path(os.path.abspath(git_dir / common.read_text(encoding="utf-8").strip()))
                return root, git_dir.resolve() if git_dir.is_dir() else None
        except (OSError, UnicodeDecodeError):
            return cwd, None
    return cwd, None


def find_project_root(argv: Sequence[str], env: Mapping[str, str], cwd: Path) -> Path | None:
    """Leading ``--project <p>``/``--project=<p>`` → PARROT_PROJECT → CLAUDE_PROJECT_DIR → walk-up to ``.git``."""
    pinned: list[str] = []
    if argv:
        first = argv[0]
        if first == "--project" and len(argv) > 1:
            pinned.append(argv[1])
        elif first.startswith("--project="):
            pinned.append(first.split("=", 1)[1])
    pinned.extend(v for v in (env.get(PARROT_PROJECT_ENV), env.get("CLAUDE_PROJECT_DIR")) if v)
    for value in pinned:
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = cwd / candidate
        try:
            if candidate.is_dir():
                return candidate.resolve()
        except OSError:
            continue
    try:
        current = _existing_directory(cwd)
        for candidate in (current, *current.parents):
            if _is_temp_root(candidate):
                break
            if (candidate / ".git").exists():
                return candidate
    except OSError:
        return None
    return None


def script_path(venv: Path, name: str, *, os_name: str | None = None) -> Path:
    """``venv/bin/<name>`` on POSIX; ``venv/Scripts/<name>.exe`` on Windows."""
    if (os_name or os.name) == "nt":
        return venv / "Scripts" / f"{name}.exe"
    return venv / "bin" / name


def _warn_once(key: str, message: str) -> None:
    """Write ``message`` to stderr at most once per process for ``key``."""
    if key in _WARNED:
        return
    _WARNED.add(key)
    sys.stderr.write(f"parrot: {message}\n")


def resolve_venv(script: str, *, argv: Sequence[str], env: Mapping[str, str], cwd: Path) -> tuple[Path, str]:
    """Return ``(venv, rule)``; rule ∈ {'PARROT_VENV','project','VIRTUAL_ENV','managed'}.

    A candidate is valid iff it has ``pyvenv.cfg`` and ``script_path(venv, script)`` exists and it
    is not the managed venv itself. A project ``.venv`` lacking the script warns once (stderr) and
    is skipped. Never raises: any OSError while probing a candidate skips that candidate.
    """
    managed = parrot_home(env) / "venv"
    managed_real = os.path.realpath(managed)
    candidates: list[tuple[Path, str]] = []
    explicit = env.get(PARROT_VENV_ENV)
    if explicit:
        candidates.append((Path(explicit).expanduser(), "PARROT_VENV"))
    root = find_project_root(argv, env, cwd)
    if root is not None:
        candidates.append((root / ".venv", "project"))
        common = repository_paths(root)[1]
        if common is not None and common.parent != root:
            candidates.append((common.parent / ".venv", "project"))
    if env.get("VIRTUAL_ENV"):
        candidates.append((Path(env["VIRTUAL_ENV"]).expanduser(), "VIRTUAL_ENV"))
    for venv, rule in candidates:
        try:
            if os.path.realpath(venv) == managed_real:
                continue
            valid = (venv / "pyvenv.cfg").is_file() and script_path(venv, script).exists()
            exists = venv.is_dir()
        except OSError:
            continue
        if valid:
            return venv, rule
        if rule == "PARROT_VENV":
            _warn_once("PARROT_VENV", f"PARROT_VENV={venv} is not a venv providing '{script}'; ignoring it")
        elif rule == "project" and exists:
            _warn_once(f"project:{venv}", f"project venv {venv} has no '{script}'; using the next candidate instead")
    return managed, "managed"
