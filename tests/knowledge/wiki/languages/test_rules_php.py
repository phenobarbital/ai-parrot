"""FEAT-498 TASK-2743 — `php.yaml` symbol table + parity tests."""

from __future__ import annotations

from pathlib import Path

from parrot.knowledge.wiki.languages import astgrep
from parrot.knowledge.wiki.languages.php import PhpScanner

from .conftest import requires_astgrep

FIXTURES = Path(__file__).parent / "fixtures" / "structural"


@requires_astgrep
def test_php_qualnames_namespaced():
    src = (FIXTURES / "sample.php").read_text(encoding="utf-8")
    out = PhpScanner().outline(src, "sample.php")
    q = {s.qualname for s in out.symbols}
    assert "App\\Models\\User" in q
    assert "App\\Models\\User::getFullName" in q
    package = next(s for s in out.symbols if s.kind.value == "package")
    assert package.name == "App\\Models"


@requires_astgrep
def test_php_symbol_table():
    src = (FIXTURES / "sample.php").read_text(encoding="utf-8")
    out = PhpScanner().outline(src, "sample.php")
    rows = {(s.kind.value, s.name): s for s in out.symbols}
    cls = rows[("class", "User")]
    assert (cls.start_line, cls.end_line) == (5, 8)
    assert cls.doc == "Represents an application user."
    method = rows[("method", "getFullName")]
    assert method.parent == "App\\Models\\User"
    assert method.doc == "Get the full name."
    assert ("interface", "Serializable") in rows
    assert ("trait", "HasTimestamps") in rows
    assert ("enum", "Status") in rows
    assert ("function", "helper_function") in rows
    assert ("package", "App\\Models") in rows


@requires_astgrep
def test_php_package_not_rendered():
    src = (FIXTURES / "sample.php").read_text(encoding="utf-8")
    out = PhpScanner().outline(src, "sample.php")
    assert not any("App\\Models" in line for line in out.outline)


@requires_astgrep
def test_php_refs():
    src = (FIXTURES / "sample.php").read_text(encoding="utf-8")
    out = astgrep.extract(src, "php", "sample.php")
    assert out is not None
    rels = {(r.rel, r.target_text) for r in out.refs}
    assert ("extends", "Model") in rels
    assert ("implements", "Serializable") in rels


@requires_astgrep
def test_php_calls_all_three_kinds():
    src = (
        "<?php\nclass A {\n    function m() {\n        helper(1);\n"
        "        $this->other();\n        self::stat();\n    }\n}\n"
    )
    out = astgrep.extract(src, "php", "x.php")
    assert out is not None
    targets = {r.target_text for r in out.refs if r.rel == "calls"}
    assert targets == {"helper", "other", "stat"}


def test_outline_parity_php():
    src = (FIXTURES / "sample.php").read_text(encoding="utf-8")
    scanner = PhpScanner()
    with_seam = scanner.outline(src, "sample.php")

    original = astgrep.is_available
    try:
        astgrep.is_available = lambda: False
        without_seam = scanner.outline(src, "sample.php")
    finally:
        astgrep.is_available = original

    assert with_seam.outline == without_seam.outline
    assert with_seam.summary == without_seam.summary
    assert with_seam.imports == without_seam.imports


def test_ruleset_loads_without_warning(caplog):
    astgrep.RuleSet.load.cache_clear()
    ruleset = astgrep.RuleSet.load("php")
    assert ruleset is not None
    assert ruleset.language == "php"
    assert not [r for r in caplog.records if r.levelname == "WARNING"]
