"""Managed installation of the host read guards (FEAT-543).

Installs, reports on, and removes the opt-in ``PreToolUse`` guard for
Claude Code and Codex, following the same "touch only what we own"
discipline as the existing wiki installers:

* **Idempotent.** Installing twice produces identical bytes and an
  "already installed" message.
* **Foreign configuration is preserved.** Other hook entries, other
  matchers and unknown keys are never rewritten or dropped.
* **A malformed config is never clobbered.** It raises an actionable
  error and leaves the file untouched.
* **Uninstall removes only owned entries**, identified by the hook module
  name in the command string, and only collapses containers it emptied.

The user's home directory is never touched: Codex hooks are written to
``<root>/.codex/hooks.json``, project scope only.
"""

from __future__ import annotations

import json
import shutil
import subprocess  # noqa: S404 — used only to read `--version` from a host binary
import sys
from pathlib import Path
from typing import Any, Optional

__all__ = (
    "CLAUDE_MATCHER",
    "CODEX_MATCHER",
    "HOOK_MODULE",
    "guard_status",
    "guard_thresholds",
    "hook_command",
    "install_guards",
    "resolve_python",
    "uninstall_guards",
)

#: Ownership marker: any hook command mentioning this module is ours.
HOOK_MODULE = "parrot_tools.tool_optimizations.hooks"

#: Claude Code intercepts both the structured Read tool and shell reads.
CLAUDE_MATCHER = "Read|Bash"

#: Codex reads through the shell only.
CODEX_MATCHER = "Bash"

#: Default thresholds, matching the bounded reader's own defaults.
_DEFAULT_MAX_LINES = 350
_DEFAULT_LARGE_FILE_BYTES = 64_000
_DEFAULT_READER_SERVER = "parrot-bounded-source"
_READER_CLASS = "parrot_tools.tool_optimizations.reader.BoundedSourceToolkit"

#: Minimum host versions known to support the hook contract used here.
_MIN_VERSIONS = {"claude": (2, 1), "codex": (0, 150)}

_HOSTS = {
    "claude": (Path(".claude") / "settings.json", CLAUDE_MATCHER),
    "codex": (Path(".codex") / "hooks.json", CODEX_MATCHER),
}


def resolve_python(root: Path) -> str:
    """Return an absolute interpreter path for the hook command.

    Hooks run without the virtualenv on ``$PATH`` — notably inside git
    worktrees — so the command must name the interpreter absolutely.

    Args:
        root: The repository root.

    Returns:
        An absolute path to a Python interpreter.
    """
    candidate = root / ".venv" / "bin" / "python"
    if candidate.exists():
        return str(candidate.resolve())
    return sys.executable


def hook_command(root: Path, host: str) -> str:
    """Build the guard's hook command for a host.

    Args:
        root: The repository root.
        host: ``claude`` or ``codex``.

    Returns:
        The full command string.

    Raises:
        ValueError: The host is not supported.
    """
    if host not in _HOSTS:
        raise ValueError(f"unsupported host {host!r}")
    return f"{resolve_python(root)} -m {HOOK_MODULE} --host {host}"


def guard_thresholds(root: Path) -> dict[str, Any]:
    """Derive guard thresholds from the configured bounded-source toolkit.

    The guard must use the same limits as the MCP reader it points at;
    reading them from the same configuration is what keeps them aligned.

    Args:
        root: The repository root.

    Returns:
        The thresholds mapping written to ``.parrot/tool-guards.json``.
    """
    thresholds: dict[str, Any] = {
        "max_lines": _DEFAULT_MAX_LINES,
        "large_file_bytes": _DEFAULT_LARGE_FILE_BYTES,
        "reader_server": _DEFAULT_READER_SERVER,
        "tool": "source_read",
    }
    try:
        from parrot.mcp.toolkit_config import load_toolkits_config

        config = load_toolkits_config(root)
    except Exception:  # noqa: BLE001 — defaults are a valid outcome
        return thresholds

    for name, section in config.toolkits.items():
        if section.class_path != _READER_CLASS:
            continue
        kwargs = section.kwargs or {}
        thresholds["max_lines"] = int(kwargs.get("max_lines", _DEFAULT_MAX_LINES))
        thresholds["large_file_bytes"] = int(kwargs.get("large_file_bytes", _DEFAULT_LARGE_FILE_BYTES))
        thresholds["reader_server"] = f"parrot-{name}"
        break
    return thresholds


