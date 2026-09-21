"""Spike evaluator: one-to-one IoU matching, per-profile metrics, gates (FEAT-574). Stdlib + pydantic only."""

from __future__ import annotations

from typing import Dict, List, Literal, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

Box = Tuple[int, int, int, int]
GateState = Literal["passed", "failed", "untested"]
Outcome = Literal["passed", "failed", "inconclusive"]
MIN_EVALUABLE_PHOTOS = 3
REQUIRED_CONDITIONS = ("partial_view", "adjacent_fixture", "absent_anchors")
SYNTHETIC_GATE_CASES = ("partial_shelf", "absent_anchors", "adjacent_fixture")
SLOT_KINDS = ("product", "box")
#: Slot proposals of different profiles over the same object are collapsed above this IoU.
SLOT_DEDUP_IOU = 0.7


class AnnotatedObject(BaseModel):
    """One manually annotated object."""

    id: str
    kind: str
    box: Box
    membership: Literal["on_fixture", "off_fixture", "uncertain"] = "on_fixture"
    slot_target: bool = False


class PhotoAnnotation(BaseModel):
    """All annotations of one photo."""

    image: str
    image_size: Tuple[int, int]
    conditions: List[str] = Field(default_factory=list)
    objects: List[AnnotatedObject]


class Proposal(BaseModel):
    """Proposer output reduced to what the evaluator needs."""

    profile: str
    kind: str
    box: Box
    admitted: Optional[bool] = None  # None = membership not evaluated


class ProfileMetrics(BaseModel):
    """Precision/recall of one profile on one photo."""

    profile: str
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: Optional[float]  # None when there are no proposals
    recall: Optional[float]  # None when there is nothing to find


class PhotoResult(BaseModel):
    """Everything measured on one photo (anonymous index, never a filename)."""

    index: int
    conditions: List[str]
    per_profile: List[ProfileMetrics]
    slot_precision: Optional[float]
    slot_recall: Optional[float]
    off_fixture_proposals: int
    off_fixture_admitted: Optional[int]


def iou(a: Box, b: Box) -> float:
    """Intersection over union of two [x1, y1, x2, y2] boxes; 0.0 for degenerate boxes.

    Args:
        a: First box.
        b: Second box.

    Returns:
        IoU in ``[0, 1]``.
    """
    area_a = max(0, a[2] - a[0]) * max(0, a[3] - a[1])
    area_b = max(0, b[2] - b[0]) * max(0, b[3] - b[1])
    if area_a == 0 or area_b == 0:
        return 0.0
    inter = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def match_one_to_one(
    proposals: Sequence[Box], truths: Sequence[Box], threshold: float = 0.5
) -> List[Tuple[int, int, float]]:
    """Greedy best-IoU-first one-to-one matching. Returns (proposal_idx, truth_idx, iou) triples.

    Args:
        proposals: Proposed boxes.
        truths: Ground-truth boxes.
        threshold: Minimum IoU for a match.

    Returns:
        Matches sorted by decreasing IoU; ties broken by lower proposal index then lower truth index.
    """
    pairs = [
        (score, p_idx, t_idx)
        for p_idx, p in enumerate(proposals)
        for t_idx, t in enumerate(truths)
        if (score := iou(p, t)) >= threshold
    ]
    pairs.sort(key=lambda item: (-item[0], item[1], item[2]))
    used_p: set[int] = set()
    used_t: set[int] = set()
    matches: List[Tuple[int, int, float]] = []
    for score, p_idx, t_idx in pairs:
        if p_idx in used_p or t_idx in used_t:
            continue
        used_p.add(p_idx)
        used_t.add(t_idx)
        matches.append((p_idx, t_idx, score))
    return matches


def _ratio(numerator: int, denominator: int) -> Optional[float]:
    """``numerator / denominator`` or ``None`` when the denominator is zero."""
    return numerator / denominator if denominator else None


def _dedup_boxes(boxes: Sequence[Box], overlap: float) -> List[Box]:
    """Keep boxes in order, dropping one whose IoU with an already kept box exceeds ``overlap``."""
    kept: List[Box] = []
    for candidate in boxes:
        if all(iou(candidate, other) <= overlap for other in kept):
            kept.append(candidate)
    return kept


