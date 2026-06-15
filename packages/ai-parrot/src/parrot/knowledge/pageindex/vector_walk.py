"""Embedding-guided beam walk over a PageIndex tree (Phase B of FEAT-237).

The beam walk descends the tree using local ``(N_children, d) @ (d,)``
cosine-similarity matmuls at each level, keeping the top ``beam_width``
branches.  This is a *proposer* — it produces candidate node_ids that can
be fused with BM25 / LLM-walk rankings via RRF.

Phase B is flag-gated via ``use_embedding_walk`` on
:class:`~parrot.knowledge.pageindex.hybrid_search.HybridPageIndexSearch`.
When the flag is ``False``, the system behaves identically to Phase A.

Design invariant (platform guarantee): the beam walk is deterministic
(pure numpy matmul); the LLM walk / reranker is the final arbiter.

Usage example::

    query_vec = embed_fn(["What is HIPAA?"])[0]
    candidates = await embedding_tree_walk(tree, query_vec, store, beam_width=3)
    # candidates is a list of node_id strings ordered by beam descent
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

import numpy as np


if TYPE_CHECKING:
    from .embedding_store import NodeEmbeddingStore

logger = logging.getLogger("parrot.knowledge.pageindex.vector_walk")


class FlatMatrixSearch:
    """Brute-force cosine similarity search over a node embedding submatrix.

    Rows are L2-normalised at construction time so inner products equal
    cosine similarities.

    Args:
        matrix: ``(N, d)`` float32 numpy array of node embeddings.
        node_ids: List of node identifiers aligned with ``matrix`` rows.

    Raises:
        ValueError: When ``len(node_ids) != matrix.shape[0]``.
    """

    def __init__(self, matrix: np.ndarray, node_ids: list[str]) -> None:
        if len(node_ids) != matrix.shape[0]:
            raise ValueError(
                f"node_ids length {len(node_ids)} != matrix rows {matrix.shape[0]}"
            )
        mat = np.asarray(matrix, dtype=np.float32)
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        self._matrix = mat / np.maximum(norms, 1e-10)
        self._node_ids = list(node_ids)

    def search(
        self, query_vec: np.ndarray, top_k: int
    ) -> list[tuple[str, float]]:
        """Return the top ``top_k`` nodes by cosine similarity.

        Args:
            query_vec: 1-D float32 query embedding (will be L2-normalised
                internally).
            top_k: Maximum number of results.

        Returns:
            List of ``(node_id, score)`` tuples sorted by descending score.
        """
        q = np.asarray(query_vec, dtype=np.float32)
        q_norm = np.linalg.norm(q)
        if q_norm > 1e-10:
            q = q / q_norm
        scores = self._matrix @ q  # (N,)
        k = min(top_k, len(self._node_ids))
        top_idx = np.argsort(scores)[::-1][:k]
        return [(self._node_ids[int(i)], float(scores[i])) for i in top_idx]


async def embedding_tree_walk(
    tree: dict,
    query_vec: np.ndarray,
    store: "NodeEmbeddingStore",
    beam_width: int = 3,
    max_depth: int = 10,
    embed_fn=None,
) -> list[str]:
    """Beam search over per-node embeddings to propose candidate node_ids.

    At each level, cosine-scores the children of surviving branches, keeps
    the top ``beam_width`` candidates, and descends into their subtrees.
    Both branch and leaf node_ids are collected as candidates.

    The walk is ``async`` so it can be awaited inside async search methods;
    current implementation is purely synchronous numpy.

    Args:
        tree: PageIndex tree dict (``{"doc_name": str, "structure": [...]}}``).
        query_vec: 1-D float32 query embedding produced by the caller.
        store: :class:`NodeEmbeddingStore` instance.
        beam_width: Number of top candidates to keep at each level.
        max_depth: Maximum descent depth (prevents infinite loops on cycles).
        embed_fn: Callable ``(list[str]) -> np.ndarray`` used to embed node
            texts when their vectors are not already in the store.  When
            ``None``, nodes missing from the store are skipped.

    Returns:
        List of ``node_id`` strings in beam-descent order (higher-ranked
        nodes appear first).  May be empty if no embeddings are available.
    """
    tree_name: str = tree.get("doc_name") or ""
    root_structure = tree.get("structure", [])
    if isinstance(root_structure, dict):
        root_structure = [root_structure]
    root_nodes: list[dict] = list(root_structure or [])

    if not root_nodes or not tree_name:
        return []

    collected: list[str] = []  # all visited node_ids in order

    # Each beam entry: the node dict whose children to expand next.
    # Start with the root-level nodes.
    current_level: list[dict] = root_nodes

    for _depth in range(max_depth):
        if not current_level:
            break

        # Gather children of all current-level nodes into a flat pool.
        child_pool: list[dict] = []
        for node in current_level:
            children = node.get("nodes", [])
            if isinstance(children, dict):
                children = [children]
            child_pool.extend(children or [])

        if not child_pool:
            # Leaf level — add current-level node_ids as candidates.
            for node in current_level:
                nid = node.get("node_id")
                if nid and nid not in collected:
                    collected.append(nid)
            break

        # Score child_pool nodes with available embeddings.
        scored: list[tuple[str, float, dict]] = []  # (node_id, score, node)

        # Try per-tree matrix first for efficiency; fall back to global cache.
        mat_result = store.load_tree_matrix(tree_name)
        if mat_result is not None:
            matrix, node_order = mat_result
            order_idx: dict[str, int] = {nid: i for i, nid in enumerate(node_order)}

        for node in child_pool:
            nid = node.get("node_id") or ""
            if not nid:
                continue
            title = node.get("title") or ""
            summary = node.get("summary") or node.get("prefix_summary") or ""

            vec: Optional[np.ndarray] = None
            # Fast path: per-tree matrix
            if mat_result is not None and nid in order_idx:
                idx = order_idx[nid]
                vec = np.asarray(matrix[idx], dtype=np.float32)
            else:
                # Fallback: global cache
                vec = store.get_or_embed(tree_name, nid, title, summary)

            if vec is None and embed_fn is not None:
                # Last resort: embed on demand (single text, slow path)
                text = f"{title} {summary}".strip()
                try:
                    vecs = embed_fn([text])
                    vec = np.asarray(vecs[0], dtype=np.float32)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("embed_fn failed for node %s: %s", nid, exc)

            if vec is None:
                continue

            q = np.asarray(query_vec, dtype=np.float32)
            # Cosine similarity
            q_norm = np.linalg.norm(q)
            v_norm = np.linalg.norm(vec)
            if q_norm > 1e-10 and v_norm > 1e-10:
                score = float(np.dot(q / q_norm, vec / v_norm))
            else:
                score = 0.0
            scored.append((nid, score, node))

        if not scored:
            # No embeddings available for any child; collect node_ids and stop.
            for node in current_level:
                nid = node.get("node_id")
                if nid and nid not in collected:
                    collected.append(nid)
            break

        # Keep top beam_width candidates.
        scored.sort(key=lambda x: x[1], reverse=True)
        top_candidates = scored[:beam_width]

        for nid, _score, _node in top_candidates:
            if nid not in collected:
                collected.append(nid)

        # Descend into the top candidates' subtrees.
        current_level = [node for (_, _, node) in top_candidates]

    return collected
