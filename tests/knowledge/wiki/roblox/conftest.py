"""Small authored multi-plane fixtures and network traps (FEAT-532 TASK-2910).

Shared by ``test_end_to_end.py`` — never a downloaded API dump, never a
vendored creator-docs archive: every fixture is hand-authored and tiny,
matching the spec's fixture rule ("never commit an upstream dump").
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner
from parrot.knowledge.wiki.roblox import generations as roblox_generations
from parrot.knowledge.wiki.store import WikiPageRecord, create_wiki_store


def aio(coro: Any) -> Any:
    """Run one async call from a synchronous test (mirrors cli.py's own
    ``_run`` — CliRunner.invoke() already drives its own asyncio.run(),
    so every test here stays a plain ``def``, never ``async def``)."""
    return asyncio.run(coro)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def isolated_parrot_home(tmp_path: Path, monkeypatch):
    """Route the machine-wide Roblox API plane into this test's own tmp_path."""
    home = tmp_path / "_parrot_home"
    monkeypatch.setenv("PARROT_HOME", str(home))
    return home


@pytest.fixture
def no_network(monkeypatch):
    """Trap any attempt to open a real aiohttp session for the duration
    of a test — the network trap the spec's fixture rule requires."""
    import aiohttp

    def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("no network access is allowed in this end-to-end test")

    monkeypatch.setattr(aiohttp, "ClientSession", _boom)


def write_file(base: Path, rel: str, content: str) -> None:
    full = base / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")


def sourcemap(instance_name: str = "Main") -> dict:
    """A tiny, hand-authored Rojo sourcemap mapping ``src/Main.luau``."""
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


@pytest.fixture
def mixed_repo(tmp_path: Path) -> Path:
    """A tiny mixed-language Roblox project: one Luau file referencing
    the API, plus one Python file — never a single-language repo, so
    polyglot regressions surface here too."""
    repo = tmp_path / "repo"
    write_file(repo, "src/Main.luau", 'local Players = game:GetService("Players")\nreturn {}\n')
    write_file(repo, "sourcemap.json", json.dumps(sourcemap()))
    write_file(
        repo,
        "pkg/app.py",
        '"""App entrypoint."""\n\n\ndef main() -> None:\n    """Run the app."""\n    return None\n',
    )
    write_file(repo, "README.md", "# Demo Roblox project\n")
    return repo


async def _publish_generation_async(class_names: list[str], generation_id: str, enum_names: list[str] = ()) -> None:
    gen_dir = roblox_generations.generation_dir_for(generation_id)
    store = create_wiki_store(gen_dir, wiki_name="roblox-api", backend="sqlite")
    pages = [
        WikiPageRecord(
            concept_id=f"class/{name}",
            title=name,
            category="roblox-class",
            summary=f"The {name} class.",
            body=f"# {name}\n\nThe {name} API class.",
        )
        for name in class_names
    ]
    # Enum pages render with a display title of "<Name> (Enum)" (render.py's
    # `_render_enum_body` convention) — deliberately mirrored here so any
    # regression that keys a reloaded catalog by page title instead of the
    # raw name (concept_id's `enum/<Name>` suffix) is caught by a test
    # publishing through the exact same page shape production code writes.
    pages.extend(
        WikiPageRecord(
            concept_id=f"enum/{name}",
            title=f"{name} (Enum)",
            category="roblox-enum",
            summary=f"The {name} enum.",
            body=f"# {name} (Enum)\n\nThe {name} API enum.",
        )
        for name in enum_names
    )
    await store.upsert_pages(pages)
    manifest = {
        "studio_version": "0.123.0.456789",
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


@pytest.fixture
def publish_roblox_generation():
    """``publish_roblox_generation(["Players", "Workspace"], enum_names=["Material"])``
    — publishes a tiny, hand-authored generation with the given class/enum
    names, entirely offline (real temporary SQLite planes, no acquisition
    code invoked)."""

    def _publish(class_names: list[str], generation_id: str = "gen-e2e", enum_names: list[str] = ()) -> None:
        aio(_publish_generation_async(class_names, generation_id, enum_names))

    return _publish
