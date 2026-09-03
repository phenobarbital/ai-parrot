"""FEAT-498 TASK-2744 — `rust.yaml` symbol table + parity tests."""

from __future__ import annotations

from pathlib import Path

from parrot.knowledge.wiki.languages import astgrep
from parrot.knowledge.wiki.languages.rust import RustScanner

from .conftest import requires_astgrep

FIXTURES = Path(__file__).parent / "fixtures" / "structural"


@requires_astgrep
def test_rust_table_and_trait_impl():
    src = (FIXTURES / "sample.rs").read_text(encoding="utf-8") + "\nimpl std::fmt::Display for Parser { }\n"
    out = RustScanner().outline(src, "sample.rs")
    triples = {(s.kind.value, s.name, s.parent) for s in out.symbols}
    assert ("function", "new", "Parser") in triples
    assert ("function", "private_helper", "Parser") in triples
    assert any(r.rel == "implements" and r.target_text.endswith("Display") for r in out.refs)
    assert all("not_pub" not in line for line in out.outline)


@requires_astgrep
def test_rust_symbol_table():
    src = (FIXTURES / "sample.rs").read_text(encoding="utf-8")
    out = RustScanner().outline(src, "sample.rs")
    rows = {(s.kind.value, s.name): s for s in out.symbols}
    struct = rows[("struct", "Parser")]
    assert struct.doc == "A document parser."  # #[derive(Debug)] skipped
    assert struct.exported is True
    assert rows[("impl", "Parser")].name == "Parser"
    new_fn = rows[("function", "new")]
    assert new_fn.parent == "Parser"
    assert new_fn.doc == "Create a parser."
    assert new_fn.exported is True
    private = rows[("function", "private_helper")]
    assert private.parent == "Parser"
    assert private.exported is False
    assert rows[("trait", "Visitor")].doc == "Visits every node."
    assert ("mod", "utils") in rows
    assert ("enum", "Kind") in rows
    assert ("function", "not_pub") not in rows  # not pub, not in an impl


@requires_astgrep
def test_rust_not_pub_absent_from_outline():
    src = (FIXTURES / "sample.rs").read_text(encoding="utf-8")
    out = RustScanner().outline(src, "sample.rs")
    assert all("not_pub" not in line for line in out.outline)


@requires_astgrep
def test_rust_calls_ref():
    src = "fn helper() {}\nfn caller() {\n    helper();\n}\n"
    out = astgrep.extract(src, "rust", "x.rs")
    assert out is not None
    assert any(r.rel == "calls" and r.target_text == "helper" for r in out.refs)


def test_ruleset_loads_without_warning(caplog):
    astgrep.RuleSet.load.cache_clear()
    ruleset = astgrep.RuleSet.load("rust")
    assert ruleset is not None
    assert ruleset.language == "rust"
    assert not [r for r in caplog.records if r.levelname == "WARNING"]
