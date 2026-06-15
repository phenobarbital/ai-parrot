"""Hybrid search over a PageIndex tree.

Combines three signals:

* **BM25** lexical search over flattened node text (title + summary + text).
  Backed by the ``bm25s`` library (an optional extra).
* **LLM tree walk** via :class:`PageIndexRetriever` — the existing
  reasoning-based retriever that selects a list of relevant node ids.
* **Dense cosine-similarity** via ``_vec_rank`` over a pre-built node
  embedding matrix (Phase A of FEAT-237, enabled with ``use_vec=True``).
* **Reciprocal Rank Fusion** to combine up to three rankings.

An :class:`AbstractReranker` may optionally be supplied to rerank the
fused candidate set with a cross-encoder.

The BM25 index is rebuilt lazily — every mutation calls ``mark_dirty``,
and the next ``search`` rebuilds before scoring.  The embedding matrix
uses the same dirty / invalidate pattern via :class:`NodeEmbeddingStore`.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Callable, Optional

import numpy as np

from parrot._imports import lazy_import
from .llm_adapter import PageIndexLLMAdapter
from .retriever import PageIndexRetriever
from .utils import find_node_by_id, get_nodes

if TYPE_CHECKING:
    from .embedding_store import NodeEmbeddingStore


logger = logging.getLogger("parrot.knowledge.pageindex.hybrid_search")

# bm25s pulls in ``jax.lax`` for its top-k selection, which emits noisy
# DEBUG/INFO/WARNING messages about TPU/CUDA backend probing and every
# jit compilation. None of that is actionable for PageIndex users, so we
# pin the ``jax`` logger tree to WARNING at import time.
for _jax_logger in ("jax", "jax._src", "jax._src.xla_bridge",
                    "jax._src.interpreters.pxla"):
    logging.getLogger(_jax_logger).setLevel(logging.WARNING)

_RRF_K = 60
_RERANK_TEXT_LIMIT = 2000
_BM25_TEXT_LIMIT = 4000


class HybridPageIndexSearch:
    """BM25 + LLM-walk + dense-cosine hybrid retrieval wrapping a single tree.

    Args:
        tree: A PageIndex tree dict (``{doc_name, structure: [...]}``).
        adapter: The LLM adapter used by the inner :class:`PageIndexRetriever`.
        reranker: Optional reranker applied to the fused candidate set.
        model: Model passed through to :class:`PageIndexRetriever`.
        default_bm25_k: Number of candidates fetched from BM25 per query.
        content_loader: Optional per-node content loader for BM25 index.
        embedding_store: Optional :class:`NodeEmbeddingStore` for dense search
            (Phase A of FEAT-237).  When ``None``, ``use_vec=True`` in
            :meth:`search` silently returns empty dense rankings.
        embed_fn: Callable ``(list[str]) -> np.ndarray`` used to embed node
            texts and query strings for dense ranking.  Required when
            ``embedding_store`` is supplied.
        use_vec_rank: Default value of the ``use_vec`` flag in :meth:`search`.
        use_embedding_walk: Reserved for Phase B (beam walk).  Stored but
            unused in this implementation.
    """

    def __init__(
        self,
        tree: dict[str, Any],
        adapter: PageIndexLLMAdapter,
        reranker: Optional[Any] = None,
        model: Optional[str] = None,
        default_bm25_k: int = 20,
        content_loader: Optional[Callable[[str], Optional[str]]] = None,
        embedding_store: Optional["NodeEmbeddingStore"] = None,
        embed_fn: Optional[Callable[[list[str]], "np.ndarray"]] = None,
        use_vec_rank: bool = False,
        use_embedding_walk: bool = False,
    ):
        self._tree = tree
        self._adapter = adapter
        self._reranker = reranker
        self._model = model
        self._default_bm25_k = default_bm25_k
        self._content_loader = content_loader
        self._embedding_store = embedding_store
        self._embed_fn = embed_fn
        self._use_vec_rank = use_vec_rank
        self._use_embedding_walk = use_embedding_walk

        self._bm25_index = None
        self._corpus_node_ids: list[str] = []
        self._dirty = True

    def set_content_loader(
        self,
        loader: Optional[Callable[[str], Optional[str]]],
    ) -> None:
        """Swap the per-node content loader. Marks the BM25 index dirty."""
        self._content_loader = loader
        self.mark_dirty()

    def _load_body(self, node_id: Optional[str]) -> str:
        if not node_id or self._content_loader is None:
            return ""
        try:
            body = self._content_loader(node_id)
        except Exception as exc:  # noqa: BLE001 — loader is user-supplied.
            logger.warning("content_loader raised for %s: %s", node_id, exc)
            return ""
        return body or ""

    def mark_dirty(self) -> None:
        """Invalidate the BM25 index and embedding matrix.

        Both will be rebuilt lazily on the next :meth:`search` call.
        The per-tree embedding matrix is deleted via
        :meth:`NodeEmbeddingStore.invalidate_tree`; global-tier vectors
        (content-addressed) are preserved.
        """
        self._dirty = True
        if self._embedding_store is not None:
            tree_name = self._tree.get("doc_name") or ""
            if tree_name:
                self._embedding_store.invalidate_tree(tree_name)

    def replace_tree(self, tree: dict[str, Any]) -> None:
        self._tree = tree
        self.mark_dirty()

    def _structure(self) -> list[dict[str, Any]]:
        structure = self._tree.get("structure", [])
        if isinstance(structure, dict):
            return [structure]
        return list(structure or [])

    # ---- BM25 ----------------------------------------------------------

    def _flatten_corpus(self) -> tuple[list[str], list[str]]:
        nodes = get_nodes(self._structure())
        texts: list[str] = []
        ids: list[str] = []
        for node in nodes:
            node_id = node.get("node_id")
            if not node_id:
                continue
            title = node.get("title") or ""
            summary = node.get("summary") or node.get("prefix_summary") or ""
            if self._content_loader is not None:
                body = self._load_body(node_id)[:_BM25_TEXT_LIMIT]
            else:
                body = node.get("text") or ""
            texts.append(f"{title} {summary} {body}".strip())
            ids.append(node_id)
        return ids, texts

    def _rebuild_bm25(self) -> None:
        bm25s = lazy_import("bm25s", package_name="bm25s", extra="embeddings")
        ids, texts = self._flatten_corpus()
        self._corpus_node_ids = ids
        if not texts:
            self._bm25_index = None
            self._dirty = False
            return
        retriever = bm25s.BM25()
        tokenized = bm25s.tokenize(texts, stopwords="en")
        retriever.index(tokenized)
        self._bm25_index = retriever
        self._dirty = False

    def _bm25_rank(self, query: str, top_k: int) -> list[str]:
        if self._dirty:
            self._rebuild_bm25()
        if self._bm25_index is None or not self._corpus_node_ids:
            return []
        bm25s = lazy_import("bm25s", package_name="bm25s", extra="embeddings")
        tokenized_query = bm25s.tokenize([query], stopwords="en")
        k = max(1, min(top_k, len(self._corpus_node_ids)))
        documents, _ = self._bm25_index.retrieve(tokenized_query, k=k)
        row = documents[0]
        try:
            row_iter = row.tolist()
        except AttributeError:
            row_iter = list(row)
        return [
            self._corpus_node_ids[int(i)]
            for i in row_iter
            if 0 <= int(i) < len(self._corpus_node_ids)
        ]

    # ---- Dense vector ranking ------------------------------------------

    def _vec_rank(self, query: str, top_k: int) -> list[str]:
        """Rank nodes by cosine similarity to the query embedding.

        Uses the per-tree ``(N, d)`` matrix from :class:`NodeEmbeddingStore`.
        Lazily rebuilds the matrix if it has been invalidated.

        Args:
            query: Query string to embed.
            top_k: Number of top node ids to return.

        Returns:
            Ordered list of ``node_id`` strings (highest similarity first).
            Returns an empty list if ``embedding_store`` or ``embed_fn`` is
            ``None``, or if the tree has no embeddable nodes.
        """
        if self._embedding_store is None or self._embed_fn is None:
            return []

        tree_name = self._tree.get("doc_name") or ""
        if not tree_name:
            logger.warning("_vec_rank: tree has no doc_name; skipping")
            return []

        # Lazy rebuild if the per-tree matrix was invalidated.
        result = self._embedding_store.load_tree_matrix(tree_name)
        if result is None:
            nodes = get_nodes(self._structure())
            if not nodes:
                return []
            try:
                result = self._embedding_store.build_tree_matrix(
                    tree_name, nodes, self._embed_fn
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("build_tree_matrix failed: %s", exc)
                return []

        matrix, node_order = result
        if matrix.shape[0] == 0:
            return []

        # Embed the query (sync call; embed_fn must be synchronous).
        try:
            q_vecs = self._embed_fn([query])
            q_vec = np.asarray(q_vecs[0], dtype=np.float32)
        except Exception as exc:  # noqa: BLE001
            logger.warning("embed_fn failed for query: %s", exc)
            return []

        # L2-normalise both query and matrix rows for cosine similarity.
        q_norm = np.linalg.norm(q_vec)
        if q_norm > 0.0:
            q_vec = q_vec / q_norm

        mat = np.asarray(matrix, dtype=np.float32)
        row_norms = np.linalg.norm(mat, axis=1, keepdims=True)
        row_norms = np.where(row_norms > 0.0, row_norms, 1.0)
        mat_normed = mat / row_norms

        scores = mat_normed @ q_vec  # (N,)
        k = min(top_k, len(node_order))
        top_indices = np.argsort(scores)[::-1][:k]
        return [node_order[int(i)] for i in top_indices]

    # ---- LLM walk ------------------------------------------------------

    async def _llm_rank(self, query: str) -> list[str]:
        retriever = PageIndexRetriever(
            tree=self._tree,
            adapter=self._adapter,
            model=self._model or self._adapter.model,
        )
        result = await retriever.search(query)
        return list(result.node_list or [])

    # ---- RRF -----------------------------------------------------------

    @staticmethod
    def _rrf_fuse(rankings: list[list[str]], k: int = _RRF_K) -> list[tuple[str, float]]:
        scores: dict[str, float] = {}
        for ranking in rankings:
            for rank, node_id in enumerate(ranking):
                if not node_id:
                    continue
                scores[node_id] = scores.get(node_id, 0.0) + 1.0 / (k + rank + 1)
        return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)

    # ---- Public search -------------------------------------------------

    async def search(
        self,
        query: str,
        top_k: int = 10,
        use_bm25: bool = True,
        use_llm_walk: bool = True,
        use_vec: bool = False,
        rerank: bool = False,
    ) -> list[dict[str, Any]]:
        """Run hybrid search and return a list of candidate node summaries.

        Each result is a dict with ``node_id``, ``title``, ``summary``,
        ``score`` and ``source`` (one of ``"bm25"``, ``"llm"``, ``"vec"``,
        ``"fused"``).

        When ``use_vec=False`` (the default), the output is byte-identical
        to the pre-embedding baseline.

        Args:
            query: Query string.
            top_k: Maximum number of results to return.
            use_bm25: Include BM25 lexical ranking signal.
            use_llm_walk: Include LLM tree-walk ranking signal.
            use_vec: Include dense cosine-similarity ranking signal (Phase A).
                Requires ``embedding_store`` and ``embed_fn`` to be set.
            rerank: Apply cross-encoder reranking to the fused candidates.

        Raises:
            ValueError: When all three signals are disabled.
        """
        if not (use_bm25 or use_llm_walk or use_vec):
            raise ValueError(
                "At least one of use_bm25 / use_llm_walk / use_vec must be True"
            )

        bm25_ranking: list[str] = []
        llm_ranking: list[str] = []
        vec_ranking: list[str] = []

        if use_bm25:
            bm25_ranking = self._bm25_rank(query, self._default_bm25_k)
        if use_llm_walk:
            llm_ranking = await self._llm_rank(query)
        if use_vec:
            # Run synchronous _vec_rank in a thread to avoid blocking the loop.
            vec_ranking = await asyncio.to_thread(self._vec_rank, query, top_k)

        # Build rankings list for RRF — only include signals that were requested.
        # Preserve byte-identical baseline when use_vec=False.
        rankings: list[list[str]] = []
        if use_bm25:
            rankings.append(bm25_ranking)
        if use_llm_walk:
            rankings.append(llm_ranking)
        if use_vec:
            rankings.append(vec_ranking)

        if len(rankings) > 1:
            fused = self._rrf_fuse(rankings)
            source = "fused"
        elif use_bm25:
            fused = [(nid, 1.0 / (i + 1)) for i, nid in enumerate(bm25_ranking)]
            source = "bm25"
        elif use_llm_walk:
            fused = [(nid, 1.0 / (i + 1)) for i, nid in enumerate(llm_ranking)]
            source = "llm"
        else:
            fused = [(nid, 1.0 / (i + 1)) for i, nid in enumerate(vec_ranking)]
            source = "vec"

        if not fused:
            return []

        structure = self._structure()
        results: list[dict[str, Any]] = []
        for node_id, score in fused:
            node = find_node_by_id(structure, node_id)
            if not node:
                continue
            results.append({
                "node_id": node_id,
                "title": node.get("title", ""),
                "summary": node.get("summary") or node.get("prefix_summary") or "",
                "score": score,
                "source": source,
            })

        if rerank and self._reranker is not None and results:
            results = await self._apply_reranker(query, results, top_k)
        else:
            results = results[:top_k]

        return results

    async def _apply_reranker(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        try:
            from parrot.models.stores import SearchResult
        except Exception as exc:
            logger.warning("Reranker unavailable: %s", exc)
            return candidates[:top_k]

        structure = self._structure()
        docs: list[SearchResult] = []
        for cand in candidates:
            node = find_node_by_id(structure, cand["node_id"]) or {}
            if self._content_loader is not None:
                body = self._load_body(cand["node_id"])[:_RERANK_TEXT_LIMIT]
            else:
                body = (node.get("text") or "")[:_RERANK_TEXT_LIMIT]
            content = "\n".join(
                part for part in (cand.get("title"), cand.get("summary"), body) if part
            )
            docs.append(SearchResult(
                id=cand["node_id"],
                content=content,
                metadata={"node_id": cand["node_id"]},
                score=float(cand["score"]),
            ))

        try:
            reranked = await self._reranker.rerank(query, docs, top_n=top_k)
        except Exception as exc:
            logger.warning("Reranker raised, falling back to fused order: %s", exc)
            return candidates[:top_k]

        cand_by_id = {c["node_id"]: c for c in candidates}
        ordered: list[dict[str, Any]] = []
        for item in reranked:
            doc_id = getattr(getattr(item, "document", item), "id", None) or getattr(item, "id", None)
            cand = cand_by_id.get(doc_id)
            if not cand:
                continue
            score = getattr(item, "rerank_score", None)
            new_cand = dict(cand)
            if isinstance(score, float):
                new_cand["score"] = score
            new_cand["source"] = "reranked"
            ordered.append(new_cand)
        return ordered[:top_k] if ordered else candidates[:top_k]
