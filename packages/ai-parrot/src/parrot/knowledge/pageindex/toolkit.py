"""Agent-facing toolkit for PageIndex.

This toolkit lets an Agent manage one or more named PageIndex trees:
search them (hybrid BM25 + LLM-walk), retrieve aggregated text,
insert new pages from raw content (Two-Step Chain-of-Thought ingest),
and import whole folders preserving directory structure.

Per-tree storage is split into two artefacts:

    <storage_dir>/<tree_name>.json   — lean ToC tree (titles, summaries,
                                       categories, metadata)
    <storage_dir>/<tree_name>/       — sidecar markdown, one .md per node,
                                       served by NodeContentStore

This matches the upstream PageIndex contract: vectorless retrieval over
a hierarchical index, with bodies fetched on demand by node_id.
"""
from __future__ import annotations

import asyncio
import fnmatch
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from parrot.tools.toolkit import AbstractToolkit
from .builder import build_page_index
from .content_store import NodeContentStore
from .embedding_store import NodeEmbeddingStore
from .hybrid_search import HybridPageIndexSearch
from .ingest import IngestedMarkdown, TwoStepIngester
from .llm_adapter import PageIndexLLMAdapter
from .md_builder import md_to_tree
from .retriever import PageIndexRetriever
from .store import JSONTreeStore
from .tree_ops import (
    delete_node as _delete_node,
    make_folder_node,
    splice_subtree,
)
from .utils import find_node_by_id


logger = logging.getLogger("parrot.knowledge.pageindex.toolkit")

_MAX_TREES_HARD_CAP = 10


