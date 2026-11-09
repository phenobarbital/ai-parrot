"""LLM passes of the PageIndex tree optimizer (FEAT-846, Module 2)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel

from parrot.knowledge.pageindex.builder import _LLM_SEMAPHORE, _limited_gather
from parrot.knowledge.pageindex.framing import DATA_FRAMING_INSTRUCTION, frame_segments, frame_text
from parrot.knowledge.pageindex.layout_structure import MAX_HEADING_WORDS
from parrot.knowledge.pageindex.optimizer import (
    KeyItem,
    OptimizePlan,
    OptimizerSettings,
    PassStamp,
    Revisions,
    is_stamped,
    owned_tokens,
    pass_cache_key,
    pass_input,
    split_at,
)
from parrot.knowledge.pageindex.segments import DocumentRevision, Segment, SegmentAddress, SegmentRead
from parrot.knowledge.pageindex.utils import create_clean_structure_for_description

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


def _summary_text(node: dict, revision: DocumentRevision) -> str:
    """Return the node's owned text as a whitespace-normalized string."""
    return " ".join(
        segment.text.strip() for segment in _owned_segments(node, revision).values() if segment.text.strip()
    )


def _trim_summary(text: str, max_words: int) -> str:
    """Return ``text`` within the permitted summary word cap."""
    words = text.split()
    return " ".join(words[: int(max_words * 1.2)])


async def summarize_leaf(
    node: dict,
    revision: DocumentRevision,
    adapter: Optional[Any],
    settings: OptimizerSettings,
) -> tuple[str, str]:
    """Return an inline or framed, capped summary for a leaf node."""
    text = _summary_text(node, revision)
    if owned_tokens(node, revision) <= settings.inline_summary_tokens:
        return text, "inline"
    if not adapter_is_live(adapter):
        return _trim_summary(text, settings.summary_max_words), "llm"

    prompt = (
        f"Summarize this document text in at most {settings.summary_max_words} words.\n\n"
        f"{frame_segments(reads_for(node, revision), source=f'{revision.doc_id}@{revision.revision}')}"
    )
    result = await adapter.ask_structured(prompt, SummaryOut, system_prompt=DATA_FRAMING_INSTRUCTION)
    return _trim_summary(result.summary, settings.summary_max_words), "llm"


async def compose_parent(
    node: dict,
    revision: DocumentRevision,
    adapter: Optional[Any],
    settings: OptimizerSettings,
) -> tuple[str, str]:
    """Compose a parent summary from child summaries, text, and key items."""
    children = node.get("nodes") or []
    child_titles = [str(child.get("title", "")) for child in children if child.get("title")]
    child_summaries = [str(child.get("summary", "")) for child in children if child.get("summary")]
    own_text = _summary_text(node, revision)
    key_items = [
        item.get("label", "") if isinstance(item, dict) else item.label for item in node.get("key_items") or []
    ]
    if not adapter_is_live(adapter):
        summary = own_text
        if child_titles:
            summary = (
                f"{summary}. Subsections cover: {', '.join(child_titles)}"
                if summary
                else (f"Subsections cover: {', '.join(child_titles)}")
            )
        return _trim_summary(summary, settings.summary_max_words), "composed"

    parts = ["Compose a concise parent summary from the framed document data below."]
    # Child summaries and key items derive from untrusted document text: frame them like the segments.
    if child_summaries:
        parts.append(
            frame_text("\n".join(child_summaries), source=f"{revision.doc_id}@{revision.revision} child summaries")
        )
    if key_items:
        parts.append(
            frame_text(
                "\n".join(str(item) for item in key_items if item),
                source=f"{revision.doc_id}@{revision.revision} key items",
            )
        )
    parts.append(frame_segments(reads_for(node, revision), source=f"{revision.doc_id}@{revision.revision}"))
    result = await adapter.ask_structured("\n\n".join(parts), SummaryOut, system_prompt=DATA_FRAMING_INSTRUCTION)
    return _trim_summary(result.summary, settings.summary_max_words), "composed"


async def describe_document(structure: Any, adapter: Any) -> str:
    """Return a framed description of a structure when a live adapter is available."""
    if not adapter_is_live(adapter):
        return ""
    payload = json.dumps(create_clean_structure_for_description(structure), ensure_ascii=False)
    framed = frame_text(payload, source="document structure")
    prompt = "Describe the document structure for retrieval and navigation.\n\n" + framed
    return await adapter.ask(prompt, system_prompt=DATA_FRAMING_INSTRUCTION)


def _nodes_by_depth(node: dict) -> dict[int, list[dict]]:
    """Return candidate nodes grouped by depth for bottom-up processing."""
    levels: dict[int, list[dict]] = {}

    def visit(current: dict, depth: int) -> None:
        levels.setdefault(depth, []).append(current)
        for child in current.get("nodes") or []:
            visit(child, depth + 1)

    visit(node, 0)
    return levels


def _record_stamp(plan: OptimizePlan, node: dict, pass_name: str, input_hash: str, execution: str) -> None:
    """Record a successful pass for later candidate validation and finalization."""
    plan.pending_stamps.setdefault(id(node), {})[pass_name] = PassStamp(
        version="v1",
        input=input_hash,
        settings=plan.report.settings.settings_hash(),
        execution=execution,
        at=datetime.now(timezone.utc).isoformat(),
    )


