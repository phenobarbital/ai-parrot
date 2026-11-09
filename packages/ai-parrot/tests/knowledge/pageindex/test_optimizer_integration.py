"""End-to-end scenarios for the PageIndex optimizer (FEAT-846).

Real arXiv fixture through the layout builder, a fake live adapter, and tmp storage. No network or model.
"""

from __future__ import annotations

import asyncio
import copy
import json
import multiprocessing as mp
from pathlib import Path
from typing import Any

import pytest

from parrot.knowledge.pageindex import Citation, PageIndexToolkit, validate_citations
from parrot.knowledge.pageindex.citations import ProposedCitation
from parrot.knowledge.pageindex.framing import DATA_FRAMING_INSTRUCTION
from parrot.knowledge.pageindex.optimizer_llm import HeadingProposals, KeyItemProposals, SummaryOut
from parrot.knowledge.pageindex.read_ledger import ReadLedger
from parrot.knowledge.pageindex.segment_store import SegmentStore
from parrot.knowledge.pageindex.utils import structure_to_list

pytestmark = pytest.mark.asyncio

FIXTURE = Path(__file__).parent / "fixtures" / "arxiv_2408_09869.pdf"


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    approx = lambda text, model="gpt-4o": max(1, len(text or ""))  # noqa: E731
    monkeypatch.setattr("parrot.knowledge.pageindex.utils.get_encoder", lambda model="gpt-4o": None)
    monkeypatch.setattr("parrot.knowledge.pageindex.utils.count_tokens", approx)
    monkeypatch.setattr("parrot.knowledge.pageindex.md_builder.count_tokens", approx)
    monkeypatch.setattr(
        "parrot.knowledge.pageindex.toolkit.get_injection_scoring_engine", lambda force_reresolve=False: None
    )


class _LiveAdapter:
    """Deterministic fake live adapter that records every call (no heading or key-item proposals)."""

    model = "fake-live"
    client = object()

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.on_first_call: Any = None

    async def ask_structured(self, prompt, output_type, temperature=0.0, system_prompt=None):
        """Return an empty or fixed structured result for the requested output type."""
        self.calls.append(("ask_structured", prompt, system_prompt))
        if self.on_first_call is not None and len(self.calls) == 1:
            await self.on_first_call()
        if output_type is HeadingProposals:
            return HeadingProposals(seqs=[])
        if output_type is KeyItemProposals:
            return KeyItemProposals(items=[])
        if output_type is SummaryOut:
            return SummaryOut(summary="Fake summary of the framed document data.")
        raise AssertionError(f"Unexpected structured output type: {output_type}")

    async def ask(self, prompt, structured_output=None, temperature=0.0, system_prompt=None):
        """Return a fixed description and record the call."""
        self.calls.append(("ask", prompt, system_prompt))
        return "Fake document description."


def _nodes(tree: dict[str, Any]) -> list[dict[str, Any]]:
    return structure_to_list(tree["structure"])


def _snapshot(toolkit: PageIndexToolkit, name: str) -> dict[str, Any]:
    return copy.deepcopy(toolkit._store.load(name))


async def _imported(
    tmp_path: Path, adapter: Any, *, with_summaries: bool = True, **toolkit_kwargs: Any
) -> tuple[PageIndexToolkit, dict[str, Any]]:
    toolkit = PageIndexToolkit(adapter=adapter, storage_dir=tmp_path, **toolkit_kwargs)
    await toolkit.create_tree("t")
    imported = await toolkit.import_pdf("t", str(FIXTURE), structure_mode="layout", with_summaries=with_summaries)
    return toolkit, imported


async def test_import_then_optimize_is_noop(tmp_path):
    """Import finalizes stamps; an identical optimize(apply=True) publishes nothing and makes no calls."""
    adapter = _LiveAdapter()
    toolkit, imported = await _imported(tmp_path, adapter)
    nodes = _nodes(_snapshot(toolkit, "t"))
    assert nodes and imported["doc_id"]
    assert all(node.get("optimizer", {}).get("passes", {}).get("summary") for node in nodes if node.get("doc_id"))

    before = _snapshot(toolkit, "t")
    generation = (await toolkit.get_generation("t"))["id"]
    adapter.calls.clear()

    report = await toolkit.optimize("t", apply=True)

    assert report["errors"] == []
    assert report["merged"] == [] and report["expanded"] == []
    assert report["summaries_written"] == 0 and report["key_items_added"] == 0
    assert report["llm_calls_made"] == 0
    assert adapter.calls == []
    assert (await toolkit.get_generation("t"))["id"] == generation
    assert report["generation_before"] == report["generation_after"] == generation
    assert _snapshot(toolkit, "t") == before
    assert [n.get("body_ref") for n in _nodes(before)] == [n.get("body_ref") for n in _nodes(_snapshot(toolkit, "t"))]


