"""CapabilityRegistry — semantic resource index for intent routing.

Provides embedding-based similarity search over registered capability entries
(datasets, tools, graph nodes, etc.) to identify the best routing strategy
for a given user query.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import yaml

from .models import CapabilityEntry, ResourceType, RouterCandidate


class CapabilityRegistry:
    """Semantic resource index for intent routing.

    Stores capability entries and provides embedding-based cosine similarity
    search to discover relevant strategies for a given user query.

    Supports registration from:
    - Manual CapabilityEntry objects.
    - DataSource instances (DatasetManager sources).
    - AbstractTool instances.
    - YAML configuration files.

    Args:
        not_for_penalty: Score multiplier applied when a query matches a
            ``not_for`` pattern (default 0.5 — halves the score).
    """

    def __init__(self, not_for_penalty: float = 0.5) -> None:
        self.logger = logging.getLogger(__name__)
        self._entries: list[CapabilityEntry] = []
        self._embedding_matrix: Optional[np.ndarray] = None
        self._index_dirty: bool = True
        self._embedding_fn: Optional[Callable] = None
        self._not_for_penalty: float = not_for_penalty

    # ── Registration ──────────────────────────────────────────────────────────

    def register(self, entry: CapabilityEntry) -> None:
        """Register a capability entry.

        Marks the search index as dirty so it will be rebuilt on next search.

        Args:
            entry: The capability entry to register.
        """
        self._entries.append(entry)
        self._index_dirty = True
        self.logger.debug("Registered capability: %s", entry.name)

    def register_from_datasource(self, source: Any) -> None:
        """Create and register a CapabilityEntry from a DataSource.

        Uses ``source.describe()`` as the description (if available), otherwise
        falls back to ``source.name`` or the string representation. Reads
        ``routing_meta`` from the source to populate ``not_for`` and ``metadata``.

        Args:
            source: A DataSource instance with at least a ``name`` attribute.
        """
        routing_meta: dict = getattr(source, "routing_meta", {}) or {}
        description = routing_meta.get("description", None)
        if description is None:
            # Try source.describe() (may raise or return None)
            try:
                desc_result = source.describe()
                if isinstance(desc_result, str) and desc_result:
                    description = desc_result
            except Exception:  # noqa: BLE001
                pass
        if not description:
            description = getattr(source, "name", str(source))

        entry = CapabilityEntry(
            name=getattr(source, "name", str(source)),
            description=description,
            resource_type=ResourceType.DATASET,
            metadata=routing_meta,
            not_for=routing_meta.get("not_for", []),
        )
        self.register(entry)

    def register_from_tool(self, tool: Any) -> None:
        """Create and register a CapabilityEntry from an AbstractTool.

        Uses ``tool.description`` if available, falling back to ``tool.name``.
        Reads ``routing_meta`` to populate ``not_for`` and ``metadata``.

        Args:
            tool: An AbstractTool instance with at least ``name`` and
                ``description`` attributes.
        """
        routing_meta: dict = getattr(tool, "routing_meta", {}) or {}
        description = routing_meta.get("description", None)
        if not description:
            description = getattr(tool, "description", None) or getattr(tool, "name", str(tool))

        entry = CapabilityEntry(
            name=getattr(tool, "name", str(tool)),
            description=description,
            resource_type=ResourceType.TOOL,
            metadata=routing_meta,
            not_for=routing_meta.get("not_for", []),
        )
        self.register(entry)

    def register_from_yaml(self, path: str) -> None:
        """Load and register capability entries from a YAML file.

        The YAML file must have a top-level ``capabilities`` list. Each item
        is passed directly to ``CapabilityEntry(**item)``.

        Example YAML structure::

            capabilities:
              - name: product_graph
                description: "Product category graph"
                resource_type: graph_node
                not_for: ["employee data"]

        Args:
            path: Filesystem path to the YAML capability definition file.

        Raises:
            FileNotFoundError: If the path does not exist.
            ValueError: If the YAML is malformed or missing required fields.
        """
        yaml_path = Path(path)
        if not yaml_path.exists():
            raise FileNotFoundError(f"Capability YAML not found: {path}")

        raw = yaml.safe_load(yaml_path.read_text())
        capabilities = raw.get("capabilities", [])
        for item in capabilities:
            entry = CapabilityEntry(**item)
            self.register(entry)
        self.logger.debug("Loaded %d capabilities from %s", len(capabilities), path)

    # ── Index ──────────────────────────────────────────────────────────────────

    async def build_index(self, embedding_fn: Callable) -> None:
        """Compute embeddings for all entries and build the search matrix.

        L2-normalises all embedding vectors so cosine similarity can be
        computed as a simple dot product.

        Args:
            embedding_fn: Async callable that accepts ``list[str]`` and returns
                ``list[list[float]]`` (one embedding per text).
        """
        self._embedding_fn = embedding_fn

        if not self._entries:
            self._embedding_matrix = np.empty((0, 0), dtype=np.float32)
            self._index_dirty = False
            return

        descriptions = [e.description for e in self._entries]
        embeddings: list[list[float]] = await embedding_fn(descriptions)

        # Store embeddings back on the entries
        for i, emb in enumerate(embeddings):
            self._entries[i].embedding = emb

        matrix = np.array(embeddings, dtype=np.float32)

        # L2 normalise rows for cosine similarity via dot product
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        self._embedding_matrix = matrix / norms
        self._index_dirty = False
        self.logger.debug("Built capability index for %d entries", len(self._entries))

    # ── Search ─────────────────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        top_k: int = 5,
        resource_types: Optional[list[ResourceType]] = None,
    ) -> list[RouterCandidate]:
        """Embed the query and return top-K matching capabilities.

        Auto-rebuilds the index if dirty (after a new registration) and an
        embedding function is available.

        Args:
            query: The user query to match against registered capabilities.
            top_k: Maximum number of candidates to return.
            resource_types: Optional list of resource types to filter by.
                If None, all types are considered.

        Returns:
            Ranked list of ``RouterCandidate`` objects, best match first.
        """
        # Auto-rebuild if dirty
        if self._index_dirty and self._embedding_fn:
            await self.build_index(self._embedding_fn)

        if (
            self._embedding_matrix is None
            or self._embedding_matrix.size == 0
            or not self._entries
        ):
            return []

        # Embed the query
        query_embeddings: list[list[float]] = await self._embedding_fn([query])
        query_vec = np.array(query_embeddings[0], dtype=np.float32)

        # Normalise query vector
        query_norm = np.linalg.norm(query_vec)
        if query_norm > 0:
            query_vec = query_vec / query_norm

        # Cosine similarity (dot product with pre-normalised matrix)
        scores: np.ndarray = self._embedding_matrix @ query_vec

        # Apply not_for penalty
        query_lower = query.lower()
        for i, entry in enumerate(self._entries):
            if entry.not_for and any(
                pattern.lower() in query_lower for pattern in entry.not_for
            ):
                scores[i] *= self._not_for_penalty

        # Build candidate list (with optional resource_type filter)
        candidates: list[RouterCandidate] = []
        for i, entry in enumerate(self._entries):
            if resource_types and entry.resource_type not in resource_types:
                continue
            candidates.append(
                RouterCandidate(
                    entry=entry,
                    score=float(np.clip(scores[i], 0.0, 1.0)),
                    resource_type=entry.resource_type,
                )
            )

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates[:top_k]
