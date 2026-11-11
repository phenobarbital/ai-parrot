"""Stale `parrot-<name>` MCP toolkit entries across the three hosts' config files (FEAT-795 M6)."""

from __future__ import annotations

import logging
import re
import tomllib
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Literal, Sequence

from pydantic import BaseModel

from parrot.knowledge.wiki.claude_code.installer import uninstall_toolkit_approvals
from parrot.knowledge.wiki.codex import assets as codex_assets
from parrot.knowledge.wiki.codex.installer import _remove_marker_block, _validate_toml
from parrot.knowledge.wiki.google.installer import _load_mcp_config, _save_mcp_config, toolkit_config_paths
from parrot.mcp.toolkit_config import AGENT_SECTION_PREFIX, is_agent_section, load_toolkits_config
from parrot.mcp.toolkit_seed import available_templates

logger = logging.getLogger(__name__)

StaleMcpReason = Literal["retired-toolkit", "undeclared", "foreign-repo", "missing-repo"]
_HOSTS: tuple[str, ...] = ("claude", "codex", "google")


class StaleMcpEntry(BaseModel):
    """One stale toolkit entry: ``host``, display ``file``, ``key`` ("parrot-<name>"), ``reason``, ``detail``."""

    host: Literal["claude", "codex", "google"]
    file: str
    key: str
    reason: StaleMcpReason
    detail: str


@dataclass(frozen=True)
class _McpFile:
    """One config file to scan: real ``path``, display name, ``fmt`` json|toml, ``scope`` repo|global."""

    host: str
    path: Path
    display: str
    fmt: Literal["json", "toml"]
    scope: Literal["repo", "global"]


def is_parrot_toolkit_entry(key: str, entry: Any) -> bool:
    """Check whether an entry has the ``parrot mcp-local <name>`` toolkit shape.

    No containment check is applied; that is what separates this predicate from
    the installers' ``_is_managed_toolkit_entry`` helpers.
    """
    if not key.startswith("parrot-") or not isinstance(entry, dict):
        return False
    name = key[len("parrot-") :]
    command, args = entry.get("command"), entry.get("args")
    if not isinstance(command, str) or not isinstance(args, list):
        return False
    basename = command.replace("\\", "/").rsplit("/", 1)[-1]
    basename = basename[:-4] if basename.lower().endswith(".exe") else basename
    return basename == "parrot" and args[:2] == ["mcp-local", name]


def _mcp_files(root: Path, hosts: Sequence[str], gemini_config: Path | None) -> list[_McpFile]:
    """Return the config files of ``hosts``, including files that do not exist."""
    files: list[_McpFile] = []
    if "claude" in hosts:
        files.append(_McpFile("claude", root / ".mcp.json", ".mcp.json", "json", "repo"))
    if "codex" in hosts:
        files.append(_McpFile("codex", root / ".codex" / "config.toml", ".codex/config.toml", "toml", "repo"))
    if "google" in hosts:
        global_path, plugin_path = toolkit_config_paths(root, gemini_config)
        try:
            global_display = f"~/{global_path.relative_to(Path.home()).as_posix()}"
        except ValueError:
            global_display = str(global_path)
        files.extend(
            (
                _McpFile("google", global_path, global_display, "json", "global"),
                _McpFile(
                    "google",
                    plugin_path,
                    ".agents/plugins/parrot/mcp_config.json",
                    "json",
                    "repo",
                ),
            )
        )
    return files


def _read_servers(item: _McpFile) -> dict[str, Any] | None:
    """Read an MCP server mapping, returning ``None`` and warning on parse errors."""
    if item.fmt == "json":
        try:
            return _load_mcp_config(item.path)["mcpServers"]
        except RuntimeError as exc:
            logger.warning("cannot parse MCP config %s: %s", item.path, exc)
            return None

    if not item.path.exists():
        return {}
    try:
        servers = tomllib.loads(item.path.read_text(encoding="utf-8")).get("mcp_servers", {})
    except (tomllib.TOMLDecodeError, OSError) as exc:
        logger.warning("cannot parse MCP config %s: %s", item.path, exc)
        return None
    if not isinstance(servers, dict):
        logger.warning("cannot parse MCP config %s: 'mcp_servers' is not a table", item.path)
        return None
    return servers


