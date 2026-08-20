"""Tests for TASK-2284: golden set + eval harness + routing regression gate.

Spec: sdd/specs/graphindex-retriever.spec.md §7.
"""

from pathlib import Path

import pytest
from parrot.knowledge.graphindex.schema import NodeKind, UniversalNode
from parrot.knowledge.retrieval.classifier import QueryClass, QueryClassifier
from parrot.knowledge.retrieval.eval import (
    check_regression,
    load_golden_set,
    recall_at_k,
    run_head_to_head,
    run_routing_eval,
    wasted_work_ratio,
)
from parrot.knowledge.retrieval.symbols import DerivedSymbolIndex


def test_golden_set_has_150_plus_and_covers_all_rules() -> None:
    golden = load_golden_set()
    assert len(golden.queries) >= 150
    rules = {q.expected_rule for q in golden.queries}
    assert rules == {"R1", "R2", "R3", "R4", "R5", "R6", "R7"}


def test_golden_set_covers_both_languages() -> None:
    golden = load_golden_set()
    languages = {q.language for q in golden.queries}
    assert languages == {"es", "en"}


def test_golden_set_has_version() -> None:
    golden = load_golden_set()
    assert golden.version
    assert isinstance(golden.version, str)


def test_golden_set_every_class_has_both_languages() -> None:
    golden = load_golden_set()
    by_rule_lang: dict[str, set[str]] = {}
    for q in golden.queries:
        by_rule_lang.setdefault(q.expected_rule, set()).add(q.language)
    for rule, langs in by_rule_lang.items():
        assert langs == {"es", "en"}, f"{rule} missing a language: {langs}"


def test_no_llm_import_in_eval_package() -> None:
    import parrot.knowledge.retrieval.eval as eval_pkg

    pkg_dir = Path(eval_pkg.__file__).parent
    banned_substrings = ("clients.base", "AbstractClient", "import openai", "import anthropic")
    for py_file in pkg_dir.glob("*.py"):
        source = py_file.read_text()
        for banned in banned_substrings:
            assert banned not in source, f"{py_file.name} references {banned!r}"


def test_wasted_work_ratio_computation() -> None:
    assert wasted_work_ratio(200.0, 100.0) == pytest.approx(2.0)
    assert wasted_work_ratio(100.0, 100.0) == pytest.approx(1.0)
    assert wasted_work_ratio(50.0, 0.0) == 1.0  # degenerate: no cost baseline


def test_recall_at_k_against_reference() -> None:
    retrieved = ["a", "b", "c", "d"]
    reference = {"b", "d", "z"}
    assert recall_at_k(retrieved, reference, k=4) == pytest.approx(2 / 3)
    assert recall_at_k(retrieved, reference, k=1) == pytest.approx(0.0)
    assert recall_at_k([], set(), k=5) == 1.0


def test_regression_gate_fails_on_cross_class_degradation() -> None:
    baseline = {QueryClass.DIRECT_SYMBOL: 0.95, QueryClass.LOCAL_FACT: 0.80}
    candidate_ok = {QueryClass.DIRECT_SYMBOL: 0.96, QueryClass.LOCAL_FACT: 0.78}
    candidate_regressed = {QueryClass.DIRECT_SYMBOL: 0.96, QueryClass.LOCAL_FACT: 0.60}

    assert check_regression(baseline, candidate_ok, tolerance=0.05) == []
    regressed = check_regression(baseline, candidate_regressed, tolerance=0.05)
    assert regressed == [QueryClass.LOCAL_FACT]


def test_regression_gate_improvement_does_not_offset_other_regression() -> None:
    baseline = {QueryClass.DIRECT_SYMBOL: 0.70, QueryClass.RELATIONAL: 0.70}
    # DIRECT_SYMBOL improved a lot; RELATIONAL regressed beyond tolerance.
    candidate = {QueryClass.DIRECT_SYMBOL: 0.99, QueryClass.RELATIONAL: 0.50}
    regressed = check_regression(baseline, candidate, tolerance=0.05)
    assert regressed == [QueryClass.RELATIONAL]


def _symbols_for_golden_set() -> DerivedSymbolIndex:
    """Build a DerivedSymbolIndex resolving every symbol name the golden
    set's `` `Name` `` queries reference, so `run_routing_eval` exercises
    real anchor resolution rather than always hitting R7."""
    names = {
        "NodeRef", "EdgeRef", "Evidence", "ContextBundle", "RetrievalBudget",
        "DerivedSymbolIndex", "QueryClassifier", "MarkerLexicon", "extract_features",
        "DirectSymbolPolicy", "VectorSeedPolicy", "SufficiencyCheck",
        "run_escalation_ladder", "WikiPage", "SingleFlight", "WorkspacePin",
        "check_pin_coherence", "SQLiteGraphReader", "GraphIndexEmbedder",
        "GraphExpandedRetriever", "HybridPageIndexSearch", "SectionSelector",
    }
    nodes = []
    for i, name in enumerate(sorted(names)):
        mod_id = f"mod_{i}"
        nodes.append(
            UniversalNode(
                node_id=mod_id,
                kind=NodeKind.SYMBOL,
                title=f"mod_{i}",
                source_uri=f"mod_{i}.py",
                domain_tags={"symbol_type": "module"},
            )
        )
        nodes.append(
            UniversalNode(
                node_id=f"{mod_id}::{name}",
                kind=NodeKind.SYMBOL,
                title=name,
                source_uri=f"mod_{i}.py",
                parent_id=mod_id,
                domain_tags={"symbol_type": "function"},
            )
        )
    return DerivedSymbolIndex.build(nodes, repo="ai-parrot", rev="a1b2c3d")


def test_run_routing_eval_matches_golden_set_exactly() -> None:
    golden = load_golden_set()
    classifier = QueryClassifier(_symbols_for_golden_set())
    report = run_routing_eval(classifier, golden)

    assert report.golden_set_version == golden.version
    for query_class, metrics in report.per_class.items():
        if metrics.support > 0:
            assert metrics.recall == pytest.approx(1.0), (
                f"{query_class} recall should be 1.0 against the golden set "
                f"it was authored against (verified during construction)"
            )
    assert report.rule_hit_counts.keys() == {"R1", "R2", "R3", "R4", "R5", "R6", "R7"}
    assert report.latency.count == len(golden.queries)


@pytest.mark.asyncio
async def test_head_to_head_runs_both_retrievers() -> None:
    golden = load_golden_set()

    async def feat_435_stub(query: str) -> list[str]:
        return list(golden.queries[0].reference_nodes)

    async def feat_217_stub(query: str) -> list[str]:
        return []

    report = await run_head_to_head(
        golden, feat_435_retrieve=feat_435_stub, feat_217_retrieve=feat_217_stub, k=5
    )
    assert report.golden_set_version == golden.version
    assert report.k == 5
    assert report.verdict in {"feat_435_wins", "feat_217_wins", "inconclusive"}


@pytest.mark.asyncio
async def test_head_to_head_narrow_margin_is_inconclusive() -> None:
    golden = load_golden_set()

    async def near_identical(query: str) -> list[str]:
        return ["x"]

    report = await run_head_to_head(
        golden, feat_435_retrieve=near_identical, feat_217_retrieve=near_identical, k=5
    )
    assert report.verdict == "inconclusive"
