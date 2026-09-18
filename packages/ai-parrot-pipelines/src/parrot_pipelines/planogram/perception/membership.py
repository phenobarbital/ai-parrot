"""Evidence-based fixture membership: on / off / uncertain (FEAT-574). Pure and deterministic.

Expected-SKU agreement is deliberately NOT an input: membership comes from spatial evidence only.
"""

from __future__ import annotations

from statistics import median
from typing import Dict, List, Optional, Sequence, Tuple

from ..contracts import FixtureMembership, Shape

_COLUMN_MARGIN = 0.10  # anchor column is widened by this fraction of its width (each side)
_OFF_MARGIN = 0.25  # beyond this fraction of the column width outside it => off
_MAX_GAP_PITCHES = 1.75  # larger x-gap between row neighbours breaks continuity
_BLOCK_OVERLAP = 0.50  # rows belong to one block when their x-extents overlap this much
_SINGLE_ROW_SPAN = 0.50  # a lone row is a block when it spans this fraction of the image width
_CONTAIN_EXPAND = 0.10  # container box expansion for containment votes
_Vote = Tuple[Optional[bool], str]  # (True=on | False=off | None=no vote, reason)


def _centre(shape: Shape) -> Tuple[float, float]:
    """Box centre in source pixels."""
    box = shape.box
    return (box.x1 + box.x2) / 2.0, (box.y1 + box.y2) / 2.0


def _degenerate(shape: Shape) -> bool:
    """True when the box has no area."""
    return shape.box.x2 <= shape.box.x1 or shape.box.y2 <= shape.box.y1


def _anchor_votes(shapes: Sequence[Shape], zones: Sequence[Shape]) -> Dict[str, _Vote]:
    """Votes from the fixture column spanned by zone anchors. {} when there are no zones.

    Args:
        shapes: Observations to vote on.
        zones: Zone anchors (degenerate boxes are ignored).

    Returns:
        ``shape_id -> vote`` for shapes that received an on/off vote.
    """
    valid = [z for z in zones if not _degenerate(z)]
    if not valid:
        return {}
    lo = min(z.box.x1 for z in valid)
    hi = max(z.box.x2 for z in valid)
    width = max(1.0, float(hi - lo))
    on_lo, on_hi = lo - _COLUMN_MARGIN * width, hi + _COLUMN_MARGIN * width
    off_lo, off_hi = lo - _OFF_MARGIN * width, hi + _OFF_MARGIN * width
    votes: Dict[str, _Vote] = {}
    for shape in shapes:
        cx, _ = _centre(shape)
        if on_lo <= cx <= on_hi:
            votes[shape.shape_id] = (True, "anchor_column")
        elif cx < off_lo or cx > off_hi:
            votes[shape.shape_id] = (False, "outside_anchor_column")
    return votes


def _clusters(row: List[Shape], pitch: float) -> List[List[Shape]]:
    """Split a row (sorted by x centre) where the centre gap exceeds ``_MAX_GAP_PITCHES`` pitches."""
    groups: List[List[Shape]] = [[row[0]]]
    for previous, current in zip(row, row[1:], strict=False):
        if _centre(current)[0] - _centre(previous)[0] > _MAX_GAP_PITCHES * pitch:
            groups.append([current])
        else:
            groups[-1].append(current)
    return groups


def _extent(group: Sequence[Shape]) -> Tuple[int, int]:
    """Horizontal extent of a group of shapes."""
    return min(s.box.x1 for s in group), max(s.box.x2 for s in group)


def _row_block_votes(shapes: Sequence[Shape], image_size: Tuple[int, int]) -> Dict[str, _Vote]:
    """Votes from a coherent block of rows (shapes with row_index). {} when no coherent block exists.

    Each row is split into x-contiguous clusters (gap ≤ ``_MAX_GAP_PITCHES`` × the median neighbour
    pitch over all rows); the largest cluster of a row is its main run. The block is the set of main
    runs overlapping the largest main run by ≥ 50 %; it is coherent with ≥ 2 rows, or with one row
    spanning ≥ 50 % of the image width.

    Args:
        shapes: Observations (only those with ``row_index`` take part).
        image_size: ``(width, height)`` of the source image.

    Returns:
        ``shape_id -> vote``: block members ``on`` (``row_block``), other clusters of block rows ``off``
        (``row_gap``).
    """
    rows: Dict[int, List[Shape]] = {}
    for shape in shapes:
        if shape.row_index is not None and not _degenerate(shape):
            rows.setdefault(shape.row_index, []).append(shape)
    if not rows:
        return {}
    for members in rows.values():
        members.sort(key=lambda s: (_centre(s)[0], s.shape_id))
    distances = [
        _centre(b)[0] - _centre(a)[0]
        for members in rows.values()
        for a, b in zip(members, members[1:], strict=False)
        if _centre(b)[0] > _centre(a)[0]
    ]
    pitch = median(distances) if distances else float(image_size[0])

    row_clusters = {index: _clusters(members, pitch) for index, members in rows.items()}
    main_runs = {index: max(groups, key=lambda g: (len(g), -_extent(g)[0])) for index, groups in row_clusters.items()}
    reference_row = max(main_runs, key=lambda i: (len(main_runs[i]), -i))
    ref_lo, ref_hi = _extent(main_runs[reference_row])

    block_rows: List[int] = []
    for index, run in main_runs.items():
        lo, hi = _extent(run)
        overlap = max(0, min(hi, ref_hi) - max(lo, ref_lo))
        if overlap >= _BLOCK_OVERLAP * max(1, min(hi - lo, ref_hi - ref_lo)):
            block_rows.append(index)
    coherent = len(block_rows) >= 2 or (ref_hi - ref_lo) >= _SINGLE_ROW_SPAN * image_size[0]
    if not coherent:
        return {}

    votes: Dict[str, _Vote] = {}
    for index in block_rows:
        main_ids = {s.shape_id for s in main_runs[index]}
        for group in row_clusters[index]:
            for shape in group:
                votes[shape.shape_id] = (True, "row_block") if shape.shape_id in main_ids else (False, "row_gap")
    return votes


