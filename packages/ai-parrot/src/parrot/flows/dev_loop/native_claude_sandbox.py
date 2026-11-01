"""Compile the strict Claude Code native sandbox policy for SDD sessions (FEAT-768).

Standard library only: the SDD PreToolUse hook imports this module as a script sibling.
"""

from __future__ import annotations

import getpass
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time
import tomllib
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
ROOTS_ENV = "PARROT_SDD_SANDBOX_ROOTS"  # root, common git dir, primary checkout — frozen at launch
MODE_ENV = "PARROT_SDD_SANDBOX_MODE"
DEGRADED_ENV = "PARROT_SDD_SANDBOX_DEGRADED"
SANDBOX_MODES = ("required", "preferred", "off", "legacy")
_HOSTNAME_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_NUMERIC_LABEL = re.compile(r"^(0x[0-9a-f]+|[0-9]+)$")
_CD_PREFIX = re.compile(r"^\s*cd\s+(?P<target>\S+)\s*&&\s*(?P<rest>.+)$", re.DOTALL)


def sandbox_platform() -> str:
    """Return the supported native-sandbox platform for this interpreter."""
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform in {"win32", "cygwin"}:
        return "windows"
    return "unsupported"


def _user_tag() -> str:
    """Return a filesystem-safe identifier for the current user."""
    if hasattr(os, "getuid"):
        return str(os.getuid())
    try:
        username = getpass.getuser()
    except (KeyError, OSError):
        username = ""
    return re.sub(r"[^A-Za-z0-9_.-]", "", username) or "user"


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
        labels = host.split(".")
        if any(not label or _HOSTNAME_LABEL.fullmatch(label) is None for label in labels):
            raise ValueError(f"Invalid allowed domain: {raw!r}")
        # inet_aton-style forms (``127.1``, ``2130706433``, ``0x7f.1``) parse as addresses for libc even
        # though ``ipaddress`` rejects them, and a TLD is never numeric; single labels are not DNS names.
        if len(labels) < 2 or _NUMERIC_LABEL.fullmatch(labels[-1]) is not None:
            raise ValueError(f"Allowed domains must be qualified DNS hostnames, not addresses: {raw!r}")
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
    frozen = _frozen_roots(cwd)
    if frozen is not None:
        return frozen
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


def _frozen_roots(cwd: Path) -> tuple[Path, Path, Path] | None:
    """Return the roots the launcher froze in :data:`ROOTS_ENV` when ``cwd`` lies inside them.

    The worktree's ``.git`` marker is writable by the session; re-deriving the policy roots from it on
    every hook call would let a forged marker steer the hook. The launcher/dispatcher therefore pins the
    three roots in the child environment; a cwd outside the frozen root (a pool sub-worktree) still
    derives its own roots, exactly as before.
    """
    raw = os.environ.get(ROOTS_ENV, "")
    parts = raw.split(os.pathsep) if raw else []
    if len(parts) != 3 or not all(parts):
        return None
    root, git_dir, primary = (Path(part) for part in parts)
    if not _is_within(_canonical(cwd), root):
        return None
    return root, git_dir, primary


def native_root_env(cwd: Path) -> dict[str, str]:
    """Return the :data:`ROOTS_ENV` entry that freezes ``cwd``'s policy roots for a child session."""
    root, git_dir, primary = _native_roots(cwd)
    return {ROOTS_ENV: os.pathsep.join((str(root), str(git_dir), str(primary)))}


def _rtk_data_dir() -> Path:
    """Return RTK's data directory without importing RTK."""
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "rtk"


