"""Neighbour-spill guard: brand-only slot readings that repeat an adjacent slot (ink wall false presence)."""

from __future__ import annotations

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.comparison.scoring import _decide
from parrot_pipelines.planogram.contracts import FacingStatus, Identification, Slot
from parrot_pipelines.planogram.identification.spill import SPILL_EVIDENCE, suppress_neighbour_spill


def _slot(index: int, row: int = 0) -> Slot:
    x1 = 100 * index
    return Slot(
        slot_id=f"img0:r{row}:s{index}",
        image_id="img0",
        row_index=row,
        slot_index=index,
        box=DetectionBox(x1=x1, y1=0, x2=x1 + 100, y2=100, confidence=1.0),
    )


def _ident(index: int, row: int = 0, **fields) -> Identification:
    data = {"occupancy": "occupied", "raw_confidence": 0.85, "evidence": ["seen"]}
    data.update(fields)
    return Identification(shape_id=f"img0:r{row}:s{index}", image_id="img0", **data)


def test_brand_only_next_to_richer_same_brand_is_uncertain():
    slots = [_slot(1), _slot(2), _slot(3)]
    idents = [
        _ident(1, brand="Epson", text="232"),
        _ident(2, brand="Epson"),  # empty slot, sees the edge of slot 3's box
        _ident(3, brand="Epson", text="302XL", descriptors={"family": "302", "xl": True}),
    ]
    out = suppress_neighbour_spill(idents, slots)
    assert [i.shape_id for i in out] == [i.shape_id for i in idents]
    assert out[1].uncertain
    assert any(e.startswith(SPILL_EVIDENCE) for e in out[1].evidence)
    assert out[1].raw_confidence == 0.85  # model-reported confidence is never modified
    assert not out[0].uncertain and not out[2].uncertain


def test_copied_descriptors_still_count_as_spill():
    slots = [_slot(1), _slot(2)]
    idents = [
        _ident(1, brand="Epson", descriptors={"family": "302", "xl": False}),
        _ident(2, brand="Epson", text="302XL", descriptors={"family": "302"}),
    ]
    assert suppress_neighbour_spill(idents, slots)[0].uncertain


def test_own_reading_is_kept():
    slots = [_slot(1), _slot(2)]
    idents = [
        _ident(1, brand="Epson", descriptors={"family": "252"}),
        _ident(2, brand="Epson", text="302XL", descriptors={"family": "302"}),
    ]
    assert not suppress_neighbour_spill(idents, slots)[0].uncertain


def test_row_of_brand_only_readings_is_untouched():
    slots = [_slot(i) for i in range(1, 5)]
    idents = [_ident(i, brand="HP") for i in range(1, 5)]
    assert not any(i.uncertain for i in suppress_neighbour_spill(idents, slots))


def test_different_brand_or_row_or_gap_is_untouched():
    slots = [_slot(1), _slot(2, row=1), _slot(4), _slot(6)]
    idents = [
        _ident(1, brand="HP"),
        _ident(2, row=1, brand="HP", text="64XL"),  # other row
        _ident(4, brand="Canon"),
        _ident(6, brand="Canon", text="PG-275"),  # not adjacent (slot 5 missing)
    ]
    assert not any(i.uncertain for i in suppress_neighbour_spill(idents, slots))


def test_empty_or_uncertain_neighbour_does_not_trigger():
    slots = [_slot(1), _slot(2), _slot(3)]
    idents = [
        _ident(1, occupancy="empty", brand="Epson", text="302XL"),
        _ident(2, brand="Epson"),
        _ident(3, brand="Epson", text="302XL", uncertain=True),
    ]
    assert not suppress_neighbour_spill(idents, slots)[1].uncertain


def test_spill_is_not_assessed_instead_of_variant_unresolved():
    from parrot_pipelines.planogram.comparison.definition import FacingDefinition

    facing = FacingDefinition.model_validate(
        {"facing_id": "p062_f1", "product": "9248146", "brand": "Epson", "descriptors": {"family": "252"}}
    )
    slots = [_slot(1), _slot(2)]
    idents = [_ident(1, brand="Epson"), _ident(2, brand="Epson", text="302XL")]
    before, _ = _decide(facing, [idents[0]], False)
    after, _ = _decide(facing, [suppress_neighbour_spill(idents, slots)[0]], False)
    assert before == FacingStatus.VARIANT_UNRESOLVED
    assert after == FacingStatus.NOT_ASSESSED
