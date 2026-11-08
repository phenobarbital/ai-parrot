"""Unit tests for optimizer_llm (FEAT-846 M2)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.knowledge.pageindex.framing import DATA_FRAMING_INSTRUCTION
from parrot.knowledge.pageindex.optimizer import OptimizeReport, OptimizerSettings
from parrot.knowledge.pageindex.optimizer_llm import (
    HeadingProposals,
    KeyItemProposal,
    KeyItemProposals,
    adapter_is_live,
    heading_like,
    literal_in_anchor,
    propose_headings,
    propose_key_items,
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
