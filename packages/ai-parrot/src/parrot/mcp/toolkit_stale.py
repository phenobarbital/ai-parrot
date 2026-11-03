"""Stale `parrot-<name>` MCP toolkit entries across the three hosts' config files (FEAT-795 M6)."""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Sequence

from pydantic import BaseModel

from parrot.knowledge.wiki.google.installer import _load_mcp_config, toolkit_config_paths
from parrot.mcp.toolkit_config import load_toolkits_config
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

    Returns:
        Stale entries sorted by display file and key.

    Raises:
        ValueError: If ``hosts`` contains an unknown host.
    """
    unknown = sorted(set(hosts) - set(_HOSTS))
    if unknown:
        raise ValueError(f"unknown host(s): {', '.join(unknown)}")
    templates = set(available_templates())
    try:
        cfg = load_toolkits_config(root)
        enabled: set[str] | None = {name for name, section in cfg.toolkits.items() if section.enabled}
    except ValueError as exc:
        logger.warning("toolkit config unreadable (%s); `undeclared` entries are not reported", exc)
        enabled = None

    found: list[StaleMcpEntry] = []
    for item in _mcp_files(root, hosts, gemini_config):
        servers = _read_servers(item)
        if servers is None:
            continue
        for key, entry in servers.items():
            if not is_parrot_toolkit_entry(key, entry):
                continue
            name = key[len("parrot-") :]
            stale_reason = _reason(root, item, name, entry["args"], templates, enabled)
            if stale_reason is None:
                continue
            reason, detail = stale_reason
            found.append(StaleMcpEntry(host=item.host, file=item.display, key=key, reason=reason, detail=detail))
    return sorted(found, key=lambda entry: (entry.file, entry.key))
