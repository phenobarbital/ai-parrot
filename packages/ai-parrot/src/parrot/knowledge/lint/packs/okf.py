"""OKF rule pack: the four classic knowledge-base checks (FEAT-625)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from parrot.knowledge.lint.models import Finding, Severity
from parrot.knowledge.lint.rule import make_fingerprint

logger = logging.getLogger(__name__)

KIND_TO_RULE: dict[str, str] = {
    "orphan": "okf-orphan",
    "broken_link": "okf-broken-link",
    "missing_concept": "okf-missing-concept",
    "stale": "okf-stale",
}


def _finding(
    kind: str,
    cid: str,
    message: str,
    severity: Severity,
    subjects: list[str] | None = None,
) -> Finding:
    rule_id = KIND_TO_RULE[kind]
    subs = subjects if subjects is not None else [cid]
    return Finding(
        rule_id=rule_id,
        severity=severity,
        subjects=subs,
        message=message,
        fingerprint=make_fingerprint(rule_id, subs),
        data={"kind": kind, "concept_id": cid},
    )


def okf_findings(graph: Any, tree: dict, content_store: Any, stale_days: int = 90) -> list[Finding]:
    """Run the four OKF checks and return engine Findings (pure, no I/O writes).

    Each Finding carries ``data={"kind": <okf kind>, "concept_id": <id>}`` so
    :func:`lint_knowledge_base` can rebuild its legacy report exactly.

    Args:
        graph: Pre-built ``KnowledgeGraph``.
        tree: PageIndex tree dict.
        content_store: ``NodeContentStore`` used for missing-page checks.
        stale_days: Age in days after which a node is stale.

    Returns:
        Findings ordered orphan, broken_link, missing_concept, stale.
    """
    from parrot.knowledge.pageindex.okf.projection import flatten_concept_id_for_filename
    from parrot.knowledge.pageindex.utils import structure_to_list

    nodes = structure_to_list(tree.get("structure", []))
    tree_name = (
        tree.get("tree_name")
        or tree.get("doc_name")
        or tree.get("name")
        or "_unknown"  # safe fallback — no sidecar will exist, so all concepts flag missing
    )
    known_concepts = graph.concepts()
    findings: list[Finding] = []

    # Check 1: orphans (zero inbound edges)
    inbound_count: dict[str, int] = dict.fromkeys(known_concepts, 0)
    for src_cid in known_concepts:
        for edge in graph.neighbors(src_cid):
            target = edge.get("concept", "")
            if target in inbound_count:
                inbound_count[target] += 1
    for cid in sorted(known_concepts):
        if inbound_count.get(cid, 0) == 0:
            findings.append(
                _finding("orphan", cid, f"Concept '{cid}' has zero inbound edges.", "warning")
            )

    # Check 2: broken links
    for broken in graph.broken_links():
        src = broken.get("source", "")
        target = broken.get("concept", "")
        rel = broken.get("rel", "")
        findings.append(
            _finding(
                "broken_link",
                src,
                f"Edge from '{src}' → '{target}' (rel: {rel}) targets an unknown concept_id.",
                "error",
                subjects=[src, target, rel],
            )
        )

    # Check 3: missing concept pages
    for cid in sorted(known_concepts):
        flat_key = flatten_concept_id_for_filename(cid)
        if not content_store.has(tree_name, flat_key):
            findings.append(
                _finding(
                    "missing_concept",
                    cid,
                    f"Concept '{cid}' exists in the knowledge graph but has no sidecar page in the content store.",
                    "warning",
                )
            )

    # Check 4: stale claims
    cutoff = datetime.now(tz=timezone.utc)
    for node in nodes:
        cid = node.get("concept_id", "")
        ts_raw = node.get("timestamp", "")
        if not ts_raw or not cid:
            continue
        try:
            ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_days = (cutoff - ts).days
            if age_days > stale_days:
                findings.append(
                    _finding(
                        "stale",
                        cid,
                        f"Concept '{cid}' timestamp '{ts_raw}' is {age_days} days old (threshold: {stale_days}).",
                        "warning",
                    )
                )
        except (ValueError, TypeError) as exc:
            logger.debug("Cannot parse timestamp for %r: %s", cid, exc)
    return findings
