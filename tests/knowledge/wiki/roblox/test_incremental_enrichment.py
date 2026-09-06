"""Build/refresh/remove/failure lifecycle tests (FEAT-532 TASK-2909).

Deliberately SYNCHRONOUS test functions: ``CliRunner.invoke()`` drives
``wikitoolkit`` commands that call ``asyncio.run()`` internally
(``cli.py``'s ``_run()`` helper) — invoking that from inside an
``async def`` test (this repo's ``asyncio_mode = auto``) would raise
"asyncio.run() cannot be called from a running event loop". Async store
reads/setup use the small ``_aio()`` helper instead.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner
from parrot.knowledge.wiki import cli as cli_module
from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.languages import treesitter
from parrot.knowledge.wiki.roblox import enrichment_state as roblox_enrichment_state
from parrot.knowledge.wiki.roblox import generations as roblox_generations
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord, create_wiki_store

pytestmark = pytest.mark.skipif(treesitter.get_parser("luau") is None, reason="tree-sitter-luau not installed")


def _aio(coro: Any) -> Any:
    return asyncio.run(coro)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def isolated_parrot_home(tmp_path: Path, monkeypatch):
    home = tmp_path / "_parrot_home"
    monkeypatch.setenv("PARROT_HOME", str(home))
    return home


def _write(base: Path, rel: str, content: str) -> None:
    full = base / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")


def _sourcemap(instance_name: str = "Main") -> dict:
    return {
        "className": "DataModel",
        "filePaths": [],
        "children": [
            {
                "name": "ServerScriptService",
                "className": "ServerScriptService",
                "filePaths": [],
                "children": [
                    {
                        "name": instance_name,
                        "className": "Script",
                        "filePaths": ["src/Main.luau"],
                        "children": [],
                    }
                ],
            }
        ],
    }


def _make_repo(tmp_path: Path, *, instance_name: str = "Main") -> Path:
    repo = tmp_path / "repo"
    _write(repo, "src/Main.luau", 'local Players = game:GetService("Players")\nreturn {}\n')
    _write(repo, "sourcemap.json", json.dumps(_sourcemap(instance_name)))
    _write(repo, "README.md", "# Demo\n")
    return repo


async def _publish_fake_generation_async(
    class_names: list[str], generation_id: str, enum_names: list[str] = ()
) -> None:
    gen_dir = roblox_generations.generation_dir_for(generation_id)
    store = create_wiki_store(gen_dir, wiki_name="roblox-api", backend="sqlite")
    pages = [
        WikiPageRecord(
            concept_id=f"class/{name}",
            title=name,
            category="roblox-class",
            summary=f"{name} class",
            body=f"# {name}",
        )
        for name in class_names
    ]
    # Enum pages carry a "<Name> (Enum)" display title (render.py's
    # `_render_enum_body` convention) — mirrored here deliberately so a
    # reload-from-published-generation regression (a catalog keyed by
    # `title` instead of the raw name derived from `concept_id`) is
    # actually exercised by the build pipeline, not just unit-tested in
    # isolation.
    pages.extend(
        WikiPageRecord(
            concept_id=f"enum/{name}",
            title=f"{name} (Enum)",
            category="roblox-enum",
            summary=f"{name} enum",
            body=f"# {name} (Enum)",
        )
        for name in enum_names
    )
    await store.upsert_pages(pages)
    manifest = {
        "studio_version": "0.1.0",
        "creator_docs_commit": "a" * 40,
        "renderer_schema_version": 1,
        "downloaded_at": "2026-01-01T00:00:00+00:00",
        "class_count": len(class_names),
        "enum_count": len(enum_names),
        "structural_only_count": 0,
    }
    pointer = roblox_generations.ActivePointer(generation_id, manifest)
    current = roblox_generations.read_active_pointer()
    expected_current_id = current.generation_id if current is not None else None
    assert roblox_generations.publish_generation_cas(expected_current_id, pointer) is True


def _publish_fake_generation(
    class_names: list[str], generation_id: str = "gen-test", enum_names: list[str] = ()
) -> None:
    _aio(_publish_fake_generation_async(class_names, generation_id, enum_names))


def _db_path(repo: Path) -> Path:
    return repo / ".parrot" / "wiki" / "wiki.db"


def _dump_edges(repo: Path) -> set[tuple[str, str, str]]:
    store = SQLiteWikiStore(_db_path(repo), read_only=True)
    rows = _aio(store.dump_edges())
    return {(r["src"], r["dst"], r["rel"]) for r in rows}


def _dump_pages(repo: Path) -> dict[str, str | None]:
    store = SQLiteWikiStore(_db_path(repo), read_only=True)
    rows = _aio(store.dump_pages())
    return {r["concept_id"]: r.get("body") for r in rows}


def _get_page(repo: Path, concept_id: str) -> dict | None:
    store = SQLiteWikiStore(_db_path(repo), read_only=True)
    return _aio(store.get_page(concept_id))


def _build(runner: CliRunner, repo: Path, *extra: str):
    return runner.invoke(wiki, ["build", "--path", str(repo), "--no-git", "--no-export", "--no-graph", "-q", *extra])


# ---------------------------------------------------------------------------
# test_fresh_and_incremental_have_identical_edges
# ---------------------------------------------------------------------------


def test_fresh_and_incremental_have_identical_edges(runner, isolated_parrot_home):
    repo = _make_repo(isolated_parrot_home.parent)
    _publish_fake_generation(["Players"])

    assert _build(runner, repo).exit_code == 0
    fresh_edges = _dump_edges(repo)
    fresh_pages = _dump_pages(repo)

    # Force a full incremental (non-fresh, per-file replace_source_slice) rebuild.
    assert _build(runner, repo, "--force").exit_code == 0
    incremental_edges = _dump_edges(repo)
    incremental_pages = _dump_pages(repo)

    assert fresh_edges == incremental_edges
    assert fresh_pages == incremental_pages
    assert ("file:src/Main.luau", "roblox::class/Players", "references") in fresh_edges


# ---------------------------------------------------------------------------
# test_catalog_mapping_change_rescans_unchanged_luau
# ---------------------------------------------------------------------------


def test_catalog_mapping_change_rescans_unchanged_luau(runner, isolated_parrot_home):
    repo = _make_repo(isolated_parrot_home.parent, instance_name="Main")
    _publish_fake_generation(["Players"])

    assert _build(runner, repo).exit_code == 0
    page = _get_page(repo, "file:src/Main.luau")
    assert "game.ServerScriptService.Main" in page["body"]

    # Change the MAPPING only — source bytes/mtime untouched.
    _write(repo, "sourcemap.json", json.dumps(_sourcemap(instance_name="RenamedMain")))

    result = _build(runner, repo)  # NOTE: no --force
    assert result.exit_code == 0, result.output

    page2 = _get_page(repo, "file:src/Main.luau")
    assert "game.ServerScriptService.RenamedMain" in page2["body"]


# ---------------------------------------------------------------------------
# test_partial_build_detects_context_change
# ---------------------------------------------------------------------------


def test_partial_build_detects_context_change(runner, isolated_parrot_home):
    repo = isolated_parrot_home.parent / "repo"
    _write(repo, "src/A.luau", 'local Players = game:GetService("Players")\nreturn {}\n')
    _write(repo, "src/B.luau", 'local Players = game:GetService("Players")\nreturn {}\n')
    _write(repo, "README.md", "# Demo\n")
    _publish_fake_generation(["Players"], generation_id="gen-1")

    assert _build(runner, repo).exit_code == 0
    storage_dir = repo / ".parrot" / "wiki"
    state_after_build = roblox_enrichment_state.load_state(storage_dir)
    assert "src/A.luau" in state_after_build
    assert "src/B.luau" in state_after_build

    # Publish a NEW generation (context change) but only re-upsert A.
    _publish_fake_generation(["Players", "Workspace"], generation_id="gen-2")
    result = runner.invoke(wiki, ["upsert", "src/A.luau", "--path", str(repo)])
    assert result.exit_code == 0, result.output

    state_after_partial = roblox_enrichment_state.load_state(storage_dir)
    # A's fingerprint advanced to the new context digest.
    assert state_after_partial["src/A.luau"] != state_after_build["src/A.luau"]
    # B was never touched by this partial upsert — its OLD fingerprint is
    # still recorded (never incorrectly marked "up to date" for gen-2),
    # so a future build/upsert covering B will still detect the change.
    assert state_after_partial["src/B.luau"] == state_after_build["src/B.luau"]


# ---------------------------------------------------------------------------
# test_removed_use_and_file_prune_edges
# ---------------------------------------------------------------------------


def test_removed_use_and_file_prune_edges(runner, isolated_parrot_home):
    repo = _make_repo(isolated_parrot_home.parent)
    _write(repo, "src/Other.luau", 'local Players = game:GetService("Players")\nreturn {}\n')
    _publish_fake_generation(["Players"])
    assert _build(runner, repo).exit_code == 0

    edges = _dump_edges(repo)
    assert ("file:src/Main.luau", "roblox::class/Players", "references") in edges
    assert ("file:src/Other.luau", "roblox::class/Players", "references") in edges

    # Remove the API use from Main.luau (but keep the file).
    _write(repo, "src/Main.luau", "return {}\n")
    assert _build(runner, repo).exit_code == 0

    edges2 = _dump_edges(repo)
    assert ("file:src/Main.luau", "roblox::class/Players", "references") not in edges2
    # Other.luau's edge (an unrelated source) is preserved.
    assert ("file:src/Other.luau", "roblox::class/Players", "references") in edges2

    # Now delete Other.luau entirely.
    (repo / "src" / "Other.luau").unlink()
    assert _build(runner, repo).exit_code == 0

    edges3 = _dump_edges(repo)
    assert not any(src == "file:src/Other.luau" for src, _dst, _rel in edges3)
    assert _get_page(repo, "file:src/Other.luau") is None


# ---------------------------------------------------------------------------
# test_failed_write_does_not_advance_digest
# ---------------------------------------------------------------------------


def test_failed_write_does_not_advance_digest(runner, isolated_parrot_home, monkeypatch):
    repo = _make_repo(isolated_parrot_home.parent)
    _publish_fake_generation(["Players"])

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated persistence failure")

    monkeypatch.setattr(cli_module, "_ingest_files", _boom)

    result = _build(runner, repo)
    assert result.exit_code != 0

    storage_dir = repo / ".parrot" / "wiki"
    state = roblox_enrichment_state.load_state(storage_dir)
    assert state == {}  # never recorded — _record_roblox_enrichment_success was never reached

    monkeypatch.undo()
    retry = _build(runner, repo)
    assert retry.exit_code == 0, retry.output
    state_after_retry = roblox_enrichment_state.load_state(storage_dir)
    assert "src/Main.luau" in state_after_retry


# ---------------------------------------------------------------------------
# test_enum_reference_resolves_after_catalog_reload (code-review regression)
# ---------------------------------------------------------------------------


def test_enum_reference_resolves_after_catalog_reload(runner, isolated_parrot_home):
    """An Enum reference resolves through the FULL published-generation
    reload path (``cli.py``'s ``_load_active_roblox_catalog``), not just
    the in-memory catalog a fresh render produces.

    Regression coverage for a code-review finding: the reloaded catalog
    was once keyed by page ``title`` (``"Material (Enum)"``) rather than
    the raw name derived from ``concept_id`` (``"Material"``), which
    silently broke every enum reference the moment a repo was built
    against an *already-published* generation — the ordinary case for
    every build after the first ``ingest roblox-api --refresh``.
    """
    repo = isolated_parrot_home.parent / "repo"
    _write(repo, "src/Main.luau", "local m: Material\nreturn {}\n")
    _write(repo, "README.md", "# Demo\n")
    _publish_fake_generation(["Players"], enum_names=["Material"])

    assert _build(runner, repo).exit_code == 0

    edges = _dump_edges(repo)
    assert ("file:src/Main.luau", "roblox::enum/Material", "references") in edges


# ---------------------------------------------------------------------------
# test_non_luau_manifest_and_symbols_unchanged
# ---------------------------------------------------------------------------


def test_non_luau_manifest_and_symbols_unchanged(runner, isolated_parrot_home, monkeypatch):
    """Existing batching/hash/structural behavior stays intact — a
    plain Python-only project never even imports the roblox package."""
    repo = isolated_parrot_home.parent / "repo"
    _write(
        repo,
        "pkg/mod.py",
        '"""A module."""\n\n\ndef helper() -> int:\n    """Doc."""\n    return 1\n',
    )
    _write(repo, "README.md", "# Demo\n")

    monkeypatch.setitem(sys.modules, "parrot.knowledge.wiki.roblox.enrichment", None)
    monkeypatch.setitem(sys.modules, "parrot.knowledge.wiki.roblox.project", None)
    monkeypatch.setitem(sys.modules, "parrot.knowledge.wiki.roblox.ingest", None)

    result = _build(runner, repo)
    assert result.exit_code == 0, result.output

    page = _get_page(repo, "file:pkg/mod.py")
    assert page is not None
    assert "helper" in (page.get("body") or "")
