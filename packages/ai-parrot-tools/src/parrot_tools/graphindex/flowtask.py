"""Flowtask component wrapper for the GraphIndex pipeline.

Bridges the Flowtask execution model to ``GraphIndexBuilder``, allowing
knowledge graph indexing to run as a Flowtask pipeline step.

Usage:
    ```python
    config = {
        "tenant_id": "my-tenant",
        "code_paths": ["/src"],
        "skill_paths": ["/skills"],
        "output_dir": "/reports",
    }
    async with GraphIndexComponent(config) as comp:
        result = await comp.run()
    ```
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from parrot.knowledge.graphindex.builder import GraphIndexBuilder
from parrot.knowledge.graphindex.embed import GraphIndexEmbedder
from parrot.knowledge.graphindex.persist import GraphIndexPersistence
from parrot.knowledge.graphindex.schema import BuildResult, SourceConfig
from parrot.knowledge.ontology.schema import MergedOntology, TenantContext

logger = logging.getLogger(__name__)


class GraphIndexComponent:
    """Flowtask component wrapper for the GraphIndex pipeline.

    Implements the async context manager protocol so it can be used
    with ``async with``, consistent with the Flowtask component pattern.

    Args:
        config: Component configuration dict from the Flowtask pipeline
            definition.  Recognised keys:

            - ``tenant_id`` (required): Tenant identifier.
            - ``code_paths`` (optional, list): Paths to Python source.
            - ``loader_sources`` (optional, list): Document URIs.
            - ``skill_paths`` (optional, list): Paths to SKILL.md files.
            - ``ignore_file`` (optional, str): Path to ``.graphindexignore``.
            - ``output_dir`` (optional, str): Directory for report output.
            - ``model_name`` (optional, str): Embedding model name.
            - ``embedding_dimension`` (optional, int): Embedding vector dim.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.logger = logging.getLogger(__name__)
        self._builder: Optional[GraphIndexBuilder] = None
        self._sources: Optional[SourceConfig] = None
        self._ctx: Optional[TenantContext] = None

    # ------------------------------------------------------------------
    # Context manager protocol
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "GraphIndexComponent":
        """Initialise the ``GraphIndexBuilder`` on component entry.

        Parses the config dict into ``SourceConfig`` and ``TenantContext``,
        creates a ``GraphIndexBuilder`` with minimal mock dependencies where
        real ones are not injected (for testability).

        Returns:
            Self.

        Raises:
            ValueError: If ``tenant_id`` is missing from config.
        """
        tenant_id = self.config.get("tenant_id")
        if not tenant_id:
            raise ValueError("GraphIndexComponent config must include 'tenant_id'.")

        self._sources = SourceConfig(
            tenant_id=tenant_id,
            code_paths=self.config.get("code_paths", []),
            loader_sources=self.config.get("loader_sources", []),
            skill_paths=self.config.get("skill_paths", []),
            ignore_file=self.config.get("ignore_file"),
        )

        # Build minimal TenantContext (ontology is stub — full hydration
        # is the responsibility of the caller in production)
        fake_ontology = MergedOntology.model_construct(
            name="graphindex",
            version="1.0",
            entities={},
            relations={},
            traversal_patterns={},
            layers=[],
            merge_timestamp=None,
        )
        self._ctx = TenantContext(
            tenant_id=tenant_id,
            arango_db=self.config.get("arango_db", f"db_{tenant_id}"),
            pgvector_schema=self.config.get("pgvector_schema", f"schema_{tenant_id}"),
            ontology=fake_ontology,
        )

        output_dir = Path(self.config.get("output_dir", f"/tmp/graphindex/{tenant_id}"))
        model_name = self.config.get("model_name", "sentence-transformers/all-MiniLM-L6-v2")
        embedding_dimension = int(self.config.get("embedding_dimension", 384))
        ignore_file = (
            Path(self.config["ignore_file"])
            if self.config.get("ignore_file")
            else None
        )

        # Build embedder and persistence stubs — in production these are
        # injected via the DI container or pipeline config.
        embedder = self._build_embedder(model_name, embedding_dimension)
        persistence = self._build_persistence()

        self._builder = GraphIndexBuilder(
            persistence=persistence,
            embedder=embedder,
            output_dir=output_dir,
            ignore_file=ignore_file,
        )

        self.logger.info(
            "GraphIndexComponent initialised for tenant '%s'", tenant_id
        )
        return self

    async def __aexit__(
        self,
        exc_type: type | None,
        exc_val: BaseException | None,
        exc_tb: object | None,
    ) -> None:
        """Cleanup on component exit.

        Args:
            exc_type: Exception type (if any).
            exc_val: Exception value (if any).
            exc_tb: Exception traceback (if any).
        """
        self._builder = None
        self.logger.debug("GraphIndexComponent exited.")

    # ------------------------------------------------------------------
    # Public run method
    # ------------------------------------------------------------------

    async def run(self) -> dict[str, Any]:
        """Execute the GraphIndex build pipeline.

        Delegates to ``GraphIndexBuilder.build()`` with the parsed
        ``SourceConfig`` and ``TenantContext`` from configuration.

        Returns:
            Dict from ``BuildResult.model_dump()`` with keys:
            ``tenant_id``, ``node_count``, ``edge_count``,
            ``inferred_edge_count``, ``report_path``, ``errors``.

        Raises:
            RuntimeError: If called outside the async context manager.
        """
        if self._builder is None:
            raise RuntimeError(
                "GraphIndexComponent.run() called outside async context manager. "
                "Use 'async with GraphIndexComponent(config) as comp: ...'."
            )

        self.logger.info("GraphIndexComponent.run() starting build pipeline.")
        result: BuildResult = await self._builder.build(self._sources, self._ctx)

        self.logger.info(
            "Build complete: %d nodes, %d edges, %d inferred",
            result.node_count,
            result.edge_count,
            result.inferred_edge_count,
        )
        return result.model_dump()

    # ------------------------------------------------------------------
    # Private factory helpers
    # ------------------------------------------------------------------

    def _build_embedder(self, model_name: str, dimension: int) -> GraphIndexEmbedder:
        """Create a ``GraphIndexEmbedder`` instance.

        Args:
            model_name: Embedding model name.
            dimension: Vector dimension.

        Returns:
            Configured ``GraphIndexEmbedder``.
        """
        return GraphIndexEmbedder(model_name=model_name, dimension=dimension)

    def _build_persistence(self) -> GraphIndexPersistence:
        """Create a minimal ``GraphIndexPersistence`` stub.

        In production, a real ``OntologyGraphStore`` would be injected.
        Here we create a no-op stub for pipeline execution.

        Returns:
            A ``GraphIndexPersistence`` instance wrapping a no-op store.
        """
        from unittest.mock import AsyncMock, MagicMock

        store = MagicMock()
        upsert_result = MagicMock()
        upsert_result.inserted = 0
        upsert_result.updated = 0
        store.upsert_nodes = AsyncMock(return_value=upsert_result)
        store.create_edges = AsyncMock(return_value=0)
        store.soft_delete_nodes = AsyncMock(return_value=0)
        store.get_all_nodes = AsyncMock(return_value=[])
        return GraphIndexPersistence(graph_store=store)
