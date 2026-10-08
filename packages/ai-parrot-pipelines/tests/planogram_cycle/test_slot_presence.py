"""Tri-state slot presence and representative evidence for FEAT-645."""

import pytest
from parrot_pipelines.planogram.comparison.definition import (
    FacingDefinition,
    ReportingPolicy,
    ShelfDefinition,
    SlotsDefinition,
)
from parrot_pipelines.planogram.comparison.presence import build_slot_presence, facing_presence
from parrot_pipelines.planogram.contracts import (
    ComparisonResult,
    FacingStatus,
    ObservationRef,
    ObservationSource,
    PositionResult,
    SlotPresence,
)


def _position(
    facing_id: str, status: FacingStatus, confidence: float = 0.95, identity: str | None = None
) -> PositionResult:
    """Build a position with one deciding observation."""
    return PositionResult(
        facing_id=facing_id,
        shelf_id="shelf_1",
        status=status,
        identity=identity,
        observations=[
            ObservationRef(image_id="img0", shape_id=facing_id, source=ObservationSource.CV, raw_confidence=confidence)
        ],
    )


def _definition(*facings: FacingDefinition) -> SlotsDefinition:
    """Build a direct definition without loader contiguity requirements."""
    return SlotsDefinition(
        shelves=[ShelfDefinition(shelf_id="shelf_1", shelf_number=1, level="top", facings=list(facings))]
    )


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (FacingStatus.MATCH, (True, False)),
        (FacingStatus.VARIANT_UNRESOLVED, (True, False)),
        (FacingStatus.INFERRED_PRESENT, (True, False)),
        (FacingStatus.MISPLACED, (True, True)),
        (FacingStatus.MISMATCH, (False, False)),
        (FacingStatus.EMPTY, (False, False)),
        (FacingStatus.OCCUPIED_UNASSIGNED, (None, False)),
        (FacingStatus.CONFLICT, (None, False)),
        (FacingStatus.NOT_ASSESSED, (None, False)),
        (FacingStatus.NOT_VISIBLE, (None, False)),
        (FacingStatus.EXPECTED_EMPTY, (None, False)),
        (FacingStatus.UNEXPECTED_OCCUPIED, (None, False)),
    ],
)
def test_facing_presence_truth_table(status: FacingStatus, expected: tuple[bool | None, bool]) -> None:
    """Every status follows the reporting table without changing score credit."""
    position = _position("f1", status)
    found, misplaced, confidence = facing_presence(position, ReportingPolicy())
    assert (found, misplaced) == expected
    if status in {FacingStatus.CONFLICT, FacingStatus.NOT_VISIBLE, FacingStatus.NOT_ASSESSED}:
        assert confidence is None
    else:
        assert confidence == 0.95


def test_facing_presence_threshold_missing_and_deciding_observation() -> None:
    """MISPLACED uses the first observation and treats equality as passing."""
    policy = ReportingPolicy(misplaced_min_confidence=0.9)
    assert facing_presence(_position("f1", FacingStatus.MISPLACED, 0.9), policy) == (True, True, 0.9)
    assert facing_presence(_position("f1", FacingStatus.MISPLACED, 0.5), policy) == (None, False, 0.5)
    assert facing_presence(None, policy) == (None, False, None)
    no_view = PositionResult(facing_id="f1", shelf_id="shelf_1", status=FacingStatus.NOT_VISIBLE)
    assert facing_presence(no_view, policy) == (None, False, None)
    two_views = _position("f1", FacingStatus.MISPLACED, 0.5)
    two_views.observations.append(two_views.observations[0].model_copy(update={"raw_confidence": 0.99}))
    assert facing_presence(two_views, policy) == (None, False, 0.5)