def _load_json_object(path: Path) -> Optional[dict[str, Any]]:
    """Read a JSON object, refusing to proceed on malformed content.

    Args:
        path: The file to read.

    Returns:
        The parsed object, or None when the file does not exist.

    Raises:
        RuntimeError: The file exists but is not a JSON object.
    """
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Cannot parse {path} — fix or remove it first: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"{path} is not a JSON object")
    return data


def _write_json(path: Path, data: dict[str, Any]) -> None:
    """Persist a JSON object as pretty JSON with a trailing newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _is_guard_entry(entry: Any) -> bool:
    """Whether a PreToolUse entry was installed by this module.

    Args:
        entry: A candidate hook entry.

    Returns:
        True when any of its commands names our hook module.
    """
    if not isinstance(entry, dict):
        return False
    return any(HOOK_MODULE in str(hook.get("command", "")) for hook in entry.get("hooks", []) if isinstance(hook, dict))


def _guard_entry(matcher: str, command: str) -> dict[str, Any]:
    """Build the guard's PreToolUse entry."""
    return {"matcher": matcher, "hooks": [{"type": "command", "command": command, "timeout": 10}]}


def _pre_tool_use_list(data: dict[str, Any], path: Path, *, create: bool) -> Optional[list[Any]]:
    """Return the ``hooks.PreToolUse`` list, validating the containers.

    Args:
        data: The parsed config object.
        path: The file, for error messages.
        create: Whether to create missing containers.

    Returns:
        The list, or None when absent and ``create`` is False.

    Raises:
        RuntimeError: A container exists with the wrong type.
    """
    hooks = data.get("hooks")
    if hooks is None:
        if not create:
            return None
        hooks = {}
        data["hooks"] = hooks
    if not isinstance(hooks, dict):
        raise RuntimeError(f"{path}: 'hooks' is not a JSON object")

    entries = hooks.get("PreToolUse")
    if entries is None:
        if not create:
            return None
        entries = []
        hooks["PreToolUse"] = entries
    if not isinstance(entries, list):
        raise RuntimeError(f"{path}: 'hooks.PreToolUse' is not a list")
    return entries


def install_guards(root: Path, host: str) -> list[str]:
    """Install the read guard for a host, idempotently.

    Args:
        root: The repository root.
        host: ``claude`` or ``codex``.

    Returns:
        Human-readable action strings.

    Raises:
        ValueError: The host is not supported.
        RuntimeError: A target config file is malformed; nothing is written.
    """
    if host not in _HOSTS:
        raise ValueError(f"unsupported host {host!r}")
    relative, matcher = _HOSTS[host]
    actions: list[str] = []

    thresholds = guard_thresholds(root)
    thresholds_path = root / ".parrot" / "tool-guards.json"
    desired = json.dumps(thresholds, indent=2) + "\n"
    if not thresholds_path.exists() or thresholds_path.read_text(encoding="utf-8") != desired:
        thresholds_path.parent.mkdir(parents=True, exist_ok=True)
        thresholds_path.write_text(desired, encoding="utf-8")
        actions.append(f".parrot/tool-guards.json — thresholds written ({thresholds['max_lines']} lines)")
    else:
        actions.append(".parrot/tool-guards.json — thresholds already current")
    if thresholds["reader_server"] == _DEFAULT_READER_SERVER:
        actions.append("reader MCP not configured — guard denials will reference " f"'{_DEFAULT_READER_SERVER}'")

    path = root / relative
    data = _load_json_object(path) or {}
    entries = _pre_tool_use_list(data, path, create=True)
    assert entries is not None  # create=True always returns a list

    command = hook_command(root, host)
    entry = _guard_entry(matcher, command)
    existing = next((item for item in entries if _is_guard_entry(item)), None)

    if existing == entry:
        actions.append(f"{relative.as_posix()} — tool guard already installed")
        return actions
    if existing is None:
        entries.append(entry)
        verb = "installed"
    else:
        existing.clear()
        existing.update(entry)
        verb = "updated"
    _write_json(path, data)
    actions.append(f"{relative.as_posix()} — tool guard {verb}")
    return actions


