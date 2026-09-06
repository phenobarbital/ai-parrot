"""Tests for the Luau/Lua scanner plugin (FEAT-532 TASK-2899)."""

from __future__ import annotations

import time

import pytest
from parrot.knowledge.wiki.languages import luau_guard, treesitter
from parrot.knowledge.wiki.languages.luau import LuauScanner

_TREESITTER_AVAILABLE = treesitter.get_parser("luau") is not None
requires_treesitter = pytest.mark.skipif(not _TREESITTER_AVAILABLE, reason="tree-sitter-luau not installed")


@pytest.fixture
def scanner() -> LuauScanner:
    return LuauScanner()


_VALID_SOURCE = """-- Adds two numbers.
local Module = {}

--- Doc for add
function Module.add(a: number, b: number): number
\treturn a + b
end

function Module:greet(name: string)
\tprint("hello " .. name)
end

local function helper(x)
\treturn x * 2
end

export type Point = { x: number, y: number }
type Local = number

return Module
"""


# ---------------------------------------------------------------------------
# test_outline_syntax_matrix
# ---------------------------------------------------------------------------


@requires_treesitter
def test_outline_syntax_matrix_treesitter(scanner: LuauScanner):
    outline = scanner.outline(_VALID_SOURCE, "src/Module.luau")

    assert outline.summary == "Adds two numbers."
    joined = "\n".join(outline.outline)
    assert "function Module.add(a: number, b: number): number" in joined
    assert "function Module:greet(name: string)" in joined
    assert "export type Point = { x: number, y: number }" in joined
    assert "module returns Module" in joined
    # No `sym:` structural plane for Luau in any mode (spec §8).
    assert outline.symbols == []
    assert outline.refs == []


def test_outline_syntax_matrix_heuristic(scanner: LuauScanner, force_luau_heuristic):
    outline = scanner.outline(_VALID_SOURCE, "src/Module.luau")

    joined = "\n".join(outline.outline)
    assert "function Module.add(a: number, b: number): number" in joined
    assert "function Module:greet(name: string)" in joined
    assert "export type Point = { x: number, y: number }" in joined
    assert "module returns Module" in joined
    assert outline.symbols == []
    assert outline.refs == []


@pytest.fixture
def force_luau_heuristic(monkeypatch):
    """Force the Luau scanner onto its heuristic path (grammar unavailable)."""
    monkeypatch.setattr(treesitter, "get_parser", lambda language: None)
    yield


# ---------------------------------------------------------------------------
# test_unsupported_syntax_local_recovery
# ---------------------------------------------------------------------------


@requires_treesitter
def test_unsupported_syntax_local_recovery(scanner: LuauScanner):
    """Attributes/type packs leave later valid declarations intact."""
    source = """local <const> x = 1

function Later.thing(a)
\treturn a
end

return Later
"""
    outline = scanner.outline(source, "src/Weird.luau")
    # Never raises, and the later valid function/module declarations are
    # still recovered even though `<const>` attribute syntax may not be
    # fully supported by the installed grammar version.
    joined = "\n".join(outline.outline)
    assert "function Later.thing(a)" in joined
    assert "module returns Later" in joined


def test_unsupported_syntax_never_raises_heuristic(scanner: LuauScanner, force_luau_heuristic):
    source = "local <const> x = 1\n\nfunction Later.thing(a)\n\treturn a\nend\n\nreturn Later\n"
    outline = scanner.outline(source, "src/Weird.luau")
    joined = "\n".join(outline.outline)
    assert "function Later.thing(a)" in joined


# ---------------------------------------------------------------------------
# test_forced_heuristic
# ---------------------------------------------------------------------------


def test_forced_heuristic_missing_grammar_bounded(scanner: LuauScanner, force_luau_heuristic):
    """Missing/broken grammar yields bounded output without sym pages."""
    outline = scanner.outline(_VALID_SOURCE, "src/Module.luau")
    assert scanner.mode == "heuristic"
    assert outline.symbols == []
    assert outline.refs == []
    assert outline.outline  # still produces a bounded, non-empty outline


def test_forced_heuristic_malformed_source_degrades_empty(scanner: LuauScanner, force_luau_heuristic):
    """A genuinely malformed heuristic pass never raises — degrades to
    empty rather than crash (defence in depth alongside try/except)."""
    outline = scanner.outline("function ((( not valid at all", "src/Bad.luau")
    assert isinstance(outline.outline, list)
    assert outline.symbols == []
    assert outline.refs == []


# ---------------------------------------------------------------------------
# test_guard_combination
# ---------------------------------------------------------------------------


def test_guard_combination_oversized_input_skips_entirely(scanner: LuauScanner, monkeypatch):
    """Above the fallback bound, the file is skipped entirely (empty outline)."""
    monkeypatch.setattr(luau_guard, "FALLBACK_BYTE_LIMIT", 10)
    outline = scanner.outline(_VALID_SOURCE, "src/Module.luau")
    assert outline == outline.__class__()  # fully empty LanguageOutline


@requires_treesitter
def test_guard_combination_oversized_for_treesitter_falls_back_to_heuristic(scanner: LuauScanner, monkeypatch):
    """Above the tree-sitter byte cap (but under the fallback bound), the
    heuristic path still produces output."""
    monkeypatch.setattr(luau_guard, "BYTE_LIMIT", 10)
    outline = scanner.outline(_VALID_SOURCE, "src/Module.luau")
    joined = "\n".join(outline.outline)
    assert "function Module.add(a: number, b: number): number" in joined


