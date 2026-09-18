"""Managed ``fast-jev-compaction`` plugin installation for Claude Code.

`fast-jev-compaction <https://github.com/tamaratran/fast-jev-compaction>`_ is
a Claude Code function-hook plugin that replaces the built-in compaction
summary with a verbatim history: every tool call and tool result is scored
by TypeSafe's Jev model in one fast request, stale ones are dropped or
truncated, and everything kept stays word for word. User and assistant text
is never rewritten.

``parrot claude install`` wires it in declaratively, the way Claude Code
documents team plugins (``docs/en/plugin-marketplaces``): the project's
``.claude/settings.json`` gains

- ``env.CLAUDE_CODE_ENABLE_FUNCTION_HOOKS = "1"`` — function hooks are an
  early-access surface (Claude Code >= 2.1.274) and must be switched on;
- ``extraKnownMarketplaces["fast-jev-compaction"]`` — the plugin's own
  repository is its marketplace (``.claude-plugin/marketplace.json``);
- ``enabledPlugins["fast-jev-compaction@fast-jev-compaction"] = true``.

Claude Code adds the marketplace and installs the plugin for every team
member once they trust the folder. When the ``claude`` CLI is on ``PATH`` the
installer additionally runs ``claude plugin marketplace add`` / ``claude
plugin install --scope project`` so the plugin is available in the very next
session without waiting for that reconciliation. The TypeSafe API key is
**never** written to the shared ``settings.json``: it stays in the
environment (``TYPESAFE_API_KEY``) or, when passed explicitly, goes to the
git-ignored ``.claude/settings.local.json``.

Everything is idempotent and reversible: ``parrot claude uninstall`` removes
only the entries this module wrote and never touches a marketplace or plugin
entry it does not recognise as its own.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

from .installer import _load_settings, _write_settings

#: Marketplace name as declared in the plugin's ``.claude-plugin/marketplace.json``.
MARKETPLACE_NAME = "fast-jev-compaction"
#: GitHub repository that is both the plugin and its marketplace.
MARKETPLACE_REPO = "tamaratran/fast-jev-compaction"
#: Plugin id in Claude Code's ``name@marketplace`` form.
PLUGIN_ID = f"fast-jev-compaction@{MARKETPLACE_NAME}"
#: Early-access switch for Claude Code function hooks (required by the plugin).
FUNCTION_HOOKS_ENV = "CLAUDE_CODE_ENABLE_FUNCTION_HOOKS"
#: TypeSafe API key variable the plugin (and ``JevClient``) reads.
API_KEY_ENV = "TYPESAFE_API_KEY"
#: Managed ``extraKnownMarketplaces`` entry; an entry with a different source is foreign.
MARKETPLACE_ENTRY: dict[str, Any] = {"source": {"source": "github", "repo": MARKETPLACE_REPO}}
#: Wall-clock budget for each ``claude plugin`` subprocess.
PLUGIN_CLI_TIMEOUT = 180

_SETTINGS = ".claude/settings.json"
_LOCAL_SETTINGS = ".claude/settings.local.json"


def _claude_binary() -> Optional[str]:
    """Path of the ``claude`` CLI, or ``None`` when it is not installed."""
    return shutil.which("claude")


def _is_managed_marketplace(entry: Any) -> bool:
    """Whether an ``extraKnownMarketplaces`` entry is the one this module writes."""
    return entry == MARKETPLACE_ENTRY


def _install_settings(root: Path) -> list[str]:
    """Merge the function-hooks flag, marketplace and plugin into ``.claude/settings.json``.

    Args:
        root: Repository root.

    Returns:
        Human-readable actions.

    Raises:
        RuntimeError: When the settings file exists but is not a JSON object,
            or a key this module needs holds the wrong JSON type.
    """
    path = root / _SETTINGS
    settings = _load_settings(path) or {}
    actions: list[str] = []
    dirty = False

    env = settings.setdefault("env", {})
    if not isinstance(env, dict):
        raise RuntimeError(f"{path}: 'env' is not a JSON object")
    if env.get(FUNCTION_HOOKS_ENV) != "1":
        env[FUNCTION_HOOKS_ENV] = "1"
        dirty = True
        actions.append(f"{_SETTINGS} — {FUNCTION_HOOKS_ENV}=1 (function hooks enabled)")

    marketplaces = settings.setdefault("extraKnownMarketplaces", {})
    if not isinstance(marketplaces, dict):
        raise RuntimeError(f"{path}: 'extraKnownMarketplaces' is not a JSON object")
    existing = marketplaces.get(MARKETPLACE_NAME)
    if existing is None:
        marketplaces[MARKETPLACE_NAME] = dict(MARKETPLACE_ENTRY)
        dirty = True
        actions.append(f"{_SETTINGS} — marketplace '{MARKETPLACE_NAME}' added ({MARKETPLACE_REPO})")
    elif not _is_managed_marketplace(existing):
        actions.append(
            f"{_SETTINGS} — WARNING: marketplace '{MARKETPLACE_NAME}' already exists with a different "
            f"source and was left untouched"
        )

    plugins = settings.setdefault("enabledPlugins", {})
    if not isinstance(plugins, dict):
        raise RuntimeError(f"{path}: 'enabledPlugins' is not a JSON object")
    if plugins.get(PLUGIN_ID) is not True:
        plugins[PLUGIN_ID] = True
        dirty = True
        actions.append(f"{_SETTINGS} — plugin '{PLUGIN_ID}' enabled")

    if dirty:
        _write_settings(path, settings)
    else:
        actions.append(f"{_SETTINGS} — fast-jev-compaction already installed")
    return actions


def _install_api_key(root: Path, api_key: Optional[str]) -> str:
    """Store an explicitly supplied key in the git-ignored local settings, or report where it comes from.

    Args:
        root: Repository root.
        api_key: Key passed on the command line, or ``None``.

    Returns:
        One human-readable action.
    """
    if api_key:
        path = root / _LOCAL_SETTINGS
        local = _load_settings(path) or {}
        env = local.setdefault("env", {})
        if not isinstance(env, dict):
            raise RuntimeError(f"{path}: 'env' is not a JSON object")
        if env.get(API_KEY_ENV) == api_key:
            return f"{_LOCAL_SETTINGS} — {API_KEY_ENV} already set"
        env[API_KEY_ENV] = api_key
        _write_settings(path, local)
        return f"{_LOCAL_SETTINGS} — {API_KEY_ENV} written (git-ignored, never in settings.json)"
    if os.environ.get(API_KEY_ENV):
        return f"{API_KEY_ENV} — found in the environment (not copied into any file)"
    local = None
    try:
        local = _load_settings(root / _LOCAL_SETTINGS)
    except RuntimeError:
        pass
    if isinstance(local, dict) and isinstance(local.get("env"), dict) and local["env"].get(API_KEY_ENV):
        return f"{_LOCAL_SETTINGS} — {API_KEY_ENV} already set"
    return (
        f"{API_KEY_ENV} — NOT configured: export it in your shell or re-run with "
        f"--typesafe-api-key (the plugin falls back to Claude Code's built-in summary without it)"
    )


def _run_plugin_cli(root: Path, *args: str) -> tuple[int, str]:
    """Run ``claude plugin ...`` non-interactively inside ``root``.

    Args:
        root: Working directory (the project whose settings receive the plugin).
        *args: Arguments after ``claude plugin``.

    Returns:
        ``(returncode, combined_output_tail)``; ``returncode`` is ``-1`` when
        the process could not be started or timed out.
    """
    binary = _claude_binary()
    if binary is None:
        return -1, "claude CLI not found"
    env = dict(os.environ)
    env[FUNCTION_HOOKS_ENV] = "1"
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [binary, "plugin", *args],
            cwd=str(root),
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=PLUGIN_CLI_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, str(exc)
    output = (proc.stdout + proc.stderr).strip()
    return proc.returncode, output[-300:]


def _install_via_cli(root: Path) -> list[str]:
    """Register the marketplace and install the plugin with the ``claude`` CLI when available.

    Failures are reported, never raised: the declarative settings written by
    :func:`_install_settings` already make Claude Code install the plugin on
    the next trusted session.

    Args:
        root: Repository root.

    Returns:
        Human-readable actions.
    """
    if _claude_binary() is None:
        return [
            "claude CLI — not found; Claude Code will add the marketplace and install the plugin "
            "when the project folder is next trusted"
        ]
    rc, output = _run_plugin_cli(root, "marketplace", "add", MARKETPLACE_REPO)
    if rc != 0 and "already" not in output.lower():
        return [
            f"claude plugin marketplace add {MARKETPLACE_REPO} — failed (rc={rc}): {output or 'no output'}; "
            "run it manually, the settings.json wiring is in place"
        ]
    actions = [f"claude plugin marketplace add {MARKETPLACE_REPO} — ok"]
    rc, output = _run_plugin_cli(root, "install", PLUGIN_ID, "--scope", "project", "-y")
    if rc != 0 and "already" not in output.lower():
        actions.append(
            f"claude plugin install {PLUGIN_ID} — failed (rc={rc}): {output or 'no output'}; "
            "run it manually, the settings.json wiring is in place"
        )
    else:
        actions.append(f"claude plugin install {PLUGIN_ID} --scope project — ok")
    return actions


def install_compaction(root: Path, *, api_key: Optional[str] = None, plugin_cli: bool = True) -> list[str]:
    """Install the fast-jev-compaction plugin wiring into a repository.

    Args:
        root: Repository root.
        api_key: TypeSafe API key to store in ``.claude/settings.local.json``.
            ``None`` leaves key resolution to ``TYPESAFE_API_KEY``.
        plugin_cli: Also run the ``claude plugin`` CLI when it is installed.

    Returns:
        Human-readable list of actions performed.

    Raises:
        RuntimeError: When a settings file cannot be parsed or has the wrong
            shape at a key this installer needs.
    """
    root = root.resolve()
    actions = _install_settings(root)
    actions.append(_install_api_key(root, api_key))
    if plugin_cli:
        actions.extend(_install_via_cli(root))
    actions.append("fast-jev-compaction — restart Claude Code (or /reload-plugins); /compact now goes through Jev")
    return actions


def uninstall_compaction(root: Path, *, plugin_cli: bool = True) -> list[str]:
    """Remove the managed plugin wiring; foreign entries and the API key are left alone.

    The function-hooks flag is dropped only when no other plugin remains
    enabled, since other function-hook plugins may depend on it.

    Args:
        root: Repository root.
        plugin_cli: Also run ``claude plugin uninstall`` when the CLI is installed.

    Returns:
        Human-readable list of actions performed (empty when nothing was installed).
    """
    root = root.resolve()
    path = root / _SETTINGS
    try:
        settings = _load_settings(path)
    except RuntimeError:
        settings = None
    actions: list[str] = []
    if not isinstance(settings, dict):
        return actions
    dirty = False

    plugins = settings.get("enabledPlugins")
    if isinstance(plugins, dict) and PLUGIN_ID in plugins:
        plugins.pop(PLUGIN_ID)
        if not plugins:
            settings.pop("enabledPlugins")
        dirty = True
        actions.append(f"{_SETTINGS} — plugin '{PLUGIN_ID}' removed")

    marketplaces = settings.get("extraKnownMarketplaces")
    if isinstance(marketplaces, dict) and _is_managed_marketplace(marketplaces.get(MARKETPLACE_NAME)):
        marketplaces.pop(MARKETPLACE_NAME)
        if not marketplaces:
            settings.pop("extraKnownMarketplaces")
        dirty = True
        actions.append(f"{_SETTINGS} — marketplace '{MARKETPLACE_NAME}' removed")

    env = settings.get("env")
    remaining = settings.get("enabledPlugins")
    if isinstance(env, dict) and env.get(FUNCTION_HOOKS_ENV) == "1" and not remaining and actions:
        env.pop(FUNCTION_HOOKS_ENV)
        if not env:
            settings.pop("env")
        dirty = True
        actions.append(f"{_SETTINGS} — {FUNCTION_HOOKS_ENV} removed (no plugin needs it)")

    if dirty:
        _write_settings(path, settings)
    if actions and plugin_cli and _claude_binary() is not None:
        rc, output = _run_plugin_cli(root, "uninstall", PLUGIN_ID)
        actions.append(f"claude plugin uninstall {PLUGIN_ID} — " + ("ok" if rc == 0 else f"failed (rc={rc}): {output}"))
    if actions:
        actions.append(f"{_LOCAL_SETTINGS} — {API_KEY_ENV} left in place (remove it yourself if unused)")
    return actions


def compaction_status(root: Path) -> dict[str, bool]:
    """Report whether the plugin wiring, the function-hooks flag and an API key are present.

    Args:
        root: Repository root.

    Returns:
        ``compaction_plugin``, ``compaction_function_hooks`` and
        ``compaction_api_key`` booleans.
    """
    root = root.resolve()
    try:
        settings = _load_settings(root / _SETTINGS) or {}
    except RuntimeError:
        settings = {}
    plugins = settings.get("enabledPlugins")
    env = settings.get("env")
    try:
        local = _load_settings(root / _LOCAL_SETTINGS) or {}
    except RuntimeError:
        local = {}
    local_env = local.get("env")
    key_present = bool(os.environ.get(API_KEY_ENV)) or (
        isinstance(local_env, dict) and bool(local_env.get(API_KEY_ENV))
    )
    return {
        "compaction_plugin": isinstance(plugins, dict) and plugins.get(PLUGIN_ID) is True,
        "compaction_function_hooks": isinstance(env, dict) and env.get(FUNCTION_HOOKS_ENV) == "1",
        "compaction_api_key": key_present,
    }