def uninstall_guards(root: Path, host: str) -> list[str]:
    """Remove only the guard entries this module installed.

    Args:
        root: The repository root.
        host: ``claude`` or ``codex``.

    Returns:
        Human-readable action strings.

    Raises:
        ValueError: The host is not supported.
        RuntimeError: The target config file is malformed; it is left alone.
    """
    if host not in _HOSTS:
        raise ValueError(f"unsupported host {host!r}")
    relative, _matcher = _HOSTS[host]
    path = root / relative
    actions: list[str] = []

    data = _load_json_object(path)
    if data is None:
        actions.append(f"{relative.as_posix()} — nothing to remove")
    else:
        entries = _pre_tool_use_list(data, path, create=False)
        if entries is None:
            actions.append(f"{relative.as_posix()} — nothing to remove")
        else:
            kept = [item for item in entries if not _is_guard_entry(item)]
            if len(kept) == len(entries):
                actions.append(f"{relative.as_posix()} — nothing to remove")
            else:
                hooks = data["hooks"]
                if kept:
                    hooks["PreToolUse"] = kept
                else:
                    # Only collapse containers we emptied ourselves.
                    hooks.pop("PreToolUse", None)
                    if not hooks:
                        data.pop("hooks", None)
                _write_json(path, data)
                actions.append(f"{relative.as_posix()} — tool guard removed")

    # The thresholds file is shared; drop it only when no host still uses it.
    if not any(_is_installed(root, other) for other in _HOSTS):
        thresholds_path = root / ".parrot" / "tool-guards.json"
        if thresholds_path.exists():
            thresholds_path.unlink()
            actions.append(".parrot/tool-guards.json — removed")
    return actions


def _is_installed(root: Path, host: str) -> bool:
    """Whether a host currently has our guard entry.

    Args:
        root: The repository root.
        host: The host name.

    Returns:
        True when an owned entry is present. A malformed file reads as
        "not installed" rather than raising, so status never crashes.
    """
    relative, _matcher = _HOSTS[host]
    try:
        data = _load_json_object(root / relative)
    except RuntimeError:
        return False
    if data is None:
        return False
    try:
        entries = _pre_tool_use_list(data, root / relative, create=False)
    except RuntimeError:
        return False
    return bool(entries) and any(_is_guard_entry(item) for item in entries)


def _host_version(host: str) -> Optional[str]:
    """Read a host binary's reported version, tolerating any failure.

    Args:
        host: ``claude`` or ``codex``.

    Returns:
        The version string, or None when the binary is missing or silent.
    """
    binary = shutil.which(host)
    if not binary:
        return None
    try:
        result = subprocess.run(  # noqa: S603 — fixed argv, no shell
            [binary, "--version"], capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = (result.stdout or result.stderr or "").strip()
    return output.splitlines()[0] if output else None


def _supported(host: str, version: Optional[str]) -> Optional[bool]:
    """Decide whether a reported host version supports the guard contract.

    Args:
        host: The host name.
        version: The reported version string.

    Returns:
        True/False when the version can be parsed, None when unknown — an
        unknown version is reported as unknown, never as supported.
    """
    if not version:
        return None
    import re

    match = re.search(r"(\d+)\.(\d+)", version)
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2))) >= _MIN_VERSIONS[host]


def guard_status(root: Path, host: str) -> dict[str, Any]:
    """Report whether the guard is installed and whether the host supports it.

    Args:
        root: The repository root.
        host: ``claude`` or ``codex``.

    Returns:
        A mapping with ``installed``, ``supported``, ``hook_path``,
        ``thresholds`` and ``host_version``. Never raises.

    Raises:
        ValueError: The host is not supported.
    """
    if host not in _HOSTS:
        raise ValueError(f"unsupported host {host!r}")
    relative, _matcher = _HOSTS[host]
    version = _host_version(host)

    thresholds: Optional[dict[str, Any]] = None
    thresholds_path = root / ".parrot" / "tool-guards.json"
    if thresholds_path.exists():
        try:
            thresholds = json.loads(thresholds_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            thresholds = None

    return {
        "installed": _is_installed(root, host),
        "supported": _supported(host, version),
        "hook_path": str(root / relative),
        "thresholds": thresholds,
        "host_version": version,
    }
