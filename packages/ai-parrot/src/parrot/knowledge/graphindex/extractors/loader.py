"""Loader-based extractor for GraphIndex.

Bridges ai-parrot's loader ecosystem and PageIndex hierarchical indexing
system to produce ``UniversalNode`` / ``UniversalEdge`` instances from
documents (PDF, Markdown, DOCX, audio/video transcripts, web pages, etc.).

Hierarchical content routes through :class:`PageIndexToolkit` (when one
is supplied) so the document body is persisted as per-node markdown
sidecars in a :class:`NodeContentStore` and ``UniversalNode.content_ref``
points at it via the ``pageindex://<tree_name>/<node_id>`` scheme. The
toolkit's tree name is also exposed as ``domain_tags['pageindex_tree_id']``
on the document root so the ontology's
``search_documents_scoped`` routing has something concrete to dispatch on.

When no toolkit is supplied, the extractor degrades gracefully: it
builds a transient in-memory tree via ``md_to_tree`` and emits
``content_ref=None``. This path stays so callers without a PageIndex
storage directory (legacy code, ad-hoc graph builds) keep working.

Flat content (transcripts, plain text) always produces a single
``Document`` node — there's no hierarchy to persist.
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING, Optional

from parrot.knowledge.graphindex.schema import (
    EdgeKind,
    NodeKind,
    Provenance,
    UniversalEdge,
    UniversalNode,
)

if TYPE_CHECKING:
    from parrot.knowledge.pageindex.toolkit import PageIndexToolkit

logger = logging.getLogger(__name__)

# Loader class names known to produce hierarchical content
HIERARCHICAL_LOADERS: set[str] = {
    "PDFLoader",
    "MarkdownLoader",
    "DOCXLoader",
    "EpubLoader",
    "DocxLoader",
    "PdfLoader",
}


def _make_node_id(source_uri: str, suffix: str) -> str:
    """Stable node ID from source URI and a disambiguation suffix.

    Args:
        source_uri: The source document URI.
        suffix: A discriminator (section heading, index, etc.).

    Returns:
        16-char hex SHA-1 prefix.
    """
    raw = f"{source_uri}::{suffix}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _content_ref(tree_name: str, node_id: str) -> str:
    """Build the canonical ``pageindex://<tree>/<node>`` URI scheme.

    Consumers split on ``://`` to recover the toolkit tree name and
    node id, then fetch the body via
    :meth:`NodeContentStore.load(tree_name, node_id)`.
    """
    return f"pageindex://{tree_name}/{node_id}"


class LoaderExtractor:
    """Extract document structure from ai-parrot-loaders output.

    Routes hierarchical content (PDF, Markdown, DOCX, ebook) through
    :class:`PageIndexToolkit` (when supplied) so per-node markdown is
    persisted and addressable via
    ``UniversalNode.content_ref``. Flat content (transcripts, plain text)
    becomes a single ``Document`` node.

    Args:
        llm_adapter: Optional ``PageIndexLLMAdapter`` for section summaries.
            If ``None``, falls back to the first ``summary_length`` characters.
        toolkit: Optional :class:`PageIndexToolkit`. When provided,
            hierarchical content is persisted as a PageIndex tree (lean
            ToC JSON + per-node markdown sidecars) and section
            UniversalNodes carry a ``content_ref`` that points at it.
            When omitted, the extractor falls back to a transient
            in-memory ``md_to_tree`` walk and emits ``content_ref=None``.
        summary_length: Number of characters for the fallback summary.
    """

    def __init__(
        self,
        llm_adapter: Optional[object] = None,
        toolkit: Optional["PageIndexToolkit"] = None,
        summary_length: int = 200,
    ) -> None:
        self.llm_adapter = llm_adapter
        self.toolkit = toolkit
        self.summary_length = summary_length

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def extract(
        self, loader: object, source: str
    ) -> tuple[list[UniversalNode], list[UniversalEdge]]:
        """Run loader, detect content type, and extract nodes/edges.

        Args:
            loader: Any ai-parrot-loaders loader instance.  Must implement
                ``_load(source) -> List[Document]`` (each with
                ``page_content`` and ``metadata`` attributes).
            source: Source URI (file path, URL, etc.).

        Returns:
            Tuple of ``(nodes, edges)``.  Returns ``([], [])`` on loader
            failure — the pipeline continues.
        """
        try:
            documents = await loader._load(source)
        except Exception as exc:
            logger.error("Loader %s failed for %s: %s", type(loader).__name__, source, exc)
            return [], []

        if not documents:
            logger.debug("Loader returned no documents for %s", source)
            return [], []

        if self._is_hierarchical(loader):
            return await self._extract_hierarchical(documents, source)
        else:
            return self._extract_flat(documents, source)

    def _is_hierarchical(self, loader: object) -> bool:
        """Detect if loader produces hierarchical content.

        Args:
            loader: The loader instance.

        Returns:
            ``True`` if this loader type is known to produce structured
            hierarchical content (headings, sections).
        """
        return type(loader).__name__ in HIERARCHICAL_LOADERS

    async def _extract_hierarchical(
        self,
        documents: list,
        source_uri: str,
    ) -> tuple[list[UniversalNode], list[UniversalEdge]]:
        """Route hierarchical content through PageIndex for section nodes.

        When a :class:`PageIndexToolkit` was supplied at construction,
        the body is persisted as a PageIndex tree on disk and each
        ``Section`` UniversalNode carries a ``content_ref`` resolvable
        via :class:`NodeContentStore`. When no toolkit was supplied,
        falls back to a transient in-memory ``md_to_tree`` walk.

        Either path falls back to a single ``Document`` node if the
        builder finds no headings or raises.

        Args:
            documents: List of Document objects from the loader.
            source_uri: URI of the source document.

        Returns:
            Tuple of ``(nodes, edges)``.
        """
        full_text = "\n\n".join(
            getattr(doc, "page_content", "") for doc in documents
        )

        if self.toolkit is not None:
            try:
                return await self._extract_via_toolkit(
                    full_text=full_text, source_uri=source_uri,
                )
            except Exception as exc:
                logger.warning(
                    "PageIndexToolkit ingest failed for %s: %s — "
                    "falling back to flat extraction",
                    source_uri,
                    exc,
                )
                return self._extract_flat(documents, source_uri)

        # Legacy path: in-memory md_to_tree, no sidecar persistence.
        return await self._extract_via_md_to_tree(
            full_text=full_text, source_uri=source_uri, documents=documents,
        )

    async def _extract_via_toolkit(
        self,
        full_text: str,
        source_uri: str,
    ) -> tuple[list[UniversalNode], list[UniversalEdge]]:
        """Persist the document via PageIndexToolkit and emit nodes.

        Uses the toolkit's ``insert_markdown`` ingestion path, which
        moves per-node markdown into :class:`NodeContentStore` and
        strips ``text`` from the persisted tree. After ingestion the
        tree is reloaded and walked to emit one ``Section`` UniversalNode
        per persisted node, each with a populated ``content_ref``.

        Idempotency: re-ingesting an already-known source replaces the
        existing tree (delete + recreate) so a graph rebuild always
        reflects the latest document contents.
        """
        assert self.toolkit is not None  # narrowed by caller

        tree_name = _make_node_id(source_uri, "__root__")
        # Replace any prior tree for this source so a rebuild is clean.
        existing = await self.toolkit.list_trees()
        if tree_name in existing:
            await self.toolkit.delete_tree(tree_name)
        await self.toolkit.create_tree(tree_name, doc_name=source_uri)
        await self.toolkit.insert_markdown(
            tree_name=tree_name,
            markdown=full_text,
            doc_name=source_uri,
        )

        tree = await self.toolkit.get_tree(tree_name)
        structure = tree.get("structure") or []
        if not structure:
            # Toolkit kept the tree empty (md_to_tree found no headers).
            # Clean it up so the storage dir doesn't accrue empty trees,
            # then fall back to a single Document node.
            await self.toolkit.delete_tree(tree_name)
            doc_node = self._build_flat_node(full_text, source_uri)
            return [doc_node], []

        root_id = _make_node_id(source_uri, "__root__")
        root_node = UniversalNode(
            node_id=root_id,
            kind=NodeKind.DOCUMENT,
            title=tree.get("doc_name") or source_uri,
            source_uri=source_uri,
            summary=self._fallback_summary(full_text),
            domain_tags={
                "hierarchical": True,
                "pageindex_tree_id": tree_name,
            },
        )
        nodes: list[UniversalNode] = [root_node]
        edges: list[UniversalEdge] = []
        self._walk_persisted_tree(
            pi_nodes=structure,
            source_uri=source_uri,
            tree_name=tree_name,
            parent_id=root_id,
            nodes=nodes,
            edges=edges,
        )
        return nodes, edges

    def _walk_persisted_tree(
        self,
        pi_nodes: list,
        source_uri: str,
        tree_name: str,
        parent_id: str,
        nodes: list[UniversalNode],
        edges: list[UniversalEdge],
    ) -> None:
        """Walk a toolkit-persisted PageIndex tree and emit nodes/edges.

        Each section UniversalNode carries:

        * ``content_ref = "pageindex://<tree>/<node_id>"`` so the body
          is retrievable on demand.
        * ``domain_tags['pageindex_tree_id']`` to keep the routing
          consistent with the document root.
        * ``domain_tags['page_index_id']`` mirroring the toolkit's
          assigned node id (legacy field, retained for compatibility).
        """
        for pi_node in pi_nodes:
            if not isinstance(pi_node, dict):
                continue
            title = pi_node.get("title", "")
            node_id_raw = pi_node.get("node_id") or title
            section_id = _make_node_id(source_uri, str(node_id_raw))

            summary = (
                pi_node.get("summary")
                or pi_node.get("prefix_summary")
                or ""
            )

            domain_tags: dict = {
                "page_index_id": str(node_id_raw),
                "pageindex_tree_id": tree_name,
            }
            for key in ("start_index", "end_index"):
                if pi_node.get(key) is not None:
                    domain_tags[key] = pi_node[key]
            for key in ("categories", "metadata"):
                if pi_node.get(key):
                    domain_tags[key] = pi_node[key]

            section_node = UniversalNode(
                node_id=section_id,
                kind=NodeKind.SECTION,
                title=str(title),
                source_uri=source_uri,
                summary=summary or None,
                content_ref=_content_ref(tree_name, str(node_id_raw)),
                parent_id=parent_id,
                domain_tags=domain_tags,
            )
            nodes.append(section_node)
            edges.append(
                UniversalEdge(
                    source_id=parent_id,
                    target_id=section_id,
                    kind=EdgeKind.CONTAINS,
                )
            )

            children = pi_node.get("nodes") or []
            if children:
                self._walk_persisted_tree(
                    pi_nodes=children,
                    source_uri=source_uri,
                    tree_name=tree_name,
                    parent_id=section_id,
                    nodes=nodes,
                    edges=edges,
                )

    async def _extract_via_md_to_tree(
        self,
        full_text: str,
        source_uri: str,
        documents: list,
    ) -> tuple[list[UniversalNode], list[UniversalEdge]]:
        """Legacy in-memory path used when no toolkit is configured."""
        nodes: list[UniversalNode] = []
        edges: list[UniversalEdge] = []

        try:
            from parrot.knowledge.pageindex import md_to_tree

            tree = await md_to_tree(full_text, self.llm_adapter)
            page_index_nodes = tree.get("structure") or tree.get("nodes") or []
        except Exception as exc:
            logger.warning(
                "PageIndex tree building failed for %s: %s — falling back to flat extraction",
                source_uri,
                exc,
            )
            return self._extract_flat(documents, source_uri)

        if not page_index_nodes:
            return self._extract_flat(documents, source_uri)

        root_id = _make_node_id(source_uri, "__root__")
        root_node = UniversalNode(
            node_id=root_id,
            kind=NodeKind.DOCUMENT,
            title=tree.get("doc_name") or source_uri,
            source_uri=source_uri,
            summary=self._fallback_summary(full_text),
            domain_tags={"hierarchical": True},
        )
        nodes.append(root_node)

        self._convert_page_index_nodes(
            page_index_nodes, source_uri, root_id, nodes, edges
        )

        return nodes, edges

    def _convert_page_index_nodes(
        self,
        pi_nodes: list,
        source_uri: str,
        parent_id: str,
        nodes: list[UniversalNode],
        edges: list[UniversalEdge],
    ) -> None:
        """Recursively convert PageIndexNode tree to UniversalNodes.

        Args:
            pi_nodes: List of PageIndexNode-like objects.
            source_uri: Source URI for all created nodes.
            parent_id: Parent's ``node_id`` for ``contains`` edges.
            nodes: Accumulated node list (mutated in place).
            edges: Accumulated edge list (mutated in place).
        """
        for pi_node in pi_nodes:
            title = getattr(pi_node, "title", None) or pi_node.get("title", "")
            node_id_raw = getattr(pi_node, "node_id", None) or pi_node.get("node_id") or title
            section_id = _make_node_id(source_uri, str(node_id_raw))

            summary = (
                getattr(pi_node, "summary", None) or pi_node.get("summary")
                or self._fallback_summary(
                    getattr(pi_node, "text", None) or pi_node.get("text", "")
                )
            )

            start = getattr(pi_node, "start_index", None) or pi_node.get("start_index")
            end = getattr(pi_node, "end_index", None) or pi_node.get("end_index")

            section_node = UniversalNode(
                node_id=section_id,
                kind=NodeKind.SECTION,
                title=str(title),
                source_uri=source_uri,
                summary=summary,
                parent_id=parent_id,
                domain_tags={
                    "page_index_id": str(node_id_raw),
                    **({"start_index": start} if start is not None else {}),
                    **({"end_index": end} if end is not None else {}),
                },
            )
            nodes.append(section_node)
            edges.append(
                UniversalEdge(
                    source_id=parent_id,
                    target_id=section_id,
                    kind=EdgeKind.CONTAINS,
                )
            )

            # Recurse into child sections
            children = (
                getattr(pi_node, "nodes", None) or pi_node.get("nodes") or []
            )
            if children:
                self._convert_page_index_nodes(children, source_uri, section_id, nodes, edges)

    def _build_flat_node(self, full_text: str, source_uri: str) -> UniversalNode:
        """Single ``Document`` node for content with no hierarchy."""
        node_id = _make_node_id(source_uri, "__flat_doc__")
        return UniversalNode(
            node_id=node_id,
            kind=NodeKind.DOCUMENT,
            title=source_uri,
            source_uri=source_uri,
            summary=self._fallback_summary(full_text),
            domain_tags={"flat": True},
        )

    def _extract_flat(
        self,
        documents: list,
        source_uri: str,
    ) -> tuple[list[UniversalNode], list[UniversalEdge]]:
        """Emit a single Document node from flat content.

        Args:
            documents: List of Document objects.
            source_uri: Source URI.

        Returns:
            Tuple containing a single Document node and no edges.
        """
        full_text = "\n\n".join(
            getattr(doc, "page_content", "") for doc in documents
        )
        return [self._build_flat_node(full_text, source_uri)], []

    def _fallback_summary(self, text: str) -> str:
        """First-N-chars summary when LLM adapter is unavailable.

        Args:
            text: Raw content text.

        Returns:
            Truncated text up to ``summary_length`` characters.
        """
        return text[:self.summary_length].strip()
