"""Toolkit MCP server factory for local stdio servers.

FEAT-485: Creates a StdioMCPServer for any AbstractToolkit-based class,
with optional LLM wiring and tool filtering (include/exclude/llm_dependent).
"""

import asyncio
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
from parrot.tools.toolkit import AbstractToolkit

logger = logging.getLogger(__name__)

#: Overall wall-clock budget for releasing an owned toolkit's resources on
#: server shutdown (see `_ToolkitStdioMCPServer.stop`). A module constant
#: rather than a literal so tests can shrink it instead of waiting out the
#: real budget.
_CLEANUP_TIMEOUT_SECONDS = 10.0


class _ToolkitStdioMCPServer(StdioMCPServer):
    """A `StdioMCPServer` that also owns the factory-instantiated toolkit.

    FEAT-580 M4: `create_toolkit_mcp_server` builds the toolkit once at
    startup but never released it afterwards — any resources the toolkit
    acquired via its `_open()`/`auto_open` lifecycle (DB pools, HTTP
    sessions, a spawned LSP server process, etc.) leaked for the rest of
    the process's life. This subclass retains a reference to that toolkit
    and releases it whenever the server stops — on a clean stdin EOF, on
    an unhandled error in `start()`, or on an explicit `stop()` call —
    bounded by `_CLEANUP_TIMEOUT_SECONDS` so one misbehaving toolkit can
    never wedge shutdown, with every failure caught and logged in
    isolation rather than propagated.

    Private: constructed only by `create_toolkit_mcp_server`, whose public
    signature, return type (`StdioMCPServer`) and tool filtering are
    unchanged by this class's existence.
    """

    def __init__(self, config: LocalServerConfig, toolkit: AbstractToolkit) -> None:
        super().__init__(config)
        self._owned_toolkit = toolkit
        self._stop_lock = asyncio.Lock()
        self._released = False

    async def start(self) -> None:
        """Serve until stdin EOF or an error, then always release owned resources."""
        try:
            await super().start()
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Stop the read loop, then release the owned toolkit's resources.

        Idempotent and concurrency-safe: safe to call more than once (e.g.
        both from `start()`'s `finally` and from a caller-driven shutdown
        path) and safe to call concurrently — only the first caller to
        acquire the internal lock actually runs the release; the rest
        return immediately once it completes. The whole release is bounded
        by `_CLEANUP_TIMEOUT_SECONDS`; a timeout (or any other failure) is
        logged and swallowed, never propagated, so `stop()` itself can
        never hang or raise on behalf of a broken toolkit.
        """
        await super().stop()

        async with self._stop_lock:
            if self._released:
                return
            self._released = True

            try:
                await asyncio.wait_for(self._release_toolkit(), timeout=_CLEANUP_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                self.logger.error(
                    "Timed out releasing owned toolkit %s after %.0fs",
                    type(self._owned_toolkit).__name__,
                    _CLEANUP_TIMEOUT_SECONDS,
                )

    async def _release_toolkit(self) -> None:
        """Close `_open()`-acquired resources, then run the toolkit's cleanup hook.

        Mirrors `ToolManager.cleanup_toolkits`'s two-phase, error-isolated
        release: `_close()` only runs if `_open()` ever actually ran (a
        toolkit whose `_open()` raised, or one that never opted into
        `auto_open`, is left alone), and each phase's failure is caught
        and logged independently so one broken phase never skips the
        other.
        """
        toolkit = self._owned_toolkit

        if getattr(toolkit, "_opened", False):
            try:
                await toolkit._close()
            except Exception as exc:  # noqa: BLE001 -- isolated shutdown logging
                self.logger.error("Error in _close() for owned toolkit %s: %s", type(toolkit).__name__, exc)
            finally:
                toolkit._opened = False

        # AbstractToolkit.cleanup() AND .stop() are both concrete no-op hooks
        # (never absent), so `getattr(toolkit, "cleanup", None) or
        # getattr(toolkit, "stop", None)` always short-circuits on the first
        # branch and never reaches an existing toolkit's stop()-only
        # override (e.g. WebScrapingToolkit, RSSFeedReaderToolkit,
        # MassiveToolkit release their real resources exclusively via
        # stop()). Call both hooks, independently error-isolated, so a
        # subclass overriding either one still gets released.
        for hook_name in ("cleanup", "stop"):
            cleanup_fn = getattr(toolkit, hook_name, None)
            if not callable(cleanup_fn):
                continue
            try:
                result = cleanup_fn()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:  # noqa: BLE001 -- isolated shutdown logging
                self.logger.error("Error in %s() for owned toolkit %s: %s", hook_name, type(toolkit).__name__, exc)


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

    # Load config — honoring the documented `config_path` override (the
    # `parrot mcp-local --config` flag). Needed because stdio MCP servers
    # inherit the MCP host's cwd, which is not always the project root
    # (e.g. dev-loop research dispatches run from WORKTREE_BASE_PATH).
    config_path = overrides.get("config_path")
    cfg = load_toolkits_config(root, config_path=Path(config_path) if config_path else None)

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
                extra_hint = "  Try: uv pip install ai-parrot-tools[scraping] " "or ai-parrot-tools[browsing]"
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

            # llm_kwargs is trusted server configuration (e.g. the writer's
            # required `fallback_model: null`); it reaches the client
            # constructor verbatim via LLMFactory.create's **kwargs.
            llm_client = LLMFactory.create(section.llm, **section.llm_kwargs)
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

    # Build and return server — FEAT-580 M4: retain the instantiated
    # toolkit so its resources get released on server shutdown.
    server = _ToolkitStdioMCPServer(LocalServerConfig(name=f"parrot-{name}", version="1.0.0"), toolkit)
    server.register_tools(filtered_tools)
    return server
