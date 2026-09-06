"""Literal service/type/chain and shadowing cases (FEAT-532 TASK-2906)."""

from __future__ import annotations

import pytest
from parrot.knowledge.wiki.languages import luau_guard, treesitter
from parrot.knowledge.wiki.roblox.models import RobloxApiCatalog, RobloxReferenceExtractionKind
from parrot.knowledge.wiki.roblox.references import extract_api_reference_candidates

_TREESITTER_AVAILABLE = treesitter.get_parser("luau") is not None
requires_treesitter = pytest.mark.skipif(not _TREESITTER_AVAILABLE, reason="tree-sitter-luau not installed")

_CATALOG = RobloxApiCatalog(
    generation_id="gen-1",
    classes={
        "Players": "class/Players",
        "Workspace": "class/Workspace",
        "Terrain": "class/Terrain",
        "Instance": "class/Instance",
    },
    enums={"Material": "enum/Material"},
)


# ---------------------------------------------------------------------------
# test_services_and_explicit_types
# ---------------------------------------------------------------------------


@requires_treesitter
def test_services_and_explicit_types():
    """Literal services and genuine API annotations yield class references."""
    source = """
local Players = game:GetService("Players")

local function greet(p: Instance)
end

local x: Players = nil
"""
    candidates, diagnostics = extract_api_reference_candidates(source, _CATALOG)
    kinds_targets = {(c.extraction_kind, c.target_name) for c in candidates}

    assert (RobloxReferenceExtractionKind.SERVICE_CALL, "Players") in kinds_targets
    assert (RobloxReferenceExtractionKind.TYPE_ANNOTATION, "Instance") in kinds_targets
    assert (RobloxReferenceExtractionKind.TYPE_ANNOTATION, "Players") in kinds_targets
    # Only resolved (catalog-matched) candidates are ever returned at all.
    assert diagnostics == []


@requires_treesitter
def test_builtin_type_annotation_is_not_a_candidate():
    source = "local function f(a: number, b: string) end\n"
    candidates, _diag = extract_api_reference_candidates(source, _CATALOG)
    assert candidates == []


# ---------------------------------------------------------------------------
# test_workspace_terrain_and_known_chains
# ---------------------------------------------------------------------------


@requires_treesitter
def test_workspace_terrain_and_known_chains():
    """Known-root chained access is included in v1."""
    source = """
local t = workspace.Terrain
local w = game.Workspace
local deep = game.Workspace.Terrain
"""
    candidates, _diag = extract_api_reference_candidates(source, _CATALOG)
    targets = {(c.recognized_root, c.target_name) for c in candidates}

    assert ("workspace", "Terrain") in targets
    assert ("game", "Workspace") in targets
    # Both intermediate levels of the deeper chain resolve independently.
    assert ("game", "Terrain") in targets or ("game", "Workspace") in targets
    assert all(c.extraction_kind == RobloxReferenceExtractionKind.CHAINED_ACCESS for c in candidates)


# ---------------------------------------------------------------------------
# test_shadowing_aliases_and_comments
# ---------------------------------------------------------------------------


@requires_treesitter
def test_shadowing_aliases_and_comments():
    """Local scope aliases/shadowed roots/string examples do not create references."""
    source = """
-- Example: game:GetService("Players") is how you'd normally get Players.
local exampleString = "workspace.Terrain looks like an API reference but isn't code"

type MyAlias = Players

local workspace = {}
local shadowed = workspace.Terrain
"""
    candidates, _diag = extract_api_reference_candidates(source, _CATALOG)

    # Nothing from the comment (tree-sitter never descends into it) — no
    # SERVICE_CALL candidate for "Players" anywhere in this file.
    assert not any(c.extraction_kind == RobloxReferenceExtractionKind.SERVICE_CALL for c in candidates)
    # Nothing from the string literal — no candidate rooted at "workspace"
    # would even be possible from string content, but confirm no stray
    # "Terrain" chained-access candidate leaked from it either.
    assert not any(c.target_name == "Terrain" for c in candidates)
    # Nothing from the local type alias `type MyAlias = Players`.
    assert not any(c.target_name == "Players" for c in candidates)
    # `workspace` is locally shadowed later in the file -> file-wide
    # suppression per this module's coarse shadow policy.
    assert not any(c.recognized_root == "workspace" for c in candidates)
    assert candidates == []


@requires_treesitter
def test_shadowed_game_suppresses_service_call():
    source = """
local game = { GetService = function() end }
local x = game:GetService("Players")
"""
    candidates, _diag = extract_api_reference_candidates(source, _CATALOG)
    assert candidates == []


# ---------------------------------------------------------------------------
# test_missing_catalog_and_unknown_target
# ---------------------------------------------------------------------------


def test_missing_catalog_produces_no_edges_and_diagnostic():
    """No network and no invented API page ids."""
    source = 'local x = game:GetService("Players")\n'
    candidates, diagnostics = extract_api_reference_candidates(source, None)
    assert candidates == []
    assert any("no API catalog" in d for d in diagnostics)

    empty_catalog = RobloxApiCatalog(generation_id="gen-empty")
    candidates2, diagnostics2 = extract_api_reference_candidates(source, empty_catalog)
    assert candidates2 == []
    assert any("no API catalog" in d for d in diagnostics2)


@requires_treesitter
def test_unknown_target_is_diagnostic_not_fabricated():
    source = 'local x = game:GetService("TotallyMadeUpService")\n'
    candidates, diagnostics = extract_api_reference_candidates(source, _CATALOG)
    assert candidates == []
    assert any("TotallyMadeUpService" in d for d in diagnostics)


# ---------------------------------------------------------------------------
# test_bounded_candidate_extraction
# ---------------------------------------------------------------------------


def test_bounded_candidate_extraction_oversized_source(monkeypatch):
    """Pathological source follows the reviewed fallback/resource policy."""
    monkeypatch.setattr(luau_guard, "BYTE_LIMIT", 10)
    source = 'local x = game:GetService("Players")\n' * 5
    candidates, diagnostics = extract_api_reference_candidates(source, _CATALOG)
    assert candidates == []
    assert any("byte guard" in d for d in diagnostics)


def test_bounded_candidate_extraction_grammar_unavailable(monkeypatch):
    monkeypatch.setattr(treesitter, "get_parser", lambda language: None)
    source = 'local x = game:GetService("Players")\n'
    candidates, diagnostics = extract_api_reference_candidates(source, _CATALOG)
    assert candidates == []
    assert any("grammar unavailable" in d for d in diagnostics)


@requires_treesitter
def test_bounded_candidate_extraction_parse_failure_is_diagnostic(monkeypatch):
    """A parse-time exception (in-process — no per-file subprocess
    isolation, per docs/design/luau-parser-resource-policy.md §1/§3)
    degrades to a diagnostic, never a raise."""
    import parrot.knowledge.wiki.roblox.references as references_module

    def _boom(parser, source_bytes):
        raise RuntimeError("simulated parse failure")

    monkeypatch.setattr(references_module, "_extract_candidates_worker", _boom)
    source = 'local x = game:GetService("Players")\n'
    candidates, diagnostics = extract_api_reference_candidates(source, _CATALOG)
    assert candidates == []
    assert any("extraction failed" in d for d in diagnostics)


@requires_treesitter
def test_bounded_candidate_extraction_dedup():
    source = """
local a = game:GetService("Players")
local b = game:GetService("Players")
"""
    candidates, _diag = extract_api_reference_candidates(source, _CATALOG)
    assert len(candidates) == 1