async def test_deferred_summaries_and_parent_refresh(tmp_path):
    """Summaries deferred at import are produced explicitly; an edited child summary recomposes its parent."""
    adapter = _LiveAdapter()
    toolkit, _ = await _imported(tmp_path, adapter, with_summaries=False)
    assert not any(node.get("summary") for node in _nodes(_snapshot(toolkit, "t")))

    first = await toolkit.optimize("t", apply=True)
    assert first["errors"] == []
    assert first["summaries_written"] > 0
    nodes = _nodes(_snapshot(toolkit, "t"))
    assert all(node.get("summary") for node in nodes if node.get("owned") or node.get("nodes"))

    tree = _snapshot(toolkit, "t")
    parent = next(n for n in _nodes(tree) if n.get("nodes") and n.get("doc_id") and n.get("owned") is not None)
    child = parent["nodes"][0]
    parent_stamp = copy.deepcopy(parent["optimizer"]["passes"]["summary"])
    await toolkit.update_node("t", child["node_id"], summary="Edited child summary that changes parent input.")
    adapter.calls.clear()

    second = await toolkit.optimize("t", apply=True)

    assert second["errors"] == []
    after = _nodes(_snapshot(toolkit, "t"))
    refreshed = next(n for n in after if n.get("concept_id") == parent.get("concept_id"))
    assert refreshed["optimizer"]["passes"]["summary"] != parent_stamp
    # Unrelated completed passes remain cached: far fewer calls than a from-scratch pass.
    assert second["summaries_written"] < first["summaries_written"]


async def test_import_description_is_framed(tmp_path):
    """The import description call is framed; no model means no call; opt-out keeps the legacy path."""
    adapter = _LiveAdapter()
    toolkit = PageIndexToolkit(adapter=adapter, storage_dir=tmp_path / "framed")
    await toolkit.create_tree("t")
    imported = await toolkit.import_pdf(
        "t", str(FIXTURE), structure_mode="layout", with_summaries=True, with_doc_description=True
    )
    describe = [call for call in adapter.calls if call[0] == "ask"]
    assert len(describe) == 1
    _, prompt, system_prompt = describe[0]
    assert system_prompt == DATA_FRAMING_INSTRUCTION
    assert "<document_text" in prompt and "</document_text>" in prompt
    assert imported["doc_description"] == "Fake document description."

    bare = PageIndexToolkit(adapter=None, storage_dir=tmp_path / "bare")
    await bare.create_tree("t")
    result = await bare.import_pdf("t", str(FIXTURE), structure_mode="layout", with_doc_description=True)
    assert not result["doc_description"]

    legacy_adapter = _LiveAdapter()
    legacy = PageIndexToolkit(adapter=legacy_adapter, storage_dir=tmp_path / "legacy", optimize_on_import=False)
    await legacy.create_tree("t")
    await legacy.import_pdf("t", str(FIXTURE), structure_mode="layout", with_summaries=False)
    assert all("optimizer" not in node for node in _nodes(_snapshot(legacy, "t")))


async def test_subtree_optimize_preserves_outside_ownership(tmp_path):
    """Optimizing one of two documents leaves the other's owned ranges and bodies byte-identical."""
    toolkit = PageIndexToolkit(adapter=None, storage_dir=tmp_path, optimize_on_import=False)
    await toolkit.create_tree("t")
    await toolkit.import_pdf("t", str(FIXTURE), structure_mode="layout", doc_id="alpha")
    await toolkit.insert_markdown("t", "# Beta\n\n" + "Beta paragraph with independent content. " * 40)

    before = _snapshot(toolkit, "t")
    other = [n for n in _nodes(before) if n.get("doc_id") != "alpha"]
    assert other
    other_ids = {n["concept_id"] if n.get("concept_id") else n["title"] for n in other}
    other_before = {
        (n.get("concept_id") or n["title"]): (
            n.get("owned"),
            n.get("span"),
            n.get("body_ref"),
            toolkit._content_store.load_node("t", n) if n.get("body_ref") else None,
        )
        for n in other
    }
    alpha_root = next(n for n in before["structure"] if n.get("doc_id") == "alpha")

    report = await toolkit.optimize("t", node_id=alpha_root["node_id"], apply=True, llm_passes=False)

    assert report["errors"] == []
    after = _snapshot(toolkit, "t")
    other_after = {
        (n.get("concept_id") or n["title"]): (
            n.get("owned"),
            n.get("span"),
            n.get("body_ref"),
            toolkit._content_store.load_node("t", n) if n.get("body_ref") else None,
        )
        for n in _nodes(after)
        if n.get("doc_id") != "alpha"
    }
    assert set(other_after) == other_ids
    assert other_after == other_before


