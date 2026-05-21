"""Agent-facing toolkit for PageIndex.

This toolkit lets an Agent manage one or more named PageIndex trees:
search them (hybrid BM25 + LLM-walk), retrieve aggregated text,
insert new pages from raw content (Two-Step Chain-of-Thought ingest),
and import whole folders preserving directory structure.

The toolkit lives inside ``parrot/pageindex/`` (rather than
``parrot/tools/``) because every tool here is conceptually a PageIndex
operation; the older ``parrot.tools.pageindex_toolkit.PageIndexToolkit``
is a different surface (UUID-keyed indices) and is unchanged.
"""
from __future__ import annotations

import asyncio
import fnmatch
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from ..tools.toolkit import AbstractToolkit
from .builder import build_page_index
from .content_store import NodeContentStore
from .hybrid_search import HybridPageIndexSearch
from .ingest import IngestedMarkdown, TwoStepIngester
from .llm_adapter import PageIndexLLMAdapter
from .md_builder import md_to_tree
from .retriever import PageIndexRetriever
from .store import JSONTreeStore
from .tree_ops import (
    delete_node as _delete_node,
    make_folder_node,
    reindex_node_ids,
    splice_subtree,
)
from .utils import find_node_by_id


logger = logging.getLogger("parrot.pageindex")


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

        ``parent_node_id=None`` appends at the tree root.
        """
        tree = self._load_tree(tree_name)
        subtree = await md_to_tree(
            md_text=markdown,
            adapter=self._adapter,
            doc_name=doc_name or "ingested.md",
        )
        new_ids = splice_subtree(tree, subtree, parent_node_id=parent_node_id)
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


# ---- module-level helpers ----------------------------------------------

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
