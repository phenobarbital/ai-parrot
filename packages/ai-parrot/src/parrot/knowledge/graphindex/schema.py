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
        ASSERTED: Authored directly by an agent or human (persistent
            graph memory writes). Attribution lives in ``AssertionMeta``.
    """

    EXTRACTED = "extracted"
    INFERRED = "inferred"
    AMBIGUOUS = "ambiguous"
    ASSERTED = "asserted"


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
        RUN: An agent/crew execution (work lineage — links what a run
            produced without collapsing lineage into domain knowledge).
        CLAIM: A discrete assertion produced by a run, connectable to
            the entities it is about and the sources supporting it.
    """

    DOCUMENT = "document"
    SECTION = "section"
    SYMBOL = "symbol"
    CONCEPT = "concept"
    RATIONALE = "rationale"
    SKILL = "skill"
    WIKI_PAGE = "wiki_page"
    RUN = "run"
    CLAIM = "claim"


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
        PRODUCED: A run produced a claim/node (work lineage).
        ABOUT: A claim is about an entity.
        SUPPORTED_BY: A claim is supported by a source/page.
        CONTRADICTS: Two claims/entities conflict — surfaced (never
            hidden) by the context builder and grounding evaluator.
        CALLS: A symbol invokes another symbol (FEAT-498 structural
            plane; wiki `sym:` pages only).
        IMPLEMENTS: A symbol implements an interface/trait (FEAT-498
            structural plane; wiki `sym:` pages only).
    """

    CONTAINS = "contains"
    REFERENCES = "references"
    DEFINES = "defines"
    MENTIONS = "mentions"
    EXPLAINS = "explains"
    EXTENDS = "extends"
    PRODUCED = "produced"
    ABOUT = "about"
    SUPPORTED_BY = "supported_by"
    CONTRADICTS = "contradicts"
    CALLS = "calls"
    IMPLEMENTS = "implements"


class AssertionMeta(BaseModel):
    """Attribution metadata for an agent- or human-authored graph write.

    Carried by nodes and edges whose knowledge was contributed directly
    (``Provenance.ASSERTED``) rather than extracted from source material.
    Keeping the assertion confidence here (instead of on
    ``UniversalEdge.confidence``) avoids colliding with the
    embedding-similarity semantics enforced by the edge validator.

    Args:
        asserted_by: Identity of the writer, e.g. ``"agent:<id>"``,
            ``"human:<user>"`` or ``"cli:wikitoolkit"``.
        asserted_at: ISO-8601 UTC timestamp of the write.
        agent_id: Optional stable agent identifier.
        run_id: Optional run/session identifier linking the write to the
            execution that produced it (work-lineage audit).
        source: Optional citation URI or page id supporting the assertion.
        confidence: Optional self-reported confidence in [0, 1].
    """

    asserted_by: str
    asserted_at: str
    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    source: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


def stable_edge_id(source_id: str, target_id: str, kind: str) -> str:
    """Return a stable, citable identifier for a graph edge.

    The id is a SHA-1 prefix of ``"source::target::kind"`` so the same
    logical edge always yields the same id — usable as a citation handle
    in serialized graph context and grounding results.

    Args:
        source_id: ``node_id`` of the tail node.
        target_id: ``node_id`` of the head node.
        kind: Edge kind value (e.g. ``"references"``).

    Returns:
        A 12-character hex id.
    """
    import hashlib

    raw = f"{source_id}::{target_id}::{kind}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:12]


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
        assertion: Attribution metadata when the node was authored by an
            agent or human (``Provenance.ASSERTED``). ``None`` for
            pipeline-extracted nodes.
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
    assertion: Optional[AssertionMeta] = None


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
        assertion: Attribution metadata when the edge was authored by an
            agent or human (``Provenance.ASSERTED``). Assertion-level
            confidence lives in ``AssertionMeta.confidence`` — it does
            NOT interact with the similarity ``confidence`` field.
        domain_tags: Arbitrary key-value metadata from the extractor
            (e.g. ``{"embed": true}`` for Obsidian transclusion edges —
            FEAT-392 expresses domain semantics on existing edge kinds
            through tags instead of new enum members).
    """

    source_id: str
    target_id: str
    kind: EdgeKind
    provenance: Provenance = Provenance.EXTRACTED
    confidence: Optional[float] = None
    assertion: Optional[AssertionMeta] = None
    domain_tags: dict = Field(default_factory=dict)

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


class GraphUpdate(BaseModel):
    """A validated batch of graph writes published by an agent or human.

    This is the unit of durable graph mutation (the "publish pattern"):
    nodes and edges land in one transaction, and the update is recorded
    as a commit linked to the run/agent that produced it so every write
    is auditable and revertible.

    Args:
        nodes: Nodes to upsert.
        edges: Edges to upsert.
        removed_edges: ``(source_id, target_id, kind)`` triples to delete.
        removed_nodes: ``node_id`` values to delete (e.g. the duplicate
            side of a merge). Pre-images are captured so the removal is
            revertible.
        agent_id: Stable identifier of the writing agent.
        run_id: Optional run/session identifier for work-lineage linkage.
        asserted_by: Identity string stamped onto unattributed writes.
        source: Optional citation URI supporting the whole update.
        reason: Optional human-readable rationale (e.g. merge rationale).
        op: Logical operation name (``create_node``, ``link_nodes``,
            ``merge_nodes``, ``publish``, ...).
    """

    nodes: list[UniversalNode] = Field(default_factory=list)
    edges: list[UniversalEdge] = Field(default_factory=list)
    removed_edges: list[tuple[str, str, str]] = Field(default_factory=list)
    removed_nodes: list[str] = Field(default_factory=list)
    agent_id: str
    run_id: Optional[str] = None
    asserted_by: str
    source: Optional[str] = None
    reason: Optional[str] = None
    op: str = "publish"


class CommitReceipt(BaseModel):
    """Outcome of a successfully applied :class:`GraphUpdate`.

    Args:
        commit_id: Unique identifier of the recorded commit.
        op: Logical operation name copied from the update.
        node_ids: ``node_id`` of every node upserted.
        edge_keys: ``(source_id, target_id, kind)`` of every edge
            upserted or removed.
        committed_at: ISO-8601 UTC timestamp of the transaction.
        warnings: Non-fatal issues encountered while applying the update.
    """

    commit_id: str
    op: str
    node_ids: list[str] = Field(default_factory=list)
    edge_keys: list[tuple[str, str, str]] = Field(default_factory=list)
    committed_at: str
    warnings: list[str] = Field(default_factory=list)


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