async def test_citations_survive_optimize(tmp_path):
    """A citation validated before optimize still validates afterwards against the same revision."""
    toolkit, imported = await _imported(tmp_path, None)
    doc_id, revision_id = imported["doc_id"], imported["revision"]
    read = await toolkit.read_pages("t", doc_id, "1-2", max_chars=4000)
    segment = next(s for s in read["segments"] if len(s["text"].split()) > 6)
    excerpt = " ".join(segment["text"].split()[:5])
    address = f"{doc_id}@{revision_id}#{segment['seq']}"

    store = SegmentStore(tmp_path)
    load = lambda d, r: store.load_revision("t", d, r)  # noqa: E731

    def validated() -> list[Citation]:
        ledger = ReadLedger(budget_chars=100_000, max_reads=50)
        from parrot.knowledge.pageindex.segments import ReadResult

        ledger.record(ReadResult(**{k: v for k, v in read.items() if k in ReadResult.model_fields}))
        kept, rejected = validate_citations(ledger, load, [ProposedCitation(address=address, excerpt=excerpt)])
        assert rejected == []
        return kept

    before = validated()
    assert len(before) == 1

    adapter = _LiveAdapter()
    toolkit._adapter = adapter
    report = await toolkit.optimize("t", apply=True)
    assert report["errors"] == []

    after = validated()
    assert after == before
    assert after[0].revision == revision_id


def _edit_in_child(storage_dir: str, node_id: str, out_path: str) -> None:
    """Edit one node body from a separate process."""

    async def run() -> None:
        toolkit = PageIndexToolkit(adapter=None, storage_dir=storage_dir, optimize_on_import=False)
        await toolkit.update_node_content("t", node_id, "Edited by another process.")
        Path(out_path).write_text(json.dumps({"ok": True}))

    asyncio.run(run())


def test_two_processes_optimize_and_edit(tmp_path, monkeypatch):
    """An edit landing between planning and publish is not overwritten: the stale publish re-plans."""
    approx = lambda text, model="gpt-4o": max(1, len(text or ""))  # noqa: E731
    monkeypatch.setattr("parrot.knowledge.pageindex.utils.get_encoder", lambda model="gpt-4o": None)
    monkeypatch.setattr("parrot.knowledge.pageindex.utils.count_tokens", approx)
    monkeypatch.setattr("parrot.knowledge.pageindex.md_builder.count_tokens", approx)
    monkeypatch.setattr(
        "parrot.knowledge.pageindex.toolkit.get_injection_scoring_engine", lambda force_reresolve=False: None
    )

    async def scenario() -> None:
        toolkit = PageIndexToolkit(adapter=None, storage_dir=tmp_path, optimize_on_import=False)
        await toolkit.create_tree("t")
        await toolkit.import_pdf("t", str(FIXTURE), structure_mode="layout", doc_id="alpha")
        tree = toolkit._store.load("t")
        target = next(
            n for n in structure_to_list(tree["structure"]) if n.get("doc_id") and n.get("body_ref") and not n.get("nodes")
        )
        generation = (await toolkit.get_generation("t"))["id"]

        out = tmp_path / "child.json"
        adapter = _LiveAdapter()

        async def edit_between_plan_and_publish() -> None:
            process = mp.get_context("spawn").Process(target=_edit_in_child, args=(str(tmp_path), target["node_id"], str(out)))
            process.start()
            await asyncio.to_thread(process.join, 90)
            if process.is_alive():
                process.terminate()
                pytest.fail("editor did not finish")

        adapter.on_first_call = edit_between_plan_and_publish
        toolkit._adapter = adapter
        report = await toolkit.optimize("t", apply=True)

        assert json.loads(out.read_text()) == {"ok": True}
        assert report["errors"] == []
        fresh = PageIndexToolkit(adapter=None, storage_dir=tmp_path, optimize_on_import=False)
        after = fresh._store.load("t")
        edited = next(n for n in structure_to_list(after["structure"]) if n.get("title") == target["title"])
        assert edited["locked"] is True and edited["locked_reason"] == "body_edited"
        assert fresh._content_store.load_node("t", edited) == "Edited by another process."
        assert (await fresh.get_generation("t"))["id"] > generation + 1

    asyncio.run(scenario())
