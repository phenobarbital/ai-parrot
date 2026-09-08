"""Offline scan result and isolation tests (FEAT-532 TASK-2907)."""

from __future__ import annotations

from pathlib import Path

import pytest
from parrot.knowledge.wiki.languages import treesitter
from parrot.knowledge.wiki.repo_scan import FileSlice, RepoScan, file_concept_id
from parrot.knowledge.wiki.roblox.enrichment import enrich_repo_scan
from parrot.knowledge.wiki.roblox.models import RobloxApiCatalog, RobloxInstanceIndex
from parrot.knowledge.wiki.store import WikiPageRecord, estimate_tokens

pytestmark = pytest.mark.skipif(treesitter.get_parser("luau") is None, reason="tree-sitter-luau not installed")

_CATALOG = RobloxApiCatalog(
    generation_id="gen-1",
    classes={"Players": "class/Players"},
    enums={},
)


def _write(tmp_path: Path, rel: str, content: str) -> None:
    full = tmp_path / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")


def _luau_file_slice(rel_path: str, body: str = "") -> FileSlice:
    record = WikiPageRecord(
        concept_id=file_concept_id(rel_path),
        node_id=rel_path,
        title=rel_path,
        category="module",
        summary="a luau module",
        body=body or f"# {rel_path}\n\n## Content\nplaceholder",
        token_count=estimate_tokens(body or "placeholder"),
    )
    return FileSlice(rel_path=rel_path, record=record, imports=[], language="luau")


def _python_file_slice(rel_path: str) -> FileSlice:
    record = WikiPageRecord(
        concept_id=file_concept_id(rel_path),
        node_id=rel_path,
        title=rel_path,
        category="module",
        summary="a python module",
        body=f"# {rel_path}\n\n## Content\nprint('hi')",
        token_count=estimate_tokens("print('hi')"),
    )
    return FileSlice(rel_path=rel_path, record=record, imports=[], language="python")


# ---------------------------------------------------------------------------
# test_file_identity_and_datamodel_body
# ---------------------------------------------------------------------------


def test_file_identity_and_datamodel_body(tmp_path: Path):
    """File identity remains stable and multiple DataModel mappings
    render deterministically."""
    _write(tmp_path, "src/Shared/Utils.luau", "return {}\n")
    slice_ = _luau_file_slice("src/Shared/Utils.luau")
    scan = RepoScan(root=tmp_path, files=[slice_])

    index = RobloxInstanceIndex(
        file_to_instances={
            "src/Shared/Utils.luau": [
                "game.ReplicatedStorage.Utils",
                "game.ServerScriptService.Utils",
            ]
        },
        instance_to_files={},
        class_names={
            "game.ReplicatedStorage.Utils": "ModuleScript",
            "game.ServerScriptService.Utils": "ModuleScript",
        },
        source_kind="sourcemap",
        mapping_digest="abc123",
    )

    enriched_scan, enrichment_by_path = enrich_repo_scan(scan, instance_index=index, catalog=None)

    enriched_file = enriched_scan.files[0]
    assert enriched_file.rel_path == "src/Shared/Utils.luau"
    assert enriched_file.record.concept_id == slice_.record.concept_id  # identity stable

    body = enriched_file.record.body
    idx_replicated = body.index("game.ReplicatedStorage.Utils")
    idx_server = body.index("game.ServerScriptService.Utils")
    assert idx_replicated < idx_server  # deterministic (sorted) order
    assert "(ModuleScript)" in body

    record = enrichment_by_path["src/Shared/Utils.luau"]
    assert "game.ReplicatedStorage.Utils" in record.datamodel_section
    assert record.diagnostics == ["no API catalog available, skipped API linking"]


# ---------------------------------------------------------------------------
# test_external_edges_separate_from_imports
# ---------------------------------------------------------------------------


def test_external_edges_separate_from_imports(tmp_path: Path):
    """External references never enter file: wrapping or structural resolver."""
    _write(tmp_path, "src/Main.luau", 'local p = game:GetService("Players")\n')
    slice_ = _luau_file_slice("src/Main.luau")
    slice_ = slice_.model_copy(update={"imports": ["script.Parent.Helper"]})
    scan = RepoScan(root=tmp_path, files=[slice_])

    enriched_scan, enrichment_by_path = enrich_repo_scan(scan, instance_index=None, catalog=_CATALOG)

    enriched_file = enriched_scan.files[0]
    assert enriched_file.imports == ["script.Parent.Helper"]  # untouched
    assert len(enriched_file.external_edges) == 1
    src, dst, rel = enriched_file.external_edges[0]
    assert src == file_concept_id("src/Main.luau")
    assert dst == "roblox::class/Players"
    assert rel == "references"
    assert not dst.startswith("file:")  # never wrapped like a local import target

    record = enrichment_by_path["src/Main.luau"]
    assert len(record.reference_candidates) == 1
    assert record.reference_candidates[0].target_name == "Players"


# ---------------------------------------------------------------------------
# test_dependency_digest_changes
# ---------------------------------------------------------------------------


