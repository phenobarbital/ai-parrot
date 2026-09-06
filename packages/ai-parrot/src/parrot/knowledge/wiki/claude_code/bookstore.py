"""Managed Bookstore MCP and skill installation for Claude Code.

Mirrors ``codex/bookstore.py``, adapted to Claude Code's JSON
``.mcp.json`` shape and its ``.claude/skills/<name>/SKILL.md``
skill-file convention (in place of Codex's TOML MCP table and
``.agents/skills/`` layout).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from parrot.knowledge.bookstore.config import resolve_locations

from .bookstore_assets import BOOKSTORE_SKILL

SKILL_PATH = Path(".claude/skills/bookstore/SKILL.md")

#: Managed-entry detection rule (mirrors FEAT-485's
#: ``_is_managed_toolkit_entry``): an entry is "ours" iff its ``args``
#: match this exact shape. A ``bookstore`` key with different args is a
#: foreign/user entry and must never be overwritten or removed.
_MANAGED_ARGS = ["-m", "parrot.knowledge.bookstore.cli", "mcp"]


def mcp_json_entry(root: Path) -> dict:
    """Build the managed ``.mcp.json`` entry for the bookstore MCP server."""
    return {
        "command": sys.executable,
        "args": list(_MANAGED_ARGS),
        "cwd": str(root.resolve()),
        "env": {},
    }


def _is_managed_entry(entry: Any) -> bool:
    """Whether a ``.mcp.json['mcpServers']['bookstore']`` entry is ours."""
    return isinstance(entry, dict) and entry.get("args") == _MANAGED_ARGS


def _load_mcp_json(path: Path) -> dict:
    """Read ``.mcp.json``; tolerate absence or corruption as empty."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_mcp_json(path: Path, data: dict, servers: dict) -> None:
    """Persist ``data`` after reconciling an emptied ``mcpServers``."""
    if servers:
        data["mcpServers"] = servers
    else:
        data.pop("mcpServers", None)
    if data:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    elif path.exists():
        path.unlink()


def install_bookstore(root: Path) -> list[str]:
    """Install for an existing library; silently omit unavailable Bookstore."""
    path = root / ".mcp.json"
    data = _load_mcp_json(path)
    servers = data.get("mcpServers")
    servers = dict(servers) if isinstance(servers, dict) else {}

    if not resolve_locations(cwd=root, require_exists=True):
        # Reconcile an earlier managed registration if its library
        # disappeared. User-owned server settings and existing skills
        # remain untouched.
        if "bookstore" in servers and _is_managed_entry(servers["bookstore"]):
            del servers["bookstore"]
            _write_mcp_json(path, data, servers)
        return []

    actions: list[str] = []
    entry = mcp_json_entry(root)
    existing = servers.get("bookstore")
    if existing == entry:
        actions.append("bookstore MCP — already current")
    elif existing is not None and not _is_managed_entry(existing):
        actions.append("bookstore MCP — existing user configuration preserved")
    else:
        servers["bookstore"] = entry
        _write_mcp_json(path, data, servers)
        actions.append("bookstore MCP — " + ("updated" if existing is not None else "installed"))

    skill = root / SKILL_PATH
    if skill.exists():
        state = (
            "already current"
            if skill.read_text(encoding="utf-8") == BOOKSTORE_SKILL
            else "existing user skill preserved"
        )
    else:
        skill.parent.mkdir(parents=True, exist_ok=True)
        skill.write_text(BOOKSTORE_SKILL, encoding="utf-8")
        state = "installed"
    actions.append(f"{SKILL_PATH} — {state}")
    return actions


def uninstall_bookstore(root: Path) -> list[str]:
    """Remove the managed MCP entry and unmodified packaged skill only."""
    path = root / ".mcp.json"
    data = _load_mcp_json(path)
    servers = data.get("mcpServers")
    servers = dict(servers) if isinstance(servers, dict) else {}

    actions: list[str] = []
    if "bookstore" in servers and _is_managed_entry(servers["bookstore"]):
        del servers["bookstore"]
        _write_mcp_json(path, data, servers)
        actions.append("bookstore MCP — removed")

    skill = root / SKILL_PATH
    if skill.exists() and skill.read_text(encoding="utf-8") == BOOKSTORE_SKILL:
        skill.unlink()
        actions.append(f"{SKILL_PATH} — removed")
    return actions


def bookstore_status(root: Path) -> dict[str, bool]:
    """Report configured server and discoverable skill, including user-owned ones."""
    data = _load_mcp_json(root / ".mcp.json")
    servers = data.get("mcpServers", {})
    return {
        "bookstore_mcp": isinstance(servers, dict) and "bookstore" in servers,
        "bookstore_skill": (root / SKILL_PATH).is_file(),
    }
