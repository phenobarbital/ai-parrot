"""Idempotent installer for Google Antigravity / Gemini CLI WikiToolkit infrastructure."""

from __future__ import annotations

import json
import logging
import shutil
import sys
from pathlib import Path
from typing import Any, Optional

from parrot.knowledge.wiki.google import assets
from parrot.knowledge.wiki.google.bookstore import bookstore_status, install_bookstore, uninstall_bookstore
from parrot.knowledge.wiki.project import WikiProjectConfig, config_path, load_effective_config, save_project_config
from parrot.launcher import shared_state_root
from parrot.mcp.portability import resolve_portable_mode

logger = logging.getLogger(__name__)


def _upsert_marker_block(text: str, block: str, begin: str, end: str) -> str:
    """Insert or replace a marker-delimited block."""
    block = block.rstrip("\n")
    if begin in text:
        head, _, rest = text.partition(begin)
        tail = rest.partition(end)[2] if end in rest else "\n"
        return f"{head}{block}{tail}"
    prefix = text
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    separator = "\n" if prefix else ""
    return f"{prefix}{separator}{block}\n"


def _remove_marker_block(text: str, begin: str, end: str) -> str:
    """Remove a marker-delimited block."""
    if begin not in text:
        return text
    head, _, rest = text.partition(begin)
    tail = rest.partition(end)[2] if end in rest else ""
    head = head.rstrip(" \t\n")
    tail = tail.lstrip("\n")
    if not head and not tail:
        return ""
    return f"{head}\n{tail}" if tail else f"{head}\n"


def _load_mcp_config(path: Path) -> dict[str, Any]:
    """Read and validate mcp_config.json."""
    if not path.exists():
        return {"mcpServers": {}}
    try:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return {"mcpServers": {}}
        data = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Cannot parse {path} — fix or remove it first: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"{path} is not a JSON object")
    if "mcpServers" not in data or not isinstance(data["mcpServers"], dict):
        data["mcpServers"] = {}
    return data


