"""Compile the strict Claude Code native sandbox policy for SDD sessions (FEAT-768).

Standard library only: the SDD PreToolUse hook imports this module as a script sibling.
"""

from __future__ import annotations

import ipaddress
import os
from pathlib import Path
import re
import shlex
from typing import Any, Sequence

if __package__:
    from . import worktree_environment as _we
else:  # run as a script: this file's directory is sys.path[0]
    import worktree_environment as _we

BACKEND_ENV = "PARROT_SDD_SANDBOX_BACKEND"
BACKEND_NATIVE = "claude-native"
BACKEND_BUBBLEWRAP = "bubblewrap"
CACHE_DIR_ENV = "PARROT_SDD_CACHE_DIR"
_HOSTNAME_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_CD_PREFIX = re.compile(r"^\s*cd\s+(?P<target>\S+)\s*&&\s*(?P<rest>.+)$", re.DOTALL)


def _canonical(path: Path) -> Path:
    """Return a stable absolute representation without requiring existence."""
    return Path(os.path.abspath(path)).resolve(strict=False)


def _is_within(path: Path, root: Path) -> bool:
    """Return whether ``path`` is ``root`` or is contained by it."""
    return path == root or path.is_relative_to(root)


def validate_allowed_domains(domains: Sequence[str]) -> list[str]:
    """Normalize exact DNS hostnames and reject broader network grants.

    Args:
        domains: Candidate DNS hostnames.

    Returns:
        Lowercase, deduplicated hostnames.

    Raises:
        ValueError: If a value is not an exact DNS hostname.
    """
    normalized: list[str] = []
    for raw in domains:
        if not isinstance(raw, str) or any(token in raw for token in ("://", "/", "*", ":")):
            raise ValueError(f"Invalid allowed domain: {raw!r}")
        host = raw.lower().removesuffix(".")
        if not host:
            raise ValueError("Allowed domains must not be empty")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError(f"IP literals are not allowed domains: {raw!r}")
        if any(not label or _HOSTNAME_LABEL.fullmatch(label) is None for label in host.split(".")):
            raise ValueError(f"Invalid allowed domain: {raw!r}")
        if host not in normalized:
            normalized.append(host)
    return normalized


def _worktree_admin_dir(root: Path) -> Path:
    """Resolve the linked worktree's Git administration directory.

    Args:
        root: Linked worktree root.

    Returns:
        The administration directory named by its ``.git`` marker.

    Raises:
        ValueError: If the marker is absent or malformed.
    """
    marker = root / ".git"
    if not marker.is_file():
        raise ValueError("Native sandbox requires a linked Git worktree")
    content = marker.read_text(encoding="utf-8").strip()
    if not content.startswith("gitdir: "):
        raise ValueError(f"Invalid Git worktree marker: {marker}")
    admin_dir = _canonical(root / content.removeprefix("gitdir: "))
    if not admin_dir.is_dir():
        raise ValueError("Native sandbox requires an existing worktree administration directory")
    return admin_dir


def _native_roots(cwd: Path) -> tuple[Path, Path, Path]:
    """Return linked-worktree, common-Git and primary-checkout roots.

    Args:
        cwd: A path inside the proposed linked worktree.

    Returns:
        The worktree root, common Git directory and primary checkout.

    Raises:
        ValueError: If ``cwd`` is not a valid linked worktree.
    """
    root, git_dir = _we.repository_paths(cwd)
    if git_dir is None:
        raise ValueError("Native sandbox requires a Git worktree")
    root = _canonical(root)
    git_dir = _canonical(git_dir)
    primary = git_dir.parent
    if primary == root:
        raise ValueError("Native sandbox cannot run from the primary checkout")
    admin_dir = _worktree_admin_dir(root)
    common = admin_dir / "commondir"
    if not common.is_file():
        raise ValueError("Native sandbox requires valid linked-worktree Git metadata")
    if _canonical(admin_dir / common.read_text(encoding="utf-8").strip()) != git_dir:
        raise ValueError("Linked worktree does not resolve to its common Git directory")
    return root, git_dir, primary


def _rtk_data_dir() -> Path:
    """Return RTK's data directory without importing RTK."""
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "rtk"


def _denied_write_paths(root: Path, git_dir: Path) -> list[str]:
    """Return canonical paths that remain read-only under native policy."""
    admin_dir = _worktree_admin_dir(root)
    paths = [
        *_we.shared_environments(root),
        _rtk_data_dir(),
        git_dir / "hooks",
        git_dir / "config",
        git_dir / "config.lock",
        admin_dir / "config.worktree",
        admin_dir / "hooks",
    ]
    denied: list[str] = []
    for path in paths:
        canonical = str(_canonical(path))
        if canonical not in denied:
            denied.append(canonical)
    return denied


