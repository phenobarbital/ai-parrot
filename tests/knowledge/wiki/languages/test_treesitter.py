"""Tests for the cached, never-raising tree-sitter grammar loader."""

import importlib
import importlib.util
import sys
from types import SimpleNamespace

import pytest
from parrot.knowledge.wiki.languages import treesitter
from parrot.knowledge.wiki.languages.treesitter import get_parser


def _importable(module_name: str) -> bool:
    """Whether ``module_name`` actually imports here.

    Deliberately imports rather than probing with ``find_spec``: a module
    can be discoverable yet raise on import, and only an import proves
    the difference. Independent of ``_build_parser``'s callable
    resolution, which is what these tests exist to check.
    """
    try:
        importlib.import_module(module_name)
    except Exception:  # noqa: BLE001 - any failure means "not usable here"
        return False
    return True


def _wheel_installed(module_name: str) -> bool:
    """Whether a grammar could load at all in this environment.

    Requires ``tree_sitter`` itself as well as the grammar wheel: with
    the core package unusable, ``_build_parser`` returns ``None``
    whatever wheels are present, so these tests must skip rather than
    fail when the optional extra is absent.
    """
    return _importable("tree_sitter") and _importable(module_name)


@pytest.fixture
def clear_parser_cache():
    """Drop cached parsers before AND after a test.

    ``_PARSER_CACHE`` caches ``None`` too, so a test that monkeypatches
    grammar availability without clearing it makes later tests pass or
    fail depending on collection order.
    """
    def _clear() -> None:
        for name in list(treesitter._PARSER_CACHE):
            treesitter._PARSER_CACHE.pop(name, None)

    _clear()
    yield _clear
    _clear()


def test_get_parser_unknown_language_returns_none():
    assert get_parser("nonexistent_language") is None


def test_get_parser_missing_dep_returns_none(monkeypatch):
    monkeypatch.setitem(treesitter._GRAMMAR_MODULES, "php", "no_such_module_xyz")
    treesitter._PARSER_CACHE.pop("php", None)
    assert get_parser("php") is None


def test_get_parser_caches_result(monkeypatch):
    treesitter._PARSER_CACHE.pop("nonexistent_language", None)
    first = get_parser("nonexistent_language")
    second = get_parser("nonexistent_language")
    assert first is second is None
    assert "nonexistent_language" in treesitter._PARSER_CACHE


# ---------------------------------------------------------------------------
# FEAT-396 / TASK-2019 — grammar-callable resolution across wheel conventions
# ---------------------------------------------------------------------------


def _real_capsule():
    """A genuine grammar PyCapsule, borrowed from a single-grammar wheel.

    Lets the resolution-order tests use a stand-in module while still
    handing ``tree_sitter.Language`` something it will actually accept.
    """
    import tree_sitter_javascript

    return tree_sitter_javascript.language()


@pytest.mark.parametrize(
    ("language", "module_name"),
    [
        ("typescript", "tree_sitter_typescript"),
        ("php", "tree_sitter_php"),
    ],
)
def test_build_parser_uses_language_variant(
    language, module_name, clear_parser_cache
):
    """Multi-grammar wheels expose ``language_<name>()``, not ``language()``.

    These two returned ``None`` before TASK-2019 even with the extra
    installed, silently pushing every ``.ts``/``.tsx``/``.php`` file onto
    the regex heuristic path.
    """
    if not _wheel_installed(module_name):
        pytest.skip(f"{module_name} not installed")
    parser = get_parser(language)
    assert parser is not None, (
        f"{language} grammar failed to load — {module_name} exposes a "
        "named variant, not language()"
    )


@pytest.mark.parametrize(
    ("language", "module_name"),
    [
        ("javascript", "tree_sitter_javascript"),
        ("rust", "tree_sitter_rust"),
    ],
)
def test_build_parser_single_grammar_wheel_unregressed(
    language, module_name, clear_parser_cache
):
    """Single-grammar wheels keep resolving through plain ``language()``."""
    if not _wheel_installed(module_name):
        pytest.skip(f"{module_name} not installed")
    assert get_parser(language) is not None


def test_build_parser_prefers_plain_language(monkeypatch, clear_parser_cache):
    """``language()`` wins when a module exposes both conventions."""
    if not _wheel_installed("tree_sitter_javascript"):
        pytest.skip("tree_sitter_javascript not installed")
    calls: list[str] = []

    def _language():
        calls.append("language")
        return _real_capsule()

    def _language_typescript():
        calls.append("language_typescript")
        return _real_capsule()

    stand_in = SimpleNamespace(
        language=_language, language_typescript=_language_typescript
    )
    monkeypatch.setitem(sys.modules, "fake_grammar_both", stand_in)
    monkeypatch.setitem(
        treesitter._GRAMMAR_MODULES, "typescript", "fake_grammar_both"
    )

    assert get_parser("typescript") is not None
    assert calls == ["language"], "language() must be tried first"


def test_build_parser_falls_back_to_named_variant(
    monkeypatch, clear_parser_cache
):
    """With no ``language()``, the named variant is used."""
    if not _wheel_installed("tree_sitter_javascript"):
        pytest.skip("tree_sitter_javascript not installed")
    calls: list[str] = []

    def _language_typescript():
        calls.append("language_typescript")
        return _real_capsule()

    stand_in = SimpleNamespace(language_typescript=_language_typescript)
    monkeypatch.setitem(sys.modules, "fake_grammar_named", stand_in)
    monkeypatch.setitem(
        treesitter._GRAMMAR_MODULES, "typescript", "fake_grammar_named"
    )

    assert get_parser("typescript") is not None
    assert calls == ["language_typescript"]


def test_build_parser_skips_failing_candidate(monkeypatch, clear_parser_cache):
    """A candidate that raises is skipped, not fatal to the search."""
    if not _wheel_installed("tree_sitter_javascript"):
        pytest.skip("tree_sitter_javascript not installed")

    def _language():
        raise RuntimeError("ABI mismatch")

    def _language_typescript():
        return _real_capsule()

    stand_in = SimpleNamespace(
        language=_language, language_typescript=_language_typescript
    )
    monkeypatch.setitem(sys.modules, "fake_grammar_broken", stand_in)
    monkeypatch.setitem(
        treesitter._GRAMMAR_MODULES, "typescript", "fake_grammar_broken"
    )

    assert get_parser("typescript") is not None


def test_build_parser_no_usable_callable_returns_none(
    monkeypatch, clear_parser_cache
):
    """A module exposing no known callable degrades to None, never raises."""
    stand_in = SimpleNamespace(some_other_symbol=lambda: None)
    monkeypatch.setitem(sys.modules, "fake_grammar_empty", stand_in)
    monkeypatch.setitem(
        treesitter._GRAMMAR_MODULES, "typescript", "fake_grammar_empty"
    )

    assert get_parser("typescript") is None


def test_build_parser_unknown_language_none(clear_parser_cache):
    """An unmapped language name still returns None, never raises."""
    assert get_parser("klingon") is None
