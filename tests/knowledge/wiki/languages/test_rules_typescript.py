"""FEAT-498 TASK-2742 — `typescript.yaml` symbol table + parity tests."""

from __future__ import annotations

from pathlib import Path

from parrot.knowledge.wiki.languages import astgrep
from parrot.knowledge.wiki.languages.javascript import JavaScriptScanner
from parrot.knowledge.wiki.symbols import SymbolKind

from .conftest import requires_astgrep

FIXTURES = Path(__file__).parent / "fixtures" / "structural"


@requires_astgrep
def test_typescript_symbol_table():
    src = (FIXTURES / "sample.ts").read_text(encoding="utf-8")
    out = JavaScriptScanner().outline(src, "sample.ts")
    rows = {
        (s.kind.value, s.name): (s.parent, s.exported, s.start_line, s.end_line, s.doc)
        for s in out.symbols
    }
    assert rows[("class", "UserService")] == (None, True, 2, 5, "Main service class.")
    assert rows[("method", "createUser")][0] == "UserService"
    assert rows[("method", "createUser")][1] is False  # never exported
    assert rows[("function", "createUser")] == (None, True, 7, 7, "Create a new user.")
    assert rows[("function", "internalHelper")] == (None, False, 8, 8, "")
    assert rows[("interface", "UserRecord")][:2] == (None, True)
    assert rows[("const", "DEFAULT_TIMEOUT")][1] is True
    assert rows[("type", "Id")][1] is True
    assert not any(line.startswith("    ") for line in out.outline)  # methods not rendered


@requires_astgrep
def test_typescript_method_depth_2_not_rendered():
    src = (FIXTURES / "sample.ts").read_text(encoding="utf-8")
    out = JavaScriptScanner().outline(src, "sample.ts")
    method = next(s for s in out.symbols if s.kind == SymbolKind.METHOD)
    assert method.depth == 2
    assert not any("createUser" in line and line.startswith("    ") for line in out.outline)


@requires_astgrep
def test_typescript_refs():
    src = "class Base {}\ninterface Foo {}\nclass Sub extends Base implements Foo {\n  m() { helper(1); }\n}\n"
    out = astgrep.extract(src, "typescript", "x.ts")
    assert out is not None
    rels = {(r.rel, r.target_text) for r in out.refs}
    assert ("extends", "Base") in rels
    assert ("implements", "Foo") in rels
    assert ("calls", "helper") in rels


def test_ruleset_loads_without_warning(caplog):
    astgrep.RuleSet.load.cache_clear()
    ruleset = astgrep.RuleSet.load("typescript")
    assert ruleset is not None
    assert ruleset.language == "typescript"
    assert not [r for r in caplog.records if r.levelname == "WARNING"]


def test_ruleset_serves_aliases():
    astgrep.RuleSet.load.cache_clear()
    for lang in ("typescript", "tsx", "javascript"):
        assert astgrep.RuleSet.load(lang) is not None


def test_outline_parity_ts_tsx_js_svelte():
    """``outline()`` is byte-identical with and without the seam."""
    import importlib

    for suffix, fixture in (
        (".ts", "sample.ts"),
        (".tsx", "sample.ts"),
        (".js", "sample.ts"),
        (".svelte", "sample.svelte"),
    ):
        src = (FIXTURES / fixture).read_text(encoding="utf-8")
        scanner = JavaScriptScanner()
        with_seam = scanner.outline(src, f"x{suffix}")

        module = importlib.import_module("parrot.knowledge.wiki.languages.astgrep")
        original = module.is_available
        try:
            module.is_available = lambda: False
            without_seam = scanner.outline(src, f"x{suffix}")
        finally:
            module.is_available = original

        assert with_seam.outline == without_seam.outline, suffix
        assert with_seam.summary == without_seam.summary, suffix
        assert with_seam.imports == without_seam.imports, suffix
