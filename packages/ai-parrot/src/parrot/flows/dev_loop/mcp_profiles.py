"""Shared MCP helpers for dev-loop / dev-flow dispatch profiles.

The research seats of both flows (``dev_loop.ResearchNode`` and
``dev_flow.IdeationNode``) dispatch headless Claude Code sessions with
``strict_mcp_config=True`` (see ``ClaudeCodeDispatchProfile``), which makes
the dispatched CLI ignore any filesystem ``.mcp.json``. Reaching an MCP
server from such a dispatch therefore requires BOTH the explicit server
config on ``profile.mcp_servers`` AND the matching ``mcp__...`` allow rules
on ``profile.allowed_tools``. This module centralizes the pieces both nodes
need so they share one mechanism instead of forking it:

* the read-only wikitoolkit graph-search server entry (FEAT-482 Module 6,
  originally private to ``dev_flow/nodes/ideation.py``), and
* the allow-rule derivation for arbitrary caller-supplied servers — e.g.
  the FEAT-485 ``parrot mcp-local <toolkit>`` servers.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping

#: FEAT-482 Module 6 (§8 Q11): read-only wiki graph-search tools exposed to
#: the research seats. Deliberately excludes the write tools
#: (`wiki_remember` / `wiki_note`) — a research seat may read the graph,
#: never mutate it via this seam.
WIKI_MCP_TOOLS: tuple[str, ...] = (
    "mcp__wikitoolkit__wiki_query",
    "mcp__wikitoolkit__wiki_page",
    "mcp__wikitoolkit__wiki_related",
)


def resolve_wikitoolkit_command() -> str:
    """Resolve the ``wikitoolkit`` CLI path robustly.

    The repo's own ``.mcp.json`` hardcodes an absolute venv path, which
    would break in any other checkout/environment. Resolve it the same
    way any other console-script installed into the running
    interpreter's venv is found: ``PATH`` first (``shutil.which``), then
    a same-directory-as-``sys.executable`` fallback (covers a venv whose
    ``bin/`` is not on ``PATH`` but IS where the running Python lives).

    Returns:
        The resolved ``wikitoolkit`` command path, or the bare
        ``"wikitoolkit"`` string as a last resort (lets the CLI's own
        "not found" error surface instead of silently omitting the tool).
    """
    found = shutil.which("wikitoolkit")
    if found:
        return found
    candidate = Path(sys.executable).parent / "wikitoolkit"
    if candidate.is_file():
        return str(candidate)
    return "wikitoolkit"


def wikitoolkit_mcp_entry() -> Dict[str, Any]:
    """Build the stdio server config for the wikitoolkit MCP server.

    Returns:
        A Claude Code MCP server config dict suitable as the value of a
        ``"wikitoolkit"`` key in ``ClaudeCodeDispatchProfile.mcp_servers``.
    """
    return {
        "command": resolve_wikitoolkit_command(),
        "args": ["mcp"],
        "env": {},
    }


def derive_mcp_tool_names(mcp_servers: Mapping[str, Any]) -> List[str]:
    """Derive server-level allow rules for a set of MCP servers.

    Claude Code accepts a bare ``mcp__<serverName>`` allow rule meaning
    "every tool of that server". Enumerating per-tool names would require
    importing every toolkit class in the calling process, so this is the
    default when the caller does not supply an explicit tool list.

    Args:
        mcp_servers: Mapping of server name → server config (the same
            shape as ``ClaudeCodeDispatchProfile.mcp_servers``).

    Returns:
        Sorted ``["mcp__<name>", ...]`` rules, one per server.
    """
    return [f"mcp__{name}" for name in sorted(mcp_servers)]