def _reason(
    root: Path, item: _McpFile, name: str, args: list[Any], templates: set[str], enabled: set[str] | None
) -> tuple[StaleMcpReason, str] | None:
    """Return the highest-precedence stale reason for one toolkit entry."""
    if name not in templates:
        return "retired-toolkit", f"toolkit {name!r} has no packaged template"

    config = args[3] if len(args) >= 4 and args[2] == "--config" and isinstance(args[3], str) else None
    config_path = Path(config) if config is not None else None
    if item.scope == "repo":
        if config_path is not None and config_path.is_absolute():
            resolved_config = config_path.resolve()
            resolved_root = root.resolve()
            if resolved_config != resolved_root and resolved_root not in resolved_config.parents:
                return "foreign-repo", f"toolkit config points outside this repository: {config}"
        if enabled is not None and name not in enabled:
            return "undeclared", f"toolkit {name!r} is not enabled in this repository"
    elif config_path is not None and config_path.is_absolute():
        repository = config_path.parent.parent
        if not repository.is_dir():
            return "missing-repo", f"pinned repository does not exist: {repository}"
    return None


def find_stale_mcp_entries(
    root: Path, hosts: Sequence[str], *, gemini_config: Path | None = None
) -> list[StaleMcpEntry]:
    """Find stale toolkit entries without modifying their host config files.

    Args:
        root: Repository whose host files and toolkit declarations are checked.
        hosts: Host names to inspect.
        gemini_config: Optional global Gemini config override.

    ``parrot-agent-*`` entries (FEAT-877) are known when this repository declares the section. They
    are also deliberately treated as known when the config is unreadable or the entry lives in a
    user-global host file: a global entry may have been installed from another repository, so this
    repository's config cannot prove it retired. Retired repo-scoped agent entries are reported.

    Returns:
        Stale entries sorted by display file and key.

    Raises:
        ValueError: If ``hosts`` contains an unknown host.
    """
    unknown = sorted(set(hosts) - set(_HOSTS))
    if unknown:
        raise ValueError(f"unknown host(s): {', '.join(unknown)}")
    templates = set(available_templates())
    agent_sections: set[str] = set()
    config_readable = True
    try:
        cfg = load_toolkits_config(root)
        enabled: set[str] | None = {name for name, section in cfg.toolkits.items() if section.enabled}
        agent_sections = {name for name, section in cfg.toolkits.items() if is_agent_section(section)}
    except ValueError as exc:
        logger.warning("toolkit config unreadable (%s); `undeclared` entries are not reported", exc)
        enabled = None
        config_readable = False
    known = templates | agent_sections

    found: list[StaleMcpEntry] = []
    for item in _mcp_files(root, hosts, gemini_config):
        servers = _read_servers(item)
        if servers is None:
            continue
        for key, entry in servers.items():
            if not is_parrot_toolkit_entry(key, entry):
                continue
            name = key[len("parrot-") :]
            item_known = known
            if name.startswith(AGENT_SECTION_PREFIX) and (not config_readable or item.scope == "global"):
                item_known = known | {name}
            stale_reason = _reason(root, item, name, entry["args"], item_known, enabled)
            if stale_reason is None:
                continue
            reason, detail = stale_reason
            found.append(StaleMcpEntry(host=item.host, file=item.display, key=key, reason=reason, detail=detail))
    return sorted(found, key=lambda entry: (entry.file, entry.key))


def _remove_from_file(item: _McpFile, keys: Sequence[str]) -> tuple[list[str], str | None]:
    """Delete ``keys`` from one config file and write it once.

    Args:
        item: Config file to update.
        keys: Candidate server keys identified as stale.

    Returns:
        Removed keys and an optional warning line.
    """
    try:
        if item.fmt == "json":
            data = _load_mcp_config(item.path)
            servers = data["mcpServers"]
            removed = [key for key in keys if key in servers and is_parrot_toolkit_entry(key, servers[key])]
            if removed:
                for key in removed:
                    servers.pop(key)
                _save_mcp_config(item.path, data)
            return removed, None

        text = item.path.read_text(encoding="utf-8")
        servers = tomllib.loads(text).get("mcp_servers", {})
        if not isinstance(servers, dict):
            raise RuntimeError(f"{item.path}: 'mcp_servers' is not a table")
        removed = [key for key in keys if key in servers and is_parrot_toolkit_entry(key, servers[key])]
        if not removed:
            return [], None
        for key in removed:
            text = _remove_server_table(text, key)
        if codex_assets.MCP_BEGIN in text:
            _, _, rest = text.partition(codex_assets.MCP_BEGIN)
            block = rest.partition(codex_assets.MCP_END)[0] if codex_assets.MCP_END in rest else rest
            if not any(line.lstrip().startswith("[") for line in block.splitlines()):
                text = _remove_marker_block(text, codex_assets.MCP_BEGIN, codex_assets.MCP_END)
        _validate_toml(item.path, text)
        left = tomllib.loads(text).get("mcp_servers", {})
        still = [key for key in removed if isinstance(left, dict) and key in left]
        if still:
            raise RuntimeError(f"could not remove {', '.join(still)} (unsupported TOML layout)")
        item.path.write_text(text, encoding="utf-8")
        return removed, None
    except (OSError, RuntimeError, tomllib.TOMLDecodeError) as exc:
        return [], f"warning: {item.display} — not changed ({exc})"


