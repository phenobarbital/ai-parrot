"""GraphMemoryMixin — persistent knowledge-graph memory for bots.

Opt-in mixin (modeled on ``EpisodicMemoryMixin``) that gives any bot a
durable, per-agent knowledge graph: writes made through the graph tools
survive process restarts ("the agent forgets, the graph does not"), and
task-relevant subgraph context can be injected before each ask.

Usage::

    class MyAgent(GraphMemoryMixin, BasicAgent):
        enable_graph_memory = True

    # inside the bot's configure():
    await self._configure_graph_memory()

The graph plane lives at ``AGENTS_DIR/{agent_id}/graph_memory`` by
default (same convention as ``kb/``, ``skills/``, ``episodic_data``),
overridable via ``graph_memory_path``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class GraphMemoryMixin:
    """Mixin that adds persistent graph memory to bots.

    Configuration attributes (override in subclass or set via kwargs):
        enable_graph_memory: Master toggle for the mixin.
        graph_memory_path: Directory of the SQLite graph plane; defaults
            to ``AGENTS_DIR/{agent_id}/graph_memory``.
        graph_memory_tenant: Tenant id inside the plane (one ``.db`` per
            tenant).
        graph_memory_inject_context: Whether ``_build_graph_context``
            should produce pre-ask context.
        graph_memory_context_tokens: Token budget for injected context.
        graph_memory_dimension: Embedding dimension for the default
            offline embedder.
    """

    enable_graph_memory: bool = False
    graph_memory_path: Optional[str] = None
    graph_memory_tenant: str = "default"
    graph_memory_inject_context: bool = True
    graph_memory_context_tokens: int = 4000
    graph_memory_dimension: int = 256

    _graph_memory_toolkit: Any = None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def _get_graph_agent_id(self) -> str:
        """Agent identifier used for attribution and the storage path."""
        return str(getattr(self, "name", None) or "agent")

    def _resolve_graph_memory_path(self) -> Optional[str]:
        """Resolve the graph plane directory.

        Priority: explicit ``graph_memory_path`` >
        ``AGENTS_DIR/{agent_id}/graph_memory`` (the framework-wide
        per-agent data convention).

        Returns:
            Resolved path string, or ``None`` when no location is
            configured and ``AGENTS_DIR`` is unavailable.
        """
        if self.graph_memory_path is not None:
            return self.graph_memory_path
        agents_dir = None
        if hasattr(self, "_resolve_agents_dir"):
            agents_dir = self._resolve_agents_dir()
        if agents_dir is None:
            try:
                from parrot.conf import AGENTS_DIR
            except Exception:  # noqa: BLE001 — conf stack optional in tests
                return None
            if AGENTS_DIR is None:
                return None
            agents_dir = Path(AGENTS_DIR)
        return str(Path(agents_dir) / self._get_graph_agent_id() / "graph_memory")

    async def _configure_graph_memory(self) -> None:
        """Open (or create) the persistent graph and register its tools.

        Call this from the bot's ``configure()``. Idempotent — repeated
        calls (multi-configure hosts) neither rebuild the toolkit nor
        re-register tools.
        """
        if not self.enable_graph_memory:
            return
        if self._graph_memory_toolkit is not None:
            return

        path = self._resolve_graph_memory_path()
        if path is None:
            logger.warning(
                "GraphMemoryMixin: no storage path resolvable — set "
                "graph_memory_path or configure AGENTS_DIR."
            )
            return

        tool_manager = getattr(self, "tool_manager", None)
        if tool_manager is not None and tool_manager.get_tool(
            "graph_history"
        ) is not None:
            return

        try:
            from parrot.knowledge.graphindex.factory import (
                build_graph_memory_toolkit,
            )

            toolkit = await build_graph_memory_toolkit(
                db_dir=Path(path),
                tenant_id=self.graph_memory_tenant,
                agent_id=self._get_graph_agent_id(),
                client=getattr(self, "_llm", None),
                dimension=self.graph_memory_dimension,
            )
            self._graph_memory_toolkit = toolkit

            # Register the tools and expose the toolkit on the bot's
            # knowledge-toolkit slot (same seam ToolInterface uses).
            if tool_manager is not None:
                for tool in toolkit.get_tools():
                    tool_manager.register_tool(tool)
            if hasattr(self, "_capture_knowledge_toolkit"):
                self._capture_knowledge_toolkit(toolkit)
            elif getattr(self, "_graphindex_toolkit", None) is None:
                self._graphindex_toolkit = toolkit

            logger.info(
                "Graph memory configured: %s (tenant=%s, %d nodes)",
                path,
                self.graph_memory_tenant,
                toolkit.graph.num_nodes(),
            )
        except Exception as exc:  # noqa: BLE001 — memory is optional
            logger.error("GraphMemoryMixin configuration failed: %s", exc)
            self._graph_memory_toolkit = None

    # ------------------------------------------------------------------
    # Ask-flow hooks
    # ------------------------------------------------------------------

    def set_graph_memory_run(self, run_id: Optional[str]) -> None:
        """Stamp subsequent graph writes with a run/session id."""
        if self._graph_memory_toolkit is not None:
            self._graph_memory_toolkit.run_id = run_id

    async def _build_graph_context(self, query: str) -> Optional[str]:
        """Build pre-ask context from the agent's graph memory.

        Returns ``None`` when the mixin is disabled, unconfigured, the
        graph is empty, or context injection is switched off — callers
        can append the result to the system prompt unconditionally.

        Args:
            query: The user query/task to ground.

        Returns:
            Markdown context text, or ``None``.
        """
        if (
            not self.enable_graph_memory
            or not self.graph_memory_inject_context
            or self._graph_memory_toolkit is None
        ):
            return None
        toolkit = self._graph_memory_toolkit
        if toolkit.graph.num_nodes() == 0:
            return None
        try:
            from parrot.knowledge.graphindex.context_builder import (
                ContextBuildConfig,
                GraphContextBuilder,
            )
            from parrot.knowledge.graphindex.retriever import (
                GraphExpandedRetriever,
            )

            retriever = GraphExpandedRetriever(
                graph=toolkit.graph,
                nodes=toolkit.nodes,
                embedder=toolkit.embedder,
                signal_config=toolkit.signal_config,
            )
            builder = GraphContextBuilder(retriever)
            context = await builder.build(
                query,
                ContextBuildConfig(
                    max_tokens=self.graph_memory_context_tokens,
                ),
            )
            if not context.node_ids:
                return None
            return context.text
        except Exception as exc:  # noqa: BLE001 — context is best-effort
            logger.warning("GraphMemoryMixin context build failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    async def flush_graph_memory(self) -> None:
        """Delete the persisted graph plane for this agent's tenant.

        Removes the tenant's ``.db`` file (and its WAL/SHM sidecars).
        The in-memory toolkit is dropped so the next
        ``_configure_graph_memory`` starts from a clean slate.
        """
        path = self._resolve_graph_memory_path()
        if path:
            base = Path(path)
            for suffix in ("", "-wal", "-shm"):
                target = base / f"{self.graph_memory_tenant}.db{suffix}"
                if target.exists():
                    target.unlink()
                    logger.info("Graph memory flush: removed %s", target)
        self._graph_memory_toolkit = None