def _denied_write_paths(root: Path, git_dir: Path) -> list[str]:
    """Return canonical paths that remain read-only under native policy."""
    admin_dir = _worktree_admin_dir(root)
    controls = root / "packages" / "ai-parrot" / "src" / "parrot" / "flows" / "dev_loop"
    paths = [
        *_we.shared_environments(root),
        _rtk_data_dir(),
        # Policy/hook control files: the hook only guards file tools, so Bash needs the OS deny too.
        controls / "native_claude_sandbox.py",
        controls / "worktree_environment.py",
        root / ".claude" / "settings.json",
        root / ".claude" / "settings.local.json",
        root / ".claude" / "agents",
        git_dir / "hooks",
        git_dir / "config",
        git_dir / "config.lock",
        admin_dir / "config.worktree",
        admin_dir / "hooks",
    ]
    # Other linked worktrees' administration directories: the common Git directory is writable so this
    # worktree can commit, but a sibling's config.worktree/hooks/HEAD are not this session's business.
    worktrees_dir = git_dir / "worktrees"
    if worktrees_dir.is_dir():
        paths.extend(sorted(entry for entry in worktrees_dir.iterdir() if _canonical(entry) != admin_dir))
    denied: list[str] = []
    for path in paths:
        canonical = str(_canonical(path))
        if canonical not in denied:
            denied.append(canonical)
    return denied


def resolve_sandbox_mode(repo_root: Path) -> str:
    """Resolve the native sandbox transition mode for a repository.

    Args:
        repo_root: Linked worktree root containing the repository configuration.

    Returns:
        One of :data:`SANDBOX_MODES`.

    Raises:
        ValueError: If an environment or project value is malformed.
    """
    environment_value = (os.environ.get(MODE_ENV) or "").strip().lower()
    if environment_value:
        mode = environment_value
        source = MODE_ENV
    else:
        config_path = repo_root / "pyproject.toml"
        mode = "required"
        source = "default"
        if config_path.is_file():
            try:
                with config_path.open("rb") as handle:
                    configuration = tomllib.load(handle)
            except (OSError, ValueError) as exc:  # TOMLDecodeError and UnicodeDecodeError are ValueErrors
                raise ValueError(
                    f"Invalid sandbox mode in {config_path}: unreadable or malformed TOML ({exc})"
                ) from exc
            configured: Any = configuration
            seen = ""
            for table in ("tool", "parrot", "sdd"):
                if not isinstance(configured, dict):
                    raise ValueError(f"Invalid sandbox mode in {config_path}: [{seen}] is not a table")
                configured = configured.get(table)
                seen = f"{seen}.{table}" if seen else table
                if configured is None:
                    break
            if isinstance(configured, dict):
                configured = configured.get("sandbox")
            if configured is not None:
                if not isinstance(configured, str):
                    raise ValueError(f"Invalid sandbox mode in {config_path}: {configured!r}")
                mode = configured.strip().lower()
                source = str(config_path)
                if mode in ("off", "legacy"):
                    # The worktree's pyproject is writable by the sandboxed session itself; letting it
                    # weaken the boundary would be a self-disable path. Only the operator's
                    # environment may select "off" or "legacy"; a repository may go as far as "preferred".
                    raise ValueError(
                        f"Invalid sandbox mode in {config_path}: '{mode}' may only be set through {MODE_ENV}"
                    )
    if mode not in SANDBOX_MODES:
        raise ValueError(f"Invalid sandbox mode from {source}: {mode!r}")
    return mode


_PROBE_TTL_SECONDS = 60.0
_probe_cache: tuple[float, bool, str] | None = None