def _save_mcp_config(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _script_basename(command: str) -> str:
    """Basename of a command path, separator- and ``.exe``-agnostic (codex S4)."""
    name = command.replace("\\", "/").rsplit("/", 1)[-1]
    return name[:-4] if name.lower().endswith(".exe") else name


def portable_mode_of_config(path: Path, root: Path) -> bool | None:
    """Infer the deployment form from ONE MCP config file, judged against ``root``.

    Unlike :func:`_current_portable_mode`, this inspects exactly the file it is given and never
    falls back to the other config. A caller that must report a single file's own form (``parrot
    self doctor``) therefore does not have to suppress the fallback by passing a config file in
    place of ``root``, and ``root`` stays a real directory for the managed-entry check. Never
    raises.

    Args:
        path: the MCP config file to inspect.
        root: the repository root the managed-entry shape is judged against.

    Returns:
        ``True`` (portable) or ``False`` (baked) when ``path`` holds a managed ``wikitoolkit``
        entry; ``None`` when the file is missing, unreadable, malformed, or carries only foreign
        entries.
    """
    try:
        if not path.exists():
            return None
        servers = _load_mcp_config(path).get("mcpServers")
    except (RuntimeError, OSError, ValueError):
        return None
    if not isinstance(servers, dict):
        return None
    entry = servers.get("wikitoolkit")
    if entry is None or not _is_managed_wikitoolkit_entry(entry, root):
        return None
    return entry == assets.wikitoolkit_mcp_entry(root, portable=True)


def _current_portable_mode(root: Path, mcp_path: Optional[Path] = None) -> bool | None:
    """Infer the current mode (FEAT-633, sticky) from the managed wikitoolkit entry.

    Reads the repo-local plugin config first (per-repo — one repo's choice must not leak into
    another through the USER-GLOBAL file), then the user-global config. A foreign (not
    managed) ``wikitoolkit`` entry carries no information about our form and is skipped.
    Never raises.

    Returns:
        ``True`` (portable) or ``False`` (baked) from the first managed entry found; ``None``
        when neither file holds a managed ``wikitoolkit`` entry (FEAT-804 M2 — the caller then
        applies the launcher rule).
    """
    for path in (root / assets.PLUGIN_DIR / "mcp_config.json", mcp_path or assets.default_mcp_config_path()):
        mode = portable_mode_of_config(path, root)
        if mode is not None:
            return mode
    return None


def _is_managed_wikitoolkit_entry(entry: Any, root: Path) -> bool:
    if not isinstance(entry, dict):
        return False
    command = entry.get("command")
    return isinstance(command, str) and _script_basename(command) == "wikitoolkit" and entry.get("args") == ["mcp"]


def _is_managed_toolkit_entry(entry: Any, root: Path, name: str) -> bool:
    """Whether a `parrot-<name>` entry was written by us.

    Accepts the pinned shape `["mcp-local", name, "--config", <path>]`
    (FEAT-556) and the pre-FEAT-556 shape `["mcp-local", name]`; the
    `command` check is unchanged. Accepting the legacy shape lets
    reconciliation upgrade an operator's hand-written entry in place
    instead of skipping it with a warning.

    A pinned entry whose `--config` points outside `root` is treated as a
    foreign operator override and never overwritten — mirrors
    `claude_code/installer.py::_is_managed_toolkit_entry` (FEAT-556 fix):
    without this check, reconciliation would unconditionally clobber any
    hand-pinned `--config`/`cwd`/extra args on every install.
    """
    if not isinstance(entry, dict):
        return False
    command = entry.get("command")
    if not isinstance(command, str) or _script_basename(command) != "parrot":
        return False
    args = entry.get("args")
    if not isinstance(args, list) or args[:2] != ["mcp-local", name]:
        return False
    if len(args) >= 4 and args[2] == "--config":
        if args[3] == assets.PORTABLE_TOOLKIT_CONFIG:  # portable form — ours
            return True
        config_path = Path(args[3])
        if not config_path.is_absolute():
            return False
        resolved_config = config_path.resolve()
        resolved_root = root.resolve()
        if resolved_config != resolved_root and resolved_root not in resolved_config.parents:
            return False
    return True


def _is_parrot_toolkit_shape(entry: Any, name: str) -> bool:
    """Whether ``entry`` is a ``parrot mcp-local <name> ...`` server, whatever repository it is pinned to."""
    if not isinstance(entry, dict):
        return False
    command = entry.get("command")
    args = entry.get("args")
    return (
        isinstance(command, str)
        and _script_basename(command) == "parrot"
        and isinstance(args, list)
        and args[:2] == ["mcp-local", name]
    )


def _is_inside(path: Path, root: Path) -> bool:
    """Whether ``path`` (resolved) is ``root`` or lives under it; ``False`` on filesystem errors."""
    try:
        resolved, base = path.resolve(), root.resolve()
    except (OSError, RuntimeError):
        return False
    return resolved == base or base in resolved.parents


def _global_parrot_command(root: Path, existing: dict[str, Any]) -> str:
    """``parrot`` command for the USER-GLOBAL toolkit entries.

    Resolution order:

    1. bare ``parrot`` when the managed launcher (under ``parrot_home()``) is first on PATH;
    2. bare ``parrot`` when the managed launcher is installed on disk (the ``bin/`` shim AND the managed
       venv script exist), whatever the PATH order — an active repository venv shadows ``~/.parrot/bin``
       but the launcher still resolves the repository from the working directory;
    3. the command a parrot-shaped entry already uses when it still exists (keeps the file stable across
       repositories), with a warning when that command lives outside ``root``;
    4. this repository's resolved ``parrot`` binary.
    """
    from parrot.launcher import parrot_home, script_path

    found = shutil.which("parrot")
    if found:
        home = parrot_home()
        homes = {home, home.resolve()}
        for candidate in {Path(found), Path(found).resolve()}:
            if any(h == candidate or h in candidate.parents for h in homes):
                return "parrot"
    try:
        home = parrot_home()
        shim = home / "bin" / ("parrot.exe" if sys.platform == "win32" else "parrot")
        if shim.is_file() and script_path(home / "venv", "parrot").is_file():
            return "parrot"
    except OSError:
        pass
    for name, entry in existing.items():
        if name.startswith("parrot-") and _is_parrot_toolkit_shape(entry, name[len("parrot-") :]):
            command = entry["command"]
            if command == "parrot" or Path(command).is_file():
                if command != "parrot" and not _is_inside(Path(command), root):
                    logger.warning(
                        "%s: reusing parrot command %s from another location for the user-global toolkit "
                        "entries; install the managed launcher (parrot self install) or pass --portable",
                        name,
                        command,
                    )
                return command
    return assets.resolve_binary(root, "parrot")


def _install_gemini_md(root: Path) -> str:
    path = root / assets.GEMINI_PATH
    before = path.read_text(encoding="utf-8") if path.exists() else ""
    after = _upsert_marker_block(before, assets.GEMINI_SECTION, assets.AGENTS_BEGIN, assets.AGENTS_END)
    after = _upsert_marker_block(
        after, assets.conventions_section(root), assets.CONVENTIONS_BEGIN, assets.CONVENTIONS_END
    )
    if after != before:
        path.write_text(after, encoding="utf-8")
        return f"{assets.GEMINI_PATH} — wiki + conventions sections {'updated' if before else 'created'}"
    return f"{assets.GEMINI_PATH} — wiki + conventions sections already current"


def _install_skills(root: Path) -> list[str]:
    actions: list[str] = []
    targets = [assets.SKILL_PATH]
    if (root / ".agent/skills").exists():
        targets.append(assets.ALT_SKILL_PATH)

    for skill_path in targets:
        path = root / skill_path
        before = path.read_text(encoding="utf-8") if path.exists() else None
        if before == assets.SKILL:
            actions.append(f"{skill_path} — already current")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(assets.SKILL, encoding="utf-8")
            actions.append(f"{skill_path} — {'updated' if before is not None else 'created'}")
    return actions


def toolkit_config_paths(root: Path, mcp_path: Optional[Path] = None) -> tuple[Path, ...]:
    """Return the two files that carry Antigravity toolkit entries, primary first.

    (1) the USER-GLOBAL config — `~/.gemini/config/mcp_config.json`
        (verified: google/assets.py:59) — shared by every project on the machine,
        which is why `parrot toolkits` warns before writing it (spec §8 Q1);
    (2) the repo-local workspace plugin config
        `<root>/.agents/plugins/parrot/mcp_config.json` (verified: installer.py:214).
    """
    primary = mcp_path or assets.default_mcp_config_path()
    return (primary, root / assets.PLUGIN_DIR / "mcp_config.json")


def reconcile_toolkit_entries(
    root: Path, mcp_path: Optional[Path] = None, *, portable: Optional[bool] = None
) -> tuple[list[str], list[str]]:
    """Reconcile ONLY `parrot-<name>` entries, in BOTH Antigravity config files.

    ``portable=None`` resolves the form via ``resolve_portable_mode`` (sticky from
    ``_current_portable_mode``, then the managed-launcher rule — the `parrot toolkits` path
    through ``mcp/hosts.py::GoogleAdapter.reconcile``). A baked fallback adds its note once
    to the returned actions.

    Never reads or writes the "wikitoolkit" key in either file (FEAT-570 AC5).
    Upserts one entry per ENABLED section, preserves a `parrot-<name>` key whose
    content is not our shape (reported as a warning), and deletes managed entries
    whose section is disabled or gone.

    The USER-GLOBAL file is shared by every repository, so its entries are always
    written in the portable form (relative ``--config``, no ``cwd``) and replace any
    ``parrot mcp-local <name>`` entry, even one pinned to another repository; the
    command is resolved by ``_global_parrot_command``. Portable global entries are
    never deleted because one repository disabled the toolkit — others may use it.

    Returns:
        (actions, warnings) — human-readable strings.
    """
    from parrot.mcp.toolkit_config import load_toolkits_config

    cfg = load_toolkits_config(root)
    enabled_toolkits = {name: section for name, section in cfg.toolkits.items() if section.enabled}
    decision = resolve_portable_mode(portable, current=_current_portable_mode(root, mcp_path))
    portable = decision.portable
    desired_local = assets.toolkit_mcp_entries(root, enabled_toolkits, portable=portable)
    global_path, _local_path = toolkit_config_paths(root, mcp_path)

    all_actions: list[str] = []
    all_warnings: list[str] = []
    if decision.note:
        all_actions.append(decision.note)

    for path in toolkit_config_paths(root, mcp_path):
        data = _load_mcp_config(path)
        servers = data.setdefault("mcpServers", {})
        is_global = path == global_path
        if is_global:
            command = "parrot" if portable else _global_parrot_command(root, servers)
            desired_toolkits = {
                name: {**entry, "command": command}
                for name, entry in assets.toolkit_mcp_entries(root, enabled_toolkits, portable=True).items()
            }
        else:
            desired_toolkits = desired_local

        changed = False
        added: list[str] = []
        updated: list[str] = []
        removed: list[str] = []

        for name, entry in desired_toolkits.items():
            existing = servers.get(name)
            if existing == entry:
                continue
            raw_name = name[len("parrot-") :]
            ours = (
                _is_parrot_toolkit_shape(existing, raw_name)
                if is_global
                else _is_managed_toolkit_entry(existing, root, raw_name)
            )
            if existing is not None and not ours:
                warning = (
                    f"{path} — '{name}' already exists and was not written by "
                    "`parrot google install`; leaving it untouched."
                )
                print(f"Warning: {warning}", file=sys.stderr)
                all_warnings.append(warning)
                continue
            servers[name] = entry
            changed = True
            (updated if existing is not None else added).append(name)

        # Clean up disabled/deleted toolkits
        for name in list(servers.keys()):
            if name != "wikitoolkit" and name.startswith("parrot-"):
                raw_name = name[len("parrot-") :]
                entry = servers[name]
                args = entry.get("args") if isinstance(entry, dict) else None
                shared = is_global and isinstance(args, list) and args[3:4] == [assets.PORTABLE_TOOLKIT_CONFIG]
                if raw_name not in enabled_toolkits and not shared and _is_managed_toolkit_entry(entry, root, raw_name):
                    del servers[name]
                    changed = True
                    removed.append(name)

        if changed:
            _save_mcp_config(path, data)
            if added:
                all_actions.append(f"{path} — added {len(added)} toolkit(s): {', '.join(added)}")
            if updated:
                all_actions.append(f"{path} — updated {len(updated)} toolkit(s): {', '.join(updated)}")
            if removed:
                all_actions.append(f"{path} — removed {len(removed)} toolkit(s): {', '.join(removed)}")

    return all_actions, all_warnings


def _install_mcp(root: Path, mcp_path: Optional[Path] = None, *, portable: bool = False) -> list[str]:
    """Write/refresh wikitoolkit and toolkit MCP entries in mcp_config.json and workspace plugin."""
    actions: list[str] = []
    target_mcp = mcp_path or assets.default_mcp_config_path()
    mcp_data = _load_mcp_config(target_mcp)
    servers = mcp_data.setdefault("mcpServers", {})

    # wikitoolkit entry — never delegated to reconcile_toolkit_entries (FEAT-570 AC5)
    wiki_entry = assets.wikitoolkit_mcp_entry(root, portable=portable)
    existing_wiki = servers.get("wikitoolkit")
    changed_global = False

    if existing_wiki is not None and not _is_managed_wikitoolkit_entry(existing_wiki, root):
        actions.append(f"{target_mcp} — wikitoolkit MCP: foreign user configuration preserved")
    elif existing_wiki == wiki_entry:
        actions.append(f"{target_mcp} — wikitoolkit MCP already current")
    else:
        servers["wikitoolkit"] = wiki_entry
        changed_global = True
        actions.append(f"{target_mcp} — wikitoolkit MCP installed")

    if changed_global:
        _save_mcp_config(target_mcp, mcp_data)

    # Toolkit entries — one reconciliation covering both config files (FEAT-570)
    toolkit_actions, _toolkit_warnings = reconcile_toolkit_entries(root, mcp_path, portable=portable)
    actions.extend(toolkit_actions)

    # Also maintain workspace plugin (.agents/plugins/parrot)
    plugin_dir = root / assets.PLUGIN_DIR
    plugin_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = plugin_dir / "plugin.json"
    manifest_content = json.dumps(assets.plugin_manifest(), indent=2) + "\n"
    if not manifest_file.exists() or manifest_file.read_text(encoding="utf-8") != manifest_content:
        manifest_file.write_text(manifest_content, encoding="utf-8")
        actions.append(f"{manifest_file.relative_to(root)} — plugin manifest written")

    plugin_mcp_file = plugin_dir / "mcp_config.json"
    plugin_data = _load_mcp_config(plugin_mcp_file)
    plugin_servers = plugin_data.setdefault("mcpServers", {})
    if plugin_servers.get("wikitoolkit") != wiki_entry:
        plugin_servers["wikitoolkit"] = wiki_entry
        _save_mcp_config(plugin_mcp_file, plugin_data)
        actions.append(f"{plugin_mcp_file.relative_to(root)} — plugin MCP config written")

    return actions


def _install_gitignore(root: Path) -> str:
    path = root / ".gitignore"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    ignored = {".parrot", ".parrot/", "/.parrot", "/.parrot/"}
    if any(line.strip() in ignored for line in text.splitlines()):
        return ".gitignore — .parrot/ already ignored"
    if text and not text.endswith("\n"):
        text += "\n"
    path.write_text(
        text + "# parrot LLM-wiki state (local retrieval plane)\n.parrot/\n",
        encoding="utf-8",
    )
    return ".gitignore — added .parrot/"


def install_google_integration(
    root: Path,
    config: Optional[WikiProjectConfig] = None,
    gitignore: bool = True,
    bookstore: bool = True,
    mcp_config_path: Optional[Path] = None,
    portable: Optional[bool] = None,
) -> list[str]:
    """Install Google Antigravity / Gemini CLI instructions, skills, and MCP configuration.

    Args:
        root: Install target — every host asset (GEMINI.md, skills, plugin) is written here.
        config: Wiki configuration to persist. ``None`` loads the effective configuration of
            the shared state root (the primary checkout when ``root`` is a linked worktree); an
            explicit value is a deliberate library override.
        portable: True: bare launcher commands, no cwd (multi-repo-safe user-global config);
            False: baked absolute paths; None: keep the current form (plugin file, then
            user-global) and, with no managed entry, follow the managed-launcher rule
            (FEAT-804 M2 — a baked fallback adds one note to the returned actions).

    Note:
        Seeding `.parrot/mcp-toolkits.yaml` sections no longer happens here —
        use `parrot toolkits install` (FEAT-570). This command only
        reconciles whatever the toolkit config already declares.
        ``.parrot/wiki.json`` lives at the shared state root (FEAT-804 M4), never in a
        linked worktree.
    """
    root = root.resolve()
    state_root = shared_state_root(root)
    config = config or load_effective_config(state_root).config
    existed = config_path(state_root).exists()
    save_project_config(state_root, config)
    decision = resolve_portable_mode(portable, current=_current_portable_mode(root, mcp_config_path))
    portable = decision.portable

    wiki_json = ".parrot/wiki.json" if state_root == root else str(config_path(state_root))
    actions = [
        (
            f"{wiki_json} — config already present"
            if existed
            else f"{wiki_json} — config written (wiki '{config.wiki_name}', backend {config.backend})"
        ),
    ]
    if decision.note:
        actions.append(decision.note)
    actions.append(_install_gemini_md(root))
    actions.extend(_install_skills(root))

    actions.extend(_install_mcp(root, mcp_path=mcp_config_path, portable=portable))

    from parrot.mcp.toolkit_config import load_toolkits_config

    if not load_toolkits_config(root).toolkits:
        actions.append("no local MCP toolkits configured — add them with: parrot toolkits install")

    if gitignore:
        actions.append(_install_gitignore(root))

    if bookstore:
        actions.extend(install_bookstore(root, mcp_path=mcp_config_path, portable=portable))

    return actions


def uninstall_google_integration(
    root: Path,
    mcp_config_path: Optional[Path] = None,
) -> list[str]:
    """Remove only managed Google Antigravity artifacts."""
    root = root.resolve()
    actions: list[str] = []

    # 1. Bookstore
    actions.extend(uninstall_bookstore(root, mcp_path=mcp_config_path))

    # 2. GEMINI.md
    gemini_path = root / assets.GEMINI_PATH
    if gemini_path.exists():
        before = gemini_path.read_text(encoding="utf-8")
        after = _remove_marker_block(before, assets.AGENTS_BEGIN, assets.AGENTS_END)
        after = _remove_marker_block(after, assets.CONVENTIONS_BEGIN, assets.CONVENTIONS_END)
        if after != before:
            if after.strip():
                gemini_path.write_text(after, encoding="utf-8")
            else:
                gemini_path.unlink()
            actions.append(f"{assets.GEMINI_PATH} — wiki + conventions sections removed")

    # 3. Skills
    targets = [assets.SKILL_PATH, assets.ALT_SKILL_PATH]
    for skill_path in targets:
        path = root / skill_path
        if path.exists() and path.read_text(encoding="utf-8") == assets.SKILL:
            path.unlink()
            actions.append(f"{skill_path} — removed")

    # 4. MCP servers in mcp_config.json
    target_mcp = mcp_config_path or assets.default_mcp_config_path()
    if target_mcp.exists():
        try:
            mcp_data = _load_mcp_config(target_mcp)
            servers = mcp_data.get("mcpServers", {})
            removed_keys: list[str] = []

            if "wikitoolkit" in servers and _is_managed_wikitoolkit_entry(servers["wikitoolkit"], root):
                del servers["wikitoolkit"]
                removed_keys.append("wikitoolkit")

            for key in list(servers.keys()):
                if key.startswith("parrot-"):
                    raw_name = key[len("parrot-") :]
                    if _is_managed_toolkit_entry(servers[key], root, raw_name):
                        del servers[key]
                        removed_keys.append(key)

            if removed_keys:
                _save_mcp_config(target_mcp, mcp_data)
                actions.append(f"{target_mcp} — managed MCP entries removed ({', '.join(removed_keys)})")
        except Exception as exc:
            logger.warning("Could not clean up %s: %s", target_mcp, exc)

    # 5. Workspace plugin
    plugin_dir = root / assets.PLUGIN_DIR
    plugin_mcp_file = plugin_dir / "mcp_config.json"
    manifest_file = plugin_dir / "plugin.json"
    if plugin_mcp_file.exists():
        plugin_mcp_file.unlink()
        actions.append(f"{assets.PLUGIN_DIR}/mcp_config.json — removed")
    if manifest_file.exists():
        manifest_file.unlink()
        actions.append(f"{assets.PLUGIN_DIR}/plugin.json — removed")
    if plugin_dir.exists() and not any(plugin_dir.iterdir()):
        plugin_dir.rmdir()

    if not actions:
        actions.append("nothing to remove — integration not installed")
    return actions


def integration_status(
    root: Path,
    mcp_config_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Report status of Google Antigravity integration pieces.

    Wiki state (config, built plane) is read at the shared state root; host assets at ``root``.
    """
    root = root.resolve()
    state_root = shared_state_root(root)
    config = load_effective_config(state_root).config
    gemini_path = root / assets.GEMINI_PATH
    target_mcp = mcp_config_path or assets.default_mcp_config_path()

    mcp_installed = False
    toolkit_count = 0
    if target_mcp.exists():
        try:
            mcp_data = _load_mcp_config(target_mcp)
            servers = mcp_data.get("mcpServers", {})
            mcp_installed = "wikitoolkit" in servers
            toolkit_count = sum(1 for k in servers if k.startswith("parrot-"))
        except Exception:
            mcp_installed = False

    plugin_dir = root / assets.PLUGIN_DIR
    plugin_installed = (plugin_dir / "plugin.json").exists() and (plugin_dir / "mcp_config.json").exists()

    bs_status = bookstore_status(root, mcp_path=mcp_config_path)

    return {
        **bs_status,
        "root": str(root),
        "config": config_path(state_root).exists(),
        "wiki_built": config.is_built(state_root),
        "gemini_md_section": (gemini_path.exists() and assets.AGENTS_BEGIN in gemini_path.read_text(encoding="utf-8")),
        "skill": (root / assets.SKILL_PATH).exists() or (root / assets.ALT_SKILL_PATH).exists(),
        "mcp": mcp_installed,
        "plugin": plugin_installed,
        "toolkit_count": toolkit_count,
    }