def test_slot_presence_grouping_closeout_and_order() -> None:
    """Three facings at one position become one entry with counted presence."""
    definition = _definition(
        FacingDefinition(facing_id="f1", shelf_id="shelf_1", slot=1, position=97, product="CLOSEOUT", brand="Epson"),
        FacingDefinition(facing_id="f2", shelf_id="shelf_1", slot=2, position=97, product="CLOSEOUT", brand="Epson"),
        FacingDefinition(facing_id="f3", shelf_id="shelf_1", slot=3, position=97, product="CLOSEOUT", brand="Epson"),
        FacingDefinition(facing_id="f4", shelf_id="shelf_1", slot=4, position=98, product="OTHER"),
    )
    entries = build_slot_presence(
        [_position("f1", FacingStatus.EMPTY), _position("f2", FacingStatus.MATCH), _position("f3", FacingStatus.EMPTY)],
        definition,
        ReportingPolicy(),
    )
    assert [(entry.position, entry.facing_ids) for entry in entries] == [(97, ["f1", "f2", "f3"]), (98, ["f4"])]
    assert entries[0].found is True and entries[0].facings == 3 and entries[0].facings_found == 1
    assert entries[0].status is FacingStatus.MATCH


def test_slot_presence_mixed_unknown_and_empty() -> None:
    """Unknown plus empty is unknown; all empty is absent."""
    definition = _definition(
        FacingDefinition(facing_id="f1", shelf_id="shelf_1", slot=1, position=10, product="A"),
        FacingDefinition(facing_id="f2", shelf_id="shelf_1", slot=2, position=10, product="A"),
    )
    entries = build_slot_presence(
        [_position("f1", FacingStatus.EMPTY), _position("f2", FacingStatus.NOT_VISIBLE)], definition, ReportingPolicy()
    )
    assert entries[0].found is None and entries[0].facings_found == 0 and entries[0].status is FacingStatus.NOT_VISIBLE
    all_empty = build_slot_presence(
        [_position("f1", FacingStatus.EMPTY), _position("f2", FacingStatus.EMPTY)], definition, ReportingPolicy()
    )
    assert all_empty[0].found is False and all_empty[0].status is FacingStatus.EMPTY


def test_slot_presence_mismatch_observed_and_missing_result() -> None:
    """Mismatch keeps observed identity, while absent results represent NOT_VISIBLE."""
    definition = _definition(FacingDefinition(facing_id="f1", shelf_id="shelf_1", slot=1, product="EXPECTED"))
    entries = build_slot_presence(
        [_position("f1", FacingStatus.MISMATCH, identity="OBSERVED")], definition, ReportingPolicy()
    )
    assert entries[0].found is False and entries[0].observed == "OBSERVED"
    missing = build_slot_presence([], definition, ReportingPolicy())
    assert missing[0].found is None and missing[0].status is FacingStatus.NOT_VISIBLE


def test_slot_presence_excludes_expected_empty_and_fallback_key() -> None:
    """Expected-empty facings never enter a group; position-less facings use slot."""
    definition = _definition(
        FacingDefinition(facing_id="empty", shelf_id="shelf_1", slot=1, product=None, expected_occupancy="empty"),
        FacingDefinition(facing_id="occupied", shelf_id="shelf_1", slot=2, position=None, product="A"),
    )
    entries = build_slot_presence([], definition, ReportingPolicy())
    assert len(entries) == 1 and entries[0].slot == 2 and entries[0].position is None


def test_slot_presence_defaults_and_serialization() -> None:
    """Defaults are independent and nullable presence/status serialize as JSON values."""
    first = ComparisonResult()
    second = ComparisonResult()
    first.products_found.append(
        SlotPresence(shelf_id="shelf_1", slot=1, facing_ids=["f1"], model="A", status=FacingStatus.NOT_VISIBLE)
    )
    assert second.products_found == []
    restored = ComparisonResult.model_validate(first.model_dump(mode="json"))
    assert restored.products_found[0].found is None
    assert restored.products_found[0].status is FacingStatus.NOT_VISIBLE
