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
from typing import Literal

from pydantic import BaseModel, Field

from parrot.knowledge.pageindex.content_store import NodeContentStore
from parrot.knowledge.pageindex.okf.graph import KnowledgeGraph

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

    kind: Literal["orphan", "broken_link", "missing_concept", "stale"]
    concept_id: str
    detail: str
    severity: Literal["warning", "error"] = "warning"


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
    from parrot.knowledge.lint.packs.okf import okf_findings

    tree_name = (
        tree.get("tree_name")
        or tree.get("doc_name")
        or tree.get("name")
        or "_unknown"  # safe fallback — no sidecar will exist, so all concepts flag missing
    )

    report = LintReport(tree_name=tree_name)
    report.total_concepts = len(graph.concepts())

    buckets = {
        "orphan": report.orphans,
        "broken_link": report.broken_links,
        "missing_concept": report.missing_concepts,
        "stale": report.stale_claims,
    }
    for f in okf_findings(graph, tree, content_store, stale_days):
        buckets[f.data["kind"]].append(
            LintFinding(
                kind=f.data["kind"],
                concept_id=f.data["concept_id"],
                detail=f.message,
                severity=f.severity,
            )
        )

    report.total_findings = sum(len(b) for b in buckets.values())
    return report
