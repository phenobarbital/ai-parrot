"""Deterministic registration of one photo against the planogram (FEAT-565, Module 8).

Pure functions: no I/O, no LLM, no ``parrot`` import. Same observations → identical result.
"""

from __future__ import annotations

import logging
from itertools import combinations

from plancheck.models import (
    Catalog,
    Grade,
    ImageRegistration,
    PlanogramFacing,
    PlanogramRef,
    RowRegistration,
    SlotObservation,
)

logger = logging.getLogger(__name__)

SCORE_SAME_SKU = 4.0
SCORE_CANDIDATE = 3.0
SCORE_BRAND_FAMILY = 2.0
SCORE_BRAND = 1.0
SCORE_NEUTRAL = 0.0
SCORE_OTHER_BRAND = -2.0
GAP_INTERIOR = -1.5
GAP_END_PLANOGRAM = 0.0
GAP_END_OBSERVED = -0.5
PITCH_TOLERANCE = 0.35
PITCH_PENALTY = -1.0
PRIOR_CONSECUTIVE = 1.0
PRIOR_FULL_HEIGHT = 2.0
MARGIN_HIGH = 3.0
MARGIN_LOW = 1.0
ANCHORS_HIGH = 2


def _norm(text: str | None) -> str | None:
    """Casefold/strip a brand or family token; ``None`` stays ``None``."""
    return text.casefold().strip() if text else None


def _observed_brand_family(obs: SlotObservation, catalog: Catalog) -> tuple[str | None, str | None]:
    """Brand/family of what was seen: catalog entry of ``resolved_sku`` if any, else the raw reading."""
    if obs.resolved_sku is not None:
        item = catalog.by_sku(obs.resolved_sku)
        if item is not None:
            return _norm(item.brand), _norm(item.family)
    return _norm(obs.reading.brand if obs.reading else None), _norm(obs.reading.family if obs.reading else None)


def pair_score(obs: SlotObservation, facing: PlanogramFacing, catalog: Catalog) -> float:
    """Score one observed slot against one expected facing (spec §2 score table).

    Args:
        obs: Pass-1 observation of the slot.
        facing: Expected planogram facing.
        catalog: Catalog used to look up brand/family of SKUs.

    Returns:
        One of +4, +3, +2, +1, 0, -2 following the 8-rule order of the task.
    """
    if obs.reading is None or obs.reading.occupancy != "occupied":
        return SCORE_NEUTRAL
    if not facing.identity_required:
        return SCORE_NEUTRAL
    if obs.resolution == "direct" and obs.resolved_sku == facing.sku:
        return SCORE_SAME_SKU
    if facing.sku in obs.candidate_skus:
        return SCORE_CANDIDATE
    obs_brand, obs_family = _observed_brand_family(obs, catalog)
    exp_brand = _norm(facing.brand)
    exp_item = catalog.by_sku(facing.sku)
    exp_family = _norm(exp_item.family) if exp_item else None
    if obs_brand == exp_brand and obs_family == exp_family:
        return SCORE_BRAND_FAMILY
    if obs_brand == exp_brand:
        return SCORE_BRAND
    if obs_brand is None:
        return SCORE_NEUTRAL
    return SCORE_OTHER_BRAND


def _center_x(obs: SlotObservation) -> float:
    """Horizontal centre of the slot box in original pixels."""
    x1, _, x2, _ = obs.slot.box
    return (x1 + x2) / 2.0