def native_sandbox_settings(cwd: Path, *, allowed_domains: Sequence[str] = ()) -> dict[str, Any]:
    """Build strict CLI settings including hooks.

    Args:
        cwd: A path in the linked worktree.
        allowed_domains: Exact DNS hostnames permitted for network egress.

    Returns:
        The complete native Claude sandbox settings object.
    """
    domains = validate_allowed_domains(allowed_domains)
    root, git_dir, _primary = _native_roots(cwd)
    allow_paths = [root, git_dir, _we.claude_scratch_root(), *_we.worktree_admin_dirs(root, git_dir)]
    allow_paths.extend(_we.shared_ledger_dirs(root, git_dir))
    allow_write: list[str] = []
    for path in allow_paths:
        canonical = str(_canonical(path))
        if canonical not in allow_write:
            allow_write.append(canonical)
    hook_command = shlex.join(["python3", str(Path(_we.__file__).resolve()), "--hook"]) + " || exit 2"
    return {
        "sandbox": {
            "enabled": True,
            "failIfUnavailable": True,
            "allowUnsandboxedCommands": False,
            "excludedCommands": [],
            "allowNestedUserNamespaces": False,
            "network": {"allowAllUnixSockets": False, "allowedDomains": domains},
            "filesystem": {"allowWrite": allow_write, "denyWrite": _denied_write_paths(root, git_dir)},
        },
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash|Write|Edit|MultiEdit|NotebookEdit",
                    "hooks": [{"type": "command", "command": hook_command, "timeout": 10}],
                }
            ]
        },
    }


def _control_path(root: Path, target: Path) -> bool:
    """Return whether a target is a native-policy or hook control file."""
    controls = root / "packages" / "ai-parrot" / "src" / "parrot" / "flows" / "dev_loop"
    if target in {controls / "native_claude_sandbox.py", controls / "worktree_environment.py"}:
        return True
    claude_dir = root / ".claude"
    if target.parent == claude_dir and target.name.startswith("settings") and target.suffix == ".json":
        return True
    agents_dir = claude_dir / "agents"
    return target.suffix == ".md" and _is_within(target, agents_dir)


def validate_native_write_path(cwd: Path, path: Path) -> None:
    """Reject paths outside native allowances or in protected control areas.

    Args:
        cwd: A path in the linked worktree.
        path: Requested write destination.

    Raises:
        ValueError: If the destination is not permitted.
    """
    root, git_dir, _primary = _native_roots(cwd)
    target = _canonical(path)
    _we.validate_write_path(cwd, path)
    denied = [Path(value) for value in _denied_write_paths(root, git_dir)]
    if any(_is_within(target, item) for item in denied) or _control_path(root, target):
        raise ValueError("Native sandbox policy forbids writes to protected paths")
    settings = native_sandbox_settings(root)
    allowed = [Path(value) for value in settings["sandbox"]["filesystem"]["allowWrite"]]
    if not any(_is_within(target, item) for item in allowed):
        raise ValueError("Native sandbox policy forbids writes outside allowed roots")


def native_task_cwd(session_cwd: Path, command: str) -> Path:
    """Resolve an exact leading task-worktree ``cd`` prefix.

    Args:
        session_cwd: The session's linked-worktree directory.
        command: A shell command from the native hook payload.

    Returns:
        The task worktree for a valid prefix, otherwise ``session_cwd``.

    Raises:
        ValueError: If a leading ``cd`` is malformed or targets a disallowed path.
    """
    match = _CD_PREFIX.match(command)
    if match is None:
        if command.lstrip().startswith("cd "):
            raise ValueError("A leading cd must have the exact form 'cd <absolute path> && <command>'")
        return session_cwd
    target_text = match.group("target")
    if any(character in target_text for character in ("'", '"', "$", "`", "~", "*")):
        raise ValueError("Native task cwd must be an unquoted, literal absolute path")
    try:
        tokens = shlex.split(target_text)
    except ValueError as exc:
        raise ValueError("Invalid native task cwd prefix") from exc
    if len(tokens) != 1 or not Path(tokens[0]).is_absolute():
        raise ValueError("Native task cwd must be an absolute path")
    session_root, _session_git, session_primary = _native_roots(session_cwd)
    target_root, target_git, target_primary = _native_roots(Path(tokens[0]))
    if target_primary != session_primary:
        raise ValueError("Native task cwd must belong to the session primary checkout")
    permitted_roots = (session_root, *_we.worktree_admin_dirs(session_root, target_git))
    if not any(_is_within(target_root, _canonical(item)) for item in permitted_roots):
        raise ValueError("Native task cwd is outside the allowed worktree roots")
    return target_root


def native_command_environment(cwd: Path) -> dict[str, str]:
    """Return task-cwd import, cache and safety overrides without mutation.

    Args:
        cwd: A path in the linked worktree.

    Returns:
        Environment variables for native child commands.
    """
    root, _git_dir, _primary = _native_roots(cwd)
    env = {"UV_NO_SYNC": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    source_roots = sorted((root / "packages").glob("*/src"))
    if source_roots:
        python_path = os.pathsep.join(map(str, source_roots))
        if inherited := os.environ.get("PYTHONPATH"):
            python_path += os.pathsep + inherited
        env["PYTHONPATH"] = python_path
    scratch_root = _we.claude_scratch_root()
    configured = os.environ.get(CACHE_DIR_ENV)
    cache_root = _canonical(Path(configured)) if configured else scratch_root / "parrot-sdd-cache" / f"shared-{os.getuid()}"
    if not _is_within(cache_root, scratch_root):
        cache_root = scratch_root / "parrot-sdd-cache" / f"shared-{os.getuid()}"
    env["XDG_CACHE_HOME"] = str(cache_root / "xdg")
    env["UV_CACHE_DIR"] = str(cache_root / "uv")
    return env
