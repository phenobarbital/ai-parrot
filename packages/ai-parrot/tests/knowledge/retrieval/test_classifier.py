"""Tests for TASK-2278: `QueryClassifier` decision list + replay tests.

Spec: sdd/specs/graphindex-retriever.spec.md §4.3.
"""

import socket
from pathlib import Path

import pytest
from parrot.knowledge.graphindex.schema import NodeKind, UniversalNode
from parrot.knowledge.retrieval.classifier import (
    QueryClass,
    QueryClassifier,
    RetrievalRoutingDecision,
)
from parrot.knowledge.retrieval.symbols import DerivedSymbolIndex


def _index_with_symbols() -> DerivedSymbolIndex:
    module = UniversalNode(
        node_id="mod",
        kind=NodeKind.SYMBOL,
        title="payrate",
        source_uri="domain/payrate.py",
        domain_tags={"symbol_type": "module"},
    )
    cls = UniversalNode(
        node_id="mod::PayRateEngine",
        kind=NodeKind.SYMBOL,
        title="PayRateEngine",
        source_uri="domain/payrate.py",
        parent_id="mod",
        domain_tags={"symbol_type": "class"},
    )
    resolve_method = UniversalNode(
        node_id="mod::PayRateEngine::resolve",
        kind=NodeKind.SYMBOL,
        title="resolve",
        source_uri="domain/payrate.py",
        parent_id="mod::PayRateEngine",
        domain_tags={"symbol_type": "function"},
    )
    no_applicable_rule = UniversalNode(
        node_id="mod::NoApplicableRule",
        kind=NodeKind.SYMBOL,
        title="NoApplicableRule",
        source_uri="domain/payrate.py",
        parent_id="mod",
        domain_tags={"symbol_type": "class"},
    )
    eventbus_mod = UniversalNode(
        node_id="eb_mod",
        kind=NodeKind.SYMBOL,
        title="navigator-eventbus",
        source_uri="eventbus/__init__.py",
        domain_tags={"symbol_type": "module"},
    )
    return DerivedSymbolIndex.build(
        [module, cls, resolve_method, no_applicable_rule, eventbus_mod],
        repo="fieldsync",
        rev="9f8e7d6",
    )


@pytest.fixture
def classifier() -> QueryClassifier:
    return QueryClassifier(_index_with_symbols())


@pytest.mark.parametrize(
    ("rule", "query", "expected"),
    [
        ("R1", "`PayRateEngine.resolve`", QueryClass.DIRECT_SYMBOL),
        ("R2", "¿por qué el rate se congela en clock-out?", QueryClass.RATIONALE),
        (
            "R3",
            "diferencia entre `PayRateEngine` y `NoApplicableRule`",
            QueryClass.COMPARATIVE,
        ),
        ("R4", "¿quién llama a `NoApplicableRule`?", QueryClass.RELATIONAL),
        ("R5", "¿cómo funciona el módulo de outputs?", QueryClass.GLOBAL_SUMMARY),
        ("R6", "`resolve()`", QueryClass.LOCAL_FACT),
        ("R7", "hola", QueryClass.UNKNOWN),
    ],
)
def test_every_rule_reachable_and_named(
    classifier: QueryClassifier, rule: str, query: str, expected: QueryClass
) -> None:
    decision = classifier.classify(query)
    assert decision.query_class == expected
    assert decision.matched_rule == rule


def test_first_match_wins_r2_beats_r3(classifier: QueryClassifier) -> None:
    # Causal marker + two anchors: R2 must win over R3 (R2 is checked first).
    query = "¿por qué difieren `PayRateEngine` y `NoApplicableRule`?"
    decision = classifier.classify(query)
    assert decision.matched_rule == "R2"
    assert decision.query_class == QueryClass.RATIONALE


def test_classify_is_pure_inv3(
    classifier: QueryClassifier, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise(*args: object, **kwargs: object) -> None:
        raise AssertionError("classify() must not perform I/O, network, or clock calls")

    monkeypatch.setattr("builtins.open", _raise)
    monkeypatch.setattr(Path, "read_bytes", _raise)
    monkeypatch.setattr(socket.socket, "connect", _raise)

    import datetime

    monkeypatch.setattr(
        datetime, "datetime", type("FrozenDatetime", (), {"now": staticmethod(_raise)})
    )

    decision = classifier.classify("`resolve()`")
    assert decision.query_class == QueryClass.LOCAL_FACT


def test_classify_byte_identical_across_calls(classifier: QueryClassifier) -> None:
    a = classifier.classify("¿quién llama a `NoApplicableRule`?")
    b = classifier.classify("¿quién llama a `NoApplicableRule`?")
    assert a == b
    assert a.model_dump_json() == b.model_dump_json()


def test_override_sets_matched_rule_and_logs(
    classifier: QueryClassifier, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("INFO"):
        decision = classifier.classify("anything", policy_override="DirectSymbolPolicy")
    assert decision.matched_rule == "OVERRIDE"
    assert decision.policy == "DirectSymbolPolicy"
    assert any("policy_override" in record.message for record in caplog.records)


def test_shadow_mode_does_not_change_decision(classifier: QueryClassifier) -> None:
    normal = classifier.classify("`resolve()`", shadow_mode=False)
    shadow = classifier.classify("`resolve()`", shadow_mode=True)
    assert normal.query_class == shadow.query_class
    assert normal.matched_rule == shadow.matched_rule
    assert normal.policy == shadow.policy


def test_shadow_mode_logs_marker(
    classifier: QueryClassifier, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("INFO"):
        classifier.classify("`resolve()`", shadow_mode=True)
    assert any("shadow_mode" in record.message for record in caplog.records)


def test_deferred_policy_substitution_is_recorded(classifier: QueryClassifier) -> None:
    # RELATIONAL's spec-table default is PersonalizedPageRankPolicy, deferred
    # in the v1 cut — must substitute VectorSeedPolicy and record it.
    decision = classifier.classify("¿quién llama a `NoApplicableRule`?")
    assert decision.query_class == QueryClass.RELATIONAL
    assert decision.policy == "VectorSeedPolicy"
    assert decision.intended_policy == "PersonalizedPageRankPolicy"


def test_direct_symbol_policy_is_not_substituted(classifier: QueryClassifier) -> None:
    decision = classifier.classify("`PayRateEngine.resolve`")
    assert decision.query_class == QueryClass.DIRECT_SYMBOL
    assert decision.policy == "DirectSymbolPolicy"
    assert decision.intended_policy is None


def test_model_named_retrieval_routing_decision_not_routing_decision() -> None:
    import parrot.knowledge.retrieval.classifier as classifier_module

    assert hasattr(classifier_module, "RetrievalRoutingDecision")
    assert not hasattr(classifier_module, "RoutingDecision")


def test_no_import_of_intent_router() -> None:
    import parrot.knowledge.retrieval.classifier as classifier_module

    source = Path(classifier_module.__file__).read_text()
    assert "bots.mixins.intent_router" not in source
    assert "import RoutingDecision" not in source


def test_frozen_and_forbid_extra(classifier: QueryClassifier) -> None:
    from pydantic import ValidationError

    decision = classifier.classify("hola")
    with pytest.raises(ValidationError):
        decision.matched_rule = "R99"  # type: ignore[misc]


def test_decision_round_trips_through_json(classifier: QueryClassifier) -> None:
    decision = classifier.classify("¿por qué falla `resolve`?")
    dumped = decision.model_dump_json()
    restored = RetrievalRoutingDecision.model_validate_json(dumped)
    assert restored == decision
