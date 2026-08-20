"""Tests for TASK-2276: `DerivedSymbolIndex`.

Spec: sdd/specs/graphindex-retriever.spec.md §3.5.2.
"""

from pathlib import Path

import pytest
from parrot.knowledge.graphindex.schema import NodeKind, UniversalNode
from parrot.knowledge.retrieval.symbols import DerivedSymbolIndex


def _module_node() -> UniversalNode:
    return UniversalNode(
        node_id="mod",
        kind=NodeKind.SYMBOL,
        title="payrate",
        source_uri="domain/payrate.py",
        domain_tags={"symbol_type": "module"},
    )


def _class_node(parent_id: str = "mod") -> UniversalNode:
    return UniversalNode(
        node_id="mod::PayRateEngine",
        kind=NodeKind.SYMBOL,
        title="PayRateEngine",
        source_uri="domain/payrate.py",
        parent_id=parent_id,
        domain_tags={"symbol_type": "class", "lineno": 10, "end_lineno": 50},
    )


def _method_node(parent_id: str = "mod::PayRateEngine") -> UniversalNode:
    return UniversalNode(
        node_id="mod::PayRateEngine::resolve",
        kind=NodeKind.SYMBOL,
        title="resolve",
        source_uri="domain/payrate.py",
        parent_id=parent_id,
        domain_tags={
            "symbol_type": "function",
            "qualified_name": "PayRateEngine.resolve",
            "lineno": 20,
            "end_lineno": 30,
        },
    )


def test_full_qualname_from_parent_chain() -> None:
    nodes = [_module_node(), _class_node(), _method_node()]
    index = DerivedSymbolIndex.build(nodes, repo="fieldsync", rev="9f8e7d6")
    assert index.qualname_of("mod::PayRateEngine::resolve") == "payrate.PayRateEngine.resolve"


def test_trailing_segment_returns_all_candidates() -> None:
    other_class = UniversalNode(
        node_id="mod::OtherClass",
        kind=NodeKind.SYMBOL,
        title="OtherClass",
        source_uri="domain/payrate.py",
        parent_id="mod",
        domain_tags={"symbol_type": "class"},
    )
    other_method = UniversalNode(
        node_id="mod::OtherClass::resolve",
        kind=NodeKind.SYMBOL,
        title="resolve",
        source_uri="domain/payrate.py",
        parent_id="mod::OtherClass",
        domain_tags={"symbol_type": "function"},
    )
    nodes = [_module_node(), _class_node(), _method_node(), other_class, other_method]
    index = DerivedSymbolIndex.build(nodes, repo="fieldsync", rev="9f8e7d6")

    candidates = index.resolve("resolve")
    assert len(candidates) == 2
    qualnames = {c.qualname for c in candidates}
    assert qualnames == {"payrate.PayRateEngine.resolve", "payrate.OtherClass.resolve"}


def test_full_qualname_exact_match_returns_single_candidate() -> None:
    nodes = [_module_node(), _class_node(), _method_node()]
    index = DerivedSymbolIndex.build(nodes, repo="fieldsync", rev="9f8e7d6")
    candidates = index.resolve("PayRateEngine.resolve")
    assert len(candidates) == 1
    assert candidates[0].qualname == "payrate.PayRateEngine.resolve"


def test_symbol_type_filter() -> None:
    nodes = [_module_node(), _class_node(), _method_node()]
    index = DerivedSymbolIndex.build(nodes, repo="fieldsync", rev="9f8e7d6")

    assert index.resolve("PayRateEngine", symbol_type="class")
    assert not index.resolve("PayRateEngine", symbol_type="function")


def test_agrees_with_l0_qualified_name_where_present() -> None:
    # _method_node()'s domain_tags["qualified_name"] == "PayRateEngine.resolve"
    # which is exactly the derived qualname's trailing two segments.
    nodes = [_module_node(), _class_node(), _method_node()]
    index = DerivedSymbolIndex.build(nodes, repo="fieldsync", rev="9f8e7d6")
    derived = index.qualname_of("mod::PayRateEngine::resolve")
    l0_value = _method_node().domain_tags["qualified_name"]
    assert derived.endswith(l0_value)


def test_works_for_class_nodes_lacking_qualified_name() -> None:
    # _class_node() has no domain_tags["qualified_name"] at all (only
    # function nodes emit it, code.py:351/367) — derivation must still work.
    nodes = [_module_node(), _class_node()]
    index = DerivedSymbolIndex.build(nodes, repo="fieldsync", rev="9f8e7d6")
    assert index.qualname_of("mod::PayRateEngine") == "payrate.PayRateEngine"


def test_odoo_node_without_qualified_name_still_derives() -> None:
    # odoo_code.py never emits domain_tags["qualified_name"] at all.
    module = UniversalNode(
        node_id="odoo_mod",
        kind=NodeKind.SYMBOL,
        title="sale_order",
        source_uri="odoo-model://sale.order",
        domain_tags={"symbol_type": "module"},
    )
    model_class = UniversalNode(
        node_id="odoo_mod::SaleOrder",
        kind=NodeKind.SYMBOL,
        title="SaleOrder",
        source_uri="odoo-model://sale.order",
        parent_id="odoo_mod",
        domain_tags={"symbol_type": "class"},
    )
    index = DerivedSymbolIndex.build([module, model_class], repo="odoo", rev="a1b2c3d")
    assert index.qualname_of("odoo_mod::SaleOrder") == "sale_order.SaleOrder"


def test_cyclic_parent_id_terminates() -> None:
    node_a = UniversalNode(
        node_id="a",
        kind=NodeKind.SYMBOL,
        title="A",
        source_uri="mod.py",
        parent_id="b",
        domain_tags={"symbol_type": "class"},
    )
    node_b = UniversalNode(
        node_id="b",
        kind=NodeKind.SYMBOL,
        title="B",
        source_uri="mod.py",
        parent_id="a",
        domain_tags={"symbol_type": "class"},
    )
    # Must terminate (no RecursionError / infinite loop), not necessarily
    # produce a "correct" qualname for a pathological cycle.
    index = DerivedSymbolIndex.build([node_a, node_b], repo="ai-parrot", rev="a1b2c3d")
    assert index.qualname_of("a") is not None
    assert index.qualname_of("b") is not None


def test_non_symbol_nodes_are_skipped() -> None:
    rationale = UniversalNode(
        node_id="rat",
        kind=NodeKind.RATIONALE,
        title="WHY: something",
        source_uri="mod.py",
        domain_tags={"tag": "WHY"},
    )
    index = DerivedSymbolIndex.build([rationale], repo="ai-parrot", rev="a1b2c3d")
    assert index.qualname_of("rat") is None
    assert index.resolve("something") == ()


def test_build_does_no_io(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*args: object, **kwargs: object) -> None:
        raise AssertionError("DerivedSymbolIndex.build must not perform I/O")

    monkeypatch.setattr("builtins.open", _raise)
    monkeypatch.setattr(Path, "read_bytes", _raise)
    monkeypatch.setattr(Path, "read_text", _raise)

    nodes = [_module_node(), _class_node(), _method_node()]
    index = DerivedSymbolIndex.build(nodes, repo="fieldsync", rev="9f8e7d6")
    assert index.resolve("resolve")
