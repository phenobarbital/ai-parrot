"""Managed Bookstore MCP and skill installation for Codex."""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

from parrot.knowledge.bookstore.config import resolve_locations

from .bookstore_assets import BOOKSTORE_SKILL

MCP_BEGIN = "# >>> parrot-bookstore Codex MCP >>>"
MCP_END = "# <<< parrot-bookstore Codex MCP <<<"
SKILL_PATH = Path(".agents/skills/bookstore/SKILL.md")


def _config(root: Path) -> tuple[Path, str]:
    """Read and validate before mutating a user-owned configuration."""
    from .installer import _validate_toml

    path = root / ".codex/config.toml"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    _validate_toml(path, text)
    if text.count(MCP_BEGIN) != text.count(MCP_END) or text.count(MCP_BEGIN) > 1:
        raise RuntimeError(f"Incomplete or duplicate Bookstore markers in {path}")
    if MCP_BEGIN in text and text.index(MCP_BEGIN) > text.index(MCP_END):
        raise RuntimeError(f"Reversed Bookstore markers in {path}")
    return path, text


def mcp_block(root: Path) -> str:
    """Use the installer environment and explicit target cwd in any project."""
    return "\n".join(
        [
            MCP_BEGIN,
            "[mcp_servers.bookstore]",
            f"command = {json.dumps(sys.executable)}",
            'args = ["-m", "parrot.knowledge.bookstore.cli", "mcp"]',
            f"cwd = {json.dumps(str(root.resolve()))}",
            'env_vars = ["PARROT_LIBRARY_DIR", "PARROT_HOME", ' '"PARROT_BOOKSTORE_LLM", "PARROT_BOOKSTORE_LLM_LIGHT"]',
            "startup_timeout_sec = 30",
            "tool_timeout_sec = 180",
            MCP_END,
            "",
        ]
    )


def install_bookstore(root: Path) -> list[str]:
    """Install for an existing library; silently omit unavailable Bookstore."""
    from .installer import _remove_marker_block, _upsert_marker_block, _validate_toml

    path, before = _config(root)
    outside = _remove_marker_block(before, MCP_BEGIN, MCP_END)
    if not resolve_locations(cwd=root, require_exists=True):
        # Reconcile an earlier managed registration if its library disappeared.
        # User-owned server settings and existing skills remain untouched.
        if outside != before:
            path.write_text(outside, encoding="utf-8")
        return []
    actions: list[str] = []
    if "bookstore" in tomllib.loads(outside).get("mcp_servers", {}):
        actions.append("bookstore MCP — existing user configuration preserved")
    else:
        after = _upsert_marker_block(before, mcp_block(root), MCP_BEGIN, MCP_END)
        _validate_toml(path, after)
        if after != before:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(after, encoding="utf-8")
        actions.append("bookstore MCP — installed" if after != before else "bookstore MCP — already current")

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
    """Remove the managed MCP block and unmodified packaged skill only."""
    from .installer import _remove_marker_block

    path, before = _config(root)
    after = _remove_marker_block(before, MCP_BEGIN, MCP_END)
    actions: list[str] = []
    if after != before:
        path.write_text(after, encoding="utf-8")
        actions.append("bookstore MCP — removed")
    skill = root / SKILL_PATH
    if skill.exists() and skill.read_text(encoding="utf-8") == BOOKSTORE_SKILL:
        skill.unlink()
        actions.append(f"{SKILL_PATH} — removed")
    return actions


def bookstore_status(root: Path) -> dict[str, bool]:
    """Report configured server and discoverable skill, including user-owned ones."""
    _, text = _config(root)
    return {
        "bookstore_mcp": "bookstore" in tomllib.loads(text).get("mcp_servers", {}),
        "bookstore_skill": (root / SKILL_PATH).is_file(),
    }
