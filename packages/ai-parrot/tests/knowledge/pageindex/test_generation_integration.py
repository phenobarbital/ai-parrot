"""End-to-end guarantees of FEAT-831 generation publication."""

from __future__ import annotations

import asyncio
import json
import multiprocessing as mp
import os
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from parrot.knowledge.bookstore.config import LibraryLocation
from parrot.knowledge.bookstore.library import Bookstore
from parrot.knowledge.pageindex import PageIndexToolkit, StaleGenerationError
from parrot.knowledge.pageindex.store import JSONTreeStore


async def _ask_structured(_prompt: str, schema: type[Any], **_kwargs: Any) -> Any:
    """Return the legacy fixture node for the retrieve LLM-walk branch."""
    return schema(thinking="", node_list=["0001"])


def _adapter() -> SimpleNamespace:
    """Build the minimal adapter required by ``PageIndexToolkit``."""
    return SimpleNamespace(model="none", client=None, ask_structured=_ask_structured)


def _writer(storage_dir: str, tree: str, count: int) -> None:
    """Append ``count`` nodes from a spawn-safe child process."""

    async def run() -> None:
        toolkit = PageIndexToolkit(adapter=_adapter(), storage_dir=storage_dir)
        for index in range(count):
            try:
                await toolkit.add_node(tree_name=tree, title=f"n{index}")
            except StaleGenerationError as exc:
                raise AssertionError("PageIndexToolkit._mutate exhausted its stale-generation retries") from exc

    asyncio.run(run())


