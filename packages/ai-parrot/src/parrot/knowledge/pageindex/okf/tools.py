"""Named read tools for OKF knowledge-layer retrieval and traversal.

Provides **separate named tools** (spec constraint — no branching search)
for type-scoped retrieval and multi-hop compliance traversal:

- ``find_by_type``: Exact type pre-filter then search over nodes.
- ``list_concepts``: Browse ToC, optionally filtered by type.
- ``get_concept``: Retrieve frontmatter + body for a stable concept_id.
- ``get_related``: In-memory graph traversal, optional rel filter.
- ``trace_mapping``: Multi-hop typed-chain traversal.
- ``cite``: Per-node provenance (document, pages, URL).

Each tool is a ``@tool``-decorated function wrapped in ``OKFToolkit``, which
holds the shared state (tree dict, graph, content_store).

Design notes (spec §2.5, §3 Module 7):
- **Deterministic gate before probabilistic ranker**: ``find_by_type`` filters
  candidates by ``type`` *exactly* before any ranking.
- **Type/rel filters are a guide, not a contract**: access restriction for
  sensitive types lives in the execution layer (PBAC), not here.
- **Separate named tools**: each is its own ``@tool``-decorated function.
  No branching ``search(type=...)`` multi-purpose tool.
"""

from typing import Any, Optional

from parrot.knowledge.pageindex.content_store import NodeContentStore
from parrot.knowledge.pageindex.okf.graph import KnowledgeGraph
from parrot.knowledge.pageindex.okf.ontology import ConceptType
from parrot.knowledge.pageindex.okf.projection import flatten_concept_id_for_filename
from parrot.knowledge.pageindex.utils import structure_to_list
from parrot.tools import tool


