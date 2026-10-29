"""Compile the strict Claude Code native sandbox policy for SDD sessions (FEAT-768).

Standard library only: the SDD PreToolUse hook imports this module as a script sibling.
"""

from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sys
from typing import Any, Sequence
import uuid

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
    cache_root = (
        _canonical(Path(configured)) if configured else scratch_root / "parrot-sdd-cache" / f"shared-{os.getuid()}"
    )
    if not _is_within(cache_root, scratch_root):
        cache_root = scratch_root / "parrot-sdd-cache" / f"shared-{os.getuid()}"
    env["XDG_CACHE_HOME"] = str(cache_root / "xdg")
    env["UV_CACHE_DIR"] = str(cache_root / "uv")
    return env


_REJECTED_OPTIONS = ("--settings", "--add-dir")
_DEFAULT_MODEL = "sonnet"


def _option_value(argv: Sequence[str], index: int, option: str) -> tuple[str, int]:
    """Return a split option value and the index after it.

    Args:
        argv: Launcher arguments.
        index: Index of ``option``.
        option: Option whose value is required.

    Returns:
        The option value and next unconsumed argument index.

    Raises:
        ValueError: If the option has no value.
    """
    if index + 1 >= len(argv) or not argv[index + 1] or argv[index + 1].startswith("--"):
        raise ValueError(f"{option} requires a value")
    return argv[index + 1], index + 2


def _parse_launch_arguments(argv: Sequence[str]) -> tuple[list[str], list[str], bool, bool]:
    """Validate launcher arguments and separate policy-only domain grants.

    Args:
        argv: Arguments intended for Claude Code.

    Returns:
        Allowed domains, forwarded arguments, model presence and setting-source presence.

    Raises:
        ValueError: If an argument attempts to override launcher policy.
    """
    domains: list[str] = []
    forwarded: list[str] = []
    has_model = False
    has_sources = False
    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument == "--":
            forwarded.extend(argv[index:])
            break
        if argument == "--sandbox-allow-domain":
            domain, index = _option_value(argv, index, argument)
            domains.append(domain)
            continue
        if argument.startswith("--sandbox-allow-domain="):
            domain = argument.partition("=")[2]
            if not domain:
                raise ValueError("--sandbox-allow-domain requires a value")
            domains.append(domain)
            index += 1
            continue
        if any(argument == option or argument.startswith(f"{option}=") for option in _REJECTED_OPTIONS):
            raise ValueError(f"{argument.split('=', 1)[0]} is controlled by the native launcher")
        if argument == "--agent":
            agent, index = _option_value(argv, index, argument)
            if agent != "sdd-worker":
                raise ValueError("--agent must be sdd-worker")
            continue
        if argument.startswith("--agent="):
            if argument.partition("=")[2] != "sdd-worker":
                raise ValueError("--agent must be sdd-worker")
            index += 1
            continue
        if argument == "--setting-sources":
            sources, next_index = _option_value(argv, index, argument)
            if any(source.strip() == "user" for source in sources.split(",")):
                raise ValueError("--setting-sources must not include user")
            has_sources = True
            forwarded.extend((argument, sources))
            index = next_index
            continue
        if argument.startswith("--setting-sources="):
            sources = argument.partition("=")[2]
            if not sources:
                raise ValueError("--setting-sources requires a value")
            if any(source.strip() == "user" for source in sources.split(",")):
                raise ValueError("--setting-sources must not include user")
            has_sources = True
        if argument == "--model":
            model, next_index = _option_value(argv, index, argument)
            has_model = True
            forwarded.extend((argument, model))
            index = next_index
            continue
        if argument.startswith("--model="):
            if not argument.partition("=")[2]:
                raise ValueError("--model requires a value")
            has_model = True
        forwarded.append(argument)
        index += 1
    return domains, forwarded, has_model, has_sources


def _process_is_alive(pid: int) -> bool:
    """Return whether a process exists or cannot safely be inspected."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _allocate_session_cache() -> Path:
    """Remove dead launcher-owned caches and allocate one for this process."""
    cache_root = _we.claude_scratch_root() / "parrot-sdd-cache"
    cache_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    for candidate in cache_root.iterdir():
        owner_file = candidate / "owner.pid"
        if candidate.is_symlink() or not candidate.is_dir() or not owner_file.is_file():
            continue
        try:
            cache_id = uuid.UUID(candidate.name)
            owner_pid = int(owner_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            continue
        if cache_id.version != 4 or str(cache_id) != candidate.name:
            continue
        if owner_pid > 0 and not _process_is_alive(owner_pid):
            try:
                shutil.rmtree(candidate)
            except FileNotFoundError:
                pass
    session_cache = cache_root / str(uuid.uuid4())
    session_cache.mkdir(mode=0o700)
    (session_cache / "owner.pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
    return session_cache


def launch_worker(argv: Sequence[str]) -> int:
    """Launch sdd-worker with strict settings; return policy or host errors."""
    try:
        domains, forwarded, has_model, has_sources = _parse_launch_arguments(argv)
        settings = native_sandbox_settings(Path.cwd(), allowed_domains=domains)
    except ValueError as exc:
        print(f"launch_worker: {exc}", file=sys.stderr)
        return 2
    missing = [name for name in ("claude", "bwrap", "socat") if shutil.which(name) is None]
    if missing:
        print(f"launch_worker: missing host prerequisite(s): {', '.join(missing)}", file=sys.stderr)
        return 1
    env = dict(os.environ)
    env[BACKEND_ENV] = BACKEND_NATIVE
    env[CACHE_DIR_ENV] = str(_allocate_session_cache())
    command = [shutil.which("claude") or "claude", "--agent", "sdd-worker"]
    if not has_sources:
        command += ["--setting-sources", "project,local"]
    if not has_model:
        command += ["--model", _DEFAULT_MODEL]
    command += ["--settings", json.dumps(settings), *forwarded]
    os.execvpe(command[0], command, env)
    return 1


def main() -> None:
    """Serve the launch-worker subcommand, forwarding the child exit status."""
    if len(sys.argv) < 2 or sys.argv[1] != "launch-worker":
        print("usage: native_claude_sandbox.py launch-worker [args...]", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(launch_worker(sys.argv[2:]))


if __name__ == "__main__":
    main()
