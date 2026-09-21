"""Deterministic per-image registration of observed slot rows against the slots definition (FEAT-574).

Pure functions: no I/O, no LLM. Same input, identical output.
"""

from __future__ import annotations

import logging
from itertools import combinations
from typing import Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

from parrot_pipelines.planogram.comparison.definition import FacingDefinition, ShelfDefinition, SlotsDefinition
from parrot_pipelines.planogram.contracts import Identification, Slot

logger = logging.getLogger(__name__)

SCORE_SAME_PRODUCT = 4.0
SCORE_BRAND_FAMILY = 2.0
SCORE_BRAND = 1.0
SCORE_NEUTRAL = 0.0
SCORE_OTHER_BRAND = -2.0
GAP_INTERIOR = -1.5
GAP_END_DEFINITION = 0.0
GAP_END_OBSERVED = -0.5
PRIOR_CONSECUTIVE = 1.0
PRIOR_FULL_HEIGHT = 2.0
MARGIN_LOW = 1.0

_MOVE_RANK = {"match": 2, "skip-facing": 1, "skip-slot": 0}


class ImageRegistration(BaseModel):
    """Result of registering ONE image against the slots definition."""

    image_id: str
    row_to_shelf: Dict[int, str] = Field(default_factory=dict, description="row_index -> shelf_id")
    assignments: Dict[str, str] = Field(default_factory=dict, description="Identification.shape_id -> facing_id")
    ambiguous: bool = False


def _norm(text: Optional[str]) -> Optional[str]:
    """Casefold/strip a token; None stays None."""
    return text.casefold().strip() if text else None


def _identification_for(slot: Slot, by_shape: Dict[str, Identification]) -> Optional[Identification]:
    """Join rule: identification.shape_id in {slot.anchor_shape_id, slot.slot_id}."""
    for key in (slot.anchor_shape_id, slot.slot_id):
        if key and key in by_shape:
            return by_shape[key]
    return None


def _pair_score(identification: Optional[Identification], facing: FacingDefinition) -> float:
    """Score one observed slot against one expected facing.

    Only evidence carried by the ``Identification`` is used (product id, brand, descriptor family).

    Args:
        identification: The slot's identification (``None`` / uncertain ⇒ neutral).
        facing: The expected facing.

    Returns:
        One of the ``SCORE_*`` constants.
    """
    if identification is None or identification.uncertain:
        return SCORE_NEUTRAL
    observed_product = _norm(identification.product)
    if observed_product and observed_product == _norm(facing.product):
        return SCORE_SAME_PRODUCT
    observed_brand = _norm(identification.brand)
    expected_brand = _norm(facing.brand)
    if observed_brand is None or expected_brand is None:
        return SCORE_NEUTRAL
    if observed_brand != expected_brand:
        return SCORE_OTHER_BRAND
    observed_family = _norm(str(identification.descriptors.get("family") or "") or None)
    expected_family = _norm(facing.descriptors.family)
    if observed_family and observed_family == expected_family:
        return SCORE_BRAND_FAMILY
    return SCORE_BRAND


