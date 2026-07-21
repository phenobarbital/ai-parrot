"""Core schema models for GraphIndex.

Defines the universal node/edge contract that all pipeline stages share:
``UniversalNode``, ``UniversalEdge``, ``Provenance``, ``NodeKind``,
``EdgeKind``, ``SourceConfig``, ``GraphProjectionReport``, ``BuildResult``,
and ``IngestResult``.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class Provenance(str, Enum):
    """How a node or edge was created.

    Attributes:
        EXTRACTED: Directly extracted from source material.
        INFERRED: Inferred via embedding similarity (cross-domain resolution).
        AMBIGUOUS: Extraction was attempted but produced uncertain results
            (e.g., dynamic code features, malformed input).
    """

    EXTRACTED = "extracted"
    INFERRED = "inferred"
    AMBIGUOUS = "ambiguous"


class NodeKind(str, Enum):
    """Semantic category of a graph node.

    Attributes:
        DOCUMENT: Top-level document (PDF, DOCX, web page, transcript, etc.)
        SECTION: Hierarchical section within a document (PageIndex path).
        SYMBOL: Code element (module, class, function, variable).
        CONCEPT: Abstract concept extracted from content.
        RATIONALE: Design rationale from docstring or tagged comment.
        SKILL: Skill definition parsed from a SKILL.md file.
        WIKI_PAGE: LLM-generated wiki page (FEAT-260 LLM Wiki).
    """

    DOCUMENT = "document"
    SECTION = "section"
    SYMBOL = "symbol"
    CONCEPT = "concept"
    RATIONALE = "rationale"
    SKILL = "skill"
    WIKI_PAGE = "wiki_page"


class EdgeKind(str, Enum):
    """Semantic category of a directed graph edge.

    Attributes:
        CONTAINS: Parent–child containment (document→section, class→method).
        REFERENCES: One node cites or imports another.
        DEFINES: A module or document provides the authoritative definition.
        MENTIONS: Cross-domain inferred link (provenance=INFERRED).
        EXPLAINS: A rationale/docstring explains a symbol.
        EXTENDS: Odoo model inheritance — a class extends a canonical model
            node via ``_inherit`` or ``_inherits``. Added by FEAT-240.
    """

    CONTAINS = "contains"
    REFERENCES = "references"
    DEFINES = "defines"
    MENTIONS = "mentions"
    EXPLAINS = "explains"
    EXTENDS = "extends"


class UniversalNode(BaseModel):
    """A node in the GraphIndex knowledge graph.

    Args:
        node_id: Globally unique identifier within the tenant graph.
        kind: Semantic category of this node.
        title: Human-readable display name.
        source_uri: URI of the source artefact (file path, URL, etc.).
        content_ref: Optional reference to the full source body (not stored
            inline to keep the graph lightweight).
        summary: Optional short textual summary suitable for embedding.
        embedding_ref: Reference into the FAISS/pgvector index after the
            embedding stage has run (e.g. ``"faiss:42"``).
        domain_tags: Arbitrary key-value metadata from the extractor
            (e.g. ``{"symbol_type": "function"}``, ``{"flat": true}``).
        parent_id: Optional ``node_id`` of the logical parent node.
        provenance: How this node was created.
    """

    node_id: str
    kind: NodeKind
    title: str
    source_uri: str
    content_ref: Optional[str] = None
    summary: Optional[str] = None
    embedding_ref: Optional[str] = None
    domain_tags: dict = Field(default_factory=dict)
    parent_id: Optional[str] = None
    provenance: Provenance = Provenance.EXTRACTED


class UniversalEdge(BaseModel):
    """A directed edge in the GraphIndex knowledge graph.

    The ``confidence`` field MUST be set (non-None) if and only if
    ``provenance == Provenance.INFERRED``.  A ``field_validator`` enforces
    this invariant.

    Args:
        source_id: ``node_id`` of the tail node.
        target_id: ``node_id`` of the head node.
        kind: Semantic category of this edge.
        provenance: How this edge was created.
        confidence: Cosine similarity score in [0, 1].  Required for
            ``INFERRED`` edges; must be ``None`` for others.
    """

    source_id: str
    target_id: str
    kind: EdgeKind
    provenance: Provenance = Provenance.EXTRACTED
    confidence: Optional[float] = None

    @model_validator(mode="after")
    def _validate_confidence_with_provenance(self) -> "UniversalEdge":
        """Enforce that confidence is set iff provenance is INFERRED.

        Returns:
            Self after validation.

        Raises:
            ValueError: When the confidence/provenance combination is invalid.
        """
        if self.provenance == Provenance.INFERRED and self.confidence is None:
            raise ValueError(
                "confidence must be set when provenance is INFERRED"
            )
        if self.provenance != Provenance.INFERRED and self.confidence is not None:
            raise ValueError(
                "confidence must be None when provenance is not INFERRED"
            )
        return self


class SourceConfig(BaseModel):
    """Configuration describing what to index in a pipeline run.

    Args:
        code_paths: Filesystem directories/files to parse with tree-sitter.
        loader_sources: URIs (files, URLs) to process via ai-parrot-loaders.
        skill_paths: Directories/files containing SKILL.md definitions.
        ignore_file: Path to a ``.graphindexignore`` file (gitignore syntax).
        tenant_id: Tenant identifier — used for graph isolation.
    """

    code_paths: list[str] = Field(default_factory=list)
    loader_sources: list[str] = Field(default_factory=list)
    skill_paths: list[str] = Field(default_factory=list)
    ignore_file: Optional[str] = None
    tenant_id: str = "default"


class GraphProjectionReport(BaseModel):
    """Summary of a completed GraphIndex OKF projection run (FEAT-239).

    Produced by ``project_graph_sidecars()`` and stored on ``BuildResult``.

    Attributes:
        output_dir: Base directory where sidecars were written.
        nodes_projected: Count of nodes successfully projected.
        files_written: Absolute file paths of every sidecar written.
        report_frontmatter_added: ``True`` when ``GRAPH_REPORT.md`` was
            generated with OKF frontmatter during the same build run.
    """

    output_dir: str
    nodes_projected: int = 0
    files_written: list[str] = Field(default_factory=list)
    report_frontmatter_added: bool = False


class BuildResult(BaseModel):
    """Outcome of a full ``GraphIndexBuilder.build()`` run.

    Args:
        tenant_id: Tenant that was indexed.
        node_count: Total number of nodes persisted.
        edge_count: Total number of edges persisted.
        inferred_edge_count: Subset of edges with ``provenance=INFERRED``.
        report_path: Path to the generated ``GRAPH_REPORT.md`` file, if any.
        errors: List of non-fatal error messages encountered during the run.
        projection_report: Summary of the OKF projection stage (FEAT-239).
            ``None`` when the builder has no ``output_dir`` or projection
            was skipped.
        graph_html_path: Path to the interactive ``graph.html`` map, if the
            HTML export stage ran. ``None`` when export was disabled or no
            ``output_dir`` was configured.
        graph_json_path: Path to the serialized ``graph.json`` written
            alongside ``graph.html``. ``None`` when export was skipped.
    """

    model_config = {"arbitrary_types_allowed": True}

    tenant_id: str
    node_count: int = 0
    edge_count: int = 0
    inferred_edge_count: int = 0
    report_path: Optional[Path] = None
    errors: list[str] = Field(default_factory=list)
    projection_report: Optional[GraphProjectionReport] = Field(
        default=None,
        description="OKF projection summary; None when projection was skipped.",
    )
    graph_html_path: Optional[Path] = None
    graph_json_path: Optional[Path] = None


class IngestResult(BaseModel):
    """Outcome of an incremental ``GraphIndexBuilder.ingest_document()`` run.

    Args:
        tenant_id: Tenant that was updated.
        document_uri: URI of the document that was reprocessed.
        nodes_replaced: Number of nodes soft-deleted and replaced.
        edges_replaced: Number of edges replaced.
        errors: List of non-fatal error messages.
    """

    tenant_id: str
    document_uri: str
    nodes_replaced: int = 0
    edges_replaced: int = 0
    errors: list[str] = Field(default_factory=list)
