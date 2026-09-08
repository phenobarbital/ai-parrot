"""Managed Bookstore PageIndex MCP and skill installation for Google Antigravity."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from parrot.knowledge.bookstore.config import resolve_locations

from . import assets
from .bookstore_assets import BOOKSTORE_SKILL

SKILL_PATH = Path(".agents/skills/bookstore/SKILL.md")
ALT_BOOKSTORE_SKILL_PATH = Path(".agent/skills/bookstore/SKILL.md")


def _is_managed_bookstore_entry(entry: Any) -> bool:
    """Check if an MCP server entry matches our managed bookstore entry."""
    if not isinstance(entry, dict):
        return False
    args = entry.get("args")
    return args == ["-m", "parrot.knowledge.bookstore.cli", "mcp"]


def _load_mcp_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"mcpServers": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Cannot parse {path} — fix or remove it first: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"{path} must contain a JSON object")
    if "mcpServers" not in data or not isinstance(data["mcpServers"], dict):
        data["mcpServers"] = {}
    return data


def _save_mcp_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def install_bookstore(root: Path, mcp_path: Optional[Path] = None) -> list[str]:
    """Install Bookstore PageIndex MCP and skill when an indexed library exists."""
    root = root.resolve()
    target_mcp = mcp_path or assets.default_mcp_config_path()
    actions: list[str] = []

    mcp_data = _load_mcp_json(target_mcp)
    servers = mcp_data.setdefault("mcpServers", {})

    locations = resolve_locations(cwd=root, require_exists=True)
    if not locations:
        # Reconcile if library disappeared
        if "bookstore" in servers and _is_managed_bookstore_entry(servers["bookstore"]):
            del servers["bookstore"]
            _save_mcp_json(target_mcp, mcp_data)
            actions.append(f"{target_mcp} — bookstore MCP removed (no library found)")
        return actions

    desired_entry = assets.bookstore_mcp_entry(root)
    existing = servers.get("bookstore")

    if existing is not None and not _is_managed_bookstore_entry(existing):
        actions.append("bookstore MCP — existing user configuration preserved")
    elif existing == desired_entry:
        actions.append("bookstore MCP — already current")
    else:
        servers["bookstore"] = desired_entry
        _save_mcp_json(target_mcp, mcp_data)
        actions.append("bookstore MCP — installed" if existing is None else "bookstore MCP — updated")

    # Install skill in .agents/skills/bookstore/SKILL.md
    for skill_rel in (SKILL_PATH, ALT_BOOKSTORE_SKILL_PATH):
        # Always install to SKILL_PATH (.agents); install to ALT only if .agent/skills already exists
        if skill_rel == ALT_BOOKSTORE_SKILL_PATH and not (root / ".agent/skills").exists():
            continue
        skill_file = root / skill_rel
        if skill_file.exists():
            state = (
                "already current"
                if skill_file.read_text(encoding="utf-8") == BOOKSTORE_SKILL
                else "existing user skill preserved"
            )
        else:
            skill_file.parent.mkdir(parents=True, exist_ok=True)
            skill_file.write_text(BOOKSTORE_SKILL, encoding="utf-8")
            state = "installed"
        actions.append(f"{skill_rel} — {state}")

    return actions


def uninstall_bookstore(root: Path, mcp_path: Optional[Path] = None) -> list[str]:
    """Remove managed Bookstore MCP entry and unmodified packaged skill."""
    root = root.resolve()
    target_mcp = mcp_path or assets.default_mcp_config_path()
    actions: list[str] = []

    if target_mcp.exists():
        mcp_data = _load_mcp_json(target_mcp)
        servers = mcp_data.get("mcpServers", {})
        if "bookstore" in servers and _is_managed_bookstore_entry(servers["bookstore"]):
            del servers["bookstore"]
            _save_mcp_json(target_mcp, mcp_data)
            actions.append(f"{target_mcp} — bookstore MCP removed")

    for skill_rel in (SKILL_PATH, ALT_BOOKSTORE_SKILL_PATH):
        skill_file = root / skill_rel
        if skill_file.exists() and skill_file.read_text(encoding="utf-8") == BOOKSTORE_SKILL:
            skill_file.unlink()
            actions.append(f"{skill_rel} — removed")

    return actions


def bookstore_status(root: Path, mcp_path: Optional[Path] = None) -> dict[str, bool]:
    """Report configured Bookstore server and discoverable skill."""
    root = root.resolve()
    target_mcp = mcp_path or assets.default_mcp_config_path()
    mcp_present = False
    if target_mcp.exists():
        try:
            mcp_data = _load_mcp_json(target_mcp)
            mcp_present = "bookstore" in mcp_data.get("mcpServers", {})
        except Exception:
            mcp_present = False

    skill_present = (root / SKILL_PATH).is_file() or (root / ALT_BOOKSTORE_SKILL_PATH).is_file()
    return {
        "bookstore_mcp": mcp_present,
        "bookstore_skill": skill_present,
    }
