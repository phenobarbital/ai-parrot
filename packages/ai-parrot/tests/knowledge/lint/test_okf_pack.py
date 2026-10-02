"""Parity tests for the OKF rule pack (TASK-4012)."""

from datetime import datetime, timedelta, timezone

import pytest

from parrot.knowledge.lint.packs.okf import KIND_TO_RULE, okf_findings
from parrot.knowledge.pageindex.content_store import NodeContentStore
from parrot.knowledge.pageindex.okf.graph import KnowledgeGraph
from parrot.knowledge.pageindex.okf.lint import lint_knowledge_base


def _node(cid: str, rel: list[dict], ts: str) -> dict:
    return {
        "node_id": cid,
        "concept_id": cid,
        "type": "Policy",
        "title": cid,
        "summary": "",
        "timestamp": ts,
        "relates_to": rel,
        "nodes": [],
    }


@pytest.fixture
def tree() -> dict:
    old = (datetime.now(tz=timezone.utc) - timedelta(days=200)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "tree_name": "t",
        "structure": [
            _node("a", [{"concept": "b", "rel": "references"}, {"concept": "ghost", "rel": "references"}], old),
            _node("b", [], "2999-01-01T00:00:00Z"),
        ],
    }


def test_okf_parity(tree, tmp_path):
    store = NodeContentStore(tmp_path)
    graph = KnowledgeGraph(tree)
    findings = okf_findings(graph, tree, store)
    report = lint_knowledge_base(graph, tree, store)
    got = {(f.data["kind"], f.data["concept_id"]) for f in findings}
    legacy = {
        (f.kind, f.concept_id)
        for lst in (report.orphans, report.broken_links, report.missing_concepts, report.stale_claims)
        for f in lst
    }
    assert got == legacy
    assert report.total_findings == len(findings)
    assert {f.rule_id for f in findings} <= set(KIND_TO_RULE.values())
    assert [f.data["kind"] for f in findings if f.data["kind"] == "stale"] == ["stale"]


def test_fingerprints_stable(tree, tmp_path):
    store = NodeContentStore(tmp_path)
    graph = KnowledgeGraph(tree)
    first = [f.fingerprint for f in okf_findings(graph, tree, store)]
    second = [f.fingerprint for f in okf_findings(graph, tree, store)]
    assert first == second
    assert len(set(first)) == len(first)
