"""Tests for the cached, never-raising tree-sitter grammar loader."""

from parrot.knowledge.wiki.languages import treesitter
from parrot.knowledge.wiki.languages.treesitter import get_parser


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
