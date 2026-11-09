"""Deterministic PageIndex tree optimizer (FEAT-846, Module 1)."""

from __future__ import annotations

import hashlib
import json
import copy
import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from parrot.knowledge.pageindex import utils as _utils
from parrot.knowledge.pageindex.layout import running_key
from parrot.knowledge.pageindex.layout_structure import MAX_HEADING_WORDS, heading_title
from parrot.knowledge.pageindex.segments import (
    DocumentRevision,
    Segment,
    _heading_text,
    _subtract,
    _titles_match,
    normalize_title,
    validate_ownership,
)
from parrot.knowledge.pageindex.utils import structure_to_list

OPTIMIZER_VERSION = "v1"
Revisions = dict[tuple[str, str], DocumentRevision]
# A pseudo-heading title seen more often than this in one leaf is a running header/footer, not a heading.
PSEUDO_HEADING_MAX_REPEATS = 2
RUNNING_LINE_MIN_DENSITY = 0.8
"""Share of its page range a repeated paragraph title must cover to count as a running header or footer."""
_TRAILING_CONJUNCTIONS = frozenset({"and", "or", "nor", "y", "e", "o", "u", "ni"})
_LIST_MARKER_RE = re.compile(r"^(?:\(\w{1,4}\)|[a-z]\)|[-•*–])\s")


