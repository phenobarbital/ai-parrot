"""FEAT-498 TASK-2745 — `perl.yaml` symbol table + parity + fallback tests."""

from __future__ import annotations

import importlib.resources
from pathlib import Path

import yaml
from parrot.knowledge.wiki.languages import astgrep
from parrot.knowledge.wiki.languages.perl import PerlScanner

from .conftest import requires_astgrep

FIXTURES = Path(__file__).parent / "fixtures" / "structural"


def test_perl_rules_have_no_patterns():
    data = yaml.safe_load(
        importlib.resources.files("parrot.knowledge.wiki.languages.rules")
        .joinpath("perl.yaml")
        .read_text(encoding="utf-8")
    )
    assert "pattern" not in yaml.safe_dump(data)


def test_ruleset_loads_without_warning(caplog):
    astgrep.RuleSet.load.cache_clear()
    ruleset = astgrep.RuleSet.load("perl")
    assert ruleset is not None
    assert ruleset.language == "perl"
    assert not [r for r in caplog.records if r.levelname == "WARNING"]


@requires_astgrep
def test_perl_symbol_table():
    src = (FIXTURES / "sample.pm").read_text(encoding="utf-8")
    out = PerlScanner().outline(src, "sample.pm")
    rows = {(s.kind.value, s.name): s for s in out.symbols}
    assert rows[("package", "MyApp::Model::User")].depth == 1
    validate = rows[("function", "validate")]
    assert validate.parent == "MyApp::Model::User"
    assert validate.depth == 2
    assert validate.doc == "Validate the user."
    assert ("attribute", "name") in rows
    assert ("field", "$x") in rows
    other_pkg = rows[("package", "MyApp::Other")]
    assert other_pkg.name == "MyApp::Other"
    bar = rows[("function", "bar")]
    assert bar.parent == "MyApp::Other"  # parent switches after the 2nd package


@requires_astgrep
def test_perl_imports_match_walker():
    src = (FIXTURES / "sample.pm").read_text(encoding="utf-8")
    out = PerlScanner().outline(src, "sample.pm")
    assert "Moose" in out.imports
    assert "MyApp::Schema" in out.imports
    assert "strict" not in out.imports
    assert "warnings" not in out.imports
    assert "Baz" in out.imports


@requires_astgrep
def test_perl_mode_is_ast_grep():
    src = (FIXTURES / "sample.pm").read_text(encoding="utf-8")
    scanner = PerlScanner()
    scanner.outline(src, "sample.pm")
    assert scanner.mode == "ast-grep"


def test_perl_fallback_when_so_missing(monkeypatch):
    """Missing the tree-sitter-perl binding: cached False, silent fallback."""
    astgrep._PERL_REGISTERED = None
    monkeypatch.setattr(astgrep, "_locate_perl_binding", lambda: None)
    try:
        assert astgrep.supported_language("perl") is False
        scanner = PerlScanner()
        src = "package Foo;\nsub bar { }\n1;\n"
        out = scanner.outline(src, "x.pm")
        assert scanner.mode != "ast-grep"
        assert any("package Foo" in line for line in out.outline)
    finally:
        astgrep._PERL_REGISTERED = None
