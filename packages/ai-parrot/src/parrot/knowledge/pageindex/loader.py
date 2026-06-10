"""PageIndexLoader — :class:`AbstractLoader` wrapper around PageIndex.

This loader accepts a list of files (PDF / Markdown / plain text), drives the
existing :class:`~parrot.knowledge.pageindex.toolkit.PageIndexToolkit` to build a
single hierarchical **PageIndex tree** (a lean ToC tree plus per-node markdown
sidecars persisted under ``storage_dir``), and exposes the result through the
familiar loader contract.

Two complementary views of the same build are offered:

* ``load()`` returns **one** :class:`~parrot.stores.models.Document` **per tree
  node** so the output flows straight into the existing RAG / vector-store
  pipeline. Re-chunking is disabled by default because tree nodes are already
  bounded retrieval units.
* :meth:`build_tree` / the :pyattr:`tree` property return the **native** tree
  dict (validated against :class:`PageIndexTree`), and :pyattr:`toolkit`
  exposes the underlying toolkit for downstream hybrid search / retrieval.

Persistence is mandatory (decision recorded in the feature plan): a
``storage_dir`` must be supplied and every tree is written to disk via the
toolkit so it is immediately searchable afterwards.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional, Union

from parrot.loaders.abstract import AbstractLoader
from parrot.stores.models import Document

from .content_store import NodeContentStore
from .llm_adapter import PageIndexLLMAdapter
from .schemas import PageIndexTree
from .toolkit import PageIndexToolkit
from .utils import find_node_by_id


class PageIndexLoader(AbstractLoader):
    """Build a PageIndex tree from a list of files.

    Args:
        source: Path, directory, or list of paths/directories to ingest.
            Resolved the same way :class:`AbstractLoader` resolves sources,
            filtered by :pyattr:`extensions`.
        storage_dir: **Required.** Directory where the tree JSON and per-node
            markdown sidecars are persisted (via :class:`PageIndexToolkit`).
        tree_name: Name of the single aggregate tree all files are imported
            into. Must match ``[A-Za-z0-9_-]{1,128}``.
        client: An ``AbstractClient`` used to drive the PageIndex LLM calls.
            Ignored when ``adapter`` is supplied. When both ``client`` and
            ``adapter`` are ``None`` a default client is created via
            :meth:`AbstractLoader.get_default_llm`.
        model: Heavy model id for the adapter (tree-walk, summaries, Step-2
            markdown generation).
        lightweight_model: Optional cheaper model id for the toolkit's helper
            calls (TOC detection, Step-1 analysis, summaries).
        adapter: A pre-built :class:`PageIndexLLMAdapter`. Takes precedence over
            ``client`` / ``model``.
        with_summaries: Generate per-node LLM summaries when importing PDFs.
        with_doc_description: Generate a one-sentence document description when
            importing PDFs.
        reset_tree: When ``True`` (default) an existing tree with the same name
            is deleted before ingestion so each ``load()`` is reproducible.
            Set ``False`` to append to an existing tree.
        **kwargs: Forwarded to :class:`AbstractLoader`.

    Raises:
        ValueError: If ``storage_dir`` is not provided.
    """

    extensions: List[str] = ['.pdf', '.md', '.markdown', '.txt', '.text']

    def __init__(
        self,
        source: Optional[Union[str, Path, List[Union[str, Path]]]] = None,
        *,
        storage_dir: Optional[Union[str, Path]] = None,
        tree_name: str = "pageindex",
        client: Any = None,
        model: Optional[str] = None,
        lightweight_model: Optional[str] = None,
        adapter: Optional[PageIndexLLMAdapter] = None,
        with_summaries: bool = True,
        with_doc_description: bool = True,
        reset_tree: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(source, **kwargs)
        if storage_dir is None:
            raise ValueError(
                "PageIndexLoader requires a 'storage_dir' — trees are always "
                "persisted via PageIndexToolkit."
            )

        self.doctype = 'pageindex_node'
        self.storage_dir = Path(storage_dir)
        self.tree_name = tree_name
        self.with_summaries = with_summaries
        self.with_doc_description = with_doc_description
        self.reset_tree = reset_tree

        # Resolve / build the LLM adapter.
        if adapter is not None:
            self._adapter = adapter
        else:
            if client is None:
                client = self.get_default_llm(model=model)
            self._adapter = PageIndexLLMAdapter(client=client, model=model)

        self.toolkit = PageIndexToolkit(
            adapter=self._adapter,
            storage_dir=self.storage_dir,
            lightweight_model=lightweight_model,
        )
        # Independent reader over the same sidecar directory (public API).
        self._content_store = NodeContentStore(self.storage_dir)
        self._tree: Optional[dict] = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def load(  # type: ignore[override]
        self,
        source: Optional[Any] = None,
        split_documents: bool = False,
        **kwargs: Any,
    ) -> List[Document]:
        """Import every file into one tree and return per-node Documents.

        Unlike the base loader this runs ingestion **sequentially** (the
        toolkit performs read-modify-write on a shared tree JSON, so concurrent
        splices would race) and leaves ``split_documents`` ``False`` by default.

        Args:
            source: Override for the source provided at construction time.
            split_documents: Re-chunk node Documents. Off by default — tree
                nodes are already bounded retrieval units.
            **kwargs: Accepted for signature compatibility; ignored.

        Returns:
            One :class:`Document` per node in the resulting tree.
        """
        files = self._resolve_files(source)
        await self._ensure_tree(reset=self.reset_tree)
        for path in files:
            await self._import_one(path)
        self._tree = await self.toolkit.get_tree(self.tree_name)
        return self._tree_to_documents(self._tree)

    async def build_tree(self, source: Optional[Any] = None) -> dict:
        """Build the tree and return the native tree dict.

        Args:
            source: Optional override for the construction-time source.

        Returns:
            The raw tree dict (``{"doc_name", "structure": [...]}``). It is also
            validated into a :class:`PageIndexTree` to surface schema errors
            early; the dict (not the model) is returned for direct toolkit use.
        """
        await self.load(source)
        # Validate shape — raises if the tree drifts from the schema.
        PageIndexTree.model_validate(
            {
                "doc_name": (self._tree or {}).get("doc_name", self.tree_name),
                "doc_description": (self._tree or {}).get("doc_description"),
                "structure": (self._tree or {}).get("structure", []),
            }
        )
        return self._tree or {}

    @property
    def tree(self) -> Optional[dict]:
        """The most recently built tree dict, or ``None`` before ``load()``."""
        return self._tree

    # ------------------------------------------------------------------
    # AbstractLoader hook (single file) — kept for ABC + base-class reuse
    # ------------------------------------------------------------------

    async def _load(self, source: Union[str, Path], **kwargs: Any) -> List[Document]:
        """Import a single file into the tree and return its node Documents."""
        path = Path(source)
        await self._ensure_tree(reset=False)
        new_ids = await self._import_one(path)
        self._tree = await self.toolkit.get_tree(self.tree_name)
        structure = self._tree.get("structure", [])
        docs: List[Document] = []
        seen: set[str] = set()
        for node_id in new_ids:
            node = find_node_by_id(structure, node_id)
            if node is None:
                continue
            for sub in self._iter_subtree(node):
                sid = sub.get("node_id")
                if sid and sid not in seen:
                    seen.add(sid)
                    docs.append(self._node_to_document(sub, path))
        return docs

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _ensure_tree(self, reset: bool) -> None:
        """Ensure the target tree exists, optionally resetting it first."""
        existing = await self.toolkit.list_trees()
        if self.tree_name in existing:
            if reset:
                await self.toolkit.delete_tree(self.tree_name)
                await self.toolkit.create_tree(self.tree_name)
        else:
            await self.toolkit.create_tree(self.tree_name)

    async def _import_one(self, path: Path) -> List[str]:
        """Import a single file into the tree; return the new node ids."""
        if path.suffix.lower() == '.pdf':
            result = await self.toolkit.import_pdf(
                self.tree_name,
                str(path),
                with_summaries=self.with_summaries,
                with_doc_description=self.with_doc_description,
            )
        else:
            result = await self.toolkit.import_file(self.tree_name, str(path))
        return list(result.get("new_node_ids", []) or [])

    def _resolve_files(self, source: Optional[Any]) -> List[Path]:
        """Expand ``source`` / ``self.path`` into a de-duplicated file list."""
        src = source if source is not None else self.path
        if src is None:
            raise ValueError(
                "No source provided and self.path is not set. Pass a source to "
                "load() or set it during initialization."
            )
        items = list(src) if isinstance(src, list) else [src]
        files: List[Path] = []
        for item in items:
            p = Path(item)
            if p.is_dir():
                for ext in self.extensions:
                    globber = p.rglob if self._recursive else p.glob
                    files.extend(sorted(globber(f"*{ext}")))
            elif p.is_file():
                files.append(p)
            else:
                self.logger.warning("Path %s is not a valid file or directory.", p)
        seen: set[Path] = set()
        ordered: List[Path] = []
        for f in files:
            if f not in seen:
                seen.add(f)
                ordered.append(f)
        return ordered

    def _iter_subtree(self, node: dict):
        """Yield ``node`` and every descendant (depth-first)."""
        yield node
        for child in node.get("nodes") or []:
            yield from self._iter_subtree(child)

    def _tree_to_documents(self, tree: dict) -> List[Document]:
        """Flatten a tree into one Document per node (depth-first)."""
        docs: List[Document] = []

        def _walk(nodes: list, parent_id: Optional[str]) -> None:
            for node in nodes:
                docs.append(self._node_to_document(node, parent_id=parent_id))
                _walk(node.get("nodes") or [], node.get("node_id"))

        _walk(tree.get("structure", []), None)
        return docs

    def _node_to_document(
        self,
        node: dict,
        source_path: Optional[Path] = None,
        parent_id: Optional[str] = None,
    ) -> Document:
        """Convert a single tree node into a canonical :class:`Document`."""
        node_id = node.get("node_id")
        body: Optional[str] = None
        if node_id:
            body = self._content_store.load(self.tree_name, node_id)
        content = (
            body
            or node.get("text")
            or node.get("summary")
            or node.get("prefix_summary")
            or node.get("title")
            or ""
        )
        origin = (
            str(source_path)
            if source_path is not None
            else f"pageindex://{self.tree_name}/{node_id or ''}"
        )
        metadata = self.create_metadata(
            path=origin,
            doctype='pageindex_node',
            source_type=self._source_type,
            title=node.get("title"),
            node_id=node_id,
            parent_id=parent_id if parent_id is not None else node.get("parent_id"),
            tree_name=self.tree_name,
            doc_name=(self._tree or {}).get("doc_name"),
            summary=node.get("summary"),
        )
        return Document(page_content=content, metadata=metadata)