def _file_snapshot(root: Path) -> dict[str, tuple[int, int]]:
    """Return relative file paths mapped to stable metadata."""
    return {
        path.relative_to(root).as_posix(): (path.stat().st_mtime_ns, path.stat().st_size)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_two_processes_one_tree(tmp_path: Path) -> None:
    """Serialize two independent writers without losing either process's nodes."""
    asyncio.run(PageIndexToolkit(adapter=_adapter(), storage_dir=tmp_path).create_tree("t"))
    context = mp.get_context("spawn")
    processes = [context.Process(target=_writer, args=(str(tmp_path), "t", 20)) for _ in range(2)]

    for process in processes:
        process.start()
    for process in processes:
        process.join(60)
        if process.is_alive():
            process.terminate()
            process.join(5)
            pytest.fail(f"writer process {process.pid} did not finish within 60 seconds")
        assert process.exitcode == 0

    toolkit = PageIndexToolkit(adapter=_adapter(), storage_dir=tmp_path)
    tree = asyncio.run(toolkit.get_tree("t"))
    generation = asyncio.run(toolkit.get_generation("t"))

    assert len(tree["structure"]) == 40
    assert generation["id"] == 41


@pytest.mark.asyncio
async def test_bookstore_reindex_keeps_book_readable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep serving a non-empty live section throughout a Bookstore reindex."""
    monkeypatch.setattr("parrot.knowledge.pageindex.utils.count_tokens", lambda text, model="gpt-4o": len(text))
    monkeypatch.setattr("parrot.knowledge.pageindex.md_builder.count_tokens", lambda text, model="gpt-4o": len(text))
    location = LibraryLocation(scope="project", root=tmp_path / "library")
    bookstore = Bookstore([location])
    book_path = tmp_path / "concurrency-handbook.md"
    original = (
        "# Concurrency Handbook\n\n"
        "Readers retain a complete published body while another generation is prepared.\n\n"
        "## Publication\n\n"
        "The JSON switch makes the new generation visible atomically to every reader.\n"
    )
    book_path.write_text(original, encoding="utf-8")
    card, status = await bookstore.add_book(book_path)
    assert status == "added"
    tree = await bookstore._toolkit("project").get_tree(card.tree_name)
    node = next(node for node in tree["structure"] if node.get("body_ref"))
    node_id = node["node_id"]

    book_path.write_text(
        original + "\n## Vacuum\n\nOld unreferenced bodies are removed after the configured grace period.\n",
        encoding="utf-8",
    )
    writer_done = asyncio.Event()
    reads = 0

    async def reindex() -> str:
        try:
            _, update_status = await bookstore.add_book(book_path)
            return update_status
        finally:
            writer_done.set()

    async def read_while_reindexing() -> None:
        nonlocal reads
        while not writer_done.is_set():
            section = bookstore.read_section(card.book_id, node_id)
            assert section["content"]
            reads += 1
            await asyncio.sleep(0)

    update_status, _ = await asyncio.gather(reindex(), read_while_reindexing())

    assert update_status == "updated"
    assert reads > 0
    assert bookstore.read_section(card.book_id, node_id)["content"]


@pytest.mark.asyncio
async def test_crash_between_bodies_and_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Leave the live tree unchanged when JSON publication fails after blob writes."""
    toolkit = PageIndexToolkit(adapter=_adapter(), storage_dir=tmp_path)
    await toolkit.create_tree("t")
    tree_path = tmp_path / "t.json"
    original_tree = tree_path.read_bytes()
    original_save = JSONTreeStore.save

    def fail_json_switch(self: JSONTreeStore, tree_name: str, tree: dict[str, Any]) -> tuple[int, int]:
        raise RuntimeError("simulated crash before JSON switch")

    monkeypatch.setattr(JSONTreeStore, "save", fail_json_switch)
    with pytest.raises(RuntimeError, match="simulated crash"):
        await toolkit.add_node("t", "orphan", body="unpublished body")

    assert tree_path.read_bytes() == original_tree
    orphan_paths = list((tmp_path / "t" / "bodies").glob("*.md"))
    assert len(orphan_paths) == 1

    monkeypatch.setattr(JSONTreeStore, "save", original_save)
    reopened = PageIndexToolkit(adapter=_adapter(), storage_dir=tmp_path)
    assert await reopened.get_tree("t") == json.loads(original_tree)
    # Orphan recovery is an in-process admin path, so it uses the unclamped
    # sweep; the LLM-callable vacuum_tree() would raise max_age_s to the grace
    # floor and leave the orphan for later.
    report = await reopened._vacuum_tree("t", max_age_s=0)

    assert report["removed"] == 1
    assert not orphan_paths[0].exists()


@pytest.mark.asyncio
async def test_legacy_tree_read_only_untouched(tmp_path: Path) -> None:
    """Read, search, and retrieve a legacy tree without writing any file."""
    tree = {
        "doc_name": "legacy",
        "structure": [
            {
                "node_id": "0001",
                "title": "Immutable Legacy Section",
                "summary": "A generation-less section about compatibility.",
                "nodes": [],
            }
        ],
    }
    (tmp_path / "legacy.json").write_text(json.dumps(tree, indent=2), encoding="utf-8")
    sidecar_dir = tmp_path / "legacy"
    sidecar_dir.mkdir()
    (sidecar_dir / "0001.md").write_text("Legacy compatibility body with an immutable quasar.", encoding="utf-8")
    before = _file_snapshot(tmp_path)
    toolkit = PageIndexToolkit(adapter=_adapter(), storage_dir=tmp_path)

    assert await toolkit.get_tree("legacy") == tree
    hits = await toolkit.search("legacy", "immutable quasar", use_llm_walk=False)
    retrieved = await toolkit.retrieve("legacy", "immutable quasar", top_k=1)

    assert hits and hits[0]["node_id"] == "0001"
    assert "immutable quasar" in retrieved.lower()
    assert _file_snapshot(tmp_path) == before


@pytest.mark.asyncio
async def test_vacuum_tree_cannot_breach_generation_grace(tmp_path: Path) -> None:
    """An LLM-supplied ``max_age_s`` must not delete a body still inside the grace window."""
    toolkit = PageIndexToolkit(adapter=_adapter(), storage_dir=tmp_path, generation_grace_s=3600)
    await toolkit.create_tree("t")
    added = await toolkit.add_node("t", "Intro", body="first body")
    node_id = added["node_id"]
    tree = await toolkit.get_tree("t")
    old_ref = next(n["body_ref"] for n in tree["structure"] if n["node_id"] == node_id)
    old_blob = toolkit._content_store.body_path("t", old_ref)
    await toolkit.update_node_content("t", node_id, "second body")
    assert old_blob.is_file(), "precondition: the superseded blob is still on disk"

    report = await toolkit.vacuum_tree("t", max_age_s=0)

    assert report["removed"] == 0
    assert old_blob.is_file(), "vacuum_tree is LLM-callable; max_age_s must not breach the grace floor"


@pytest.mark.asyncio
async def test_vacuum_tree_floor_still_allows_a_longer_age(tmp_path: Path) -> None:
    """A ``max_age_s`` above the floor is honoured: the floor only ever makes the sweep safer."""
    toolkit = PageIndexToolkit(adapter=_adapter(), storage_dir=tmp_path, generation_grace_s=60)
    await toolkit.create_tree("t")
    added = await toolkit.add_node("t", "Intro", body="first body")
    node_id = added["node_id"]
    tree = await toolkit.get_tree("t")
    old_ref = next(n["body_ref"] for n in tree["structure"] if n["node_id"] == node_id)
    old_blob = toolkit._content_store.body_path("t", old_ref)
    await toolkit.update_node_content("t", node_id, "second body")
    ancient = time.time() - 10 * 3600
    os.utime(old_blob, (ancient, ancient))

    report = await toolkit.vacuum_tree("t", max_age_s=7200)

    assert report["removed"] == 1
    assert not old_blob.exists()
