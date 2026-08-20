"""Tests for TASK-2277: `QueryFeatures` extractor.

Spec: sdd/specs/graphindex-retriever.spec.md §4.2.
"""

import socket
from pathlib import Path

import pytest
from parrot.knowledge.graphindex.schema import NodeKind, UniversalNode
from parrot.knowledge.retrieval.features import extract_features
from parrot.knowledge.retrieval.lexicon import Interrogative
from parrot.knowledge.retrieval.symbols import DerivedSymbolIndex


def _empty_index() -> DerivedSymbolIndex:
    return DerivedSymbolIndex.build([], repo="ai-parrot", rev="a1b2c3d")


def _index_with_resolve() -> DerivedSymbolIndex:
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
    method = UniversalNode(
        node_id="mod::PayRateEngine::resolve",
        kind=NodeKind.SYMBOL,
        title="resolve",
        source_uri="domain/payrate.py",
        parent_id="mod::PayRateEngine",
        domain_tags={"symbol_type": "function"},
    )
    return DerivedSymbolIndex.build([module, cls, method], repo="fieldsync", rev="9f8e7d6")


def test_por_que_is_causal_but_que_alone_is_not() -> None:
    features_causal = extract_features(
        "¿por qué el rate se congela en clock-out?", _empty_index()
    )
    assert features_causal.has_causal_marker is True

    features_bare = extract_features("¿qué devuelve resolve()?", _empty_index())
    assert features_bare.has_causal_marker is False


def test_accent_insensitive_causal_match() -> None:
    a = extract_features("por qué falla esto", _empty_index())
    b = extract_features("por que falla esto", _empty_index())
    assert a.has_causal_marker is True
    assert b.has_causal_marker is True


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("`foo`", True),
        ("look at snake_case_name here", True),
        ("look at CamelCaseName here", True),
        ("look at a.b.c here", True),
        ("how are you", False),
        ("what is the weather today", False),
    ],
)
def test_has_code_literal(query: str, expected: bool) -> None:
    features = extract_features(query, _empty_index())
    assert features.has_code_literal is expected


def test_has_relational_verb() -> None:
    assert extract_features("¿quién llama a NoApplicableRule?", _empty_index()).has_relational_verb
    assert extract_features("what calls resolve()", _empty_index()).has_relational_verb
    assert not extract_features("hello there", _empty_index()).has_relational_verb


def test_has_aggregation_marker() -> None:
    assert extract_features(
        "¿cómo funciona el módulo de outputs?", _empty_index()
    ).has_aggregation_marker
    assert extract_features("give me an overview", _empty_index()).has_aggregation_marker
    assert not extract_features("what does resolve() return", _empty_index()).has_aggregation_marker


def test_interrogative_detection() -> None:
    assert extract_features("¿qué hace esto?", _empty_index()).interrogative == Interrogative.WHAT
    assert extract_features("¿por qué falla?", _empty_index()).interrogative == Interrogative.WHY
    assert extract_features("hello world", _empty_index()).interrogative == Interrogative.NONE


def test_token_count() -> None:
    assert extract_features("a b c d", _empty_index()).token_count == 4


def test_resolves_backtick_symbol_to_anchor() -> None:
    features = extract_features("show me `resolve`", _index_with_resolve())
    assert features.anchor_count == 1
    assert features.resolved_symbols[0].qualname == "payrate.PayRateEngine.resolve"


def test_no_anchors_when_nothing_resolves() -> None:
    features = extract_features("show me `nonexistent_symbol`", _index_with_resolve())
    assert features.anchor_count == 0
    assert features.resolved_symbols == ()


def test_extract_features_is_pure(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*args: object, **kwargs: object) -> None:
        raise AssertionError("extract_features must not perform I/O or call the clock")

    monkeypatch.setattr("builtins.open", _raise)
    monkeypatch.setattr(Path, "read_bytes", _raise)
    monkeypatch.setattr(socket.socket, "connect", _raise)

    import datetime

    monkeypatch.setattr(datetime, "datetime", type("FrozenDatetime", (), {"now": staticmethod(_raise)}))

    features = extract_features("¿por qué falla `resolve`?", _index_with_resolve())
    assert features.has_causal_marker is True


def test_deterministic_across_runs() -> None:
    index = _index_with_resolve()
    a = extract_features("¿quién llama a `resolve`?", index)
    b = extract_features("¿quién llama a `resolve`?", index)
    assert a == b


def test_frozen_and_forbid_extra() -> None:
    from pydantic import ValidationError

    features = extract_features("hello", _empty_index())
    with pytest.raises(ValidationError):
        features.token_count = 99  # type: ignore[misc]
