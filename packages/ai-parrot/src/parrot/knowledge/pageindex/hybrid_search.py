"""Hybrid search over a PageIndex tree.

Combines three signals:

* **BM25** lexical search over flattened node text (title + summary + text).
  Backed by the ``bm25s`` library (an optional extra).
* **LLM tree walk** via :class:`PageIndexRetriever` — the existing
  reasoning-based retriever that selects a list of relevant node ids.
* **Reciprocal Rank Fusion** to combine the two rankings.

An :class:`AbstractReranker` may optionally be supplied to rerank the
fused candidate set with a cross-encoder.

The BM25 index is rebuilt lazily — every mutation calls ``mark_dirty``,
and the next ``search`` rebuilds before scoring.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from parrot._imports import lazy_import
from .llm_adapter import PageIndexLLMAdapter
from .retriever import PageIndexRetriever
from .utils import find_node_by_id, get_nodes


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
    """BM25 + LLM-walk hybrid retrieval wrapping a single tree.

    Args:
        tree: A PageIndex tree dict (``{doc_name, structure: [...]}``).
        adapter: The LLM adapter used by the inner :class:`PageIndexRetriever`.
        reranker: Optional reranker applied to the fused candidate set.
        model: Model passed through to :class:`PageIndexRetriever`.
        default_bm25_k: Number of candidates fetched from BM25 per query.
    """

    def __init__(
        self,
        tree: dict[str, Any],
        adapter: PageIndexLLMAdapter,
        reranker: Optional[Any] = None,
        model: Optional[str] = None,
        default_bm25_k: int = 20,
        content_loader: Optional[Callable[[str], Optional[str]]] = None,
    ):
        self._tree = tree
        self._adapter = adapter
        self._reranker = reranker
        self._model = model
        self._default_bm25_k = default_bm25_k
        self._content_loader = content_loader

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
        """Invalidate the BM25 index; it will be rebuilt on next search."""
        self._dirty = True

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
        rerank: bool = False,
    ) -> list[dict[str, Any]]:
        """Run hybrid search and return a list of candidate node summaries.

        Each result is a dict with ``node_id``, ``title``, ``summary``,
        ``score`` and ``source`` (one of ``"bm25"``, ``"llm"``, ``"fused"``).
        """
        if not (use_bm25 or use_llm_walk):
            raise ValueError("At least one of use_bm25 / use_llm_walk must be True")

        bm25_ranking: list[str] = []
        llm_ranking: list[str] = []
        if use_bm25:
            bm25_ranking = self._bm25_rank(query, self._default_bm25_k)
        if use_llm_walk:
            llm_ranking = await self._llm_rank(query)

        if use_bm25 and use_llm_walk:
            fused = self._rrf_fuse([bm25_ranking, llm_ranking])
            source = "fused"
        elif use_bm25:
            fused = [(nid, 1.0 / (i + 1)) for i, nid in enumerate(bm25_ranking)]
            source = "bm25"
        else:
            fused = [(nid, 1.0 / (i + 1)) for i, nid in enumerate(llm_ranking)]
            source = "llm"

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
            from parrot.stores.models import SearchResult
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
