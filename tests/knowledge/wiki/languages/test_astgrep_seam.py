"""Tests for the FEAT-498 ast-grep structural extraction seam (TASK-2739)."""

from __future__ import annotations

import logging

from parrot.knowledge.wiki.languages import astgrep

from .conftest import requires_astgrep


def test_astgrep_unavailable_returns_none(monkeypatch):
    monkeypatch.setattr(astgrep, "is_available", lambda: False)
    assert astgrep.parse("x", "python") is None


def test_unsupported_language_short_circuits(monkeypatch):
    calls = []
    monkeypatch.setattr(astgrep, "_sgroot_factory", lambda *a: calls.append(a))
    assert astgrep.parse("x", "cobol") is None
    assert calls == []


@requires_astgrep
def test_panic_fence(monkeypatch):
    monkeypatch.setattr(astgrep, "supported_language", lambda lang: True)
    assert astgrep.parse("x", "definitely-not-a-language") is None


@requires_astgrep
def test_perl_dynamic_registration():
    assert astgrep.supported_language("perl") is True
    root = astgrep.parse("package Foo::Bar;\nsub bar {}\n", "perl")
    assert root is not None
    assert root.root().find_all(kind="subroutine_declaration_statement")


def test_perl_dynamic_registration_missing_binding(monkeypatch, caplog):
    astgrep._PERL_REGISTERED = None
    monkeypatch.setattr(astgrep, "_locate_perl_binding", lambda: None)
    with caplog.at_level(logging.DEBUG, logger=astgrep.logger.name):
        assert astgrep.supported_language("perl") is False
    # Cached: a second call does not re-probe or re-log.
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger=astgrep.logger.name):
        assert astgrep.supported_language("perl") is False
    assert caplog.records == []
    astgrep._PERL_REGISTERED = None


def test_ruleset_missing_is_none(caplog):
    astgrep.RuleSet.load.cache_clear()
    assert astgrep.RuleSet.load("nope-does-not-exist") is None
    assert not [r for r in caplog.records if r.levelname == "WARNING"]


def test_ruleset_load_validates_schema(tmp_path, monkeypatch, caplog):
    (tmp_path / "bad.yaml").write_text(
        "language: fakelang\nsymbols:\n  - id: class\n    rule: {kind: x}\n    doc: not_a_real_extractor\n",
        encoding="utf-8",
    )
    with caplog.at_level(logging.WARNING):
        result = astgrep.RuleSet._load_from_dir(tmp_path, "fakelang")
    assert result is None
    assert [r for r in caplog.records if r.levelname == "WARNING"]


def test_ruleset_load_valid_file(tmp_path):
    (tmp_path / "fakelang.yaml").write_text(
        "language: fakelang\naliases: [fakelang2]\nsummary: none\n"
        "symbols:\n  - id: class\n    rule: {kind: class_definition}\n"
        "    name: {field: name}\n",
        encoding="utf-8",
    )
    result = astgrep.RuleSet._load_from_dir(tmp_path, "fakelang2")
    assert result is not None
    assert result.language == "fakelang"
    assert result.symbols[0].id == "class"


def test_named_text_filters_anonymous_nodes():
    class FakeNode:
        def __init__(self, text, named):
            self._text, self._named = text, named

        def text(self):
            return self._text

        def is_named(self):
            return self._named

    class FakeMatch:
        def get_multiple_matches(self, var):
            return [FakeNode("1", True), FakeNode(",", False), FakeNode("b=2", True)]

    assert astgrep.named_text(FakeMatch(), "ARGS") == "1, b=2"


@requires_astgrep
def test_named_text_real_capture():
    root = astgrep.parse("helper(1, b=2)", "python").root()
    match = root.find_all(pattern="helper($$$ARGS)")[0]
    assert astgrep.named_text(match, "ARGS") == "1, b=2"


@requires_astgrep
def test_extract_bad_kind_is_isolated(monkeypatch):
    """A rule with a nonexistent kind is isolated; other rules still work."""
    ruleset = astgrep.RuleSet(
        language="python",
        symbols=[
            astgrep.SymbolSpec(id="class", rule={"kind": "definitely_not_a_kind"}, name={"field": "name"}),
            astgrep.SymbolSpec(id="function", rule={"kind": "function_definition"}, name={"field": "name"}),
        ],
    )
    monkeypatch.setattr(astgrep.RuleSet, "load", classmethod(lambda cls, lang: ruleset))
    astgrep._WARNED_RULE_KEYS.clear()
    outline = astgrep.extract("def f():\n    pass\n", "python", "a.py")
    assert outline is not None
    assert len(outline.symbols) == 1
    assert outline.symbols[0].name == "f"
    assert ("python", "class") in astgrep._WARNED_RULE_KEYS


@requires_astgrep
def test_extract_returns_none_without_ruleset(monkeypatch):
    monkeypatch.setattr(astgrep.RuleSet, "load", classmethod(lambda cls, lang: None))
    assert astgrep.extract("x = 1\n", "python", "a.py") is None