def _is_completed(
    plan: OptimizePlan, node: dict, settings: OptimizerSettings, pass_name: str, input_hash: str, execution: str
) -> bool:
    """Return whether a persisted or pending record matches this exact pass input."""
    pending = plan.pending_stamps.get(id(node), {}).get(pass_name)
    return (pending is not None and pending.input == input_hash and pending.execution == execution) or is_stamped(
        node, settings, pass_name=pass_name, input_hash=input_hash, execution=execution
    )


async def run_llm_passes(
    plan: OptimizePlan,
    revisions: Revisions,
    adapter: Optional[Any],
    settings: OptimizerSettings,
    *,
    with_summaries: bool = True,
) -> None:
    """Run optimizer LLM work and retain successful completion records for later finalization."""
    token = None
    if _LLM_SEMAPHORE.get() is None:
        token = _LLM_SEMAPHORE.set(asyncio.Semaphore(16))
    live = settings.llm_passes and adapter_is_live(adapter)
    plan.report.llm_passes = (
        "ran" if live else ("skipped (disabled)" if not settings.llm_passes else "skipped (no model)")
    )

    async def cached_call(key: str, call: Any) -> Any:
        if key not in plan.llm_cache:
            plan.llm_cache[key] = await call()
        return plan.llm_cache[key]

    try:
        roots: list[dict] = []

        def collect_roots(node: dict, parent_key: Optional[tuple[Any, Any]] = None) -> None:
            key = (node.get("doc_id"), node.get("revision"))
            if key in revisions and key != parent_key:
                roots.append(node)
                return
            for child in node.get("nodes") or []:
                collect_roots(child, key)

        collect_roots(plan.candidate)
        for root in roots:
            revision = revisions[(root["doc_id"], root["revision"])]
            nodes = [node for level in _nodes_by_depth(root).values() for node in level]
            if live:
                for node in list(nodes):
                    if node.get("nodes"):
                        continue
                    input_hash = pass_input(node, "headings")
                    execution = execution_digest(adapter, mode="live")
                    if _is_completed(plan, node, settings, "headings", input_hash, execution):
                        continue
                    key = pass_cache_key("headings", input_hash, execution, settings)
                    try:
                        headings = await cached_call(
                            key,
                            lambda node=node: propose_headings(node, revision, adapter, settings, report=plan.report),
                        )
                        plan.report.llm_calls_made += 1
                        split_at(node, revision, headings, source="llm", settings=settings, report=plan.report)
                        _record_stamp(plan, node, "headings", input_hash, execution)
                    except Exception as error:
                        plan.report.errors.append(str(error))

                nodes = [node for level in _nodes_by_depth(root).values() for node in level]
                for node in nodes:
                    if node.get("nodes") or owned_tokens(node, revision) <= settings.target_leaf_tokens:
                        continue
                    input_hash = pass_input(node, "key_items")
                    execution = execution_digest(adapter, mode="live")
                    if _is_completed(plan, node, settings, "key_items", input_hash, execution):
                        continue
                    key = pass_cache_key("key_items", input_hash, execution, settings)
                    try:
                        items = await cached_call(
                            key,
                            lambda node=node: propose_key_items(node, revision, adapter, settings, report=plan.report),
                        )
                        # Keep key items already attached (e.g. titles absorbed by a merge); add proposals after them.
                        merged_items: list[Any] = list(node.get("key_items") or [])
                        seen = {
                            (m.get("label"), m.get("seq")) if isinstance(m, dict) else (m.label, m.seq)
                            for m in merged_items
                        }
                        for item in items:
                            if (item.label, item.seq) not in seen:
                                seen.add((item.label, item.seq))
                                merged_items.append(item.model_dump())
                        node["key_items"] = merged_items
                        plan.report.key_items_added += len(items)
                        plan.report.llm_calls_made += 1
                        _record_stamp(plan, node, "key_items", input_hash, execution)
                    except Exception as error:
                        plan.report.errors.append(str(error))

            if not with_summaries:
                continue
            levels = _nodes_by_depth(root)
            for depth in sorted(levels, reverse=True):

                async def summarize(node: dict) -> None:
                    input_hash = pass_input(node, "summary")
                    is_leaf = not node.get("nodes")
                    mode = (
                        "deterministic"
                        if is_leaf and owned_tokens(node, revision) <= settings.inline_summary_tokens
                        else ("live" if live else "deterministic")
                    )
                    execution = execution_digest(adapter if live else None, mode=mode)
                    if _is_completed(plan, node, settings, "summary", input_hash, execution):
                        return
                    key = pass_cache_key("summary", input_hash, execution, settings)
                    try:
                        summary, kind = await cached_call(
                            key,
                            lambda node=node: (
                                summarize_leaf(node, revision, adapter if live else None, settings)
                                if not node.get("nodes")
                                else compose_parent(node, revision, adapter if live else None, settings)
                            ),
                        )
                        node["summary"] = summary
                        node["optimizer"] = {**(node.get("optimizer") or {}), "summary": kind}
                        plan.report.summaries_written += 1
                        if live and not (is_leaf and owned_tokens(node, revision) <= settings.inline_summary_tokens):
                            plan.report.llm_calls_made += 1
                        _record_stamp(plan, node, "summary", input_hash, execution)
                    except Exception as error:
                        plan.report.errors.append(str(error))

                results = await _limited_gather((summarize(node) for node in levels[depth]), return_exceptions=True)
                for result in results:
                    if isinstance(result, Exception):
                        plan.report.errors.append(str(result))
    finally:
        if token is not None:
            _LLM_SEMAPHORE.reset(token)
