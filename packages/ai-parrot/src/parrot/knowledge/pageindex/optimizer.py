"""Deterministic PageIndex tree optimizer (FEAT-846, Module 1)."""

from __future__ import annotations

import hashlib
import json
import copy
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from parrot.knowledge.pageindex import utils as _utils
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


def _ranges_contiguous(ranges: list[list[int]]) -> bool:
    """Return whether ranges form one non-empty continuous interval."""
    if not ranges:
        return False
    ordered = sorted((int(start), int(end)) for start, end in ranges)
    if any(end <= start for start, end in ordered):
        return False
    return all(end == next_start for (_, end), (next_start, _) in zip(ordered, ordered[1:]))


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
    """Merge a leaf into another leaf while retaining the absorbed title and alias."""
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
    _record_merge(absorbed, absorber, reason, report)


def normalize(
    parent_children: list[dict], revision: DocumentRevision, settings: OptimizerSettings, report: OptimizeReport
) -> None:
    """Collapse duplicate/empty leaves and contiguous undersized sibling leaves."""
    for child in parent_children:
        if not is_locked(child):
            normalize(child.get("nodes") or [], revision, settings, report)

    index = 0
    while index < len(parent_children):
        node = parent_children[index]
        if is_locked(node):
            index += 1
            continue
        if not node.get("nodes") and not (node.get("owned") or []):
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
    node: dict, revision: DocumentRevision, settings: OptimizerSettings, report: OptimizeReport, *, depth: int
) -> None:
    """Recursively expand oversized leaves at their shallowest owned heading level."""
    if is_locked(node) or depth >= settings.max_depth:
        return
    children = node.get("nodes") or []
    if children:
        for child in children:
            expand_at_headings(child, revision, settings, report, depth=depth + 1)
        assign_ownership(node)
        return
    if owned_tokens(node, revision) <= settings.target_leaf_tokens:
        return
    headings = [
        segment
        for segment in heading_segments(node, revision)
        if segment.level is not None and len(heading_title(segment.text).split()) <= MAX_HEADING_WORDS
    ]
    if not headings:
        return
    shallowest = min(segment.level for segment in headings if segment.level is not None)
    pieces = split_at(
        node,
        revision,
        [segment.seq for segment in headings if segment.level == shallowest],
        source="layout",
        settings=settings,
        report=report,
    )
    for piece in pieces:
        expand_at_headings(piece, revision, settings, report, depth=depth + 1)


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
        normalize(root.get("nodes") or [], revision, settings, report)
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
    report.nodes_after = len(structure_to_list(candidate))
    before_roots = optimizable_roots(tree, revisions, node_id=node_id)
    report.leaves_over_target_before = leaves_over_target(before_roots, revisions, settings)
    report.leaves_over_target_after = leaves_over_target(roots, revisions, settings)
    return plan


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
