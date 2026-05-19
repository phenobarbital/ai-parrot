"""Loader-based extractor for GraphIndex.

Bridges ai-parrot's loader ecosystem and PageIndex hierarchical indexing
system to produce ``UniversalNode`` / ``UniversalEdge`` instances from
documents (PDF, Markdown, DOCX, audio/video transcripts, web pages, etc.).

Hierarchical content routes through ``build_page_index`` / ``md_to_tree``
to produce ``Section`` nodes.  Flat content (transcripts, plain text) produces
a single ``Document`` node.
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
    pass

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


class LoaderExtractor:
    """Extract document structure from ai-parrot-loaders output.

    Routes hierarchical content (PDF, Markdown, DOCX, ebook) through PageIndex
    for section-level extraction, and flat content (transcripts, plain text)
    to a single ``Document`` node.

    Args:
        llm_adapter: Optional ``PageIndexLLMAdapter`` for section summaries.
            If ``None``, falls back to the first ``summary_length`` characters.
        summary_length: Number of characters for the fallback summary.
    """

    def __init__(
        self,
        llm_adapter: Optional[object] = None,
        summary_length: int = 200,
    ) -> None:
        self.llm_adapter = llm_adapter
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
        """Route through build_page_index / md_to_tree for section nodes.

        Concatenates all document page_content and attempts to build a
        PageIndex tree.  Falls back to a single Document node if no
        hierarchical structure is found.

        Args:
            documents: List of Document objects from the loader.
            source_uri: URI of the source document.

        Returns:
            Tuple of ``(nodes, edges)``.
        """
        nodes: list[UniversalNode] = []
        edges: list[UniversalEdge] = []

        # Concatenate all pages
        full_text = "\n\n".join(
            getattr(doc, "page_content", "") for doc in documents
        )

        try:
            from parrot.pageindex import md_to_tree

            tree = await md_to_tree(full_text, self.llm_adapter)
            page_index_nodes = tree.get("nodes") or []
        except Exception as exc:
            logger.warning(
                "PageIndex tree building failed for %s: %s — falling back to flat extraction",
                source_uri,
                exc,
            )
            return self._extract_flat(documents, source_uri)

        if not page_index_nodes:
            return self._extract_flat(documents, source_uri)

        # Convert PageIndex nodes to UniversalNodes
        root_id = _make_node_id(source_uri, "__root__")
        root_node = UniversalNode(
            node_id=root_id,
            kind=NodeKind.DOCUMENT,
            title=tree.get("title", source_uri),
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
        node_id = _make_node_id(source_uri, "__flat_doc__")
        doc_node = UniversalNode(
            node_id=node_id,
            kind=NodeKind.DOCUMENT,
            title=source_uri,
            source_uri=source_uri,
            summary=self._fallback_summary(full_text),
            domain_tags={"flat": True},
        )
        return [doc_node], []

    def _fallback_summary(self, text: str) -> str:
        """First-N-chars summary when LLM adapter is unavailable.

        Args:
            text: Raw content text.

        Returns:
            Truncated text up to ``summary_length`` characters.
        """
        return text[:self.summary_length].strip()
