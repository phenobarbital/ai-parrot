"""LLM passes of the PageIndex tree optimizer (FEAT-846, Module 2)."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal, Optional

from pydantic import BaseModel

from parrot.knowledge.pageindex.framing import DATA_FRAMING_INSTRUCTION, frame_segments
from parrot.knowledge.pageindex.layout_structure import MAX_HEADING_WORDS
from parrot.knowledge.pageindex.optimizer import KeyItem, OptimizerSettings
from parrot.knowledge.pageindex.segments import DocumentRevision, Segment, SegmentAddress, SegmentRead

PROMPT_VERSION = "v1"
_NON_HEADING_KINDS = frozenset({"table", "code", "caption"})


class HeadingProposals(BaseModel):
    """Structured output containing segment sequences for printed sub-headings."""

    seqs: list[int]


class KeyItemProposal(BaseModel):
    """A model-proposed key item anchored to a document segment."""

    label: str
    kind: Literal["literal", "abstractive"]
    seq: int


class KeyItemProposals(BaseModel):
    """Structured output containing proposed key items."""

    items: list[KeyItemProposal]


class SummaryOut(BaseModel):
    """Structured output reserved for the optimizer summary pass."""

    summary: str


def adapter_is_live(adapter: Any) -> bool:
    """Return whether an adapter has a configured client."""
    return adapter is not None and getattr(adapter, "client", None) is not None


def execution_digest(adapter: Optional[Any], *, mode: str, prompt_version: str = PROMPT_VERSION) -> str:
    """Return a stable, credential-free digest of the LLM execution context."""
    payload: list[Optional[str]] = [mode, prompt_version]
    if adapter_is_live(adapter):
        payload.extend([type(adapter.client).__name__, getattr(adapter, "model", None)])
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def reads_for(node: dict, revision: DocumentRevision) -> list[SegmentRead]:
    """Return complete reads for the unique segments owned by ``node``."""
    reads: list[SegmentRead] = []
    seen: set[int] = set()
    for start, end in node.get("owned") or []:
        for seq in range(max(int(start), 0), min(int(end), len(revision.segments))):
            if seq in seen:
                continue
            seen.add(seq)
            segment = revision.segments[seq]
            reads.append(
                SegmentRead(
                    address=SegmentAddress(
                        doc_id=revision.doc_id,
                        revision=revision.revision,
                        seq=segment.seq,
                        page=segment.page,
                        ordinal=segment.ordinal,
                        section=segment.section,
                    ),
                    seq=segment.seq,
                    kind=segment.kind,
                    text=segment.text,
                    start=0,
                    end=len(segment.text),
                    flags=segment.flags,
                )
            )
    return reads


def heading_like(segment: Segment) -> bool:
    """Return whether a segment can be accepted as a printed sub-heading."""
    text = (segment.text or "").strip()
    if not text or "\n" in text or segment.kind in _NON_HEADING_KINDS:
        return False
    return len(text.split()) <= MAX_HEADING_WORDS and not text.endswith(".")


def literal_in_anchor(label: str, text: str) -> bool:
    """Return whether a literal label occurs in its anchor after normalization."""
    normalized_label = re.sub(r"\s+", " ", label).strip().casefold()
    normalized_text = re.sub(r"\s+", " ", text).strip().casefold()
    return bool(normalized_label) and normalized_label in normalized_text


def _owned_segments(node: dict, revision: DocumentRevision) -> dict[int, Segment]:
    """Return node-owned segments indexed by their stable sequence number."""
    return {read.seq: revision.segments[read.seq] for read in reads_for(node, revision)}


def _record_rejection(report: Optional[Any]) -> None:
    """Increment a compatible optimizer report's rejection counter when supplied."""
    if report is not None:
        report.rejected_proposals += 1


async def propose_headings(
    node: dict,
    revision: DocumentRevision,
    adapter: Any,
    settings: OptimizerSettings,
    *,
    report: Optional[Any] = None,
) -> list[int]:
    """Return valid printed-heading sequences proposed by a live, framed LLM call."""
    if not settings.llm_passes or not adapter_is_live(adapter):
        return []

    prompt = (
        "Identify the segments that are printed sub-headings. Return only their sequence numbers.\n\n"
        f"{frame_segments(reads_for(node, revision), source=f'{revision.doc_id}@{revision.revision}')}"
    )
    proposals = await adapter.ask_structured(
        prompt,
        HeadingProposals,
        system_prompt=DATA_FRAMING_INSTRUCTION,
    )
    owned = _owned_segments(node, revision)
    accepted: list[int] = []
    for seq in proposals.seqs:
        segment = owned.get(seq)
        if segment is None or not heading_like(segment):
            _record_rejection(report)
            continue
        if seq not in accepted:
            accepted.append(seq)
    return accepted


async def propose_key_items(
    node: dict,
    revision: DocumentRevision,
    adapter: Any,
    settings: OptimizerSettings,
    *,
    report: Optional[Any] = None,
) -> list[KeyItem]:
    """Return valid, capped key items proposed by a live, framed LLM call."""
    if not settings.llm_passes or not adapter_is_live(adapter):
        return []

    prompt = (
        "Identify up to "
        f"{settings.max_key_items} key concepts. Each item must provide a label, a literal or abstractive kind, "
        "and the sequence number of its anchor segment.\n\n"
        f"{frame_segments(reads_for(node, revision), source=f'{revision.doc_id}@{revision.revision}')}"
    )
    proposals = await adapter.ask_structured(
        prompt,
        KeyItemProposals,
        system_prompt=DATA_FRAMING_INSTRUCTION,
    )
    owned = _owned_segments(node, revision)
    accepted: list[KeyItem] = []
    for proposal in proposals.items:
        segment = owned.get(proposal.seq)
        if segment is None or (proposal.kind == "literal" and not literal_in_anchor(proposal.label, segment.text)):
            _record_rejection(report)
            continue
        if len(accepted) >= settings.max_key_items:
            continue
        accepted.append(
            KeyItem(
                label=proposal.label,
                kind=proposal.kind,
                seq=proposal.seq,
                page=segment.page,
                ordinal=segment.ordinal,
            )
        )
    return accepted