class OptimizerSettings(BaseModel):
    """Provisional defaults (tuned by optimizer_eval, TASK-5376)."""

    target_leaf_tokens: int = 1500
    min_leaf_tokens: int = 200
    inline_summary_tokens: int = 120
    summary_max_words: int = 60
    max_key_items: int = 8
    routing_tokens_per_child: int = 48
    max_depth: int = 8
    llm_passes: bool = True

    def settings_hash(self) -> str:
        """Return a stable, abbreviated digest of these settings."""
        raw = json.dumps(self.model_dump(), sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


class KeyItem(BaseModel):
    """An item anchored to a segment in a document revision."""

    label: str
    kind: Literal["literal", "abstractive"]
    seq: int
    page: Optional[int] = None
    ordinal: int = 0


class PassStamp(BaseModel):
    """Completion record for one optimizer pass."""

    version: str
    input: str
    settings: str
    execution: str
    at: str


class OptimizerStamp(BaseModel):
    """Optimizer pass records and the origin of the node summary."""

    passes: dict[Literal["headings", "key_items", "summary"], PassStamp] = Field(default_factory=dict)
    summary: Literal["inline", "llm", "composed", "none"] = "none"


class MergeAction(BaseModel):
    """A normalization merge recorded for the optimization report."""

    absorbed_concept_id: Optional[str]
    absorbed_title: str
    into_concept_id: Optional[str]
    into_title: str
    reason: Literal["duplicate_span", "empty", "under_minimum"]


class ExpandAction(BaseModel):
    """A leaf expansion recorded for the optimization report."""

    parent_title: str
    parent_concept_id: Optional[str]
    pieces: list[str]
    source: Literal["layout", "llm"]


class OptimizeReport(BaseModel):
    """Results and diagnostics for one optimizer plan."""

    tree_name: str = ""
    node_id: Optional[str] = None
    dry_run: bool = True
    generation_before: Optional[int] = None
    generation_after: Optional[int] = None
    documents: list[str] = Field(default_factory=list)
    nodes_before: int = 0
    nodes_after: int = 0
    leaves_over_target_before: int = 0
    leaves_over_target_after: int = 0
    merged: list[MergeAction] = Field(default_factory=list)
    expanded: list[ExpandAction] = Field(default_factory=list)
    key_items_added: int = 0
    summaries_written: int = 0
    repaired_gaps: int = 0
    skipped_locked: int = 0
    skipped_stamped: int = 0
    rejected_proposals: int = 0
    key_items_rehomed: int = 0
    llm_passes: str = "skipped (disabled)"
    llm_calls_estimated: int = 0
    llm_calls_made: int = 0
    errors: list[str] = Field(default_factory=list)
    settings: OptimizerSettings = Field(default_factory=OptimizerSettings)


class OptimizePlan:
    """A candidate tree (deep copy of the input) plus the report and the per-node LLM cache."""

    def __init__(self, candidate: dict[str, Any], report: OptimizeReport) -> None:
        self.candidate = candidate
        self.report = report
        self.mutable: set[int] = set()
        self.touched: set[int] = set()
        self.pending_stamps: dict[int, dict[str, PassStamp]] = {}
        self.llm_cache: dict[str, Any] = {}
        self.optimizable_roots: list[dict] = []


def _ranges_contiguous(ranges: list[list[int]]) -> bool:
    """Return whether ranges form one non-empty continuous interval."""
    if not ranges:
        return False
    ordered = sorted((int(start), int(end)) for start, end in ranges)
    if any(end <= start for start, end in ordered):
        return False
    return all(end == next_start for (_, end), (next_start, _) in zip(ordered, ordered[1:], strict=False))


def _merge_ranges(ranges: list[list[int]]) -> list[list[int]]:
    """Return sorted, maximal half-open ranges."""
    merged: list[list[int]] = []
    for start, end in sorted((int(start), int(end)) for start, end in ranges if end > start):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def owned_tokens(node: dict, revision: DocumentRevision) -> int:
    """Sum of ``segments[seq].tokens`` over the node's owned ranges."""
    total = 0
    for start, end in node.get("owned") or []:
        for seq in range(max(int(start), 0), min(int(end), len(revision.segments))):
            segment = revision.segments[seq]
            total += segment.tokens if segment.tokens is not None else _utils.count_tokens(segment.text)
    return total


def is_locked(node: dict) -> bool:
    """Return whether a node is explicitly locked."""
    return node.get("locked") is True


def optimizable_roots(tree: dict, revisions: Revisions, *, node_id: Optional[str] = None) -> list[dict]:
    """Return top-most imported roots in scope, excluding effective locks."""
    selected = tree
    selected_locked = False
    if node_id is not None:
        path: list[dict] = []

        def locate(node: dict, ancestors_locked: bool) -> bool:
            path.append(node)
            if node.get("node_id") == node_id:
                return True
            child_locked = ancestors_locked or is_locked(node)
            for child in node.get("nodes") or []:
                if locate(child, child_locked):
                    return True
            path.pop()
            return False

        if not locate(tree, False):
            raise KeyError(node_id)
        selected = path[-1]
        selected_locked = any(is_locked(ancestor) for ancestor in path[:-1])
    if selected_locked or is_locked(selected):
        return []

    roots: list[dict] = []

    def visit(node: dict, ancestor_locked: bool, imported_ancestor: bool) -> None:
        if ancestor_locked or is_locked(node):
            return
        imported = (node.get("doc_id"), node.get("revision")) in revisions
        if imported and not imported_ancestor:
            roots.append(node)
            return
        for child in node.get("nodes") or []:
            visit(child, False, imported_ancestor or imported)

    visit(selected, False, False)
    return roots


def repair_ownership(doc_nodes: list[dict], revision: DocumentRevision, report: OptimizeReport) -> list[str]:
    """Repair uncovered document ranges unless the current ownership overlaps."""
    problems = validate_ownership(doc_nodes, revision)
    overlaps = [problem for problem in problems if problem.startswith("overlap")]
    if overlaps:
        return overlaps

    owned: set[int] = set()
    for node in doc_nodes:
        for start, end in node.get("owned") or []:
            owned.update(range(max(int(start), 0), min(int(end), len(revision.segments))))
    gap_start: Optional[int] = None
    gaps: list[tuple[int, int]] = []
    for seq in range(len(revision.segments) + 1):
        uncovered = seq < len(revision.segments) and seq not in owned
        if uncovered and gap_start is None:
            gap_start = seq
        elif not uncovered and gap_start is not None:
            gaps.append((gap_start, seq))
            gap_start = None

    depths: dict[int, int] = {}

    def record_depth(node: dict, depth: int) -> None:
        depths[id(node)] = max(depths.get(id(node), 0), depth)
        for child in node.get("nodes") or []:
            record_depth(child, depth + 1)

    for document_node in doc_nodes:
        record_depth(document_node, 0)

    for start, end in gaps:
        candidates = [
            node
            for node in doc_nodes
            if not is_locked(node)
            and node.get("span")
            and int(node["span"][0]) <= start
            and int(node["span"][1]) >= end
        ]
        if not candidates:
            continue
        target = min(
            candidates,
            key=lambda node: (-depths.get(id(node), 0), int(node["span"][1]) - int(node["span"][0])),
        )
        target["owned"] = _merge_ranges(list(target.get("owned") or []) + [[start, end]])
        report.repaired_gaps += 1
    return []


def _record_merge(
    absorbed: dict, absorber: dict, reason: Literal["duplicate_span", "empty", "under_minimum"], report: OptimizeReport
) -> None:
    """Preserve absorbed identity and title, then record a merge action."""
    report.merged.append(
        MergeAction(
            absorbed_concept_id=absorbed.get("concept_id"),
            absorbed_title=absorbed.get("title", ""),
            into_concept_id=absorber.get("concept_id"),
            into_title=absorber.get("title", ""),
            reason=reason,
        )
    )


def _absorb(
    absorber: dict,
    absorbed: dict,
    reason: Literal["duplicate_span", "empty", "under_minimum"],
    report: OptimizeReport,
    revision: DocumentRevision,
) -> None:
    """Merge a leaf into another node, retaining the absorbed title and alias.

    When ``absorbed`` owns ranges, ``absorber["span"]`` is widened to cover their extent so that a later
    ``assign_ownership`` (which rebuilds a leaf's ``owned`` from its ``span``) keeps them with the absorber.
    An absorbed node without owned ranges adds no key item and leaves the span unchanged.
    """
    absorber["owned"] = _merge_ranges(list(absorber.get("owned") or []) + list(absorbed.get("owned") or []))
    absorbed_id = absorbed.get("concept_id")
    if absorbed_id:
        aliases = absorber.setdefault("aliases", [])
        if absorbed_id not in aliases:
            aliases.append(absorbed_id)
    for alias in absorbed.get("aliases") or []:
        aliases = absorber.setdefault("aliases", [])
        if alias not in aliases:
            aliases.append(alias)
    if absorbed.get("key_items"):
        absorber.setdefault("key_items", []).extend(absorbed["key_items"])
    ranges = absorbed.get("owned") or []
    if ranges:
        seq = int(ranges[0][0])
        segment = revision.segments[seq]
        key_item = KeyItem(
            label=absorbed.get("title", ""), kind="literal", seq=seq, page=segment.page, ordinal=segment.ordinal
        )
        absorber.setdefault("key_items", []).append(key_item.model_dump())
        report.key_items_added += 1
    if ranges and absorber.get("span"):
        # Keep the absorbed ranges with the absorber: assign_ownership rebuilds a leaf's owned from its span.
        absorber["span"] = [
            min(int(absorber["span"][0]), min(int(start) for start, _ in ranges)),
            max(int(absorber["span"][1]), max(int(end) for _, end in ranges)),
        ]
    _record_merge(absorbed, absorber, reason, report)


def normalize(
    parent_children: list[dict],
    revision: DocumentRevision,
    settings: OptimizerSettings,
    report: OptimizeReport,
    *,
    parent: Optional[dict] = None,
) -> None:
    """Collapse duplicate/empty leaves and contiguous undersized sibling leaves.

    An empty leaf (no children, no owned ranges) is absorbed into ``parent`` with reason ``"empty"`` (its
    ``concept_id`` becomes a parent alias) and removed. A published empty leaf (``node_id`` set) without a
    ``concept_id`` is kept, because its removal could never pass ``validate_candidate``. Without ``parent`` an
    empty leaf is removed unrecorded (legacy behaviour). The recursion passes each child as the ``parent`` of
    its own children.

    Args:
        parent_children: The sibling list to normalize in place.
        revision: The document revision the nodes are anchored to.
        settings: Optimizer settings (``min_leaf_tokens``).
        report: Report receiving merge actions and counters.
        parent: The node owning ``parent_children``; it absorbs empty leaves.
    """
    for child in parent_children:
        if not is_locked(child):
            normalize(child.get("nodes") or [], revision, settings, report, parent=child)

    index = 0
    while index < len(parent_children):
        node = parent_children[index]
        if is_locked(node):
            index += 1
            continue
        if not node.get("nodes") and not (node.get("owned") or []):
            if node.get("node_id") is not None and not node.get("concept_id"):
                # Published without an identity to alias: removing it could never pass validate_candidate.
                index += 1
                continue
            if parent is not None:
                _absorb(parent, node, "empty", report, revision)
            parent_children.pop(index)
            continue
        duplicate_index = next(
            (
                other_index
                for other_index in range(index + 1, len(parent_children))
                if not is_locked(parent_children[other_index])
                and node.get("span") == parent_children[other_index].get("span")
            ),
            None,
        )
        if duplicate_index is not None:
            absorbed = parent_children.pop(duplicate_index)
            _absorb(node, absorbed, "duplicate_span", report, revision)
            continue
        index += 1

    index = 0
    while index < len(parent_children):
        node = parent_children[index]
        if is_locked(node) or node.get("nodes") or owned_tokens(node, revision) >= settings.min_leaf_tokens:
            index += 1
            continue
        choices = [index - 1, index + 1]
        absorber_index = next(
            (
                candidate
                for candidate in choices
                if 0 <= candidate < len(parent_children)
                and not is_locked(parent_children[candidate])
                and not parent_children[candidate].get("nodes")
                and _ranges_contiguous(
                    list(node.get("owned") or []) + list(parent_children[candidate].get("owned") or [])
                )
            ),
            None,
        )
        if absorber_index is None:
            index += 1
            continue
        absorber = parent_children[absorber_index]
        _absorb(absorber, node, "under_minimum", report, revision)
        parent_children.pop(index)


def assign_ownership(node: dict) -> None:
    """Assign parent residual ranges after recursively widening child spans."""
    if is_locked(node):
        return
    children = node.get("nodes") or []
    for child in children:
        assign_ownership(child)
    spans = [tuple(child["span"]) for child in children if child.get("span")]
    if node.get("span"):
        spans.append(tuple(node["span"]))
    if not spans:
        return
    start = min(span[0] for span in spans)
    end = max(span[1] for span in spans)
    node["span"] = [start, end]
    node["owned"] = [
        list(rng) for rng in _subtract((start, end), [tuple(child["span"]) for child in children if child.get("span")])
    ]


def is_heading_text(title: str) -> bool:
    """Return whether a cleaned, single-line title reads as a printed heading.

    False for empty or multi-line text, more than ``MAX_HEADING_WORDS`` words, a trailing ``.``, ``;``, ``:`` or
    ``,``, a lower-case last word that is a conjunction (and, or, nor, y, e, o, u, ni), or a list-marker prefix
    (``(a) ``, ``a) ``, ``(iv) ``, ``- ``, ``• ``, ``* ``). Numbered headings such as ``1. Introduction`` and
    appendix labels such as ``Appendix E`` stay valid.

    Args:
        title: The title text, already cleaned with ``heading_title``.

    Returns:
        True when the text can be accepted as a heading.
    """
    text = (title or "").strip()
    if not text or "\n" in text:
        return False
    words = text.split()
    if len(words) > MAX_HEADING_WORDS or text.endswith((".", ";", ":", ",")):
        return False
    last = words[-1].strip("!?\"'()[]")
    if last.islower() and last in _TRAILING_CONJUNCTIONS:
        return False
    return _LIST_MARKER_RE.match(text) is None


def heading_segments(node: dict, revision: DocumentRevision) -> list[Segment]:
    """Return owned heading segments, excluding a matching first title heading."""
    headings = [
        segment
        for start, end in node.get("owned") or []
        for segment in revision.segments[max(int(start), 0) : min(int(end), len(revision.segments))]
        if segment.kind == "heading"
    ]
    if headings and _titles_match(
        normalize_title(node.get("title", "")), normalize_title(_heading_text(headings[0].text))
    ):
        return headings[1:]
    return headings


def _is_emphasis_wrapped(text: str) -> bool:
    """Return whether a stripped line is fully wrapped in bold/underline emphasis markers."""
    return len(text) > 4 and (
        (text.startswith("**") and text.endswith("**")) or (text.startswith("__") and text.endswith("__"))
    )


def _is_upper_case(title: str) -> bool:
    """Return whether every cased letter of ``title`` (at least two) is upper case."""
    cased = [char for char in title if char.isalpha() and char.lower() != char.upper()]
    return len(cased) >= 2 and all(char.isupper() for char in cased)


def document_running_keys(revision: DocumentRevision) -> frozenset[str]:
    """Return the ``running_key`` of every paragraph title that runs through the revision as a header or footer.

    A key qualifies when its paged ``paragraph`` segments sit on more than ``PSEUDO_HEADING_MAX_REPEATS`` distinct
    pages, never twice on one page, and those pages cover at least ``RUNNING_LINE_MIN_DENSITY`` of the page range they
    span. Segments without a page are ignored, so an unpaged revision returns an empty set.

    Args:
        revision: The document revision whose paragraphs are scanned.

    Returns:
        The running keys of the revision's running headers and footers.
    """
    pages_by_key: dict[str, list[int]] = {}
    for segment in revision.segments:
        if segment.kind == "paragraph" and segment.page is not None:
            pages_by_key.setdefault(running_key(heading_title(segment.text)), []).append(int(segment.page))
    keys: set[str] = set()
    for key, pages in pages_by_key.items():
        distinct = set(pages)
        if len(distinct) <= PSEUDO_HEADING_MAX_REPEATS or len(distinct) != len(pages):
            continue
        if len(distinct) / (max(distinct) - min(distinct) + 1) >= RUNNING_LINE_MIN_DENSITY:
            keys.add(key)
    return frozenset(keys)


def pseudo_heading_segments(
    node: dict, revision: DocumentRevision, *, running_keys: Optional[frozenset[str]] = None
) -> list[Segment]:
    """Return owned single-line paragraph segments that read as headings.

    A candidate is a ``paragraph`` segment whose stripped text is one line, either fully wrapped in emphasis
    (starts and ends with ``**`` or ``__``; split runs such as ``**P****ROLOGO**`` included) or whose cased letters
    (at least two) are all upper case, and whose ``heading_title`` passes ``is_heading_text``. Titles occurring more
    than ``PSEUDO_HEADING_MAX_REPEATS`` times among the node's owned paragraphs are dropped (running headers and
    footers), as are titles whose ``running_key`` is a running line of the whole document (``running_keys``), and a
    first candidate whose title matches the node title (same rule as ``heading_segments``).

    Args:
        node: The leaf whose owned segments are scanned.
        revision: The document revision the node is anchored to.
        running_keys: The document's running-line keys; ``None`` computes ``document_running_keys(revision)``.

    Returns:
        The candidate segments in document order.
    """
    running = document_running_keys(revision) if running_keys is None else running_keys
    paragraphs = [
        segment
        for start, end in node.get("owned") or []
        for segment in revision.segments[max(int(start), 0) : min(int(end), len(revision.segments))]
        if segment.kind == "paragraph"
    ]
    counts: dict[str, int] = {}
    for segment in paragraphs:
        key = running_key(heading_title(segment.text))
        counts[key] = counts.get(key, 0) + 1
    candidates: list[Segment] = []
    for segment in paragraphs:
        text = (segment.text or "").strip()
        if not text or "\n" in text:
            continue
        title = heading_title(text)
        if not (_is_emphasis_wrapped(text) or _is_upper_case(title)) or not is_heading_text(title):
            continue
        key = running_key(title)
        if counts.get(key, 0) > PSEUDO_HEADING_MAX_REPEATS or key in running:
            continue
        candidates.append(segment)
    if candidates and _titles_match(
        normalize_title(node.get("title", "")), normalize_title(heading_title(candidates[0].text))
    ):
        return candidates[1:]
    return candidates


def _coalesce_split_points(
    node: dict, revision: DocumentRevision, seqs: list[int], settings: OptimizerSettings
) -> list[int]:
    """Return the split points that leave no piece under ``settings.min_leaf_tokens``.

    Walks the sorted points: a point whose piece since the last kept point is under the minimum is dropped
    (merged forward); if the final piece is under the minimum and more than one point is kept, the last kept point
    is dropped (merged backward). Token counts use ``owned_tokens`` over the owned ranges between points.

    Args:
        node: The leaf about to be split.
        revision: The document revision the node is anchored to.
        seqs: Candidate split sequences.
        settings: Optimizer settings (``min_leaf_tokens``).

    Returns:
        The kept split points, sorted.
    """
    owned = list(node.get("owned") or [])
    if not owned:
        return []
    points = sorted({int(seq) for seq in seqs if any(int(start) <= int(seq) < int(end) for start, end in owned)})
    final_end = max(int(end) for _, end in owned)

    def piece_tokens(start: int, end: int) -> int:
        return owned_tokens({"owned": _owned_in_span(owned, start, end)}, revision)

    kept: list[int] = []
    for seq in points:
        if kept and piece_tokens(kept[-1], seq) < settings.min_leaf_tokens:
            continue
        kept.append(seq)
    if len(kept) > 1 and piece_tokens(kept[-1], final_end) < settings.min_leaf_tokens:
        kept.pop()
    return kept


def routing_cost(pieces: list[dict], revision: DocumentRevision, settings: OptimizerSettings) -> int:
    """Return estimated routing tokens for proposed child pieces."""
    cost = 0
    for piece in pieces:
        title_tokens = _utils.count_tokens(str(piece.get("title", "")))
        summary = piece.get("summary")
        cost += title_tokens + (
            _utils.count_tokens(str(summary)) if summary is not None else settings.routing_tokens_per_child
        )
    return cost


def should_expand(node_tokens: int, piece_tokens: list[int], cost: int, settings: OptimizerSettings) -> bool:
    """Return whether a split reduces scanning cost without undersized pieces."""
    if not piece_tokens:
        return False
    return cost + max(piece_tokens) < node_tokens and min(piece_tokens) >= settings.min_leaf_tokens


def _owned_in_span(owned: list[list[int]], start: int, end: int) -> list[list[int]]:
    """Return the intersection of owned ranges with one half-open span."""
    return [
        [max(start, int(left)), min(end, int(right))]
        for left, right in owned
        if max(start, int(left)) < min(end, int(right))
    ]


def _item_seq(item: Any) -> int:
    """Return the anchor sequence of a key item stored as a dict or a ``KeyItem``."""
    return int(item["seq"] if isinstance(item, dict) else item.seq)


def _item_key(item: Any) -> tuple[Any, int]:
    """Return the ``(label, seq)`` identity of a key item stored as a dict or a ``KeyItem``."""
    label = item.get("label") if isinstance(item, dict) else item.label
    return label, _item_seq(item)


def _owns_seq(node: dict, seq: int) -> bool:
    """Return whether ``seq`` lies inside one of the node's half-open owned ranges."""
    return any(int(start) <= seq < int(end) for start, end in node.get("owned") or [])


def _add_key_item(node: dict, item: Any) -> bool:
    """Append ``item`` to the node's key items unless an item with the same label and anchor is there."""
    existing = node.setdefault("key_items", [])
    if _item_key(item) in {_item_key(other) for other in existing}:
        return False
    existing.append(item)
    return True


def _move_key_items_to_pieces(node: dict, pieces: list[dict], report: OptimizeReport) -> None:
    """Move key items of a just-split node onto the piece whose owned ranges now hold their anchor.

    Args:
        node: The node that ``split_at`` turned into a parent (its ``owned`` is already the residual).
        pieces: The new child pieces.
        report: Report whose ``key_items_rehomed`` counts every moved item.
    """
    items = node.get("key_items")
    if not items:
        return
    kept: list[Any] = []
    for item in items:
        seq = _item_seq(item)
        target = None if _owns_seq(node, seq) else next((piece for piece in pieces if _owns_seq(piece, seq)), None)
        if target is None:
            kept.append(item)
            continue
        _add_key_item(target, item)
        report.key_items_rehomed += 1
    if kept:
        node["key_items"] = kept
    else:
        node.pop("key_items", None)


def _piece_pages(piece: dict, revision: DocumentRevision) -> Optional[tuple[int, int]]:
    """Return the first and last page of a piece's owned segments, or ``None`` when none is paged."""
    pages = [
        segment.page
        for start, end in piece.get("owned") or []
        for segment in revision.segments[max(int(start), 0) : min(int(end), len(revision.segments))]
        if segment.page is not None
    ]
    return (min(pages), max(pages)) if pages else None


def split_at(
    node: dict,
    revision: DocumentRevision,
    seqs: list[int],
    *,
    source: str,
    settings: OptimizerSettings,
    report: OptimizeReport,
) -> list[dict]:
    """Create children at valid owned split sequences when the cost model permits it."""
    owned = list(node.get("owned") or [])
    valid_seqs = sorted(
        {
            int(seq)
            for seq in seqs
            if any(int(start) <= int(seq) < int(end) for start, end in owned) and 0 <= int(seq) < len(revision.segments)
        }
    )
    if not valid_seqs:
        return []
    final_end = max(int(end) for _, end in owned)
    pieces: list[dict] = []
    for index, seq in enumerate(valid_seqs):
        end = valid_seqs[index + 1] if index + 1 < len(valid_seqs) else final_end
        piece_owned = _owned_in_span(owned, seq, end)
        if not piece_owned:
            continue
        pieces.append(
            {
                "doc_id": node.get("doc_id"),
                "revision": node.get("revision"),
                "span": [seq, end],
                "owned": piece_owned,
                "title": heading_title(revision.segments[seq].text),
                "nodes": [],
            }
        )
    piece_tokens = [owned_tokens(piece, revision) for piece in pieces]
    if not should_expand(
        owned_tokens(node, revision), piece_tokens, routing_cost(pieces, revision, settings), settings
    ):
        return []
    node["nodes"] = pieces
    assign_ownership(node)
    for piece in pieces:
        pages = _piece_pages(piece, revision)
        if pages is not None:
            piece["start_index"], piece["end_index"] = pages
    _move_key_items_to_pieces(node, pieces, report)
    report.expanded.append(
        ExpandAction(
            parent_title=node.get("title", ""),
            parent_concept_id=node.get("concept_id"),
            pieces=[piece["title"] for piece in pieces],
            source=source,
        )
    )
    return pieces


def expand_at_headings(
    node: dict,
    revision: DocumentRevision,
    settings: OptimizerSettings,
    report: OptimizeReport,
    *,
    depth: int,
    running_keys: Optional[frozenset[str]] = None,
) -> None:
    """Recursively expand oversized leaves at their shallowest owned heading level.

    When the leaf owns no usable heading segment, it falls back to ``pseudo_heading_segments`` (standalone bold or
    upper-case lines) and drops split points that would leave a piece under ``min_leaf_tokens``
    (``_coalesce_split_points``) before ``split_at``; the expand action's source stays ``"layout"``. The document's
    running-line keys are computed once (``document_running_keys``) when ``running_keys`` is ``None`` and passed down
    the recursion.
    """
    if is_locked(node) or depth >= settings.max_depth:
        return
    if running_keys is None:
        running_keys = document_running_keys(revision)
    children = node.get("nodes") or []
    if children:
        for child in children:
            expand_at_headings(child, revision, settings, report, depth=depth + 1, running_keys=running_keys)
        assign_ownership(node)
        return
    if owned_tokens(node, revision) <= settings.target_leaf_tokens:
        return
    headings = [
        segment
        for segment in heading_segments(node, revision)
        if segment.level is not None and len(heading_title(segment.text).split()) <= MAX_HEADING_WORDS
    ]
    if headings:
        shallowest = min(segment.level for segment in headings if segment.level is not None)
        seqs = [segment.seq for segment in headings if segment.level == shallowest]
    else:
        candidates = pseudo_heading_segments(node, revision, running_keys=running_keys)
        seqs = _coalesce_split_points(node, revision, [segment.seq for segment in candidates], settings)
        if not seqs:
            return
    pieces = split_at(node, revision, seqs, source="layout", settings=settings, report=report)
    for piece in pieces:
        expand_at_headings(piece, revision, settings, report, depth=depth + 1, running_keys=running_keys)


def _digest(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]


def stamp_input(node: dict) -> str:
    """Return the digest of structural inputs consumed by optimizer passes."""
    kids = [(child.get("title"), child.get("span")) for child in node.get("nodes") or []]
    return _digest([node.get("doc_id"), node.get("revision"), node.get("owned"), node.get("title"), kids])


def pass_input(node: dict, pass_name: str) -> str:
    """Return the digest of structural input and dependencies consumed by a pass."""
    structural = stamp_input(node)
    if pass_name in {"headings", "key_items"}:
        return structural
    if pass_name == "summary":
        children = [
            (child.get("title"), child.get("summary"), child.get("key_items"), child.get("span"))
            for child in node.get("nodes") or []
        ]
        return _digest([structural, node.get("key_items"), children])
    raise ValueError(f"Unknown optimizer pass: {pass_name}")


def pass_cache_key(pass_name: str, input_hash: str, execution: str, settings: OptimizerSettings) -> str:
    """Return the retry-cache key for one pass invocation."""
    return _digest([pass_name, OPTIMIZER_VERSION, settings.settings_hash(), input_hash, execution])


def is_stamped(node: dict, settings: OptimizerSettings, *, pass_name: str, input_hash: str, execution: str) -> bool:
    """Return whether a matching completion record exists for this pass."""
    optimizer = node.get("optimizer")
    if not isinstance(optimizer, dict):
        return False
    record = optimizer.get("passes", {}).get(pass_name)
    if not isinstance(record, dict):
        return False
    return (
        record.get("version") == OPTIMIZER_VERSION
        and record.get("settings") == settings.settings_hash()
        and record.get("input") == input_hash
        and record.get("execution") == execution
    )


def finalize_stamps(plan: OptimizePlan) -> None:
    """Persist valid pending completion records for mutable candidate nodes only."""
    for node in structure_to_list(plan.candidate):
        if id(node) not in plan.mutable:
            continue
        pending = plan.pending_stamps.get(id(node), {})
        if not pending:
            continue
        optimizer = node.get("optimizer")
        if not isinstance(optimizer, dict):
            optimizer = {}
            node["optimizer"] = optimizer
        passes = optimizer.setdefault("passes", {})
        for pass_name, record in pending.items():
            if record.input != pass_input(node, pass_name):
                continue
            if is_stamped(
                node,
                plan.report.settings,
                pass_name=pass_name,
                input_hash=record.input,
                execution=record.execution,
            ):
                continue
            passes[pass_name] = record.model_dump()


def _document_nodes(root: dict, doc_id: str, revision: str) -> list[dict]:
    """Return all nodes in a document subtree for one document revision."""
    return [
        node for node in structure_to_list(root) if node.get("doc_id") == doc_id and node.get("revision") == revision
    ]


def reconcile_key_items(root: dict, revision: DocumentRevision, mutable: set[int], report: OptimizeReport) -> None:
    """Re-home or drop key items whose anchor is outside their node's owned ranges.

    Scans the nodes of ``root``'s document revision. For each node whose ``id()`` is in ``mutable``, a key item
    (dict or ``KeyItem``) whose ``seq`` is not inside the node's ``owned`` ranges moves to the node of the same
    document revision whose ``owned`` ranges contain ``seq`` when that node is in ``mutable``, skipping a duplicate
    ``(label, seq)`` already there (``report.key_items_rehomed += 1``). Otherwise the item is dropped
    (``report.rejected_proposals += 1``). Nodes outside ``mutable`` are never modified.

    Args:
        root: The imported document root to scan.
        revision: The document revision the nodes are anchored to.
        mutable: ``id()`` of the nodes the optimizer may change.
        report: Report receiving the move and drop counters.
    """
    nodes = _document_nodes(root, revision.doc_id, revision.revision)
    owners: dict[int, dict] = {}
    for node in nodes:
        for start, end in node.get("owned") or []:
            for seq in range(int(start), int(end)):
                owners.setdefault(seq, node)
    for node in nodes:
        if id(node) not in mutable or not node.get("key_items"):
            continue
        kept: list[Any] = []
        for item in node["key_items"]:
            seq = _item_seq(item)
            if _owns_seq(node, seq):
                kept.append(item)
                continue
            owner = owners.get(seq)
            if owner is not None and id(owner) in mutable:
                _add_key_item(owner, item)
                report.key_items_rehomed += 1
            else:
                report.rejected_proposals += 1
        if kept:
            node["key_items"] = kept
        else:
            node.pop("key_items", None)


def plan_deterministic(
    tree: dict, revisions: Revisions, settings: OptimizerSettings, *, tree_name: str, node_id: Optional[str] = None
) -> OptimizePlan:
    """Build a deterministic candidate without writing completion stamps."""
    candidate = copy.deepcopy(tree)
    report = OptimizeReport(tree_name=tree_name, node_id=node_id, dry_run=True, settings=settings)
    plan = OptimizePlan(candidate, report)
    report.nodes_before = len(structure_to_list(candidate))
    roots = optimizable_roots(candidate, revisions, node_id=node_id)
    report.documents = sorted({str(root["doc_id"]) for root in roots})
    for root in roots:
        key = (root["doc_id"], root["revision"])
        revision = revisions[key]
        doc_nodes = _document_nodes(root, *key)
        problems = repair_ownership(doc_nodes, revision, report)
        if problems:
            report.errors.extend(problems)
            continue
        normalize(root.get("nodes") or [], revision, settings, report, parent=root)
        assign_ownership(root)
        expand_at_headings(root, revision, settings, report, depth=0)
        assign_ownership(root)

    def mark_mutable(node: dict, ancestor_locked: bool = False) -> None:
        locked = ancestor_locked or is_locked(node)
        if locked:
            report.skipped_locked += 1
        else:
            plan.mutable.add(id(node))
            plan.touched.add(id(node))
        for child in node.get("nodes") or []:
            mark_mutable(child, locked)

    for root in roots:
        mark_mutable(root)
    plan.optimizable_roots = roots
    for root in roots:
        reconcile_key_items(root, revisions[(root["doc_id"], root["revision"])], plan.mutable, report)
    before_roots = optimizable_roots(tree, revisions, node_id=node_id)
    report.leaves_over_target_before = leaves_over_target(before_roots, revisions, settings)
    refresh_after_counts(plan, revisions, settings)
    return plan


def refresh_after_counts(plan: OptimizePlan, revisions: Revisions, settings: OptimizerSettings) -> None:
    """Recompute the report's ``*_after`` counters from the current candidate (call after any structural pass)."""
    plan.report.nodes_after = len(structure_to_list(plan.candidate))
    plan.report.leaves_over_target_after = leaves_over_target(plan.optimizable_roots, revisions, settings)


def _node_fields(node: dict) -> dict:
    """Return stable node fields used to compare protected nodes."""
    return {key: value for key, value in node.items() if key not in {"node_id", "nodes"}}


def validate_candidate(plan: OptimizePlan, revisions: Revisions, *, base_tree: dict) -> list[str]:
    """Validate ownership, key-item anchors, and protected-node immutability."""
    errors: list[str] = []
    nodes = structure_to_list(plan.candidate)
    for (doc_id, revision_id), revision in revisions.items():
        document_nodes = [
            node for node in nodes if node.get("doc_id") == doc_id and node.get("revision") == revision_id
        ]
        errors.extend(validate_ownership(document_nodes, revision))
        for node in document_nodes:
            for item in node.get("key_items") or []:
                seq = item.get("seq") if isinstance(item, dict) else item.seq
                if not any(int(start) <= seq < int(end) for start, end in node.get("owned") or []):
                    errors.append(f"key_item anchor {seq} is outside owned ranges for {node.get('title', '')}")
    candidate_by_id = {node.get("node_id"): node for node in nodes if node.get("node_id") is not None}
    absorbed_aliases = {alias for node in nodes for alias in node.get("aliases") or []}
    for base_node in structure_to_list(base_tree):
        node_id = base_node.get("node_id")
        if node_id is None:
            continue
        candidate_node = candidate_by_id.get(node_id)
        if candidate_node is None:
            # A node merged into a sibling during normalization survives as that sibling's alias.
            if base_node.get("concept_id") and base_node["concept_id"] in absorbed_aliases:
                continue
            errors.append(f"protected node {node_id} was removed")
        elif id(candidate_node) not in plan.mutable and _node_fields(candidate_node) != _node_fields(base_node):
            errors.append(f"protected node {node_id} changed")
    return errors


def leaves_over_target(nodes: list[dict], revisions: Revisions, settings: OptimizerSettings) -> int:
    """Count oversized leaf nodes in the supplied document roots."""
    count = 0
    for root in nodes:
        for node in structure_to_list(root):
            if node.get("nodes"):
                continue
            revision = revisions.get((node.get("doc_id"), node.get("revision")))
            if revision is not None and owned_tokens(node, revision) > settings.target_leaf_tokens:
                count += 1
    return count