def _bwrap_probe(executable: str) -> tuple[bool, str]:
    """Probe whether Bubblewrap can create the namespaces needed by a sandbox.

    Args:
        executable: Resolved path to the Bubblewrap executable.

    Returns:
        Whether Bubblewrap is usable and a human-readable failure reason.
    """
    try:
        probe = subprocess.run(
            [executable, "--unshare-user", "--unshare-pid", "--ro-bind", "/", "/", "true"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "bwrap probe timed out"
    if probe.returncode:
        return False, next((line for line in probe.stderr.splitlines() if line.strip()), "bwrap probe failed")
    return True, ""


def native_sandbox_available() -> tuple[bool, str]:
    """Probe whether the native Claude sandbox can start on this host.

    The probe is a weaker proxy than Claude's own runtime (user and PID namespaces plus a read-only
    root bind, no network namespace); a false positive still fails closed because the compiled
    settings carry ``failIfUnavailable``. The result is cached for :data:`_PROBE_TTL_SECONDS` so a
    long-lived dispatcher does not block on ``bwrap`` for every launch.

    Returns:
        Whether the sandbox is available and a human-readable failure reason.
    """
    global _probe_cache
    now = time.monotonic()
    if _probe_cache is not None and now - _probe_cache[0] < _PROBE_TTL_SECONDS:
        return _probe_cache[1], _probe_cache[2]
    platform = sandbox_platform()
    if platform == "linux":
        executables = {name: shutil.which(name) for name in ("bwrap", "socat")}
        missing = [name for name, executable in executables.items() if executable is None]
        if missing:
            outcome = (False, f"missing prerequisite(s): {', '.join(missing)}")
        else:
            outcome = _bwrap_probe(executables["bwrap"] or "bwrap")
    elif platform == "macos":
        executable = shutil.which("sandbox-exec")
        if executable is None:
            outcome = (False, "missing prerequisite(s): sandbox-exec")
        else:
            try:
                probe = subprocess.run(
                    [executable, "-p", "(version 1)(allow default)", "/usr/bin/true"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                outcome = (False, "sandbox-exec probe timed out")
            else:
                if probe.returncode:
                    outcome = (
                        False,
                        next((line for line in probe.stderr.splitlines() if line.strip()), "sandbox-exec probe failed"),
                    )
                else:
                    outcome = (True, "")
    elif platform == "windows":
        outcome = (
            False,
            "native Windows has no Claude Code sandbox; run the worker inside WSL2, or set "
            "PARROT_SDD_SANDBOX_MODE=preferred for a degraded (hook-only) launch",
        )
    else:
        outcome = (False, f"unsupported platform {sys.platform!r} for the native sandbox")
    _probe_cache = (now, outcome[0], outcome[1])
    return outcome


def native_sandbox_settings(
    cwd: Path, *, allowed_domains: Sequence[str] = (), include_sandbox: bool = True
) -> dict[str, Any]:
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
    hook_command = shlex.join([sys.executable, str(Path(_we.__file__).resolve()), "--hook"]) + " || exit 2"
    settings: dict[str, Any] = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash|Write|Edit|MultiEdit|NotebookEdit",
                    "hooks": [{"type": "command", "command": hook_command, "timeout": 10}],
                }
            ]
        }
    }
    if include_sandbox:
        settings["sandbox"] = {
            "enabled": True,
            "failIfUnavailable": True,
            "allowUnsandboxedCommands": False,
            "excludedCommands": [],
            "allowNestedUserNamespaces": False,
            "network": {"allowAllUnixSockets": False, "strictAllowlist": True, "allowedDomains": domains},
            "filesystem": {"allowWrite": allow_write, "denyWrite": _denied_write_paths(root, git_dir)},
        }
    return settings


def plan_native_launch(cwd: Path, *, allowed_domains: Sequence[str] = ()) -> tuple[str, bool, str, dict[str, Any]]:
    """Resolve native-sandbox policy and settings for one Claude launch.

    Args:
        cwd: A path inside the linked worktree to launch from.
        allowed_domains: Exact DNS hostnames permitted for network egress.

    Returns:
        Mode, degraded flag, reason, and the corresponding Claude settings.

    Raises:
        ValueError: If the mode or working tree is invalid.
        RuntimeError: If required sandboxing cannot be started.
    """
    root, _git_dir, _primary = _native_roots(cwd)
    mode = resolve_sandbox_mode(root)
    if mode == "off":
        return (
            mode,
            True,
            "sandbox mode off",
            native_sandbox_settings(cwd, allowed_domains=allowed_domains, include_sandbox=False),
        )
    if mode == "legacy":
        if sandbox_platform() != "linux":
            raise RuntimeError(f"legacy mode needs Linux Bubblewrap; not available on {sandbox_platform()}")
        executable = shutil.which("bwrap")
        if executable is None:
            raise RuntimeError("legacy mode needs a working Bubblewrap: missing prerequisite(s): bwrap")
        available, reason = _bwrap_probe(executable)
        if not available:
            raise RuntimeError(f"legacy mode needs a working Bubblewrap: {reason}")
        return mode, False, "", native_sandbox_settings(cwd, include_sandbox=False)
    available, reason = native_sandbox_available()
    if not available:
        if mode == "required":
            raise RuntimeError(reason)
        return mode, True, reason, native_sandbox_settings(cwd, allowed_domains=allowed_domains, include_sandbox=False)
    return mode, False, "", native_sandbox_settings(cwd, allowed_domains=allowed_domains)