_TABLE_LINE = re.compile(r"^\s*\[(?!\[)(.+?)\]\s*(?:#.*)?$")


def _table_key_path(header: str) -> list[str] | None:
    """Return the dotted key path of a ``[table]`` header, decoding quoted keys; ``None`` if it is not one."""
    try:
        node: Any = tomllib.loads(f"[{header}]\n")
    except tomllib.TOMLDecodeError:
        return None
    path: list[str] = []
    while isinstance(node, dict) and len(node) == 1:
        key, node = next(iter(node.items()))
        path.append(key)
    return path or None


def _remove_server_table(text: str, key: str) -> str:
    """Remove ``[mcp_servers.<key>]`` and its sub-tables, matching bare and quoted spellings of the key."""
    target = ["mcp_servers", key]
    lines = text.splitlines(keepends=True)
    kept: list[str] = []
    inside = False
    for line in lines:
        match = _TABLE_LINE.match(line.rstrip("\n"))
        if match is not None:
            path = _table_key_path(match.group(1).strip())
            inside = path is not None and path[:2] == target
        if not inside:
            kept.append(line)
    return "".join(kept).rstrip("\n") + "\n"


def remove_stale_mcp_entries(
    root: Path,
    hosts: Sequence[str],
    *,
    keep: Sequence[str] = (),
    dry_run: bool = False,
    gemini_config: Path | None = None,
) -> list[str]:
    """Remove stale toolkit MCP entries from selected host configuration files.

    Args:
        root: Repository owning repo-scoped host configuration files.
        hosts: Host names whose configuration files are eligible for cleanup.
        keep: Globs matching ``<file>#<key>`` entries to retain.
        dry_run: Return the planned changes without writing any file.
        gemini_config: Optional global Gemini MCP config override.

    Returns:
        Per-entry removal, retention, warning, approval, and re-registration lines.
    """
    entries = find_stale_mcp_entries(root, hosts, gemini_config=gemini_config)
    if not entries:
        return ["no stale MCP entries"]

    kept = [entry for entry in entries if any(fnmatch(f"{entry.file}#{entry.key}", glob) for glob in keep)]
    to_remove = [entry for entry in entries if entry not in kept]
    if dry_run:
        return [
            *[f"plan: stale-mcp-remove {entry.file}#{entry.key} ({entry.reason})" for entry in to_remove],
            *[f"plan: keep-stale {entry.file}#{entry.key} (--keep)" for entry in kept],
        ]

    files = {item.display: item for item in _mcp_files(root, hosts, gemini_config)}
    by_file: dict[str, list[StaleMcpEntry]] = {}
    for entry in to_remove:
        by_file.setdefault(entry.file, []).append(entry)

    lines: list[str] = []
    removed_claude_keys: list[str] = []
    removed_toolkits: set[str] = set()
    for file, file_entries in by_file.items():
        item = files[file]
        removed, warning = _remove_from_file(item, [entry.key for entry in file_entries])
        entries_by_key = {entry.key: entry for entry in file_entries}
        for key in removed:
            entry = entries_by_key[key]
            lines.append(f"{entry.file}#{key} — removed ({entry.reason})")
            removed_toolkits.add(key[len("parrot-") :])
            if item.host == "claude":
                removed_claude_keys.append(key)
        if warning is not None:
            lines.append(warning)

    lines.extend(f"{entry.file}#{entry.key} — kept (--keep)" for entry in kept)
    if removed_claude_keys:
        approval_message = uninstall_toolkit_approvals(root, removed_claude_keys)
        if approval_message is not None:
            lines.append(approval_message)
    try:
        enabled = {name for name, section in load_toolkits_config(root).toolkits.items() if section.enabled}
    except ValueError:
        enabled = set()
    names = sorted(removed_toolkits & enabled)
    if names:
        lines.append(f"note: re-register with `parrot toolkits install {' '.join(names)}`")
    return lines
