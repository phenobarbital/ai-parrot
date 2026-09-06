"""Managed assets for Google Antigravity / Gemini CLI WikiToolkit integration."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from parrot.mcp.toolkit_config import ToolkitSection

AGENTS_BEGIN = "<!-- parrot:wiki:google:begin -->"
AGENTS_END = "<!-- parrot:wiki:google:end -->"
GEMINI_PATH = Path("GEMINI.md")
SKILL_PATH = Path(".agents/skills/parrot-wiki/SKILL.md")
ALT_SKILL_PATH = Path(".agent/skills/parrot-wiki/SKILL.md")
PLUGIN_DIR = Path(".agents/plugins/parrot")

NUDGE = (
    "This repository has an ai-parrot LLM-wiki. Before scanning source files, "
    'run `wikitoolkit query "<focused question>"` or use the `wiki_*` MCP tools, '
    "then inspect a result with `wikitoolkit page <id>` or `wikitoolkit related <id>`. "
    "When you learn a durable fact or decision, save it: "
    '`wikitoolkit remember "<fact>" --category decision`.'
)

GEMINI_SECTION = f"""{AGENTS_BEGIN}
## Codebase Knowledge Graph (LLM Wiki)

{NUDGE}

{AGENTS_END}
"""

SKILL = """---
name: parrot-wiki
description: Query the repository LLM-wiki before raw source scans, and save durable knowledge into it.
---

# Parrot Wiki

Start codebase investigations with `wikitoolkit query "<focused question>"`
or the native MCP tools (`wiki_query`, `wiki_page`, `wiki_related`,
`wiki_symbol_lookup`, `wiki_code_outline`, `wiki_blast_radius`). Fall back to
raw search only after those paths are empty.

The wiki is also persistent memory. Save durable facts, decisions, and lessons
with `wikitoolkit remember "<fact>" --category <note|decision|lesson|concept>`
or the `wiki_remember` MCP tool. Use `wikitoolkit note`, `wikitoolkit link`,
`wikitoolkit memories`, and `wikitoolkit audit` to maintain and review that knowledge.
"""


def default_mcp_config_path() -> Path:
    """Return the user-level Antigravity MCP configuration path (~/.gemini/config/mcp_config.json)."""
    return Path.home() / ".gemini" / "config" / "mcp_config.json"


def resolve_binary(root: Path, name: str) -> str:
    """Resolve a project-venv binary, then PATH, then bare name."""
    venv_binary = root / ".venv" / "bin" / name
    if venv_binary.exists():
        return str(venv_binary)
    return shutil.which(name) or name


def wikitoolkit_mcp_entry(root: Path) -> dict[str, Any]:
    """Build the wikitoolkit MCP server entry for Antigravity."""
    return {
        "command": resolve_binary(root, "wikitoolkit"),
        "args": ["mcp"],
        "cwd": str(root.resolve()),
    }


def toolkit_mcp_entries(root: Path, sections: dict[str, ToolkitSection]) -> dict[str, dict[str, Any]]:
    """Build dictionary of parrot-<name> MCP server entries for enabled toolkits."""
    entries: dict[str, dict[str, Any]] = {}
    parrot_bin = resolve_binary(root, "parrot")
    for name in sorted(sections):
        section = sections[name]
        entry: dict[str, Any] = {
            "command": parrot_bin,
            "args": ["mcp-local", name],
            "cwd": str(root.resolve()),
        }
        if section.env:
            entry["env"] = dict(section.env)
        entries[f"parrot-{name}"] = entry
    return entries


def bookstore_mcp_entry(root: Path) -> dict[str, Any]:
    """Build bookstore PageIndex MCP server entry for Antigravity."""
    env: dict[str, str] = {}
    for key in (
        "PARROT_LIBRARY_DIR",
        "PARROT_HOME",
        "PARROT_BOOKSTORE_LLM",
        "PARROT_BOOKSTORE_LLM_LIGHT",
    ):
        val = os.environ.get(key)
        if val:
            env[key] = val

    entry: dict[str, Any] = {
        "command": sys.executable,
        "args": ["-m", "parrot.knowledge.bookstore.cli", "mcp"],
        "cwd": str(root.resolve()),
    }
    if env:
        entry["env"] = env
    return entry


def plugin_manifest() -> dict[str, Any]:
    """Manifest for .agents/plugins/parrot/plugin.json."""
    return {
        "name": "parrot",
        "description": "ai-parrot knowledge base and MCP local tools",
    }
