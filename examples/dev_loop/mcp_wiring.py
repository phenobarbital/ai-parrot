"""Research-seat MCP wiring for the dev-loop example consoles (FEAT-484/485).

Builds the ``(mcp_servers, mcp_tools)`` pair both consoles forward to the
research seats — ``ResearchNode`` (ops console, ``server.py``) and
``IdeationNode`` (dev console, ``server_dev.py``) — so the dispatched
research agents can reach:

* the **LLM-wiki graph-search** MCP server (``wikitoolkit mcp``, FEAT-403),
  read-only: ``wiki_query`` / ``wiki_page`` / ``wiki_related``; and
* the **FEAT-485 local toolkit servers** (``parrot mcp-local <name>``)
  declared in ``<repo>/.parrot/mcp-toolkits.yaml`` — e.g. a ``repo``
  section exposing the FEAT-484 :class:`~parrot.tools.repo.ReadOnlyRepoToolkit`
  for confined repository access (see ``mcp-toolkits.example.yaml``).

Everything degrades gracefully: a missing binary, a missing/invalid YAML,
or an unknown section name logs a warning and yields whatever subset still
resolves — MCP access is additive and never blocks server startup.

Environment:
    DEV_LOOP_RESEARCH_MCP_ENABLED: Kill switch (default ``true``).
    DEV_LOOP_RESEARCH_MCP_TOOLKITS: Comma-separated section names from
        ``.parrot/mcp-toolkits.yaml`` to serve, or ``auto`` (default) for
        exactly the sections DECLARED IN THE FILE. ``auto`` deliberately
        skips undeclared built-ins (``scraping``/``browsing``/``memory``):
        those may need optional extras and must not be auto-spawned.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

import yaml

from parrot import conf
from parrot.flows.dev_loop.mcp_profiles import WIKI_MCP_TOOLS
from parrot.knowledge.wiki.claude_code.assets import (
    resolve_wikitoolkit_bin,
    toolkit_mcp_json_entry,
)
from parrot.mcp.toolkit_config import load_toolkits_config

logger = logging.getLogger("dev_loop.mcp_wiring")

_TRUTHY = {"1", "true", "yes", "on"}


def _config_flag(key: str, default: bool) -> bool:
    """Read a boolean config key via ``conf.config.get``.

    Deliberately avoids ``getboolean``: the server-wiring tests stub
    ``conf.config`` with a minimal ``get``/``getint`` mock.
    """
    raw = conf.config.get(key, fallback=str(default))
    return str(raw).strip().lower() in _TRUTHY


def _declared_section_names(config_path: Path) -> list[str]:
    """Return the toolkit names DECLARED in the YAML file itself.

    ``load_toolkits_config`` merges built-ins in, so ``auto`` mode reads the
    raw file to know which sections the operator actually wrote down.

    Args:
        config_path: Path to ``.parrot/mcp-toolkits.yaml``.

    Returns:
        The file's ``toolkits:`` keys, or ``[]`` when the file is absent or
        unreadable (the caller logs the loader's own error separately).
    """
    if not config_path.exists():
        return []
    try:
        with open(config_path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except yaml.YAMLError:
        return []
    toolkits = data.get("toolkits") if isinstance(data, dict) else None
    return list(toolkits.keys()) if isinstance(toolkits, dict) else []


def build_research_mcp(repo_root: Path) -> tuple[dict[str, Any], list[str]]:
    """Build the research seats' MCP servers and their allow rules.

    Args:
        repo_root: The repository the console serves (normally
            ``conf.PROJECT_ROOT``). Used to resolve the ``wikitoolkit`` /
            ``parrot`` binaries and ``.parrot/mcp-toolkits.yaml``.

    Returns:
        ``(mcp_servers, mcp_tools)`` — the dict/list to pass as
        ``research_mcp_servers`` / ``research_mcp_tools`` to
        ``build_dev_loop_flow`` / ``build_dev_flow``. ``({}, [])`` when
        nothing usable resolved (callers then pass ``None`` to keep the
        dispatch profiles byte-identical).
    """
    enabled = _config_flag("DEV_LOOP_RESEARCH_MCP_ENABLED", True)
    if not enabled:
        logger.info("Research-seat MCP wiring disabled (DEV_LOOP_RESEARCH_MCP_ENABLED=false).")
        return {}, []

    repo_root = Path(repo_root).resolve()
    servers: dict[str, Any] = {}
    tools: list[str] = []

    # 1. LLM-wiki graph search (FEAT-403). Read-only tool trio; skipped
    # with a warning when the binary cannot be resolved, matching the
    # consoles' existing missing-wikitoolkit warning for Bash triage.
    wikitoolkit_cmd = resolve_wikitoolkit_bin(repo_root)
    if Path(wikitoolkit_cmd).is_file() or shutil.which(wikitoolkit_cmd):
        servers["wikitoolkit"] = {"command": wikitoolkit_cmd, "args": ["mcp"], "env": {}}
        tools.extend(WIKI_MCP_TOOLS)
    else:
        logger.warning(
            "wikitoolkit binary not found (looked at %r) — research agents "
            "get no wiki graph-search MCP server.",
            wikitoolkit_cmd,
        )

    # 2. FEAT-485 local toolkit servers from .parrot/mcp-toolkits.yaml.
    config_path = repo_root / ".parrot" / "mcp-toolkits.yaml"
    selection_raw = conf.config.get("DEV_LOOP_RESEARCH_MCP_TOOLKITS", fallback="auto").strip()
    try:
        cfg = load_toolkits_config(repo_root)
    except ValueError as exc:
        logger.warning("Ignoring invalid %s: %s", config_path, exc)
        return servers, tools

    if selection_raw.lower() == "auto":
        selected = _declared_section_names(config_path)
    else:
        selected = [name.strip() for name in selection_raw.split(",") if name.strip()]

    for name in selected:
        section = cfg.toolkits.get(name)
        if section is None:
            logger.warning(
                "DEV_LOOP_RESEARCH_MCP_TOOLKITS names unknown toolkit %r "
                "(resolvable: %s) — skipped.",
                name,
                ", ".join(sorted(cfg.toolkits)),
            )
            continue
        if not section.enabled:
            logger.info("Toolkit %r is disabled in %s — skipped.", name, config_path)
            continue
        entry = toolkit_mcp_json_entry(repo_root, name, section)
        if config_path.exists():
            # The MCP host spawns `parrot mcp-local` with the DISPATCH cwd
            # (dev-loop research runs from WORKTREE_BASE_PATH, not the repo
            # root), so the server must be told where the config lives.
            entry["args"] = [*entry["args"], "--config", str(config_path)]
        servers[f"parrot-{name}"] = entry
        # Server-level allow rule ("every tool of this server") — per-tool
        # enumeration would require importing each toolkit class here.
        tools.append(f"mcp__parrot-{name}")

    return servers, tools
