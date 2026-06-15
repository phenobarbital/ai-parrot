"""Two-tier content-addressed embedding store for PageIndex trees.

Each PageIndex node's embedding is identified by a content-addressed SHA-1 key
derived from the model identifier, node title, and node summary. This design
survives ``reindex_node_ids`` mutations that rewrite all node_ids on every tree
mutation.

Storage layout::

    <storage_dir>/
        <tree_name>/
            embeddings/
                global/           <- content-addressed .npy sidecar files
                    <sha1_hex>.npy
                <tree_name>.matrix.npy     <- per-tree (N, d) matrix
                <tree_name>.node_order.json <- node_id ordering for the matrix

The global tier caches individual node embeddings keyed by content hash.
The per-tree tier materializes a contiguous ``(N, d)`` float32 numpy array
for fast BLAS matmul — rebuilt via ``build_tree_matrix()``, loaded
(memory-mapped) via ``load_tree_matrix()``, deleted via ``invalidate_tree()``.

An in-memory LRU cache fronts the global tier to avoid repeated disk I/O for
hot nodes across multiple search calls.
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections import OrderedDict
from pathlib import Path
from typing import Callable, Optional

import numpy as np


logger = logging.getLogger("parrot.knowledge.pageindex.embedding_store")


class NodeEmbeddingStore:
    """Two-tier content-addressed embedding cache for PageIndex trees.

    Global tier: per-node embedding vectors keyed by
        ``sha1(model_id + "\\x00" + title + "\\x00" + summary)``.
    Per-tree tier: materialized ``(N, d)`` contiguous numpy matrix,
        rebuilt on ``build_tree_matrix()``; mmap for fast matmul.

    The store is model-agnostic — the caller supplies an ``embed_fn``
    to ``build_tree_matrix()``.  This keeps model loading in the toolkit
    and the store as a pure caching / persistence layer.

    Args:
        storage_dir: Directory for sidecar ``.npy`` files.  Created on
            first write if it does not exist.
        model_id: Embedding model identifier used in the content key.
            Changing this effectively invalidates all existing entries
            (new hash, no collision with old).
        dimension: Embedding vector dimension.  Used to validate loaded
            vectors but not enforced at write time — mismatches will
            surface at matmul time.
        cache_size: Maximum number of content-key → vector entries held in
            the in-memory LRU cache.

    Notes:
        * Global-tier writes are idempotent — the same content key always
          produces the same vector, so concurrent writers cannot corrupt
          the store.
        * Per-tree matrix rebuild is NOT thread-safe.  The single-writer
          invariant is maintained by ``PageIndexToolkit._persist()`` which
          calls ``mark_dirty()`` only after the tree JSON is saved.
    """

    def __init__(
        self,
        storage_dir: str | Path,
        model_id: str,
        dimension: int,
        cache_size: int = 512,
    ) -> None:
        self._storage_dir = Path(storage_dir)
        self._model_id = model_id
        self._dimension = dimension
        self._cache_size = max(1, int(cache_size))
        # LRU cache: content_key (str) -> np.ndarray (1-D)
        self._cache: OrderedDict[str, np.ndarray] = OrderedDict()

    # ---- content key ---------------------------------------------------

    @staticmethod
    def content_key(model_id: str, title: str, summary: str) -> str:
        """Compute the SHA-1 content-addressed cache key.

        The ``"\\x00"`` separator prevents collisions between prefix-equal
        strings: ``("ab", "c")`` and ``("a", "bc")`` hash to different values.

        Args:
            model_id: Embedding model identifier.
            title: Node title text.
            summary: Node summary text.

        Returns:
            40-character lowercase hex SHA-1 digest.
        """
        raw = f"{model_id}\x00{title}\x00{summary}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    # ---- storage paths -------------------------------------------------

    def _global_dir(self, tree_name: str) -> Path:
        """Return the global-tier directory for a tree."""
        return self._storage_dir / tree_name / "embeddings" / "global"

    def _global_path(self, tree_name: str, key: str) -> Path:
        """Return the .npy path for a content-addressed vector."""
        return self._global_dir(tree_name) / f"{key}.npy"

    def _matrix_path(self, tree_name: str) -> Path:
        """Return the per-tree matrix .npy path."""
        return self._storage_dir / tree_name / "embeddings" / f"{tree_name}.matrix.npy"

    def _order_path(self, tree_name: str) -> Path:
        """Return the per-tree node_order JSON path."""
        return self._storage_dir / tree_name / "embeddings" / f"{tree_name}.node_order.json"

    # ---- LRU cache helpers ---------------------------------------------

    def _cache_get(self, key: str) -> Optional[np.ndarray]:
        """Return cached vector or None; moves to end on hit (LRU)."""
        vec = self._cache.get(key)
        if vec is not None:
            self._cache.move_to_end(key)
        return vec

    def _cache_put(self, key: str, vec: np.ndarray) -> None:
        """Insert or update a vector in the LRU cache; evict LRU if full."""
        if key in self._cache:
            self._cache.move_to_end(key)
            self._cache[key] = vec
            return
        self._cache[key] = vec
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)

    # ---- global-tier helpers -------------------------------------------

    def _load_global(self, tree_name: str, key: str) -> Optional[np.ndarray]:
        """Load a single vector from disk (global tier)."""
        path = self._global_path(tree_name, key)
        if not path.exists():
            return None
        try:
            return np.load(str(path))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load global embedding %s: %s", path, exc)
            return None

    def _save_global(self, tree_name: str, key: str, vec: np.ndarray) -> None:
        """Persist a single vector to disk (global tier)."""
        path = self._global_path(tree_name, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.save(str(path), vec.astype(np.float32))

    # ---- public API ----------------------------------------------------

    def get_or_embed(
        self,
        tree_name: str,
        node_id: str,
        title: str,
        summary: str,
    ) -> Optional[np.ndarray]:
        """Return the cached embedding vector for a node, or None if missing.

        Checks the in-memory LRU cache first, then the global .npy sidecar.
        Does NOT call the embed function — use ``build_tree_matrix`` for
        batch embedding.

        Args:
            tree_name: Name of the tree this node belongs to.
            node_id: Node identifier (used only for logging).
            title: Node title text.
            summary: Node summary text.

        Returns:
            1-D float32 numpy array if cached; ``None`` otherwise.
        """
        key = self.content_key(self._model_id, title, summary)
        # 1) In-memory LRU
        vec = self._cache_get(key)
        if vec is not None:
            return vec
        # 2) Global disk tier
        vec = self._load_global(tree_name, key)
        if vec is not None:
            self._cache_put(key, vec)
        return vec

    def build_tree_matrix(
        self,
        tree_name: str,
        nodes: list[dict],
        embed_fn: Callable[[list[str]], np.ndarray],
    ) -> tuple[np.ndarray, list[str]]:
        """Build (or rebuild) the per-tree ``(N, d)`` embedding matrix.

        Only nodes whose content key is absent from the global cache are
        sent to ``embed_fn`` — unchanged nodes incur zero embed cost.
        The resulting matrix is saved as a contiguous C-order float32
        ``.npy`` file alongside a node_order JSON sidecar.

        Args:
            tree_name: Name of the tree to embed.
            nodes: List of node dicts, each with at least ``"node_id"``,
                ``"title"``, and one of ``"summary"`` / ``"prefix_summary"``.
            embed_fn: Callable accepting a list of text strings and returning
                an ``(n, d)`` float32 numpy array.

        Returns:
            Tuple of ``(matrix, node_id_order)`` where
            ``matrix[i]`` is the embedding for ``node_id_order[i]``.

        Raises:
            ValueError: When ``nodes`` is empty.
        """
        if not nodes:
            raise ValueError("nodes must be non-empty")

        # Build ordered list of (node_id, key, text) for every node.
        items: list[tuple[str, str, str]] = []
        for node in nodes:
            node_id = node.get("node_id") or ""
            title = node.get("title") or ""
            summary = node.get("summary") or node.get("prefix_summary") or ""
            key = self.content_key(self._model_id, title, summary)
            text = f"{title} {summary}".strip() if (title or summary) else ""
            items.append((node_id, key, text))

        # Determine which keys need fresh embeddings.
        missing_indices: list[int] = []
        cached_vecs: dict[str, np.ndarray] = {}

        for idx, (node_id, key, text) in enumerate(items):
            # Check LRU first.
            vec = self._cache_get(key)
            if vec is not None:
                cached_vecs[key] = vec
                continue
            # Check global disk tier.
            vec = self._load_global(tree_name, key)
            if vec is not None:
                self._cache_put(key, vec)
                cached_vecs[key] = vec
            else:
                missing_indices.append(idx)

        # Batch-embed only the cache misses.
        if missing_indices:
            texts = [items[i][2] for i in missing_indices]
            new_vecs = embed_fn(texts)
            new_vecs = np.asarray(new_vecs, dtype=np.float32)
            for batch_pos, idx in enumerate(missing_indices):
                node_id, key, text = items[idx]
                vec = new_vecs[batch_pos]
                self._save_global(tree_name, key, vec)
                self._cache_put(key, vec)
                cached_vecs[key] = vec

        # Assemble the contiguous (N, d) matrix in node order.
        n = len(items)
        dim = self._dimension
        # Infer dim from actual vectors if available.
        if cached_vecs:
            first_vec = next(iter(cached_vecs.values()))
            dim = first_vec.shape[0]

        matrix = np.empty((n, dim), dtype=np.float32)
        node_id_order: list[str] = []
        for i, (node_id, key, _) in enumerate(items):
            matrix[i] = cached_vecs[key]
            node_id_order.append(node_id)

        # Ensure C-contiguous layout for efficient BLAS matmul.
        matrix = np.ascontiguousarray(matrix, dtype=np.float32)

        # Persist per-tree matrix + node_order sidecar.
        matrix_path = self._matrix_path(tree_name)
        order_path = self._order_path(tree_name)
        matrix_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(str(matrix_path), matrix)
        order_path.write_text(
            json.dumps(node_id_order, ensure_ascii=False), encoding="utf-8"
        )
        logger.debug(
            "Built tree matrix for %r: shape=%s, n_embedded=%d",
            tree_name, matrix.shape, len(missing_indices),
        )

        return matrix, node_id_order

    def load_tree_matrix(
        self, tree_name: str
    ) -> Optional[tuple[np.ndarray, list[str]]]:
        """Load the materialized per-tree matrix (memory-mapped read-only).

        Args:
            tree_name: Name of the tree whose matrix to load.

        Returns:
            Tuple of ``(matrix, node_id_order)`` if the matrix exists,
            or ``None`` if it has not yet been built or was invalidated.
        """
        matrix_path = self._matrix_path(tree_name)
        order_path = self._order_path(tree_name)
        if not matrix_path.exists() or not order_path.exists():
            return None
        try:
            matrix = np.load(str(matrix_path), mmap_mode="r")
            node_id_order = json.loads(order_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load tree matrix for %r: %s", tree_name, exc)
            return None
        return matrix, node_id_order

    def invalidate_tree(self, tree_name: str) -> None:
        """Delete the per-tree matrix without touching global-tier entries.

        After invalidation, the next ``build_tree_matrix`` call will
        reassemble the matrix (re-embedding only truly changed nodes;
        unchanged nodes will hit the global tier cache).

        Args:
            tree_name: Name of the tree to invalidate.
        """
        matrix_path = self._matrix_path(tree_name)
        order_path = self._order_path(tree_name)
        for path in (matrix_path, order_path):
            if path.exists():
                try:
                    path.unlink()
                    logger.debug("Invalidated %s", path)
                except OSError as exc:
                    logger.warning("Could not delete %s: %s", path, exc)