def test_dependency_digest_changes(tmp_path: Path):
    """Mapping/catalog/namespace changes alter enrichment identity even
    with unchanged source bytes."""
    _write(tmp_path, "src/Main.luau", "return {}\n")
    slice_ = _luau_file_slice("src/Main.luau")
    scan = RepoScan(root=tmp_path, files=[slice_])

    index_a = RobloxInstanceIndex(source_kind="sourcemap", mapping_digest="digest-a")
    index_b = RobloxInstanceIndex(source_kind="sourcemap", mapping_digest="digest-b")
    catalog_a = RobloxApiCatalog(generation_id="gen-a")
    catalog_b = RobloxApiCatalog(generation_id="gen-b")

    _, base = enrich_repo_scan(
        scan, instance_index=index_a, catalog=catalog_a, namespace="roblox", renderer_schema_version=1
    )
    _, mapping_changed = enrich_repo_scan(
        scan, instance_index=index_b, catalog=catalog_a, namespace="roblox", renderer_schema_version=1
    )
    _, catalog_changed = enrich_repo_scan(
        scan, instance_index=index_a, catalog=catalog_b, namespace="roblox", renderer_schema_version=1
    )
    _, schema_changed = enrich_repo_scan(
        scan, instance_index=index_a, catalog=catalog_a, namespace="roblox", renderer_schema_version=2
    )
    _, namespace_changed = enrich_repo_scan(
        scan, instance_index=index_a, catalog=catalog_a, namespace="other", renderer_schema_version=1
    )

    base_digest = base["src/Main.luau"].dependency_digest
    assert base_digest != mapping_changed["src/Main.luau"].dependency_digest
    assert base_digest != catalog_changed["src/Main.luau"].dependency_digest
    assert base_digest != schema_changed["src/Main.luau"].dependency_digest
    assert base_digest != namespace_changed["src/Main.luau"].dependency_digest


# ---------------------------------------------------------------------------
# test_partial_scan_and_polyglot
# ---------------------------------------------------------------------------


def test_partial_scan_and_polyglot(tmp_path: Path):
    """Partial targets resolve through full mapping and non-Luau behavior remains unchanged."""
    _write(tmp_path, "src/Main.luau", 'local p = game:GetService("Players")\n')
    _write(tmp_path, "src/app.py", "print('hi')\n")

    luau_slice = _luau_file_slice("src/Main.luau")
    python_slice = _python_file_slice("src/app.py")
    scan = RepoScan(root=tmp_path, files=[luau_slice, python_slice])

    # The mapping only covers files elsewhere in the (full) project —
    # this file's own mapping is resolved through the FULL index, not a
    # per-file re-derivation, even on a partial re-scan of just this file.
    full_index = RobloxInstanceIndex(
        file_to_instances={"src/Main.luau": ["game.ServerScriptService.Main"]},
        class_names={"game.ServerScriptService.Main": "Script"},
        source_kind="sourcemap",
        mapping_digest="full-index-digest",
    )

    enriched_scan, enrichment_by_path = enrich_repo_scan(scan, instance_index=full_index, catalog=_CATALOG)

    luau_result = next(f for f in enriched_scan.files if f.rel_path == "src/Main.luau")
    python_result = next(f for f in enriched_scan.files if f.rel_path == "src/app.py")

    assert "game.ServerScriptService.Main" in luau_result.record.body
    assert luau_result.external_edges  # API reference resolved

    # Non-Luau file is returned byte-for-byte identical.
    assert python_result == python_slice
    assert "src/app.py" not in enrichment_by_path


# ---------------------------------------------------------------------------
# test_missing_context_degrades_offline
# ---------------------------------------------------------------------------


def test_missing_context_degrades_offline(tmp_path: Path):
    """Missing plane yields local pages and clear skipped-linking diagnostics."""
    _write(tmp_path, "src/Main.luau", 'local p = game:GetService("Players")\n')
    slice_ = _luau_file_slice("src/Main.luau")
    scan = RepoScan(root=tmp_path, files=[slice_])

    enriched_scan, enrichment_by_path = enrich_repo_scan(scan, instance_index=None, catalog=None)

    enriched_file = enriched_scan.files[0]
    # The local page still builds fully — same body/identity, no crash.
    assert enriched_file.record.concept_id == slice_.record.concept_id
    assert enriched_file.external_edges == []

    record = enrichment_by_path["src/Main.luau"]
    assert record.datamodel_section == ""
    assert record.reference_candidates == []
    assert "no DataModel mapping available" in record.diagnostics
    assert "no API catalog available, skipped API linking" in record.diagnostics


def test_missing_context_never_touches_network(tmp_path: Path, monkeypatch):
    """No HTTP, LLM use, or external tool invocation — pure offline computation."""
    import aiohttp

    def _boom(*_args, **_kwargs):
        raise AssertionError("no network access is allowed during enrichment")

    monkeypatch.setattr(aiohttp, "ClientSession", _boom)

    _write(tmp_path, "src/Main.luau", "return {}\n")
    slice_ = _luau_file_slice("src/Main.luau")
    scan = RepoScan(root=tmp_path, files=[slice_])

    enrich_repo_scan(scan, instance_index=None, catalog=_CATALOG)  # must not raise