class PageIndexToolkit(AbstractToolkit):
    """Toolkit exposing search / retrieve / insert tools over PageIndex trees.

    Args:
        adapter: Heavy LLM adapter. Used for Step-2 markdown generation,
            tree-walk search, and node summarisation via :func:`md_to_tree`.
        storage_dir: Filesystem directory where each tree is persisted as
            ``<tree_name>.json``.
        reranker: Optional :class:`AbstractReranker` instance applied to
            the fused candidate set when ``rerank=True`` is requested.
        lightweight_model: Model id used for the cheaper helper calls —
            Step-1 Chain-of-Thought analysis during text ingest, and during
            ``import_pdf``: TOC-page detection, per-node summaries, doc
            description, title verification, and TOC accuracy checks. A
            second :class:`PageIndexLLMAdapter` is built with this model,
            sharing the same underlying client; ``adapter`` is never
            mutated.
        model: Optional override for the model passed to
            :class:`PageIndexRetriever`. Defaults to ``adapter.model``.
        default_bm25_k: Number of BM25 candidates fetched per query.
        folder_concurrency: Maximum concurrent file ingests during
            ``import_folder``.
        embedding_model: Sentence-Transformers model identifier for
            dense node embeddings (FEAT-237).  Defaults to the
            ``EMBEDDING_DEFAULT_MODEL`` config value when embedding is
            enabled.
        embedding_dimension: Dimensionality of the embedding vectors.
            Must match the selected model's output (or MRL truncation dim).
        embedding_backend: Optional runtime backend for
            ``SentenceTransformerModel`` — ``"onnx"``, ``"openvino"``, or
            ``None`` (default torch).
        use_vec_rank: Enable Phase A dense cosine-similarity ranking signal.
        use_embedding_walk: Enable Phase B embedding-guided beam walk.
    """

    name = "pageindex"
    tool_prefix = "pageindex"

    def __init__(
        self,
        adapter: PageIndexLLMAdapter,
        storage_dir: str | Path,
        reranker: Optional[Any] = None,
        lightweight_model: Optional[str] = None,
        model: Optional[str] = None,
        default_bm25_k: int = 20,
        folder_concurrency: int = 4,
        content_cache_size: int = 256,
        embedding_model: Optional[str] = None,
        embedding_dimension: int = 256,
        embedding_backend: Optional[str] = None,
        use_vec_rank: bool = False,
        use_embedding_walk: bool = False,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self._adapter = adapter
        self._light_adapter: Optional[PageIndexLLMAdapter] = (
            PageIndexLLMAdapter(client=adapter.client, model=lightweight_model)
            if lightweight_model
            else None
        )
        self._store = JSONTreeStore(storage_dir)
        self._content_store = NodeContentStore(
            storage_dir, cache_size=content_cache_size
        )
        self._reranker = reranker
        self._model = model or adapter.model
        self._default_bm25_k = default_bm25_k
        self._folder_concurrency = max(1, folder_concurrency)
        self._use_vec_rank = use_vec_rank
        self._use_embedding_walk = use_embedding_walk

        # ---- Embedding store (FEAT-237) ---------------------------------
        # Constructed only when at least one embedding feature is enabled.
        # When both are False, behaviour is identical to pre-FEAT-237.
        self._embedding_store: Optional[NodeEmbeddingStore] = None
        self._embed_fn = None
        if use_vec_rank or use_embedding_walk:
            from parrot.conf import EMBEDDING_DEFAULT_MODEL
            from parrot.embeddings.registry import EmbeddingRegistry
            emb_model_name = embedding_model or EMBEDDING_DEFAULT_MODEL
            self._embedding_store = NodeEmbeddingStore(
                storage_dir=storage_dir,
                model_id=emb_model_name,
                dimension=embedding_dimension,
            )
            _backend = embedding_backend  # closure captures value

            def _make_embed_fn(name: str, backend: Optional[str]):
                """Return a lazy-loading sync embed function."""
                _raw_model = None

                def _embed(texts: list[str]):
                    nonlocal _raw_model
                    if _raw_model is None:
                        registry = EmbeddingRegistry.instance()
                        kw = {}
                        if backend is not None:
                            kw["backend"] = backend
                        wrapper = registry.get_or_create_sync(name, "huggingface", **kw)
                        _raw_model = wrapper.model  # underlying SentenceTransformer
                    import numpy as _np
                    result = _raw_model.encode(texts, convert_to_numpy=True)
                    return _np.asarray(result, dtype=_np.float32)

                return _embed

            self._embed_fn = _make_embed_fn(emb_model_name, _backend)

        self._trees: dict[str, dict[str, Any]] = {}
        self._search: dict[str, HybridPageIndexSearch] = {}
        self._batch_depth: dict[str, int] = {}
        self._batch_dirty: dict[str, bool] = {}

    # ---- internal helpers ----------------------------------------------

    def _ingester(self) -> TwoStepIngester:
        return TwoStepIngester(
            adapter=self._adapter,
            lightweight_adapter=self._light_adapter,
        )

    def _load_tree(self, tree_name: str) -> dict[str, Any]:
        if tree_name in self._trees:
            return self._trees[tree_name]
        if not self._store.exists(tree_name):
            raise KeyError(f"Tree {tree_name!r} does not exist")
        tree = self._store.load(tree_name)
        self._trees[tree_name] = tree
        return tree

    def _search_for(self, tree_name: str) -> HybridPageIndexSearch:
        tree = self._load_tree(tree_name)
        engine = self._search.get(tree_name)
        if engine is None:
            engine = HybridPageIndexSearch(
                tree=tree,
                adapter=self._adapter,
                reranker=self._reranker,
                model=self._model,
                default_bm25_k=self._default_bm25_k,
                content_loader=self._content_store.loader_for(tree_name),
                embedding_store=self._embedding_store,
                embed_fn=self._embed_fn,
                use_vec_rank=self._use_vec_rank,
                use_embedding_walk=self._use_embedding_walk,
            )
            self._search[tree_name] = engine
        return engine

    def _persist(self, tree_name: str) -> None:
        tree = self._trees.get(tree_name)
        if tree is None:
            return
        if self._batch_depth.get(tree_name, 0) > 0:
            self._batch_dirty[tree_name] = True
            return
        self._store.save(tree_name, tree)
        engine = self._search.get(tree_name)
        if engine is not None:
            engine.mark_dirty()

    @asynccontextmanager
    async def _batch(self, tree_name: str):
        self._batch_depth[tree_name] = self._batch_depth.get(tree_name, 0) + 1
        try:
            yield
        finally:
            self._batch_depth[tree_name] -= 1
            if self._batch_depth[tree_name] == 0 and self._batch_dirty.pop(tree_name, False):
                self._persist(tree_name)

    # ---- tool methods --------------------------------------------------

    async def list_trees(self) -> list[str]:
        """List all PageIndex tree names available in the storage directory."""
        return self._store.list_names()

    async def create_tree(
        self,
        tree_name: str,
        doc_name: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a new empty PageIndex tree.

        Args:
            tree_name: Unique name for the tree (filesystem-safe).
            doc_name: Optional display name for the tree's root document.
        """
        if self._store.exists(tree_name):
            raise ValueError(f"Tree {tree_name!r} already exists")
        # Defensive: a stale content directory from a previous tree with the
        # same name would silently feed wrong sidecars into retrieval.
        self._content_store.delete_tree(tree_name)
        tree = {"doc_name": doc_name or tree_name, "structure": []}
        self._trees[tree_name] = tree
        self._store.save(tree_name, tree)
        return {"tree_name": tree_name, "doc_name": tree["doc_name"]}

    async def delete_tree(self, tree_name: str) -> dict[str, Any]:
        """Delete a tree JSON and every sidecar markdown file for it."""
        tree_removed = self._store.delete(tree_name)
        sidecars_removed = self._content_store.delete_tree(tree_name)
        self._trees.pop(tree_name, None)
        self._search.pop(tree_name, None)
        return {
            "tree_name": tree_name,
            "tree_removed": tree_removed,
            "sidecars_removed": sidecars_removed,
        }

    async def get_tree(self, tree_name: str) -> dict[str, Any]:
        """Return the full tree dict for ``tree_name``."""
        return self._load_tree(tree_name)

    async def search(
        self,
        tree_name: str,
        query: str,
        top_k: int = 10,
        use_bm25: bool = True,
        use_llm_walk: bool = True,
        rerank: bool = False,
        categories: Optional[list[str]] = None,
        metadata_filter: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """Hybrid search over a tree.

        Returns ordered candidates, each ``{node_id, title, summary, score, source}``.
        ``source`` is one of ``"bm25"``, ``"llm"``, ``"fused"``, ``"reranked"``.

        Args:
            categories: When set, candidates whose node does NOT carry
                **all** of the listed categories are filtered out
                (AND-semantics).
            metadata_filter: When set, candidates whose node metadata
                does not have ``metadata[k] == v`` for every ``(k, v)``
                in the dict are filtered out (equality-only).
        """
        engine = self._search_for(tree_name)
        # Over-fetch slightly when filtering so we still return ``top_k``
        # results after the post-filter where possible. The engine itself
        # caps to its own internal bm25 budget.
        fetch_k = top_k
        if categories or metadata_filter:
            fetch_k = max(top_k * 4, top_k)
        results = await engine.search(
            query=query,
            top_k=fetch_k,
            use_bm25=use_bm25,
            use_llm_walk=use_llm_walk,
            rerank=rerank,
        )
        if categories or metadata_filter:
            results = self._apply_filters(
                tree_name, results, categories, metadata_filter
            )
        return results[:top_k]

    def _apply_filters(
        self,
        tree_name: str,
        results: list[dict[str, Any]],
        categories: Optional[list[str]],
        metadata_filter: Optional[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        tree = self._trees.get(tree_name) or self._store.load(tree_name)
        structure = tree.get("structure", [])
        required_categories = set(categories or [])
        filtered: list[dict[str, Any]] = []
        for cand in results:
            node = find_node_by_id(structure, cand["node_id"]) or {}
            if required_categories:
                node_cats = set(node.get("categories") or [])
                if not required_categories.issubset(node_cats):
                    continue
            if metadata_filter:
                node_meta = node.get("metadata") or {}
                if not all(
                    node_meta.get(k) == v for k, v in metadata_filter.items()
                ):
                    continue
            filtered.append(cand)
        return filtered

    async def retrieve(
        self,
        tree_name: str,
        query: str,
        top_k: int = 5,
    ) -> str:
        """Hybrid search + per-node markdown aggregation.

        Loads each result's markdown from :class:`NodeContentStore`. Falls
        back to summary text only when the content sidecar is missing
        (e.g. a tree imported before this feature).
        """
        candidates = await self.search(
            tree_name=tree_name,
            query=query,
            top_k=top_k,
            use_bm25=True,
            use_llm_walk=True,
            rerank=False,
        )
        if not candidates:
            return ""
        tree = self._load_tree(tree_name)
        structure = tree.get("structure", [])
        parts: list[str] = []
        for cand in candidates:
            node = find_node_by_id(structure, cand["node_id"])
            if not node:
                continue
            title = node.get("title") or "Section"
            body = self._content_store.load(tree_name, cand["node_id"])
            if not body:
                body = (
                    node.get("text")
                    or node.get("summary")
                    or node.get("prefix_summary")
                    or ""
                )
            if body:
                parts.append(f"## {title}\n{body}")
        return "\n\n".join(parts)

    async def search_documents_scoped(
        self,
        tree_names: list[str],
        query: str,
        include_tree_context: bool = False,
        max_trees: int = _MAX_TREES_HARD_CAP,
    ) -> dict[str, Any]:
        """Run an LLM tree-walk against a SUBSET of trees in one call.

        Iterates over ``tree_names``, runs :class:`PageIndexRetriever`
        per tree (LLM-walk only — no BM25), and assembles a per-tree
        ``context`` string from sidecar markdown loaded via
        :class:`NodeContentStore`. Falls back to summaries when a node
        has no sidecar (e.g. legacy tree).

        Designed for the ontology routing pattern: a graph query
        produces a list of ``Document.pageindex_tree_id`` values, this
        method searches just those trees, the agent grounds its answer
        in the merged result.

        Missing tree names are skipped with a WARNING log. Returns
        ``{"status": "empty", ...}`` when the input is empty or every
        name is missing.

        Args:
            tree_names: Tree names to search. Order is preserved.
            query: Free-form natural-language query.
            include_tree_context: When ``True``, each result entry
                carries the per-tree ``tree_context`` blob from
                :meth:`PageIndexRetriever.get_tree_context`.
            max_trees: Hard cap on the number of trees searched
                (default and max: 10). Names past the cap are dropped
                with a DEBUG log.

        Returns:
            ``{"status": "ok"|"empty", "scoped_results": [...]}``.
            Each entry has::

                {
                    "tree_name": str,
                    "doc_name":  str | None,
                    "node_list": list[str],
                    "thinking":  str,
                    "context":   str,
                    # only when include_tree_context=True:
                    "tree_context": str,
                }
        """
        if not tree_names:
            return {"status": "empty", "scoped_results": []}

        effective = tree_names[: max_trees]
        if len(tree_names) > max_trees:
            logger.debug(
                "search_documents_scoped: capping tree_names from %d to %d",
                len(tree_names),
                max_trees,
            )

        scoped_results: list[dict[str, Any]] = []

        for tree_name in effective:
            if not self._store.exists(tree_name):
                logger.warning(
                    "search_documents_scoped: tree %r not found — skipping",
                    tree_name,
                )
                continue

            tree = self._load_tree(tree_name)
            retriever = PageIndexRetriever(
                tree=tree,
                adapter=self._adapter,
                model=self._model,
            )
            search_result = await retriever.search(query)

            context_parts: list[str] = []
            structure = tree.get("structure", [])
            for node_id in search_result.node_list or []:
                node = find_node_by_id(structure, node_id)
                if not node:
                    continue
                title = node.get("title") or "Section"
                body = self._content_store.load(tree_name, node_id)
                if not body:
                    body = (
                        node.get("summary")
                        or node.get("prefix_summary")
                        or ""
                    )
                if body:
                    context_parts.append(f"## {title}\n{body}")

            entry: dict[str, Any] = {
                "tree_name": tree_name,
                "doc_name": tree.get("doc_name"),
                "node_list": list(search_result.node_list or []),
                "thinking": search_result.thinking,
                "context": "\n\n".join(context_parts),
            }
            if include_tree_context:
                entry["tree_context"] = retriever.get_tree_context(
                    include_summaries=True,
                )
            scoped_results.append(entry)

        if not scoped_results:
            return {"status": "empty", "scoped_results": []}
        return {"status": "ok", "scoped_results": scoped_results}

    async def tag_node(
        self,
        tree_name: str,
        node_id: str,
        categories: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Add or merge ``categories`` / ``metadata`` tags on a node.

        Categories are merged as a set (sorted on persist); metadata as
        a shallow dict (later writes win on overlapping keys). The tree
        is persisted and the BM25 index is marked dirty so the next
        search picks up the change.

        Args:
            tree_name: Tree containing the node.
            node_id: Node id to tag.
            categories: Categories to add to the node. Free-form strings.
            metadata: Arbitrary key/value pairs to merge into the node's
                metadata. Equality-match only for v1 — range queries
                and wildcards are out of scope.

        Returns:
            ``{tree_name, node_id, categories, metadata}`` with the
            post-merge values.
        """
        tree = self._load_tree(tree_name)
        node = find_node_by_id(tree.get("structure", []), node_id)
        if node is None:
            raise KeyError(f"node_id {node_id!r} not found in tree {tree_name!r}")

        if categories:
            existing = set(node.get("categories") or [])
            existing.update(str(c) for c in categories)
            node["categories"] = sorted(existing)
        if metadata:
            existing_meta = dict(node.get("metadata") or {})
            existing_meta.update(metadata)
            node["metadata"] = existing_meta

        # Drop empty containers so the persisted JSON stays lean.
        if not node.get("categories"):
            node.pop("categories", None)
        if not node.get("metadata"):
            node.pop("metadata", None)

        self._persist(tree_name)
        return {
            "tree_name": tree_name,
            "node_id": node_id,
            "categories": list(node.get("categories") or []),
            "metadata": dict(node.get("metadata") or {}),
        }

    async def insert_markdown(
        self,
        tree_name: str,
        markdown: str,
        parent_node_id: Optional[str] = None,
        doc_name: Optional[str] = None,
    ) -> dict[str, Any]:
        """Parse ``markdown`` into a PageIndex subtree and splice it in.

        Lean-tree semantics: the ToC keeps titles, summaries, and metadata;
        the per-node markdown body is moved to :class:`NodeContentStore`
        keyed by ``node_id``. This matches the PageIndex contract — the
        persisted JSON does NOT carry inline ``text`` fields.

        ``parent_node_id=None`` appends at the tree root.
        """
        tree = self._load_tree(tree_name)
        subtree = await md_to_tree(
            md_text=markdown,
            adapter=self._adapter,
            doc_name=doc_name or "ingested.md",
        )
        # Build-time scratch fields that should never reach disk.
        node_markdown = _pop_node_field(subtree, "text")
        _strip_keys_in_place(subtree, ("token_count", "line_num"))
        original_id_to_node = _capture_node_id_object_map(subtree)
        new_ids = splice_subtree(tree, subtree, parent_node_id=parent_node_id)
        self._save_node_markdown(tree_name, original_id_to_node, node_markdown)
        self._persist(tree_name)
        return {"tree_name": tree_name, "new_node_ids": new_ids}

    async def insert_content(
        self,
        tree_name: str,
        content: str,
        parent_node_id: Optional[str] = None,
        hint: Optional[str] = None,
    ) -> dict[str, Any]:
        """Two-Step CoT ingest of raw content into the tree.

        Step 1 analyses the content with the lightweight model; Step 2
        generates clean markdown which is then parsed via
        :func:`md_to_tree` and spliced under ``parent_node_id``.
        """
        ingested: IngestedMarkdown = await self._ingester().ingest(content, hint=hint)
        result = await self.insert_markdown(
            tree_name=tree_name,
            markdown=ingested.markdown,
            parent_node_id=parent_node_id,
            doc_name=ingested.title,
        )
        result["title"] = ingested.title
        result["summary"] = ingested.summary
        return result

    async def import_file(
        self,
        tree_name: str,
        file_path: str,
        parent_node_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Read a text file and ingest it via :meth:`insert_content`."""
        path = Path(file_path)
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{file_path!r} is not a UTF-8 text file") from exc
        return await self.insert_content(
            tree_name=tree_name,
            content=content,
            parent_node_id=parent_node_id,
            hint=f"Source filename: {path.name}",
        )

    async def import_pdf(
        self,
        tree_name: str,
        pdf_path: str,
        parent_node_id: Optional[str] = None,
        with_summaries: bool = True,
        with_doc_description: bool = False,
    ) -> dict[str, Any]:
        """Build a PageIndex subtree from a PDF and splice it into ``tree_name``.

        Args:
            tree_name: Existing tree to insert into.
            pdf_path: Path to the source PDF on disk.
            parent_node_id: Insert under this node id, or at root if ``None``.
            with_summaries: When ``True``, generate per-node LLM summaries.
            with_doc_description: When ``True``, also generate a one-sentence
                top-level document description.

        Returns:
            ``{tree_name, new_node_ids, doc_name, doc_description?, pages}``
        """
        if not Path(pdf_path).is_file():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        tree = self._load_tree(tree_name)
        subtree = await build_page_index(
            doc=pdf_path,
            adapter=self._adapter,
            options={
                "if_add_node_summary": "yes" if with_summaries else "no",
                "if_add_doc_description": "yes" if with_doc_description else "no",
                "if_add_node_id": "yes",
            },
            light_adapter=self._light_adapter,
        )
        # ``build_page_index`` returns per-node markdown keyed by the
        # build-time node ids. Splicing renumbers ids tree-wide, so we
        # capture object references BEFORE the splice to recover the
        # new ids afterwards.
        node_markdown = dict(subtree.pop("_node_markdown", {}) or {})
        original_id_to_node = _capture_node_id_object_map(subtree)
        new_ids = splice_subtree(tree, subtree, parent_node_id=parent_node_id)
        self._save_node_markdown(tree_name, original_id_to_node, node_markdown)
        self._persist(tree_name)
        return {
            "tree_name": tree_name,
            "new_node_ids": new_ids,
            "doc_name": subtree.get("doc_name"),
            "doc_description": subtree.get("doc_description"),
        }

    def _save_node_markdown(
        self,
        tree_name: str,
        original_id_to_node: dict[str, dict[str, Any]],
        node_markdown: dict[str, str],
    ) -> None:
        """Persist per-node markdown after a splice + reindex.

        ``splice_subtree`` reuses the original node dict references and
        :func:`reindex_node_ids` mutates ``node_id`` in place, so the
        same dict objects we captured before the splice now carry the
        post-splice ids — no path reconstruction needed.
        """
        if not node_markdown:
            return
        for original_id, markdown in node_markdown.items():
            node = original_id_to_node.get(original_id)
            if node is None:
                continue
            new_id = node.get("node_id")
            if not new_id:
                continue
            self._content_store.save(tree_name, new_id, markdown or "")

    async def import_folder(
        self,
        tree_name: str,
        folder_path: str,
        recursive: bool = True,
        glob_pattern: str = "*",
        parent_node_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Recursively import all matching files from ``folder_path``.

        Directories become synthetic inner nodes that mirror the source
        layout; files are ingested concurrently (capped by
        ``folder_concurrency``). Binary files that are not UTF-8 decodable
        are skipped with a WARNING log line.
        """
        root = Path(folder_path)
        if not root.is_dir():
            raise NotADirectoryError(f"{folder_path!r} is not a directory")

        tree = self._load_tree(tree_name)
        sem = asyncio.Semaphore(self._folder_concurrency)
        imported: list[str] = []
        skipped: list[str] = []

        async def _ingest_file(path: Path, parent_id: Optional[str]) -> None:
            async with sem:
                try:
                    content = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    logger.warning("Skipping non-text file: %s", path)
                    skipped.append(str(path))
                    return
                try:
                    await self.insert_content(
                        tree_name=tree_name,
                        content=content,
                        parent_node_id=parent_id,
                        hint=f"Source filename: {path.name}",
                    )
                    imported.append(str(path))
                except Exception as exc:
                    logger.warning("Failed to ingest %s: %s", path, exc)
                    skipped.append(str(path))

        async def _process_dir(dir_path: Path, parent_id: Optional[str]) -> None:
            files = [
                p for p in sorted(dir_path.iterdir())
                if p.is_file()
                and not p.name.startswith(".")
                and fnmatch.fnmatch(p.name, glob_pattern)
            ]
            subdirs = (
                [p for p in sorted(dir_path.iterdir())
                 if p.is_dir() and not p.name.startswith(".")]
                if recursive
                else []
            )
            if files:
                await asyncio.gather(*[_ingest_file(f, parent_id) for f in files])
            for sub in subdirs:
                folder_node = make_folder_node(sub.name)
                splice_subtree(tree, folder_node, parent_node_id=parent_id)
                new_parent_id = folder_node.get("node_id")
                await _process_dir(sub, new_parent_id)

        async with self._batch(tree_name):
            await _process_dir(root, parent_node_id)
            self._batch_dirty[tree_name] = True

        return {
            "tree_name": tree_name,
            "imported": imported,
            "skipped": skipped,
        }

    async def delete_node(
        self,
        tree_name: str,
        node_id: str,
    ) -> dict[str, Any]:
        """Delete a node and all its descendants from the tree.

        Also removes any sidecar markdown for the deleted subtree and
        evicts the matching LRU cache entries so a later ``retrieve``
        cannot see stale content.
        """
        tree = self._load_tree(tree_name)
        node = find_node_by_id(tree.get("structure", []), node_id)
        descendant_ids: list[str] = []
        if node is not None:
            descendant_ids = _collect_node_ids(node)
        removed = _delete_node(tree, node_id)
        if removed:
            for nid in descendant_ids:
                self._content_store.delete_node(tree_name, nid)
            self._persist(tree_name)
        return {"tree_name": tree_name, "removed": removed}

    async def add_node(
        self,
        tree_name: str,
        title: str,
        body: str = "",
        parent_node_id: Optional[str] = None,
        summary: Optional[str] = None,
        categories: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Atomically create a single node and register its content.

        The PageIndex authoring primitive: an agent says "register this
        finding under section X" and gets back the new ``node_id`` —
        one call, one node, body persisted via :class:`NodeContentStore`,
        tags merged in the same write.

        Args:
            tree_name: Tree to insert into.
            title: Node title — the human-facing label that BM25 and
                the LLM walker see.
            body: Markdown body. Persisted as the node's sidecar so
                ``retrieve`` returns it verbatim. Empty body is allowed
                (synthetic / placeholder nodes).
            parent_node_id: Insert under this node id; ``None`` appends
                at the tree root.
            summary: Optional short description the LLM walker uses
                when deciding which node to dive into. Defaults to an
                empty string.
            categories: Free-form tags merged as a set.
            metadata: Arbitrary key/value pairs (equality-only matching
                at search time).

        Returns:
            ``{tree_name, node_id, parent_node_id}`` with the post-splice
            ``node_id`` of the new node.
        """
        if not isinstance(title, str) or not title.strip():
            raise ValueError("add_node requires a non-empty title")

        node: dict[str, Any] = {
            "title": title.strip(),
            "summary": summary or "",
        }
        if categories:
            node["categories"] = sorted({str(c) for c in categories})
        if metadata:
            node["metadata"] = dict(metadata)

        tree = self._load_tree(tree_name)
        new_ids = splice_subtree(tree, node, parent_node_id=parent_node_id)
        new_id = new_ids[0] if new_ids else node.get("node_id")
        if new_id and body:
            self._content_store.save(tree_name, new_id, body)
        self._persist(tree_name)
        return {
            "tree_name": tree_name,
            "node_id": new_id,
            "parent_node_id": parent_node_id,
        }

    async def update_node_content(
        self,
        tree_name: str,
        node_id: str,
        body: str,
    ) -> dict[str, Any]:
        """Overwrite a node's sidecar markdown without touching the tree.

        Use this when an agent revises a finding — the ToC entry stays
        put (same title, summary, position) but the body is rewritten.
        Marks the BM25 index dirty so the next search reflects the
        new content.

        Raises:
            KeyError: If ``node_id`` does not exist in the tree.
        """
        tree = self._load_tree(tree_name)
        node = find_node_by_id(tree.get("structure", []), node_id)
        if node is None:
            raise KeyError(f"node_id {node_id!r} not found in tree {tree_name!r}")
        self._content_store.save(tree_name, node_id, body or "")
        engine = self._search.get(tree_name)
        if engine is not None:
            engine.mark_dirty()
        return {
            "tree_name": tree_name,
            "node_id": node_id,
            "bytes": len(body or ""),
        }

    async def update_node(
        self,
        tree_name: str,
        node_id: str,
        title: Optional[str] = None,
        summary: Optional[str] = None,
    ) -> dict[str, Any]:
        """Rename and/or re-summarize an existing node.

        Persists the tree and marks the BM25 index dirty (title and
        summary both feed the corpus). Body / categories / metadata
        are untouched — use :meth:`update_node_content` or
        :meth:`tag_node` for those.

        Raises:
            KeyError: If ``node_id`` does not exist.
            ValueError: If neither ``title`` nor ``summary`` is set.
        """
        if title is None and summary is None:
            raise ValueError("update_node needs at least one of title / summary")

        tree = self._load_tree(tree_name)
        node = find_node_by_id(tree.get("structure", []), node_id)
        if node is None:
            raise KeyError(f"node_id {node_id!r} not found in tree {tree_name!r}")

        if title is not None:
            if not isinstance(title, str) or not title.strip():
                raise ValueError("title must be a non-empty string")
            node["title"] = title.strip()
        if summary is not None:
            node["summary"] = summary

        self._persist(tree_name)
        return {
            "tree_name": tree_name,
            "node_id": node_id,
            "title": node.get("title"),
            "summary": node.get("summary"),
        }


# ---- module-level helpers ----------------------------------------------

def _pop_node_field(subtree: Any, field: str) -> dict[str, str]:
    """Remove ``field`` from every node and return ``{node_id: value}``.

    Used by markdown-path ingest to move the inline ``text`` field
    written by :func:`md_to_tree` into :class:`NodeContentStore` —
    keyed by ``node_id`` so it matches the PDF ingest contract.

    Nodes without a ``node_id`` (e.g. synthetic root containers) are
    skipped; the field is still removed from them so the persisted
    tree stays lean.
    """
    out: dict[str, str] = {}

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            value = node.pop(field, None)
            nid = node.get("node_id")
            if nid and isinstance(value, str) and value:
                out[str(nid)] = value
            children = node.get("nodes")
            if children:
                _walk(children)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    if isinstance(subtree, dict) and "structure" in subtree:
        _walk(subtree.get("structure"))
    else:
        _walk(subtree)
    return out


def _strip_keys_in_place(subtree: Any, keys: tuple[str, ...]) -> None:
    """Remove ``keys`` from every node dict reached from ``subtree``.

    PageIndex trees are the canonical on-disk artefact for retrieval;
    build-time scratch fields like ``token_count`` and ``line_num``
    have no consumer at retrieval time and would bloat the JSON.
    """
    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for k in keys:
                node.pop(k, None)
            children = node.get("nodes")
            if children:
                _walk(children)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    if isinstance(subtree, dict) and "structure" in subtree:
        _walk(subtree.get("structure"))
    else:
        _walk(subtree)


def _capture_node_id_object_map(subtree: Any) -> dict[str, dict[str, Any]]:
    """Record ``node_id -> node-dict`` references for every node in ``subtree``.

    ``splice_subtree`` reuses these dict objects in-place; later
    reindexing rewrites their ``node_id`` field without changing the
    object identity. Holding the references lets us recover the
    post-splice ids without rewalking the parent tree.
    """
    out: dict[str, dict[str, Any]] = {}

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            nid = node.get("node_id")
            if nid:
                out[str(nid)] = node
            children = node.get("nodes")
            if children:
                _walk(children)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    if isinstance(subtree, dict) and "structure" in subtree:
        _walk(subtree.get("structure"))
    else:
        _walk(subtree)
    return out


def _collect_node_ids(node: Any) -> list[str]:
    """Return every ``node_id`` reachable from ``node`` (inclusive)."""
    ids: list[str] = []

    def _walk(n: Any) -> None:
        if isinstance(n, dict):
            nid = n.get("node_id")
            if nid:
                ids.append(str(nid))
            children = n.get("nodes")
            if isinstance(children, list):
                for child in children:
                    _walk(child)
        elif isinstance(n, list):
            for item in n:
                _walk(item)

    _walk(node)
    return ids