def evaluate_photo(
    index: int,
    annotation: PhotoAnnotation,
    proposals: Sequence[Proposal],
    kind_of_profile: Dict[str, str],
    threshold: float = 0.5,
) -> PhotoResult:
    """Per-profile metrics (truths = on_fixture objects of the profile's kind) + slot metrics.

    Slot metrics approximate "the derived slot covers the intended product": proposals of a
    ``product``/``box`` profile (not rejected by membership) are de-duplicated across profiles and
    matched one-to-one against the ``slot_target`` objects.

    Args:
        index: Anonymous photo index (1-based) — never a filename.
        annotation: The photo's annotations.
        proposals: Proposals made on the photo.
        kind_of_profile: Profile name → kind, for every evaluated profile.
        threshold: IoU threshold for a match.

    Returns:
        The photo result.
    """
    on_fixture = [o for o in annotation.objects if o.membership == "on_fixture"]
    per_profile: List[ProfileMetrics] = []
    for profile, kind in kind_of_profile.items():
        props = [p.box for p in proposals if p.profile == profile]
        truths = [o.box for o in on_fixture if o.kind == kind]
        tp = len(match_one_to_one(props, truths, threshold))
        per_profile.append(
            ProfileMetrics(
                profile=profile,
                true_positives=tp,
                false_positives=len(props) - tp,
                false_negatives=len(truths) - tp,
                precision=_ratio(tp, len(props)),
                recall=_ratio(tp, len(truths)),
            )
        )

    slot_props = _dedup_boxes(
        [p.box for p in proposals if p.kind in SLOT_KINDS and p.admitted is not False], SLOT_DEDUP_IOU
    )
    slot_truths = [o.box for o in on_fixture if o.slot_target]
    slot_tp = len(match_one_to_one(slot_props, slot_truths, threshold))

    off_fixture = [o.box for o in annotation.objects if o.membership == "off_fixture"]
    off_matching = [p for p in proposals if any(iou(p.box, off) >= threshold for off in off_fixture)]
    evaluated = any(p.admitted is not None for p in proposals)
    off_admitted = sum(1 for p in off_matching if p.admitted) if evaluated else None

    return PhotoResult(
        index=index,
        conditions=list(annotation.conditions),
        per_profile=per_profile,
        slot_precision=_ratio(slot_tp, len(slot_props)) if slot_truths else None,
        slot_recall=_ratio(slot_tp, len(slot_truths)),
        off_fixture_proposals=len(off_matching),
        off_fixture_admitted=off_admitted,
    )


def _threshold_gate(values: Sequence[Optional[float]], minimum: float) -> GateState:
    """``passed`` when every value reaches ``minimum``; a missing value (nothing proposed) fails."""
    if not values:
        return "untested"
    return "passed" if all(v is not None and v >= minimum for v in values) else "failed"


def decide_outcome(
    photos: Sequence[PhotoResult],
    synthetic: Dict[str, bool],
    *,
    min_precision: float = 0.90,
    min_recall: float = 0.90,
) -> Tuple[Outcome, Dict[str, GateState]]:
    """Apply the gates of the task's Implementation Notes and return (outcome, gate states).

    Args:
        photos: Results of the real (private) photos.
        synthetic: Synthetic case name → passed.
        min_precision: Product-slot precision gate.
        min_recall: Product-slot recall gate.

    Returns:
        ``(outcome, gates)``. Fewer than ``MIN_EVALUABLE_PHOTOS`` evaluable photos, a
        ``REQUIRED_CONDITIONS`` entry never exercised on a real photo, or any ``untested`` gate ⇒
        ``inconclusive``; otherwise any ``failed`` gate ⇒ ``failed``; else ``passed``.
    """
    evaluable = [p for p in photos if p.slot_recall is not None]
    gates: Dict[str, GateState] = {
        "slot_recall": _threshold_gate([p.slot_recall for p in evaluable], min_recall),
        "slot_precision": _threshold_gate([p.slot_precision for p in evaluable], min_precision),
    }
    if not evaluable or any(p.off_fixture_admitted is None for p in evaluable):
        gates["off_fixture_admitted"] = "untested"
    else:
        gates["off_fixture_admitted"] = "passed" if all(p.off_fixture_admitted == 0 for p in evaluable) else "failed"
    cases = [synthetic.get(name) for name in SYNTHETIC_GATE_CASES]
    if any(c is None for c in cases):
        gates["synthetic"] = "untested"
    else:
        gates["synthetic"] = "passed" if all(cases) else "failed"

    exercised = {c for p in evaluable for c in p.conditions}
    if (
        len(evaluable) < MIN_EVALUABLE_PHOTOS
        or any(c not in exercised for c in REQUIRED_CONDITIONS)
        or any(state == "untested" for state in gates.values())
    ):
        return "inconclusive", gates
    if any(state == "failed" for state in gates.values()):
        return "failed", gates
    return "passed", gates