def launch_backend(mode: str) -> str:
    """Return the retained hook backend selected by a sandbox mode.

    Args:
        mode: Resolved native sandbox mode.

    Returns:
        Bubblewrap for legacy mode, otherwise the native backend.
    """
    return BACKEND_BUBBLEWRAP if mode == "legacy" else BACKEND_NATIVE


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
        _canonical(Path(configured)) if configured else scratch_root / "parrot-sdd-cache" / f"shared-{_user_tag()}"
    )
    if not _is_within(cache_root, scratch_root):
        cache_root = scratch_root / "parrot-sdd-cache" / f"shared-{_user_tag()}"
    env["XDG_CACHE_HOME"] = str(cache_root / "xdg")
    env["UV_CACHE_DIR"] = str(cache_root / "uv")
    return env


_REJECTED_OPTIONS = (
    "--settings",
    "--add-dir",
    "--dangerously-skip-permissions",
    "--plugin-dir",
    "--mcp-config",
    "--agents",
)
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


def launch_worker(argv: Sequence[str], *, cwd: Path | None = None, initial_prompt: str | None = None) -> int:
    """Launch sdd-worker with strict settings; return policy or host errors.

    Args:
        argv: Arguments forwarded to Claude after launcher-owned options.
        cwd: Worktree in which Claude must start. Defaults to the current directory.
        initial_prompt: Optional final Claude argument, normally the worker trigger.
    """
    cwd = cwd or Path.cwd()
    try:
        domains, forwarded, has_model, has_sources = _parse_launch_arguments(argv)
    except ValueError as exc:
        print(f"launch_worker: {exc}", file=sys.stderr)
        return 2
    claude = shutil.which("claude")
    if claude is None:
        print("launch_worker: missing host prerequisite(s): claude", file=sys.stderr)
        return 1
    try:
        mode = resolve_sandbox_mode(_native_roots(cwd)[0])
        mode, degraded, reason, settings = plan_native_launch(cwd, allowed_domains=domains)
    except ValueError as exc:
        print(f"launch_worker: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"launch_worker: native sandbox unavailable ({exc}); mode={mode} refuses to start", file=sys.stderr)
        return 1
    env = dict(os.environ)
    env[BACKEND_ENV] = launch_backend(mode)
    env.update(native_root_env(cwd))
    if mode == "legacy":
        ignored_domains = "; --sandbox-allow-domain ignored" if domains else ""
        print(
            "launch_worker: mode=legacy — native sandbox disabled, Bash runs in the hook's Bubblewrap "
            f"(filesystem only, no network isolation){ignored_domains}",
            file=sys.stderr,
        )
        env.pop(DEGRADED_ENV, None)
    elif degraded:
        print(
            f"launch_worker: WARNING native sandbox unavailable ({reason}); mode={mode} launches DEGRADED "
            "(hook only, no OS write boundary)",
            file=sys.stderr,
        )
        env[DEGRADED_ENV] = "1"
    else:
        env.pop(DEGRADED_ENV, None)
        if sandbox_platform() == "macos":
            print(
                "launch_worker: NOTICE macOS Seatbelt backend is implemented but not certified "
                "(see docs/dev_loop/claude-native-sandbox.md)",
                file=sys.stderr,
            )
    env[CACHE_DIR_ENV] = str(_allocate_session_cache())
    command = [claude, "--agent", "sdd-worker"]
    if not has_sources:
        command += ["--setting-sources", "project,local"]
    if not has_model:
        command += ["--model", _DEFAULT_MODEL]
    command += ["--settings", json.dumps(settings), *forwarded]
    if initial_prompt is not None:
        command.append(initial_prompt)
    os.chdir(cwd)
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
