"""Deterministic PageIndex tree optimizer (FEAT-846, Module 1)."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from parrot.knowledge.pageindex import utils as _utils
from parrot.knowledge.pageindex.segments import DocumentRevision, _subtract, validate_ownership

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


def _record_merge(absorbed: dict, absorber: dict, reason: Literal["duplicate_span", "empty", "under_minimum"],
                  report: OptimizeReport) -> None:
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


def _absorb(absorber: dict, absorbed: dict, reason: Literal["duplicate_span", "empty", "under_minimum"],
            report: OptimizeReport, revision: DocumentRevision) -> None:
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
        key_item = KeyItem(label=absorbed.get("title", ""), kind="literal", seq=seq,
                           page=segment.page, ordinal=segment.ordinal)
        absorber.setdefault("key_items", []).append(key_item.model_dump())
        report.key_items_added += 1
    _record_merge(absorbed, absorber, reason, report)


def normalize(parent_children: list[dict], revision: DocumentRevision, settings: OptimizerSettings,
              report: OptimizeReport) -> None:
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
                and _ranges_contiguous(list(node.get("owned") or []) + list(parent_children[candidate].get("owned") or []))
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
    node["owned"] = [list(rng) for rng in _subtract((start, end), [tuple(child["span"]) for child in children if child.get("span")])]
