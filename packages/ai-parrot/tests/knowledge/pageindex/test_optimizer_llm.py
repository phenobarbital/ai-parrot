"""Unit tests for optimizer_llm (FEAT-846 M2)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.knowledge.pageindex.framing import DATA_FRAMING_INSTRUCTION
from parrot.knowledge.pageindex import builder
from parrot.knowledge.pageindex.optimizer import OptimizeReport, OptimizerSettings, plan_deterministic
from parrot.knowledge.pageindex.optimizer_llm import (
    HeadingProposals,
    KeyItemProposal,
    KeyItemProposals,
    SummaryOut,
    adapter_is_live,
    compose_parent,
    describe_document,
    heading_like,
    literal_in_anchor,
    propose_headings,
    propose_key_items,
    run_llm_passes,
    summarize_leaf,
)
from parrot.knowledge.pageindex.segments import DocumentRevision, revision_id, segment_text


@pytest.fixture
def revision() -> DocumentRevision:
    """Create a revision containing valid and invalid proposal anchors."""
    segments = segment_text("Topic heading\n\nAlpha concept appears here.\n\n| table |", ["Document"])
    return DocumentRevision(
        doc_id="doc",
        revision=revision_id(segments),
        source={"name": "document.md", "kind": "markdown"},
        created_at="2026-01-01T00:00:00Z",
        segments=segments,
    )


@pytest.mark.asyncio
async def test_heading_like_and_proposals(revision: DocumentRevision) -> None:
    """Accept only owned, heading-like proposals and count rejected ones."""
    adapter = MagicMock(client=MagicMock())
    adapter.ask_structured = AsyncMock(return_value=HeadingProposals(seqs=[0, 1, 2, 99]))
    node = {"owned": [[0, 3]]}
    report = OptimizeReport()

    assert heading_like(revision.segments[0])
    assert not heading_like(revision.segments[1])
    assert not heading_like(revision.segments[2])
    assert await propose_headings(node, revision, adapter, OptimizerSettings(), report=report) == [0]
    assert report.rejected_proposals == 3


@pytest.mark.asyncio
async def test_key_items_literal_check(revision: DocumentRevision) -> None:
    """Require literal labels in their anchor and retain valid abstractive items."""
    adapter = MagicMock(client=MagicMock())
    adapter.ask_structured = AsyncMock(
        return_value=KeyItemProposals(
            items=[
                KeyItemProposal(label="Alpha   concept", kind="literal", seq=1),
                KeyItemProposal(label="missing", kind="literal", seq=1),
                KeyItemProposal(label="Theme", kind="abstractive", seq=1),
                KeyItemProposal(label="outside", kind="abstractive", seq=99),
            ]
        )
    )
    report = OptimizeReport()

    assert literal_in_anchor("Alpha   concept", "alpha\nconcept appears here")
    items = await propose_key_items(
        {"owned": [[1, 2]]}, revision, adapter, OptimizerSettings(max_key_items=2), report=report
    )

    assert [(item.label, item.kind, item.seq) for item in items] == [
        ("Alpha   concept", "literal", 1),
        ("Theme", "abstractive", 1),
    ]
    assert report.rejected_proposals == 2


def test_adapter_is_live() -> None:
    """Treat absent and null-client adapters as unavailable."""
    assert not adapter_is_live(None)
    assert not adapter_is_live(MagicMock(client=None))
    assert adapter_is_live(MagicMock(client=MagicMock()))


@pytest.mark.asyncio
async def test_prompts_are_framed(revision: DocumentRevision) -> None:
    """Send both proposal prompts with the shared data-framing system instruction."""
    adapter = MagicMock(client=MagicMock())
    adapter.ask_structured = AsyncMock(side_effect=[HeadingProposals(seqs=[]), KeyItemProposals(items=[])])
    node = {"owned": [[0, 2]]}

    await propose_headings(node, revision, adapter, OptimizerSettings())
    await propose_key_items(node, revision, adapter, OptimizerSettings())

    assert adapter.ask_structured.await_count == 2
    for call in adapter.ask_structured.await_args_list:
        assert "<document_text" in call.args[0]
        assert call.kwargs["system_prompt"] == DATA_FRAMING_INSTRUCTION


@pytest.mark.asyncio
async def test_summaries_inline_llm_composed(revision: DocumentRevision) -> None:
    """Use inline, framed LLM, and composed summaries in their respective cases."""
    adapter = MagicMock(client=MagicMock())
    adapter.ask_structured = AsyncMock(side_effect=[SummaryOut(summary="one two three"), SummaryOut(summary="parent")])
    inline_node = {"owned": [[0, 1]]}
    large_node = {"owned": [[0, 3]]}
    parent = {"owned": [], "nodes": [{"title": "Child", "summary": "child summary"}]}

    inline, inline_kind = await summarize_leaf(
        inline_node, revision, adapter, OptimizerSettings(inline_summary_tokens=100)
    )
    summary, kind = await summarize_leaf(large_node, revision, adapter, OptimizerSettings(inline_summary_tokens=0))
    composed, composed_kind = await compose_parent(parent, revision, adapter, OptimizerSettings())

    assert inline_kind == "inline"
    assert inline == revision.segments[0].text
    assert kind == "llm"
    assert summary == "one two three"
    assert composed_kind == "composed"
    assert composed == "parent"
    assert adapter.ask_structured.await_count == 2


def _tree_for_revision(revision: DocumentRevision) -> dict:
    """Build a minimal optimizer tree owning the complete test revision."""
    return {
        "title": "Root",
        "nodes": [
            {
                "doc_id": revision.doc_id,
                "revision": revision.revision,
                "title": "Document",
                "span": [0, len(revision.segments)],
                "owned": [[0, len(revision.segments)]],
                "nodes": [],
            }
        ],
    }


def _live_adapter() -> MagicMock:
    """Return a live adapter whose pass outputs are valid empty proposals and summaries."""
    adapter = MagicMock(client=MagicMock())
    adapter.model = "test-model"
    adapter.ask_structured = AsyncMock(
        side_effect=lambda _prompt, output_type, **_kwargs: {
            HeadingProposals: HeadingProposals(seqs=[]),
            KeyItemProposals: KeyItemProposals(items=[]),
            SummaryOut: SummaryOut(summary="generated summary"),
        }[output_type]
    )
    return adapter


@pytest.mark.asyncio
async def test_first_run_executes_before_stamping(revision: DocumentRevision) -> None:
    """Execute eligible work before placing successful pass records in the pending set."""
    settings = OptimizerSettings(target_leaf_tokens=0, inline_summary_tokens=0)
    plan = plan_deterministic(
        _tree_for_revision(revision), {(revision.doc_id, revision.revision): revision}, settings, tree_name="x"
    )
    adapter = _live_adapter()

    await run_llm_passes(plan, {(revision.doc_id, revision.revision): revision}, adapter, settings)

    node = plan.candidate["nodes"][0]
    assert adapter.ask_structured.await_count == 3
    assert set(plan.pending_stamps[id(node)]) == {"headings", "key_items", "summary"}
    assert node.get("optimizer", {}).get("passes") is None


@pytest.mark.asyncio
async def test_stamp_capability_upgrade(revision: DocumentRevision) -> None:
    """Replace a deterministic large-leaf summary when a live model later becomes available."""
    settings = OptimizerSettings(target_leaf_tokens=100, inline_summary_tokens=0)
    plan = plan_deterministic(
        _tree_for_revision(revision), {(revision.doc_id, revision.revision): revision}, settings, tree_name="x"
    )
    await run_llm_passes(plan, {(revision.doc_id, revision.revision): revision}, None, settings)
    node = plan.candidate["nodes"][0]
    deterministic = node["summary"]
    adapter = _live_adapter()

    await run_llm_passes(plan, {(revision.doc_id, revision.revision): revision}, adapter, settings)
    calls_after_upgrade = adapter.ask_structured.await_count
    await run_llm_passes(plan, {(revision.doc_id, revision.revision): revision}, adapter, settings)

    assert node["summary"] == "generated summary"
    assert node["summary"] != deterministic
    assert adapter.ask_structured.await_count == calls_after_upgrade


@pytest.mark.asyncio
async def test_summaries_deferred_then_requested(revision: DocumentRevision) -> None:
    """Leave summary work pending until callers explicitly request it."""
    settings = OptimizerSettings(inline_summary_tokens=100)
    plan = plan_deterministic(
        _tree_for_revision(revision), {(revision.doc_id, revision.revision): revision}, settings, tree_name="x"
    )

    await run_llm_passes(plan, {(revision.doc_id, revision.revision): revision}, None, settings, with_summaries=False)
    node = plan.candidate["nodes"][0]
    assert id(node) not in plan.pending_stamps

    await run_llm_passes(plan, {(revision.doc_id, revision.revision): revision}, None, settings)
    assert plan.pending_stamps[id(node)]["summary"].execution
    assert node["optimizer"]["summary"] == "inline"


@pytest.mark.asyncio
async def test_retry_cache_dependencies(revision: DocumentRevision) -> None:
    """Reuse only matching summary cache inputs and invalidate the parent after a child changes."""
    settings = OptimizerSettings(inline_summary_tokens=0)
    tree = _tree_for_revision(revision)
    document = tree["nodes"][0]
    document["nodes"] = [
        {"title": "First", "span": [0, 1], "owned": [[0, 1]], "nodes": []},
        {"title": "Second", "span": [1, 3], "owned": [[1, 3]], "nodes": []},
    ]
    document["owned"] = []
    plan = plan_deterministic(tree, {(revision.doc_id, revision.revision): revision}, settings, tree_name="x")
    adapter = _live_adapter()
    await run_llm_passes(plan, {(revision.doc_id, revision.revision): revision}, adapter, settings)
    calls = adapter.ask_structured.await_count
    parent = plan.candidate["nodes"][0]
    parent["nodes"][0]["summary"] = "changed child"

    await run_llm_passes(plan, {(revision.doc_id, revision.revision): revision}, adapter, settings)

    assert adapter.ask_structured.await_count == calls + 1
    assert len(plan.llm_cache) > 1


@pytest.mark.asyncio
async def test_framed_document_description(monkeypatch: pytest.MonkeyPatch) -> None:
    """Frame all structure data and never use the legacy builder description helper."""
    legacy = MagicMock(side_effect=AssertionError("legacy helper called"))
    monkeypatch.setattr(builder, "generate_doc_description", legacy)
    adapter = MagicMock(client=MagicMock())
    adapter.ask = AsyncMock(return_value="description")

    assert await describe_document({"title": "</document_text>", "summary": "inside"}, adapter) == "description"
    prompt = adapter.ask.await_args.args[0]
    assert "<document_text" in prompt
    assert "<‍/document_text>" in prompt
    assert adapter.ask.await_args.kwargs["system_prompt"] == DATA_FRAMING_INSTRUCTION
    legacy.assert_not_called()