def align_row(
    row_obs: list[SlotObservation], facings: list[PlanogramFacing], catalog: Catalog, pitch: float
) -> tuple[float, dict[str, str], int]:
    """Semi-global, gap-tolerant alignment of one row against one shelf.

    Args:
        row_obs: Observations of ONE row of ONE image (any order; sorted here by ``slot.index``).
        facings: Expected facings of one shelf in physical order (``PlanogramRef.shelf``).
        catalog: Catalog for brand/family lookups.
        pitch: Median tag pitch of the row in original pixels (``<= 0`` disables the pitch check).

    Returns:
        ``(score, {slot_id: facing_id}, anchors)`` — score includes gap costs and pitch penalties;
        unmatched slots are absent from the mapping; ``anchors`` counts +4 matches.
    """
    if not row_obs or not facings:
        return 0.0, {}, 0

    row_obs_sorted = sorted(row_obs, key=lambda obs: obs.slot.index)
    n, m = len(row_obs_sorted), len(facings)

    dp = [[-float("inf")] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0

    for i in range(n + 1):
        for j in range(m + 1):
            if i == 0 and j == 0:
                continue
            candidates = []
            if i > 0 and j > 0:
                score = pair_score(row_obs_sorted[i - 1], facings[j - 1], catalog)
                candidates.append((dp[i - 1][j - 1] + score, "match", i - 1, j - 1))
            if j > 0:
                gap_cost = GAP_END_PLANOGRAM if j == m else GAP_INTERIOR
                candidates.append((dp[i][j - 1] + gap_cost, "skip-facing", i, j - 1))
            if i > 0:
                gap_cost = GAP_END_OBSERVED if i == n else GAP_INTERIOR
                candidates.append((dp[i - 1][j] + gap_cost, "skip-slot", i - 1, j))

            best_score = max(candidates, key=lambda x: (x[0], {"match": 2, "skip-facing": 1, "skip-slot": 0}[x[1]]))
            dp[i][j] = best_score[0]

    best_i, best_j = 0, 0
    best_score = dp[0][0]
    for i in range(n + 1):
        for j in range(m + 1):
            if dp[i][j] > best_score or (dp[i][j] == best_score and j < best_j):
                best_score = dp[i][j]
                best_i, best_j = i, j

    score = dp[best_i][best_j]
    assignments = {}
    anchors = 0

    i, j = best_i, best_j
    while i > 0 or j > 0:
        if (
            i > 0
            and j > 0
            and dp[i][j] == dp[i - 1][j - 1] + pair_score(row_obs_sorted[i - 1], facings[j - 1], catalog)
        ):
            obs = row_obs_sorted[i - 1]
            facing = facings[j - 1]
            assignments[obs.slot.slot_id] = facing.facing_id
            if pair_score(obs, facing, catalog) == SCORE_SAME_SKU:
                anchors += 1
            i -= 1
            j -= 1
        elif j > 0 and dp[i][j] == dp[i][j - 1] + (GAP_END_PLANOGRAM if j == m else GAP_INTERIOR):
            j -= 1
        else:
            i -= 1

    if pitch > 0:
        matched_pairs = []
        for obs in row_obs_sorted:
            if obs.slot.slot_id in assignments:
                facing_id = assignments[obs.slot.slot_id]
                for facing in facings:
                    if facing.facing_id == facing_id:
                        matched_pairs.append((obs.slot.index, facing.slot))
                        break
        for idx in range(1, len(matched_pairs)):
            prev_slot_idx, prev_facing_slot = matched_pairs[idx - 1]
            curr_slot_idx, curr_facing_slot = matched_pairs[idx]
            k = curr_facing_slot - prev_facing_slot - 1
            if k >= 1:
                d = abs(_center_x(row_obs_sorted[curr_slot_idx - 1]) - _center_x(row_obs_sorted[prev_slot_idx - 1]))
                expected = (k + 1) * pitch
                if abs(d - expected) > PITCH_TOLERANCE * expected:
                    score += PITCH_PENALTY

    return round(score, 4), assignments, anchors


def _grade(anchors: int, margin: float | None) -> Grade:
    """Row grade from its direct anchors and the image margin (``None`` = no alternative exists)."""
    if anchors == 0 or (margin is not None and margin < MARGIN_LOW):
        return "low"
    if anchors >= ANCHORS_HIGH and (margin is None or margin >= MARGIN_HIGH):
        return "high"
    return "medium"


def register_image(
    image_id: str,
    observations: list[SlotObservation],
    planogram: PlanogramRef,
    catalog: Catalog,
    pitches: dict[int, float],
) -> ImageRegistration:
    """Register every row of one image to a shelf and every slot to a facing.

    Args:
        image_id: Image whose observations are given.
        observations: All observations of that image (other images are ignored).
        planogram: Expected facings.
        catalog: Catalog for brand/family lookups.
        pitches: Row number → median tag pitch (missing row → 0.0, check disabled).

    Returns:
        The best order-preserving assignment with runner-up, margin and per-row grades.
    """
    rows_dict = {}
    for obs in observations:
        if obs.slot.image_id == image_id:
            row = obs.slot.row
            if row not in rows_dict:
                rows_dict[row] = []
            rows_dict[row].append(obs)

    rows = sorted(rows_dict.keys())
    shelf_count = planogram.shelf_count
    n_rows = len(rows)

    cache = {}
    for row in rows:
        for shelf in range(1, shelf_count + 1):
            key = (row, shelf)
            if key not in cache:
                pitch = pitches.get(row, 0.0)
                cache[key] = align_row(rows_dict[row], planogram.shelf(shelf), catalog, pitch)

    best_total = -float("inf")
    best_shelves = None
    second_total = -float("inf")
    second_shelves = None

    for candidate in combinations(range(1, shelf_count + 1), n_rows):
        total = 0.0
        for idx, row in enumerate(rows):
            shelf = candidate[idx]
            score, _, _ = cache[(row, shelf)]
            total += score

        for idx in range(1, n_rows):
            if candidate[idx] == candidate[idx - 1] + 1:
                total += PRIOR_CONSECUTIVE

        if n_rows == shelf_count:
            total += PRIOR_FULL_HEIGHT

        if total > best_total:
            second_total = best_total
            second_shelves = best_shelves
            best_total = total
            best_shelves = candidate
        elif total > second_total:
            second_total = total
            second_shelves = candidate

    rows_list = []
    for idx, row in enumerate(rows):
        shelf = best_shelves[idx] if best_shelves else None
        score, assignments, anchors = cache[(row, shelf)] if shelf else (0.0, {}, 0)
        grade = _grade(anchors, best_total - second_total if second_shelves else None)
        rows_list.append(
            RowRegistration(
                image_id=image_id,
                row=row,
                shelf=shelf,
                score=round(score, 4),
                anchors=anchors,
                grade=grade,
                assignments=assignments,
            )
        )

    runner_up_shelves = list(second_shelves) if second_shelves else None
    if runner_up_shelves:
        runner_up_shelves += [None] * (len(rows) - len(runner_up_shelves))

    margin = round(best_total - second_total, 4) if second_shelves else None

    return ImageRegistration(
        image_id=image_id,
        rows=rows_list,
        total_score=round(best_total, 4),
        runner_up_shelves=runner_up_shelves,
        margin=margin,
    )


def apply_registration(observations: list[SlotObservation], registration: ImageRegistration) -> None:
    """Set ``facing_id`` and ``registration_grade`` in place for the registration's image.

    Slots of that image absent from every row mapping get ``facing_id = None`` and keep the
    grade of their row (``None`` when the row is unknown to the registration).
    """
    slot_to_facing = {}
    row_to_grade = {}
    for row_reg in registration.rows:
        for slot_id, facing_id in row_reg.assignments.items():
            slot_to_facing[slot_id] = facing_id
        row_to_grade[row_reg.row] = row_reg.grade

    for obs in observations:
        if obs.slot.image_id == registration.image_id:
            obs.facing_id = slot_to_facing.get(obs.slot.slot_id)
            obs.registration_grade = row_to_grade.get(obs.slot.row)