class OKFToolkit:
    """Stateful container for OKF read tools.

    Holds shared state (tree, graph, content_store) and exposes ``@tool``
    decorated methods callable by agents.

    Args:
        tree: OKF-enriched PageIndex tree dict.
        graph: Pre-built ``KnowledgeGraph`` instance.
        content_store: ``NodeContentStore`` for loading sidecar bodies.
        tree_name: PageIndex tree name (for concept_id lookup).
    """

    def __init__(
        self,
        tree: dict[str, Any],
        graph: KnowledgeGraph,
        content_store: NodeContentStore,
        tree_name: str,
    ) -> None:
        self._tree = tree
        self._graph = graph
        self._content_store = content_store
        self._tree_name = tree_name
        # Build a flat concept_id → node lookup for O(1) access
        self._by_concept_id: dict[str, dict] = {}
        for node in structure_to_list(tree.get("structure", [])):
            cid = node.get("concept_id")
            if cid:
                self._by_concept_id[cid] = node

    def get_tools(self) -> list:
        """Return all OKF tool callables.

        Returns:
            List of ``@tool``-decorated bound methods.
        """
        return [
            self.find_by_type,
            self.list_concepts,
            self.get_concept,
            self.get_related,
            self.trace_mapping,
            self.cite,
        ]

    @tool
    def find_by_type(self, type: ConceptType, query: str) -> list[dict]:
        """Search for concepts of a specific type.

        Applies an **exact type pre-filter** on the candidate set before
        ranking.  Deterministic gate: only nodes with ``node["type"] == type``
        are considered; all other nodes are excluded.

        Args:
            type: The concept type to filter by (e.g. ``Control``, ``Safeguard``).
            query: Query string used for substring matching against title and
                summary (lowercase).  Pass ``""`` to return all concepts of
                the given type.

        Returns:
            List of matching node dicts (title, concept_id, summary, type).
        """
        q = query.lower()
        results = []
        for node in structure_to_list(self._tree.get("structure", [])):
            if node.get("type") != type.value:
                continue
            if q and q not in (node.get("title", "") + node.get("summary", "")).lower():
                continue
            results.append({
                "concept_id": node.get("concept_id", ""),
                "title": node.get("title", ""),
                "summary": node.get("summary", ""),
                "type": node.get("type", ""),
            })
        return results

    @tool
    def list_concepts(self, type: Optional[ConceptType] = None) -> list[dict]:
        """Browse the knowledge ToC, optionally filtered by type.

        Args:
            type: Optional concept type filter.  If ``None``, returns all concepts.

        Returns:
            List of concept dicts (concept_id, title, summary, type).
        """
        results = []
        for node in structure_to_list(self._tree.get("structure", [])):
            cid = node.get("concept_id")
            if not cid:
                continue
            if type is not None and node.get("type") != type.value:
                continue
            results.append({
                "concept_id": cid,
                "title": node.get("title", ""),
                "summary": node.get("summary", ""),
                "type": node.get("type", ""),
            })
        return results

    @tool
    def get_concept(self, concept_id: str) -> dict:
        """Retrieve the self-describing unit for a concept.

        Returns frontmatter fields and body content for a stable ``concept_id``.
        Stable across ``reindex_node_ids`` — lookup is always by ``concept_id``,
        never by ``node_id``.

        Args:
            concept_id: Stable concept identity string.

        Returns:
            Dict with node fields + ``body`` key (sidecar content, or empty
            string if not found).

        Raises:
            KeyError: If ``concept_id`` is not found in the tree.
        """
        node = self._by_concept_id.get(concept_id)
        if node is None:
            raise KeyError(f"concept_id not found: {concept_id!r}")

        flat_id = flatten_concept_id_for_filename(concept_id)
        body = self._content_store.load(self._tree_name, flat_id) or ""

        return {
            "concept_id": concept_id,
            "title": node.get("title", ""),
            "summary": node.get("summary", ""),
            "type": node.get("type", ""),
            "relates_to": node.get("relates_to", []),
            "source": node.get("source"),
            "body": body,
        }

    @tool
    def get_related(
        self,
        concept_id: str,
        rel: Optional[str] = None,
    ) -> list[dict]:
        """Return in-memory graph neighbors of a concept.

        Args:
            concept_id: Source concept_id to look up.
            rel: Optional relation type filter (e.g. ``"maps_to"``,
                ``"satisfied_by"``).  If ``None``, returns all edges.

        Returns:
            List of edge dicts ``{"concept": ..., "rel": ...}``.
        """
        return self._graph.neighbors(concept_id, rel=rel)

    @tool
    def trace_mapping(
        self,
        concept_id: str,
        rel_chain: Optional[list[str]] = None,
    ) -> list[list[str]]:
        """Follow a multi-hop typed chain from a concept.

        Default chain is ``["maps_to", "satisfied_by"]`` for compliance
        queries (safeguard → control → evidence).

        Args:
            concept_id: Starting concept_id.
            rel_chain: Ordered list of relation types to follow.  Defaults to
                ``["maps_to", "satisfied_by"]``.

        Returns:
            List of paths.  Each path is an ordered list of concept_ids from
            ``concept_id`` through all hops.
        """
        chain = rel_chain if rel_chain is not None else ["maps_to", "satisfied_by"]
        return self._graph.trace(concept_id, chain)

    @tool
    def cite(self, concept_id: str) -> dict:
        """Return per-node provenance for a concept.

        Args:
            concept_id: Stable concept identity string.

        Returns:
            Dict with ``document``, ``pages`` (or ``None``), and ``url``
            (or ``None``) from the node's ``source`` field.  Returns empty
            provenance if no ``source`` is set.

        Raises:
            KeyError: If ``concept_id`` is not found in the tree.
        """
        node = self._by_concept_id.get(concept_id)
        if node is None:
            raise KeyError(f"concept_id not found: {concept_id!r}")

        src = node.get("source") or {}
        return {
            "concept_id": concept_id,
            "document": src.get("document", ""),
            "pages": src.get("pages"),
            "url": src.get("url"),
        }