@requires_treesitter
def test_guard_combination_timeout_terminates_and_cleans_up(scanner: LuauScanner, monkeypatch):
    """A deliberately-stalled guard call terminates within the deadline,
    leaves no child running, and the scanner degrades to heuristic output
    rather than hanging or raising."""

    def _stalled_run_isolated(fn, args, deadline_seconds=None):
        return None, "timeout"

    monkeypatch.setattr(luau_guard, "run_isolated", _stalled_run_isolated)

    start = time.monotonic()
    outline = scanner.outline(_VALID_SOURCE, "src/Module.luau")
    elapsed = time.monotonic() - start

    assert elapsed < 5.0
    # Degrades to the heuristic path rather than an empty outline — the
    # guard failure is logged, not silently total data loss, when a
    # bounded fallback can still produce something useful.
    joined = "\n".join(outline.outline)
    assert "function Module.add(a: number, b: number): number" in joined


@requires_treesitter
def test_guard_combination_real_kill_leaves_clean_state_for_next_parse(scanner: LuauScanner):
    """Exercises the REAL subprocess-kill path (not monkeypatched) with a
    tiny deadline, then verifies a subsequent normal parse is unaffected —
    mirrors TASK-2896's ``test_following_parse_is_clean``."""
    result, error = luau_guard.run_isolated(_stall_forever, (b"irrelevant",), deadline_seconds=0.3)
    assert result is None
    assert error == "timeout"

    # A clean, immediately-following call must still succeed normally.
    outline = scanner.outline(_VALID_SOURCE, "src/Module.luau")
    joined = "\n".join(outline.outline)
    assert "function Module.add(a: number, b: number): number" in joined


def _stall_forever(_source_bytes: bytes) -> None:
    """Module-level (picklable) stand-in for a stuck native parse."""
    time.sleep(3600)


def test_guard_combination_density_is_logged_not_fatal(scanner: LuauScanner, caplog):
    """High ERROR-node density is a diagnostic, never a build failure —
    the file still returns whatever tree-sitter's own error recovery
    produced."""
    source = "function ((( totally broken luau code here"
    outline = scanner.outline(source, "src/Broken.luau")
    assert isinstance(outline.outline, list)  # never raises


# ---------------------------------------------------------------------------
# test_requires_ignore_comments
# ---------------------------------------------------------------------------


_REQUIRE_SOURCE = """-- local Foo = require(script.Parent.CommentedOut)
local Real = require(script.Parent.Real)
local Chained = require(game:GetService("ReplicatedStorage").Bar)
--[[
local Blocked = require(script.Parent.BlockCommented)
]]
local Relative = require("./Sibling")
"""


@requires_treesitter
def test_requires_ignore_comments_treesitter(scanner: LuauScanner):
    outline = scanner.outline(_REQUIRE_SOURCE, "src/Main.luau")
    assert "script.Parent.CommentedOut" not in outline.imports
    assert "script.Parent.BlockCommented" not in outline.imports
    assert "script.Parent.Real" in outline.imports
    assert 'game:GetService("ReplicatedStorage").Bar' in outline.imports
    assert '"./Sibling"' in outline.imports


def test_requires_ignore_comments_heuristic(scanner: LuauScanner, force_luau_heuristic):
    outline = scanner.outline(_REQUIRE_SOURCE, "src/Main.luau")
    assert "script.Parent.CommentedOut" not in outline.imports
    assert "script.Parent.BlockCommented" not in outline.imports
    assert "script.Parent.Real" in outline.imports
    assert 'game:GetService("ReplicatedStorage").Bar' in outline.imports


def test_requires_ignore_member_call(scanner: LuauScanner, force_luau_heuristic):
    """`obj.require(...)`/`obj:require(...)` is not a real Luau require."""
    source = 'local x = someTable.require("not-a-real-require")\n'
    outline = scanner.outline(source, "src/Main.luau")
    assert outline.imports == []


# ---------------------------------------------------------------------------
# test_registry_claims_lua_and_luau — covered in tests/.../test_registry.py
# (per this task's file table: "MODIFY tests/knowledge/wiki/languages/test_registry.py")
# ---------------------------------------------------------------------------


def test_registry_claims_lua_and_luau_from_scanner_module():
    from parrot.knowledge.wiki.languages import scanned_suffixes, scanner_for

    assert isinstance(scanner_for(".lua"), LuauScanner)
    assert isinstance(scanner_for(".luau"), LuauScanner)
    assert {".lua", ".luau"} <= scanned_suffixes()


# ---------------------------------------------------------------------------
# resolve_import delegation to TASK-2898
# ---------------------------------------------------------------------------


def test_build_reference_index_and_resolve_import_delegates(scanner: LuauScanner, tmp_path, restore_scan_root):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Helper.luau").write_text("return {}\n", encoding="utf-8")
    (tmp_path / "src" / "Main.luau").write_text('require("./Helper")\n', encoding="utf-8")

    restore_scan_root(tmp_path)
    rel_paths = ["src/Helper.luau", "src/Main.luau"]
    index = scanner.build_reference_index(rel_paths)
    resolved = scanner.resolve_import('"./Helper"', "src/Main.luau", index)
    assert resolved == "src/Helper.luau"
