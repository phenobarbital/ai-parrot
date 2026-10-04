"""FEAT-609 M4: module-local JS/TS functions, js_call_scope, rule languages filter."""

from __future__ import annotations

import logging

from parrot.knowledge.wiki.languages import astgrep
from parrot.knowledge.wiki.languages.javascript import JavaScriptScanner
from parrot.knowledge.wiki.symbols import SymbolKind

from .conftest import requires_astgrep

SRC = (
    "let { rows }: { rows: string[] } = $props()\n"
    "const onSave = async () => { persist(rows); rows.map(r => fmt(r)) }\n"
    "const onBlur = function () { blur() }\n"
    "function onReset() { clear() }\n"
    "export const helper = (x: number) => twice(x)\n"
    "function outer() { const inner = () => deep() }\n"
)


def _extract(lang: str = "typescript"):
    out = astgrep.extract(SRC, lang, "src/lib/x.ts")
    assert out is not None
    return out


@requires_astgrep
def test_arrow_function_symbol() -> None:
    syms = {s.name: s for s in _extract().symbols}
    for name in ("onSave", "onBlur"):
        assert syms[name].kind == SymbolKind.FUNCTION
        assert syms[name].node_kind == "variable_declarator"
        assert syms[name].exported is False


@requires_astgrep
def test_exported_arrow_stays_const() -> None:
    helpers = [s for s in _extract().symbols if s.name == "helper"]
    assert [s.kind for s in helpers] == [SymbolKind.CONST]


@requires_astgrep
def test_nested_arrow_not_a_symbol() -> None:
    assert "inner" not in {s.name for s in _extract().symbols}


@requires_astgrep
def test_call_inside_arrow_scoped() -> None:
    scopes = {r.target_text: r.src_qualname for r in _extract().refs if r.rel == "calls"}
    assert scopes["persist"] == "onSave"
    assert scopes["fmt"] == "onSave"
    assert scopes["blur"] == "onBlur"
    assert scopes["deep"] == "outer"
    assert scopes["clear"] == "onReset"
    assert scopes["twice"] == "helper"
    assert scopes["$props"] == ""


@requires_astgrep
def test_ts_only_rules_skip_javascript(caplog) -> None:
    astgrep._WARNED_RULE_KEYS.clear()
    with caplog.at_level(logging.WARNING):
        astgrep.extract("function f() { g() }\n", "javascript", "a.js")
    assert "could not be evaluated" not in caplog.text


@requires_astgrep
def test_ts_only_rules_still_run_for_typescript() -> None:
    out = astgrep.extract("interface A {}\ntype B = string\nclass C extends D {}\n", "typescript", "a.ts")
    assert out is not None
    assert {s.kind for s in out.symbols} >= {SymbolKind.INTERFACE, SymbolKind.TYPE}
    assert any(r.rel == "extends" for r in out.refs)


@requires_astgrep
def test_outline_does_not_render_local_functions() -> None:
    outline = JavaScriptScanner().outline(SRC, "src/lib/x.ts").outline
    text = "\n".join(outline)
    assert "onSave" not in text and "onBlur" not in text
    assert "helper" in text  # the exported const still renders (parity)
