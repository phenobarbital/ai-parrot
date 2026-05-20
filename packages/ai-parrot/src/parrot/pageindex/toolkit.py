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
        lightweight_model: Model id used for the Step-1 Chain-of-Thought
            analysis. A second :class:`PageIndexLLMAdapter` is built with
            this model, sharing the same underlying client; ``adapter`` is
            never mutated.
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
        tree = {"doc_name": doc_name or tree_name, "structure": []}
        self._trees[tree_name] = tree
        self._store.save(tree_name, tree)
        return {"tree_name": tree_name, "doc_name": tree["doc_name"]}

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
    ) -> list[dict[str, Any]]:
        """Hybrid search over a tree.

        Returns ordered candidates, each ``{node_id, title, summary, score, source}``.
        ``source`` is one of ``"bm25"``, ``"llm"``, ``"fused"``, ``"reranked"``.
        """
        engine = self._search_for(tree_name)
        return await engine.search(
            query=query,
            top_k=top_k,
            use_bm25=use_bm25,
            use_llm_walk=use_llm_walk,
            rerank=rerank,
        )

    async def retrieve(
        self,
        tree_name: str,
        query: str,
        top_k: int = 5,
    ) -> str:
        """Hybrid search + text aggregation for use in an LLM prompt."""
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
            body = node.get("text") or node.get("summary") or node.get("prefix_summary") or ""
            if body:
                parts.append(f"## {title}\n{body}")
        return "\n\n".join(parts)

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
        )
        new_ids = splice_subtree(tree, subtree, parent_node_id=parent_node_id)
        self._persist(tree_name)
        return {
            "tree_name": tree_name,
            "new_node_ids": new_ids,
            "doc_name": subtree.get("doc_name"),
            "doc_description": subtree.get("doc_description"),
        }

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
        """Delete a node and all its descendants from the tree."""
        tree = self._load_tree(tree_name)
        removed = _delete_node(tree, node_id)
        if removed:
            self._persist(tree_name)
        return {"tree_name": tree_name, "removed": removed}
