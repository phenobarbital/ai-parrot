"""Tests for the language-scanner suffix registry."""

from parrot.knowledge.wiki.languages import all_scanners, scanned_suffixes, scanner_for
from parrot.knowledge.wiki.languages.javascript import JavaScriptScanner
from parrot.knowledge.wiki.languages.luau import LuauScanner


def test_scanner_for_unknown_suffix_returns_none():
    assert scanner_for(".cfg") is None


def test_scanner_for_unregistered_language_suffix_returns_none():
    # No scanner is registered for these suffixes at the framework stage
    # (TASK-2010) — plugins land in later tasks.
    assert scanner_for(".xyz") is None


def test_scanned_suffixes_is_frozenset():
    assert isinstance(scanned_suffixes(), frozenset)


def test_all_scanners_returns_dict():
    scanners = all_scanners()
    assert isinstance(scanners, dict)


def test_registry_claims_svelte():
    """`.svelte` routes to the JS scanner (FEAT-396 / TASK-2020).

    Routing is derived: adding the suffix to
    ``JavaScriptScanner.suffixes`` is enough, because ``_SUFFIX_INDEX``
    is a comprehension over the registered scanners' suffix sets.
    """
    assert isinstance(scanner_for(".svelte"), JavaScriptScanner)
    assert ".svelte" in scanned_suffixes()


def test_registry_claims_lua_and_luau():
    """Default discovery and explicit scanner lookup agree (FEAT-532 TASK-2899).

    Both suffixes route to the same registered `LuauScanner` instance —
    `scanner_for()` (explicit lookup) and `scanned_suffixes()` (default
    discovery) must never disagree about which suffixes are claimed.
    """
    lua_scanner = scanner_for(".lua")
    luau_scanner = scanner_for(".luau")
    assert isinstance(lua_scanner, LuauScanner)
    assert isinstance(luau_scanner, LuauScanner)
    assert lua_scanner is luau_scanner
    assert {".lua", ".luau"} <= scanned_suffixes()
    assert isinstance(all_scanners()["luau"], LuauScanner)
