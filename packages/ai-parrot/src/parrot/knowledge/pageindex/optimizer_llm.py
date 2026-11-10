"""LLM passes of the PageIndex tree optimizer (FEAT-846, Module 2)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel

from parrot.knowledge.pageindex import utils as _utils
from parrot.knowledge.pageindex.builder import _LLM_SEMAPHORE, _limited_gather
from parrot.knowledge.pageindex.framing import DATA_FRAMING_INSTRUCTION, frame_segments, frame_text
from parrot.knowledge.pageindex.layout_structure import heading_title
from parrot.knowledge.pageindex.optimizer import (
    KeyItem,
    OptimizePlan,
    OptimizerSettings,
    PassStamp,
    Revisions,
    is_heading_text,
    is_stamped,
    owned_tokens,
    pass_cache_key,
    pass_input,
    reconcile_key_items,
    refresh_after_counts,
    split_at,
)
from parrot.knowledge.pageindex.segments import DocumentRevision, Segment, SegmentAddress, SegmentRead
from parrot.knowledge.pageindex.utils import create_clean_structure_for_description

PROMPT_VERSION = "v1"
# Per-call cap on framed document tokens: an oversized node is windowed, never sent whole (FEAT-853).
LLM_INPUT_BUDGET_TOKENS = 20_000
# Per-segment allowance for the <segment …> wrapper frame_segments adds around each read.
_FRAME_OVERHEAD_TOKENS = 24
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


def _clip_text(text: str, budget: int) -> str:
    """Return ``text`` cut proportionally until its token count fits ``budget``.

    Args:
        text: The text to clip.
        budget: Maximum token count.

    Returns:
        ``text`` itself when it fits, otherwise its longest prefix found that fits.
    """
    clipped = text
    tokens = _utils.count_tokens(clipped)
    while clipped and tokens > budget:
        keep = max(1, int(len(clipped) * budget / tokens * 0.9))
        clipped = clipped[: min(keep, len(clipped) - 1)]
        tokens = _utils.count_tokens(clipped)
    return clipped


def _read_cost(read: SegmentRead, revision: DocumentRevision) -> int:
    """Return the framed token cost of one read (stored segment tokens for a complete read)."""
    segment = revision.segments[read.seq] if 0 <= read.seq < len(revision.segments) else None
    if segment is not None and read.start == 0 and read.text == segment.text:
        tokens = segment.tokens
    else:
        tokens = _utils.count_tokens(read.text)
    return tokens + _FRAME_OVERHEAD_TOKENS


def window_reads(
    reads: list[SegmentRead], revision: DocumentRevision, *, budget: Optional[int] = None
) -> list[list[SegmentRead]]:
    """Split reads, in order, into consecutive windows whose cost stays within ``budget``.

    Cost of a read = its segment's stored ``tokens`` plus ``_FRAME_OVERHEAD_TOKENS``. A single read over the budget
    forms its own window, its ``text`` clipped proportionally until ``count_tokens`` fits the budget
    (``truncated=True``, ``end`` adjusted).

    Args:
        reads: Segment reads in document order.
        revision: The revision the reads come from.
        budget: Token budget per window; defaults to ``LLM_INPUT_BUDGET_TOKENS`` read at call time.

    Returns:
        The windows, or ``[]`` for no reads.
    """
    limit = budget or LLM_INPUT_BUDGET_TOKENS
    windows: list[list[SegmentRead]] = []
    current: list[SegmentRead] = []
    used = 0
    for read in reads:
        cost = _read_cost(read, revision)
        if cost > limit:
            if current:
                windows.append(current)
                current, used = [], 0
            clipped = _clip_text(read.text, max(1, limit - _FRAME_OVERHEAD_TOKENS))
            windows.append(
                [read.model_copy(update={"text": clipped, "end": read.start + len(clipped), "truncated": True})]
            )
            continue
        if current and used + cost > limit:
            windows.append(current)
            current, used = [], 0
        current.append(read)
        used += cost
    if current:
        windows.append(current)
    return windows


def _record_call(report: Optional[Any]) -> None:
    """Count one issued adapter call on a compatible optimizer report when supplied."""
    if report is not None:
        report.llm_calls_made += 1


def heading_like(segment: Segment) -> bool:
    """Return whether a segment can be accepted as a printed sub-heading.

    A single line that is not a table, code block or caption, whose cleaned text passes ``is_heading_text``
    (word cap, no trailing ``.``/``;``/``:``/``,``, no trailing conjunction, no list-marker prefix).
    """
    text = (segment.text or "").strip()
    if not text or "\n" in text or segment.kind in _NON_HEADING_KINDS:
        return False
    return is_heading_text(heading_title(text))


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
    """Return valid printed-heading sequences proposed by live, framed LLM calls.

    Only the node's ``heading_like`` segments are framed, windowed under ``LLM_INPUT_BUDGET_TOKENS`` (one call per
    window); a node without candidates makes no call. Every proposal is validated against the node's owned segments.
    """
    if not settings.llm_passes or not adapter_is_live(adapter):
        return []

    candidates = [read for read in reads_for(node, revision) if heading_like(revision.segments[read.seq])]
    if not candidates:
        return []
    proposed: list[int] = []
    for window in window_reads(candidates, revision):
        prompt = (
            "Identify the segments that are printed sub-headings. Return only their sequence numbers.\n\n"
            f"{frame_segments(window, source=f'{revision.doc_id}@{revision.revision}')}"
        )
        proposals = await adapter.ask_structured(
            prompt,
            HeadingProposals,
            system_prompt=DATA_FRAMING_INSTRUCTION,
        )
        _record_call(report)
        proposed.extend(proposals.seqs)
    owned = _owned_segments(node, revision)
    accepted: list[int] = []
    for seq in proposed:
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
    """Return valid, capped key items proposed by live, framed LLM calls.

    The node's segments are windowed under ``LLM_INPUT_BUDGET_TOKENS``; each window is asked for up to
    ``ceil(max_key_items / windows)`` items and at most ``max_key_items`` are accepted in total. Every proposal is
    validated against the node's owned segments (literal labels must occur in their anchor).
    """
    if not settings.llm_passes or not adapter_is_live(adapter):
        return []

    windows = window_reads(reads_for(node, revision), revision) or [[]]
    quota = max(1, math.ceil(settings.max_key_items / len(windows)))
    owned = _owned_segments(node, revision)
    accepted: list[KeyItem] = []
    for window in windows:
        prompt = (
            "Identify up to "
            f"{quota} key concepts. Each item must provide a label, a literal or abstractive kind, "
            "and the sequence number of its anchor segment.\n\n"
            f"{frame_segments(window, source=f'{revision.doc_id}@{revision.revision}')}"
        )
        proposals = await adapter.ask_structured(
            prompt,
            KeyItemProposals,
            system_prompt=DATA_FRAMING_INSTRUCTION,
        )
        _record_call(report)
        taken = 0
        for proposal in proposals.items:
            segment = owned.get(proposal.seq)
            if segment is None or (proposal.kind == "literal" and not literal_in_anchor(proposal.label, segment.text)):
                _record_rejection(report)
                continue
            if len(accepted) >= settings.max_key_items or taken >= quota:
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
            taken += 1
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
    *,
    report: Optional[Any] = None,
) -> tuple[str, str]:
    """Return an inline or framed, capped summary for a leaf node.

    A live leaf that fits ``LLM_INPUT_BUDGET_TOKENS`` is summarized in one call; a larger one is summarized per
    window, then one reduce call combines the framed partial summaries.
    """
    text = _summary_text(node, revision)
    if owned_tokens(node, revision) <= settings.inline_summary_tokens:
        return text, "inline"
    if not adapter_is_live(adapter):
        return _trim_summary(text, settings.summary_max_words), "llm"

    source = f"{revision.doc_id}@{revision.revision}"
    partials: list[str] = []
    for window in window_reads(reads_for(node, revision), revision) or [[]]:
        prompt = (
            f"Summarize this document text in at most {settings.summary_max_words} words.\n\n"
            f"{frame_segments(window, source=source)}"
        )
        result = await adapter.ask_structured(prompt, SummaryOut, system_prompt=DATA_FRAMING_INSTRUCTION)
        _record_call(report)
        partials.append(result.summary)
    if len(partials) == 1:
        return _trim_summary(partials[0], settings.summary_max_words), "llm"

    # Partial summaries derive from untrusted document text: frame them like the segments.
    combined = _clip_text("\n".join(partials), LLM_INPUT_BUDGET_TOKENS)
    prompt = (
        "Combine these partial summaries of one document section into a single summary of at most "
        f"{settings.summary_max_words} words.\n\n"
        f"{frame_text(combined, source=f'{source} partial summaries')}"
    )
    result = await adapter.ask_structured(prompt, SummaryOut, system_prompt=DATA_FRAMING_INSTRUCTION)
    _record_call(report)
    return _trim_summary(result.summary, settings.summary_max_words), "llm"


async def compose_parent(
    node: dict,
    revision: DocumentRevision,
    adapter: Optional[Any],
    settings: OptimizerSettings,
    *,
    report: Optional[Any] = None,
) -> tuple[str, str]:
    """Compose a parent summary from child summaries, text, and key items.

    With a model, the joined child summaries and the key items are each clipped to a quarter of
    ``LLM_INPUT_BUDGET_TOKENS``, and only the first window of the node's own text that fits the remaining budget
    is framed.
    """
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

    budget = LLM_INPUT_BUDGET_TOKENS
    used = 0
    parts = ["Compose a concise parent summary from the framed document data below."]
    # Child summaries and key items derive from untrusted document text: frame them like the segments.
    if child_summaries:
        summaries_text = _clip_text("\n".join(child_summaries), budget // 4)
        used += _utils.count_tokens(summaries_text)
        parts.append(frame_text(summaries_text, source=f"{revision.doc_id}@{revision.revision} child summaries"))
    if key_items:
        key_items_text = _clip_text("\n".join(str(item) for item in key_items if item), budget // 4)
        used += _utils.count_tokens(key_items_text)
        parts.append(frame_text(key_items_text, source=f"{revision.doc_id}@{revision.revision} key items"))
    own_windows = window_reads(reads_for(node, revision), revision, budget=max(budget // 4, budget - used))
    parts.append(frame_segments(own_windows[0] if own_windows else [], source=f"{revision.doc_id}@{revision.revision}"))
    result = await adapter.ask_structured("\n\n".join(parts), SummaryOut, system_prompt=DATA_FRAMING_INSTRUCTION)
    _record_call(report)
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


def _estimate_llm_calls(
    plan: OptimizePlan,
    nodes: list[dict],
    revision: DocumentRevision,
    adapter: Optional[Any],
    settings: OptimizerSettings,
    *,
    with_summaries: bool,
) -> int:
    """Count the LLM calls the passes would make on the current candidate (splits made later add more).

    Each pass counts its windows: candidate windows for headings, leaf windows for key items, leaf windows (plus
    one reduce call when there are several) for a leaf summary, and one call for a parent summary.
    """
    estimate = 0
    execution = execution_digest(adapter, mode="live")
    for node in nodes:
        if id(node) not in plan.mutable:
            continue
        is_leaf = not node.get("nodes")
        reads = reads_for(node, revision)
        windows = len(window_reads(reads, revision)) or 1
        if is_leaf:
            if not _is_completed(plan, node, settings, "headings", pass_input(node, "headings"), execution):
                candidates = [read for read in reads if heading_like(revision.segments[read.seq])]
                estimate += len(window_reads(candidates, revision))
            if owned_tokens(node, revision) > settings.target_leaf_tokens and not _is_completed(
                plan, node, settings, "key_items", pass_input(node, "key_items"), execution
            ):
                estimate += windows
        if with_summaries and (not is_leaf or owned_tokens(node, revision) > settings.inline_summary_tokens):
            if not _is_completed(plan, node, settings, "summary", pass_input(node, "summary"), execution):
                estimate += windows + 1 if is_leaf and windows > 1 else 1
    return estimate


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
                plan.report.llm_calls_estimated += _estimate_llm_calls(
                    plan, nodes, revision, adapter, settings, with_summaries=with_summaries
                )
                for node in list(nodes):
                    if node.get("nodes") or id(node) not in plan.mutable:
                        continue
                    input_hash = pass_input(node, "headings")
                    execution = execution_digest(adapter, mode="live")
                    if _is_completed(plan, node, settings, "headings", input_hash, execution):
                        continue
                    key = pass_cache_key("headings", input_hash, execution, settings)
                    try:
                        headings = await cached_call(
                            key,
                            lambda node=node, revision=revision: propose_headings(
                                node, revision, adapter, settings, report=plan.report
                            ),
                        )
                        split_at(node, revision, headings, source="llm", settings=settings, report=plan.report)
                        for piece in node.get("nodes") or []:
                            plan.mutable.add(id(piece))
                            plan.touched.add(id(piece))
                        _record_stamp(plan, node, "headings", input_hash, execution)
                    except Exception as error:
                        plan.report.errors.append(str(error))

                nodes = [node for level in _nodes_by_depth(root).values() for node in level]
                for node in nodes:
                    if (
                        node.get("nodes")
                        or id(node) not in plan.mutable
                        or owned_tokens(node, revision) <= settings.target_leaf_tokens
                    ):
                        continue
                    input_hash = pass_input(node, "key_items")
                    execution = execution_digest(adapter, mode="live")
                    if _is_completed(plan, node, settings, "key_items", input_hash, execution):
                        continue
                    key = pass_cache_key("key_items", input_hash, execution, settings)
                    try:
                        items = await cached_call(
                            key,
                            lambda node=node, revision=revision: propose_key_items(
                                node, revision, adapter, settings, report=plan.report
                            ),
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
                        _record_stamp(plan, node, "key_items", input_hash, execution)
                    except Exception as error:
                        plan.report.errors.append(str(error))

            # Anchors must follow every ownership change (splits, merged-range restores) before the summary pass:
            # summary input digests include key_items, so moving items afterwards would orphan their stamps.
            reconcile_key_items(root, revision, plan.mutable, plan.report)
            if not with_summaries:
                continue
            levels = _nodes_by_depth(root)
            for depth in sorted(levels, reverse=True):

                async def summarize(node: dict, revision: DocumentRevision = revision) -> None:
                    if id(node) not in plan.mutable:
                        return
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
                                summarize_leaf(node, revision, adapter if live else None, settings, report=plan.report)
                                if not node.get("nodes")
                                else compose_parent(
                                    node, revision, adapter if live else None, settings, report=plan.report
                                )
                            ),
                        )
                        node["summary"] = summary
                        node["optimizer"] = {**(node.get("optimizer") or {}), "summary": kind}
                        plan.report.summaries_written += 1
                        _record_stamp(plan, node, "summary", input_hash, execution)
                    except Exception as error:
                        plan.report.errors.append(str(error))

                results = await _limited_gather((summarize(node) for node in levels[depth]), return_exceptions=True)
                for result in results:
                    if isinstance(result, Exception):
                        plan.report.errors.append(str(result))
        refresh_after_counts(plan, revisions, settings)
    finally:
        if token is not None:
            _LLM_SEMAPHORE.reset(token)
