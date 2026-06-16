"""Knowledge base lint engine for OKF.

Provides :func:`lint_knowledge_base` which runs four categories of checks on
a PageIndex tree and its in-memory knowledge graph:

1. **Orphan detection** — concepts with zero inbound edges are flagged as
   ``"warning"`` because they may be dead-end nodes that nobody references.
2. **Broken link audit** — edges whose target ``concept_id`` is unknown in the
   graph are flagged as ``"error"`` (surfaced from
   ``KnowledgeGraph.broken_links()``).
3. **Missing concept pages** — concepts that are referenced in ``relates_to``
   but have no sidecar body in ``NodeContentStore`` are flagged as
   ``"warning"``.
4. **Stale claims** — nodes whose frontmatter ``timestamp`` is older than
   ``stale_days`` (default 90) are flagged as ``"warning"``.

Design notes:
- Pure function — no side effects, no mutations to the graph or stores.
- Uses only the public API of :class:`KnowledgeGraph` except for computing
  inbound edge counts, which requires iterating ``neighbors()`` for every
  known concept.
- Broken-link and missing-concept checks are complementary: broken links
  identify edges to *unknown* concept_ids; missing pages identify edges to
  *known* concept_ids that have no stored body.
"""

import logging
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from parrot.knowledge.pageindex.content_store import NodeContentStore
from parrot.knowledge.pageindex.okf.graph import KnowledgeGraph
from parrot.knowledge.pageindex.utils import structure_to_list

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class LintFinding(BaseModel):
    """A single lint finding.

    Attributes:
        kind: Category of the finding.  One of ``"orphan"``,
            ``"broken_link"``, ``"missing_concept"``, ``"stale"``.
        concept_id: The concept_id the finding relates to.
        detail: Human-readable description.
        severity: ``"warning"`` (non-critical) or ``"error"`` (data integrity).
    """

    kind: str
    concept_id: str
    detail: str
    severity: str = "warning"


class LintReport(BaseModel):
    """Structured knowledge base lint report.

    Attributes:
        tree_name: Name of the PageIndex tree that was linted.
        orphans: Findings for concepts with zero inbound edges.
        broken_links: Findings for edges targeting unknown concept_ids.
        missing_concepts: Findings for known concepts with no sidecar body.
        stale_claims: Findings for concepts whose timestamp exceeds the
            configured threshold.
        total_findings: Sum of all findings across all categories.
        total_concepts: Number of concept_ids in the knowledge graph.
    """

    tree_name: str
    orphans: list[LintFinding] = Field(default_factory=list)
    broken_links: list[LintFinding] = Field(default_factory=list)
    missing_concepts: list[LintFinding] = Field(default_factory=list)
    stale_claims: list[LintFinding] = Field(default_factory=list)
    total_findings: int = 0
    total_concepts: int = 0


# ---------------------------------------------------------------------------
# Lint engine
# ---------------------------------------------------------------------------


def lint_knowledge_base(
    graph: KnowledgeGraph,
    tree: dict,
    content_store: NodeContentStore,
    stale_days: int = 90,
) -> LintReport:
    """Run lint checks on a knowledge base and return a structured report.

    Executes four checks (orphans, broken links, missing pages, stale claims)
    and aggregates the results into a :class:`LintReport`.

    Args:
        graph: Pre-built :class:`KnowledgeGraph` for the tree.
        tree: PageIndex tree dict (``{"structure": [...]}``) used to resolve
            node metadata (``timestamp``, ``relates_to``).
        content_store: :class:`NodeContentStore` used for missing-page checks.
        stale_days: Number of days after which a node is considered stale.
            Default is 90.

    Returns:
        :class:`LintReport` with all findings categorised.
    """
    nodes = structure_to_list(tree.get("structure", []))
    tree_name = (
        tree.get("tree_name")
        or tree.get("doc_name")
        or tree.get("name")
        or ""
    )

    report = LintReport(tree_name=tree_name)
    known_concepts = graph.concepts()
    report.total_concepts = len(known_concepts)

    # ------------------------------------------------------------------
    # Check 1: Orphan detection (zero inbound edges)
    # ------------------------------------------------------------------
    # Build an inbound-edge count by iterating over every concept's outbound
    # edges.  Any concept that nobody points to is an orphan.
    inbound_count: dict[str, int] = {cid: 0 for cid in known_concepts}
    for src_cid in known_concepts:
        for edge in graph.neighbors(src_cid):
            target = edge.get("concept", "")
            if target in inbound_count:
                inbound_count[target] += 1

    for cid in sorted(known_concepts):
        if inbound_count.get(cid, 0) == 0:
            report.orphans.append(
                LintFinding(
                    kind="orphan",
                    concept_id=cid,
                    detail=f"Concept '{cid}' has zero inbound edges.",
                    severity="warning",
                )
            )

    # ------------------------------------------------------------------
    # Check 2: Broken link audit (from KnowledgeGraph._broken)
    # ------------------------------------------------------------------
    for broken in graph.broken_links():
        src = broken.get("source", "")
        target = broken.get("concept", "")
        rel = broken.get("rel", "")
        report.broken_links.append(
            LintFinding(
                kind="broken_link",
                concept_id=src,
                detail=(
                    f"Edge from '{src}' → '{target}' (rel: {rel}) targets an "
                    f"unknown concept_id."
                ),
                severity="error",
            )
        )

    # ------------------------------------------------------------------
    # Check 3: Missing concept pages
    # For each known concept_id, verify that a sidecar body exists in the
    # content_store.  Concepts without bodies are present in the graph but
    # have no associated content page.
    # ------------------------------------------------------------------
    for cid in sorted(known_concepts):
        from parrot.knowledge.pageindex.okf.projection import (
            flatten_concept_id_for_filename,
        )

        flat_key = flatten_concept_id_for_filename(cid)
        if not content_store.has(tree_name, flat_key):
            report.missing_concepts.append(
                LintFinding(
                    kind="missing_concept",
                    concept_id=cid,
                    detail=(
                        f"Concept '{cid}' exists in the knowledge graph but "
                        f"has no sidecar page in the content store."
                    ),
                    severity="warning",
                )
            )

    # ------------------------------------------------------------------
    # Check 4: Stale claims (timestamp older than stale_days)
    # ------------------------------------------------------------------
    cutoff = datetime.now(tz=timezone.utc)
    for node in nodes:
        cid = node.get("concept_id", "")
        ts_raw = node.get("timestamp", "")
        if not ts_raw or not cid:
            continue
        try:
            ts_str = str(ts_raw).replace("Z", "+00:00")
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_days = (cutoff - ts).days
            if age_days > stale_days:
                report.stale_claims.append(
                    LintFinding(
                        kind="stale",
                        concept_id=cid,
                        detail=(
                            f"Concept '{cid}' timestamp '{ts_raw}' is "
                            f"{age_days} days old (threshold: {stale_days})."
                        ),
                        severity="warning",
                    )
                )
        except (ValueError, TypeError) as exc:
            logger.debug("Cannot parse timestamp for %r: %s", cid, exc)

    # Tally
    report.total_findings = (
        len(report.orphans)
        + len(report.broken_links)
        + len(report.missing_concepts)
        + len(report.stale_claims)
    )
    return report
