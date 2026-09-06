"""Tests for the shared Roblox scan/API generation models (FEAT-532 TASK-2897).

These models are proposed contracts consumed by later tasks (mapping
resolution, API acquisition/render/publication, enrichment) — this test
module only validates the models themselves: serialization round-trips,
one-to-many association fidelity, and validation rejection. It does not
exercise any acquisition/rendering behavior (none exists yet).
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest
from pydantic import ValidationError


def test_package_import_is_inert():
    """No acquisition, parser construction or filesystem mutation on import.

    Runs in a **fresh subprocess**, not the pytest process: the pytest
    session's own conftest already imports ``parrot.clients`` (and
    transitively ``aiohttp``) for unrelated reasons, so checking
    ``sys.modules`` in-process would always see ``aiohttp`` loaded
    regardless of what ``roblox/__init__.py`` itself does. A clean
    interpreter isolates "does importing this package pull these modules
    in" from "were they already loaded by something else".
    """
    src_root = None
    for path in sys.path:
        if path.endswith("packages/ai-parrot/src"):
            src_root = path
            break
    assert src_root, "packages/ai-parrot/src not found on sys.path"

    script = textwrap.dedent("""
        import sys
        import parrot.knowledge.wiki.roblox  # noqa: F401
        import parrot.knowledge.wiki.roblox.models  # noqa: F401

        forbidden = {"aiohttp", "tree_sitter", "tree_sitter_luau"}
        loaded = forbidden & set(sys.modules)
        assert not loaded, f"import pulled in forbidden modules: {loaded}"
        print("OK")
        """)
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=src_root,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


def test_manifest_roundtrip():
    from parrot.knowledge.wiki.roblox.models import RobloxApiManifest

    manifest = RobloxApiManifest(
        studio_version="0.123.0.456789",
        creator_docs_commit="a" * 40,
        renderer_schema_version=1,
        source_hashes={"api_dump": "deadbeef", "creator_docs_tarball": "cafef00d"},
        downloaded_at="2026-09-06T00:00:00+00:00",
        class_count=625,
        enum_count=120,
        structural_only_count=3,
        missing_doc_classes=["SomeInternalClass"],
        skipped=["Enum.Foo references unresolved class Bar"],
    )

    dumped = manifest.model_dump_json()
    restored = RobloxApiManifest.model_validate_json(dumped)

    assert restored == manifest
    # All provenance survives: every field, not a lossy subset.
    assert restored.studio_version == manifest.studio_version
    assert restored.creator_docs_commit == manifest.creator_docs_commit
    assert restored.source_hashes == manifest.source_hashes
    assert restored.missing_doc_classes == manifest.missing_doc_classes
    assert restored.skipped == manifest.skipped


def test_ingest_result_roundtrip_preserves_manifest():
    from parrot.knowledge.wiki.roblox.models import RobloxApiIngestResult, RobloxApiManifest

    manifest = RobloxApiManifest(
        studio_version="0.123.0.456789",
        creator_docs_commit="b" * 40,
        renderer_schema_version=2,
        downloaded_at="2026-09-06T00:00:00+00:00",
        class_count=1,
        enum_count=0,
        structural_only_count=0,
    )
    result = RobloxApiIngestResult(
        generation_dir="/home/user/.parrot/roblox/gen-20260906",
        manifest=manifest,
        reused=False,
        published=True,
        diagnostics=["fresh generation published"],
    )

    restored = RobloxApiIngestResult.model_validate_json(result.model_dump_json())
    assert restored == result
    assert restored.manifest == manifest


def test_instance_mapping_preserves_ambiguity():
    """Multiple instance/file associations survive without arbitrary collapse."""
    from parrot.knowledge.wiki.roblox.models import RobloxInstanceIndex

    index = RobloxInstanceIndex(
        file_to_instances={
            "src/Shared/Utils.luau": [
                "game.ReplicatedStorage.Utils",
                "game.ServerScriptService.Utils",
            ],
        },
        instance_to_files={
            "game.ReplicatedStorage.Utils": ["src/Shared/Utils.luau"],
            "game.ServerScriptService.Utils": ["src/Shared/Utils.luau"],
        },
        class_names={
            "game.ReplicatedStorage.Utils": "ModuleScript",
            "game.ServerScriptService.Utils": "ModuleScript",
        },
        source_kind="sourcemap",
        mapping_digest="abc123",
    )

    # Both instance paths for the shared file remain, not collapsed to one.
    assert index.file_to_instances["src/Shared/Utils.luau"] == [
        "game.ReplicatedStorage.Utils",
        "game.ServerScriptService.Utils",
    ]
    restored = RobloxInstanceIndex.model_validate_json(index.model_dump_json())
    assert restored == index


def test_instance_index_rejects_unknown_source_kind():
    from parrot.knowledge.wiki.roblox.models import RobloxInstanceIndex

    with pytest.raises(ValidationError):
        RobloxInstanceIndex(source_kind="rojo-binary")


def test_invalid_identity_is_rejected():
    """Invalid required identifiers/negative counts fail validation."""
    from parrot.knowledge.wiki.roblox.models import RobloxApiCatalog, RobloxApiManifest

    with pytest.raises(ValidationError):
        RobloxApiManifest(
            studio_version="",  # empty identity
            creator_docs_commit="a" * 40,
            renderer_schema_version=1,
            downloaded_at="2026-09-06T00:00:00+00:00",
            class_count=1,
            enum_count=0,
            structural_only_count=0,
        )

    with pytest.raises(ValidationError):
        RobloxApiManifest(
            studio_version="0.1.0",
            creator_docs_commit="not-a-sha",  # invalid hex
            renderer_schema_version=1,
            downloaded_at="2026-09-06T00:00:00+00:00",
            class_count=1,
            enum_count=0,
            structural_only_count=0,
        )

    with pytest.raises(ValidationError):
        RobloxApiManifest(
            studio_version="0.1.0",
            creator_docs_commit="a" * 40,
            renderer_schema_version=1,
            downloaded_at="2026-09-06T00:00:00+00:00",
            class_count=-1,  # negative count
            enum_count=0,
            structural_only_count=0,
        )

    with pytest.raises(ValidationError):
        RobloxApiCatalog(generation_id="")  # empty identity


def test_api_class_and_enum_page_ids_are_unqualified():
    from parrot.knowledge.wiki.roblox.models import RobloxApiCatalog, class_page_id, enum_page_id

    assert class_page_id("Players") == "class/Players"
    assert enum_page_id("Material") == "enum/Material"

    catalog = RobloxApiCatalog(
        generation_id="gen-1",
        classes={"Players": "class/Players"},
        enums={"Material": "enum/Material"},
    )
    assert catalog.page_id_for_class("Players") == "class/Players"
    assert catalog.page_id_for_class("Unknown") is None
    assert catalog.page_id_for_enum("Material") == "enum/Material"


def test_normalized_api_dump_roundtrip():
    from parrot.knowledge.wiki.roblox.models import (
        NormalizedApiDump,
        RobloxApiClass,
        RobloxApiEnum,
        RobloxApiEnumItem,
        RobloxApiMember,
        RobloxApiParameter,
    )

    dump = NormalizedApiDump(
        classes=[
            RobloxApiClass(
                name="Players",
                superclass="Instance",
                members=[
                    RobloxApiMember(
                        name="GetPlayers",
                        member_type="Function",
                        parameters=[],
                        return_type="Array<Player>",
                        security="None",
                        thread_safety="Safe",
                    ),
                    RobloxApiMember(
                        name="PlayerAdded",
                        member_type="Event",
                        parameters=[RobloxApiParameter(name="player", type="Player")],
                    ),
                ],
                description="A service to interact with the players in a game.",
                doc_url="https://create.roblox.com/docs/reference/engine/classes/Players",
            )
        ],
        enums=[
            RobloxApiEnum(
                name="Material",
                items=[RobloxApiEnumItem(name="Plastic", value=256)],
                description=None,
            )
        ],
    )
    restored = NormalizedApiDump.model_validate_json(dump.model_dump_json())
    assert restored == dump


def test_reference_candidate_rejects_invalid_span():
    from parrot.knowledge.wiki.roblox.models import RobloxApiReferenceCandidate, RobloxReferenceExtractionKind

    with pytest.raises(ValidationError):
        RobloxApiReferenceCandidate(
            source_span=(10, 5),  # end before start
            recognized_root="workspace",
            extraction_kind=RobloxReferenceExtractionKind.CHAINED_ACCESS,
            target_name="Terrain",
        )

    candidate = RobloxApiReferenceCandidate(
        source_span=(5, 10),
        recognized_root="workspace",
        extraction_kind=RobloxReferenceExtractionKind.CHAINED_ACCESS,
        target_name="Terrain",
    )
    assert candidate.source_span == (5, 10)


def test_file_enrichment_roundtrip_with_candidates():
    from parrot.knowledge.wiki.roblox.models import (
        RobloxApiReferenceCandidate,
        RobloxFileEnrichment,
        RobloxReferenceExtractionKind,
    )

    enrichment = RobloxFileEnrichment(
        rel_path="src/Main.server.luau",
        datamodel_section="DataModel path: `game.ServerScriptService.Main` (Script)",
        reference_candidates=[
            RobloxApiReferenceCandidate(
                source_span=(0, 10),
                recognized_root="game",
                extraction_kind=RobloxReferenceExtractionKind.SERVICE_CALL,
                target_name="Players",
            )
        ],
        dependency_digest="sha256:deadbeef",
        diagnostics=[],
    )
    restored = RobloxFileEnrichment.model_validate_json(enrichment.model_dump_json())
    assert restored == enrichment


def test_file_enrichment_rejects_empty_rel_path():
    from parrot.knowledge.wiki.roblox.models import RobloxFileEnrichment

    with pytest.raises(ValidationError):
        RobloxFileEnrichment(rel_path="")
