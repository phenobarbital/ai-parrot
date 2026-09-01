"""Toolkit MCP server factory for local stdio servers.

FEAT-485: Creates a StdioMCPServer for any AbstractToolkit-based class,
with optional LLM wiring and tool filtering (include/exclude/llm_dependent).
"""

import contextlib
import importlib
import logging
import sys
from pathlib import Path
from typing import Any

# NOTE: `LLMFactory` is intentionally NOT imported at module level. Its
# import chain (parrot.clients.factory -> ... -> navconfig) triggers
# navconfig's eager settings-loading side effects, which include a raw
# `print()` (not routed through logging) straight to stdout — exactly the
# channel this server reserves for JSON-RPC (FEAT-485 stdout-purity fix,
# discovered by TASK-2650's e2e test). It is imported lazily below, inside
# the same `contextlib.redirect_stdout(sys.stderr)` block that already
# guards the toolkit class resolution import.
from parrot.mcp.local_server import StdioMCPServer
from parrot.mcp.server_base import LocalServerConfig
from parrot.mcp.toolkit_config import load_toolkits_config

logger = logging.getLogger(__name__)


def create_toolkit_mcp_server(
    name: str,
    root: Path = Path.cwd(),
    **overrides: Any,
) -> StdioMCPServer:
    """Create a stdio MCP server for a toolkit.

    Loads config from `.parrot/mcp-toolkits.yaml`, resolves the toolkit class,
    instantiates it with optional LLM support, filters tools by include/exclude
    and LLM availability, and registers them on a StdioMCPServer.

    All imports happen inside a contextlib.redirect_stdout(sys.stderr) block
    to ensure stdout remains a pure JSON-RPC channel.

    Args:
        name: Toolkit name (e.g., "memory", "scraping", "custom").
        root: Project root. Defaults to current working directory.
        **overrides: CLI passthrough:
            - config_path: Override config file path (else `.parrot/mcp-toolkits.yaml`).
            - include: Whitelist of tool names (overrides section's include).
            - exclude: Blacklist of tool names (overrides section's exclude).

    Returns:
        StdioMCPServer configured with the toolkit's (filtered) tools.

    Raises:
        ValueError: If the name is unknown, config is invalid, or toolkit
            instantiation fails. Error messages name the offending section,
            file path, and dependency.
        ImportError: If the toolkit class cannot be resolved (e.g., missing
            extra like ai-parrot-tools[scraping]).
    """
    root = Path(root)

    # Load config
    cfg = load_toolkits_config(root)

    # Check for unknown name
    if name not in cfg.toolkits:
        resolvable = list(cfg.toolkits.keys())
        raise ValueError(f"Unknown toolkit name: '{name}'. Resolvable: {resolvable}")

    section = cfg.toolkits[name]

    # Resolve class inside redirect block (FEAT-403 pattern)
    with contextlib.redirect_stdout(sys.stderr):
        try:
            module_name, class_name = section.class_path.rsplit(".", 1)
            module = importlib.import_module(module_name)
            toolkit_cls = getattr(module, class_name)
        except ImportError as e:
            # Try to suggest the package extra
            if "parrot_tools" in section.class_path:
                extra_hint = f"  Try: uv pip install ai-parrot-tools[scraping] " f"or ai-parrot-tools[browsing]"
            else:
                extra_hint = ""
            raise ImportError(
                f"Cannot import toolkit '{section.class_path}' for '{name}':{extra_hint}\n" f"  Original error: {e}"
            ) from e
        except (ValueError, AttributeError) as e:
            raise ValueError(f"Invalid class path '{section.class_path}' for toolkit '{name}': {e}") from e

        # Wire LLM if configured
        llm_client = None
        drop_tools: set[str] = set()

        if section.llm:
            from parrot.clients.factory import LLMFactory

            llm_client = LLMFactory.create(section.llm)
        else:
            drop_tools = set(toolkit_cls.llm_dependent_tools)

        # Instantiate toolkit
        try:
            kwargs = dict(section.kwargs)
            if llm_client is not None:
                kwargs["llm_client"] = llm_client
            toolkit = toolkit_cls(**kwargs)
        except TypeError as e:
            raise ValueError(f"Failed to instantiate toolkit '{name}' with kwargs {section.kwargs}: {e}") from e

        # Get and filter tools
        all_tools = toolkit.get_tools()

        filtered_tools = all_tools[:]

        # Apply include/exclude/llm_dependent filters
        include = overrides.get("include") or section.include
        exclude = overrides.get("exclude") or section.exclude

        if include:
            # Whitelist: keep only named tools
            include_set = set(include)
            filtered_tools = [t for t in filtered_tools if t.name in include_set]

            # Warn about unknown names
            seen_names = {t.name for t in all_tools}
            unknown = include_set - seen_names
            if unknown:
                logger.warning("Toolkit '%s': include names not found: %s", name, unknown)
        elif exclude:
            # Blacklist: drop named tools
            exclude_set = set(exclude)
            filtered_tools = [t for t in filtered_tools if t.name not in exclude_set]

            # Warn about unknown names
            seen_names = {t.name for t in all_tools}
            unknown = exclude_set - seen_names
            if unknown:
                logger.warning("Toolkit '%s': exclude names not found: %s", name, unknown)

        # Drop LLM-dependent tools if no LLM
        if drop_tools:
            filtered_tools = [t for t in filtered_tools if t.name not in drop_tools]

    # Build and return server
    server = StdioMCPServer(LocalServerConfig(name=f"parrot-{name}", version="1.0.0"))
    server.register_tools(filtered_tools)
    return server
