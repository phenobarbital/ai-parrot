"""Pure reporting of expected model presence; scoring is intentionally unchanged."""

from typing import Dict, List, Optional, Sequence, Tuple

from parrot_pipelines.planogram.comparison.definition import FacingDefinition, ReportingPolicy, SlotsDefinition
from parrot_pipelines.planogram.contracts import FacingStatus, PositionResult, SlotPresence

_NO_DECIDING_VIEW = {
    FacingStatus.NOT_VISIBLE,
    FacingStatus.NOT_ASSESSED,
    FacingStatus.CONFLICT,
}
_FOUND = {
    FacingStatus.MATCH,
    FacingStatus.VARIANT_UNRESOLVED,
    FacingStatus.INFERRED_PRESENT,
}


def facing_presence(
    position: Optional[PositionResult], policy: ReportingPolicy
) -> Tuple[Optional[bool], bool, Optional[float]]:
    """Return found, misplaced and deciding confidence for one facing."""
    if position is None:
        return None, False, None

    confidence = None
    if position.status not in _NO_DECIDING_VIEW and position.observations:
        confidence = position.observations[0].raw_confidence

    if position.status in _FOUND:
        return True, False, confidence
    if position.status is FacingStatus.MISPLACED:
        if confidence is not None and confidence >= policy.misplaced_min_confidence:
            return True, True, confidence
        return None, False, confidence
    if position.status in {FacingStatus.MISMATCH, FacingStatus.EMPTY}:
        return False, False, confidence
    return None, False, confidence


def build_slot_presence(
    positions: Sequence[PositionResult], definition: SlotsDefinition, policy: ReportingPolicy
) -> List[SlotPresence]:
    """Group occupied-expected facings by shelf and position, preserving definition order."""
    positions_by_id: Dict[str, PositionResult] = {position.facing_id: position for position in positions}
    groups: Dict[Tuple[str, int], List[FacingDefinition]] = {}
    for shelf in definition.shelves:
        for facing in shelf.facings:
            if facing.expected_occupancy == "empty":
                continue
            key = (facing.shelf_id, facing.position if facing.position is not None else facing.slot)
            groups.setdefault(key, []).append(facing)

    result: List[SlotPresence] = []
    for facings in groups.values():
        first = facings[0]
        members = [
            (
                facing,
                positions_by_id.get(facing.facing_id),
                facing_presence(positions_by_id.get(facing.facing_id), policy),
            )
            for facing in facings
        ]
        values = [presence[2][0] for presence in members]
        found: Optional[bool]
        if True in values:
            found = True
        elif None in values:
            found = None
        else:
            found = False
        representative = next(member for member in members if member[2][0] == found)
        _, representative_position, representative_presence = representative
        _, misplaced, confidence = representative_presence
        shelf = next(shelf for shelf in definition.shelves if shelf.shelf_id == first.shelf_id)
        result.append(
            SlotPresence(
                shelf_id=first.shelf_id,
                shelf_level=shelf.level,
                slot=first.slot,
                position=first.position,
                facing_ids=[facing.facing_id for facing in facings],
                model=first.product or "",
                sku=first.descriptors.sku,
                brand=first.brand,
                display_name=first.descriptors.display_name,
                found=found,
                misplaced=misplaced,
                status=(
                    representative_position.status if representative_position is not None else FacingStatus.NOT_VISIBLE
                ),
                confidence=confidence,
                facings=len(facings),
                facings_found=sum(value is True for value in values),
                observed=representative_position.identity if representative_position is not None else None,
            )
        )
    return result