def _containment_votes(shapes: Sequence[Shape], on_ids: Sequence[str]) -> Dict[str, _Vote]:
    """'on' votes for shapes whose centre lies inside an already-on shape expanded by 10 %.

    Args:
        shapes: Observations.
        on_ids: Ids provisionally on the fixture (containers).

    Returns:
        ``shape_id -> ("on", "contained_in:<container id>")`` — never for the container itself, one pass only.
    """
    on_set = set(on_ids)
    containers = [s for s in shapes if s.shape_id in on_set and not _degenerate(s)]
    votes: Dict[str, _Vote] = {}
    for shape in shapes:
        cx, cy = _centre(shape)
        for container in containers:
            if container.shape_id == shape.shape_id:
                continue
            box = container.box
            dx = _CONTAIN_EXPAND * (box.x2 - box.x1)
            dy = _CONTAIN_EXPAND * (box.y2 - box.y1)
            if box.x1 - dx <= cx <= box.x2 + dx and box.y1 - dy <= cy <= box.y2 + dy:
                votes[shape.shape_id] = (True, f"contained_in:{container.shape_id}")
                break
    return votes


def _combine(votes: Sequence[_Vote]) -> Tuple[FixtureMembership, List[str]]:
    """Apply combination rules 1-3 of the task's evidence policy.

    Args:
        votes: Votes of one shape (``None`` votes carry no evidence).

    Returns:
        ``(membership, evidence reasons)``.
    """
    cast = [(value, reason) for value, reason in votes if value is not None]
    reasons = [reason for _, reason in cast]
    has_on = any(value for value, _ in cast)
    has_off = any(value is False for value, _ in cast)
    if has_on and not has_off:
        return FixtureMembership.ON_FIXTURE, reasons
    if has_off and not has_on:
        return FixtureMembership.OFF_FIXTURE, reasons
    if has_on and has_off:
        return FixtureMembership.UNCERTAIN, reasons
    return FixtureMembership.UNCERTAIN, ["no_anchor_evidence"]


def assign_membership(
    shapes: Sequence[Shape],
    zones: Sequence[Shape],
    image_size: Tuple[int, int],
    *,
    llm_hints: Optional[Dict[str, FixtureMembership]] = None,
) -> List[Shape]:
    """Label every shape on_fixture / off_fixture / uncertain from spatial evidence.

    Args:
        shapes: Observations of ONE image (row_index set when row structure exists).
        zones: Zone anchors of the same image (header/backlit/poster, box stack). May be empty —
            anchors are evidence, not gates.
        image_size: ``(width, height)`` of the source image.
        llm_hints: Optional ``shape_id -> membership`` suggestions. Recorded as evidence; may only
            resolve shapes that are still uncertain, never flip a deterministic decision.

    Returns:
        Copies of ``shapes`` (same order) with ``membership`` and ``membership_evidence`` set.
        Pure and deterministic; inputs are never mutated.
    """
    if not shapes:
        return []
    hints = llm_hints or {}
    valid = [s for s in shapes if not _degenerate(s)]
    anchor = _anchor_votes(valid, zones)
    rows = _row_block_votes(valid, image_size)

    provisional_on: List[str] = []
    for shape in valid:
        membership, _ = _combine([v for v in (anchor.get(shape.shape_id), rows.get(shape.shape_id)) if v])
        if membership == FixtureMembership.ON_FIXTURE:
            provisional_on.append(shape.shape_id)
    contained = _containment_votes(valid, provisional_on)

    result: List[Shape] = []
    for shape in shapes:
        if _degenerate(shape):
            membership, evidence = FixtureMembership.UNCERTAIN, ["degenerate_box"]
        else:
            votes = [
                v
                for v in (anchor.get(shape.shape_id), rows.get(shape.shape_id), contained.get(shape.shape_id))
                if v is not None
            ]
            membership, evidence = _combine(votes)
        hint = hints.get(shape.shape_id)
        if hint is not None:
            hint = FixtureMembership(hint)
            evidence.append(f"llm_hint:{hint.value}")
            if membership == FixtureMembership.UNCERTAIN and hint != FixtureMembership.UNCERTAIN:
                membership = hint
                evidence.append("resolved_by:llm_hint")
        result.append(shape.model_copy(update={"membership": membership, "membership_evidence": evidence}))
    return result


def usable_shapes(shapes: Sequence[Shape]) -> List[Shape]:
    """on_fixture only — the count the fallback threshold is compared against.

    Distractor (off-fixture or uncertain) counts can never suppress the fallback.

    Args:
        shapes: Shapes with membership assigned.

    Returns:
        The ``ON_FIXTURE`` subset, in order.
    """
    return [s for s in shapes if s.membership == FixtureMembership.ON_FIXTURE]