def _align_row(
    row_slots: Sequence[Slot], facings: Sequence[FacingDefinition], by_shape: Dict[str, Identification]
) -> Tuple[float, Dict[str, str], int]:
    """Semi-global, gap-tolerant alignment of one row against one shelf.

    Args:
        row_slots: Slots of one row of one image.
        facings: Expected facings of one shelf, in physical order.
        by_shape: Identifications keyed by ``shape_id``.

    Returns:
        (score, {Identification.shape_id: facing_id}, anchors) — anchors counts SCORE_SAME_PRODUCT pairs.
        Slots without an identification never appear in the mapping.
    """
    if not row_slots or not facings:
        return 0.0, {}, 0
    ordered = sorted(row_slots, key=lambda s: s.slot_index)
    idents = [_identification_for(slot, by_shape) for slot in ordered]
    n, m = len(ordered), len(facings)
    scores = [[_pair_score(idents[i], facings[j]) for j in range(m)] for i in range(n)]

    dp = [[-float("inf")] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            if i == 0 and j == 0:
                continue
            candidates: List[Tuple[float, str]] = []
            if i > 0 and j > 0:
                candidates.append((dp[i - 1][j - 1] + scores[i - 1][j - 1], "match"))
            if j > 0:
                candidates.append((dp[i][j - 1] + (GAP_END_DEFINITION if j == m else GAP_INTERIOR), "skip-facing"))
            if i > 0:
                candidates.append((dp[i - 1][j] + (GAP_END_OBSERVED if i == n else GAP_INTERIOR), "skip-slot"))
            dp[i][j] = max(candidates, key=lambda c: (c[0], _MOVE_RANK[c[1]]))[0]

    best_i, best_j, best = 0, 0, dp[0][0]
    for i in range(n + 1):
        for j in range(m + 1):
            if dp[i][j] > best or (dp[i][j] == best and j < best_j):
                best, best_i, best_j = dp[i][j], i, j

    mapping: Dict[str, str] = {}
    anchors = 0
    i, j = best_i, best_j
    while i > 0 or j > 0:
        if i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + scores[i - 1][j - 1]:
            identification = idents[i - 1]
            if identification is not None:
                mapping[identification.shape_id] = facings[j - 1].facing_id
            if scores[i - 1][j - 1] == SCORE_SAME_PRODUCT:
                anchors += 1
            i, j = i - 1, j - 1
        elif j > 0 and dp[i][j] == dp[i][j - 1] + (GAP_END_DEFINITION if j == m else GAP_INTERIOR):
            j -= 1
        else:
            i -= 1
    return round(best, 4), mapping, anchors


def register_image(
    image_id: str,
    slots: Sequence[Slot],
    identifications: Sequence[Identification],
    definition: SlotsDefinition,
) -> ImageRegistration:
    """Register every slot row of one image to a shelf and every identified slot to a facing.

    Ambiguous or unsupported alignment => ``ambiguous=True`` and NO assignments (facings stay
    not_assessed / not_visible). Candidate identity can never force a facing assignment.

    Args:
        image_id: Image whose slots/identifications are considered; others are ignored.
        slots: On-fixture slots (membership already applied by the caller).
        identifications: Identifications of any image; filtered by ``image_id``.
        definition: Validated slots definition.

    Returns:
        The best strictly-increasing row->shelf assignment, or an ambiguous empty registration.
    """
    rows: Dict[int, List[Slot]] = {}
    for slot in slots:
        if slot.image_id == image_id:
            rows.setdefault(slot.row_index, []).append(slot)
    by_shape = {i.shape_id: i for i in identifications if i.image_id == image_id}
    shelves: List[ShelfDefinition] = [s for s in definition.shelves if s.facings]
    row_ids = sorted(rows)
    if not row_ids or not shelves or len(row_ids) > len(shelves):
        logger.debug("register_image(%s): nothing to register or more rows than shelves", image_id)
        return ImageRegistration(image_id=image_id, ambiguous=bool(row_ids))

    cache: Dict[Tuple[int, int], Tuple[float, Dict[str, str], int]] = {}
    for row in row_ids:
        for index, shelf in enumerate(shelves):
            cache[(row, index)] = _align_row(rows[row], shelf.facings, by_shape)

    best_total = -float("inf")
    best_combo: Optional[Tuple[int, ...]] = None
    runner_up = -float("inf")
    for combo in combinations(range(len(shelves)), len(row_ids)):
        total = sum(cache[(row, combo[k])][0] for k, row in enumerate(row_ids))
        total += PRIOR_CONSECUTIVE * sum(1 for k in range(1, len(combo)) if combo[k] == combo[k - 1] + 1)
        if len(row_ids) == len(shelves):
            total += PRIOR_FULL_HEIGHT
        if total > best_total:
            runner_up, best_total, best_combo = best_total, total, combo
        elif total > runner_up:
            runner_up = total

    if best_combo is None:  # unreachable: len(row_ids) <= len(shelves) guarantees one combination
        return ImageRegistration(image_id=image_id, ambiguous=True)
    anchors = sum(cache[(row, best_combo[k])][2] for k, row in enumerate(row_ids))
    margin = best_total - runner_up if runner_up != -float("inf") else None
    if anchors == 0 or (margin is not None and margin < MARGIN_LOW):
        logger.debug("register_image(%s): ambiguous (anchors=%d, margin=%s)", image_id, anchors, margin)
        return ImageRegistration(image_id=image_id, ambiguous=True)

    row_to_shelf: Dict[int, str] = {}
    assignments: Dict[str, str] = {}
    for k, row in enumerate(row_ids):
        row_to_shelf[row] = shelves[best_combo[k]].shelf_id
        assignments.update(cache[(row, best_combo[k])][1])
    return ImageRegistration(image_id=image_id, row_to_shelf=row_to_shelf, assignments=assignments)
