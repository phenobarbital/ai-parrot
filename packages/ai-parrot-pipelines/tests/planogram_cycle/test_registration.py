"""Offline tests for per-image registration (FEAT-574, Module 13)."""

from __future__ import annotations

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.comparison.definition import load_slots_definition
from parrot_pipelines.planogram.comparison.registration import ImageRegistration, register_image
from parrot_pipelines.planogram.contracts import Identification, Slot


def _definition(shelves: int = 6, per_shelf: int = 4, duplicate_shelves: tuple[int, int] | None = None):
    """Synthetic definition: product ids 'P<shelf>-<slot>', brand alternates per shelf.

    ``duplicate_shelves=(a, b)`` gives shelf ``b`` exactly the products of shelf ``a``.
    """
    data = {"version": "1", "shelves": []}
    for shelf in range(1, shelves + 1):
        source = duplicate_shelves[0] if duplicate_shelves and shelf == duplicate_shelves[1] else shelf
        brand = "Alpha" if source % 2 else "Beta"
        data["shelves"].append(
            {
                "shelf_id": f"shelf_{shelf}",
                "shelf_number": shelf,
                "facings": [
                    {
                        "facing_id": f"s{shelf}_f{idx}",
                        "shelf_id": f"shelf_{shelf}",
                        "slot": idx,
                        "product": f"P{source}-{idx}",
                        "brand": brand,
                        "descriptors": {"display_name": f"Product {source}-{idx}"},
                    }
                    for idx in range(1, per_shelf + 1)
                ],
            }
        )
    return load_slots_definition(data)


def _slot(image_id: str, row: int, idx: int) -> Slot:
    return Slot(
        slot_id=f"{image_id}:r{row}:s{idx}",
        image_id=image_id,
        row_index=row,
        slot_index=idx,
        box=DetectionBox(x1=idx * 60, y1=row * 60, x2=idx * 60 + 50, y2=row * 60 + 50, confidence=0.9),
        anchor_shape_id=f"{image_id}:t{row}:{idx}",
    )


def _ident(slot: Slot, product: str | None, brand: str | None = None, uncertain: bool = False) -> Identification:
    return Identification(
        shape_id=slot.anchor_shape_id,
        image_id=slot.image_id,
        product=product,
        brand=brand,
        uncertain=uncertain,
    )


def _rows(image_id: str, shelves_seen, per_shelf: int = 4, skip: set | None = None):
    slots, idents = [], []
    for row, shelf in enumerate(shelves_seen):
        for idx in range(1, per_shelf + 1):
            if skip and (row, idx) in skip:
                continue
            slot = _slot(image_id, row, idx)
            slots.append(slot)
            idents.append(_ident(slot, product=f"P{shelf}-{idx}"))
    return slots, idents


def test_full_view_registers_rows_in_increasing_shelf_order():
    definition = _definition(shelves=3)
    slots, idents = _rows("img0", (1, 2, 3))
    reg = register_image("img0", slots, idents, definition)
    assert isinstance(reg, ImageRegistration)
    assert reg.ambiguous is False
    assert reg.row_to_shelf == {0: "shelf_1", 1: "shelf_2", 2: "shelf_3"}
    assert reg.assignments["img0:t1:3"] == "s2_f3"
    assert len(reg.assignments) == 12


def test_registration_partial_view_not_visible():
    """Rows identified as shelves 2-4 of a 6-shelf definition register to exactly those shelves."""
    definition = _definition(shelves=6, per_shelf=4)
    slots, idents = _rows("img0", (2, 3, 4))
    reg = register_image("img0", slots, idents, definition)
    assert reg.ambiguous is False
    assert set(reg.row_to_shelf.values()) == {definition.shelves[i].shelf_id for i in (1, 2, 3)}
    assert len(reg.assignments) == 12
    assigned_shelves = {facing_id.split("_")[0] for facing_id in reg.assignments.values()}
    assert assigned_shelves == {"s2", "s3", "s4"}


def test_registration_ambiguous_stays_unassessed():
    """Two shelves with identical products => tie => no assignments at all."""
    definition = _definition(shelves=4, duplicate_shelves=(2, 3))
    slots, idents = _rows("img0", (2,))
    reg = register_image("img0", slots, idents, definition)
    assert reg.ambiguous is True
    assert reg.row_to_shelf == {} and reg.assignments == {}


def test_zero_anchor_alignment_is_ambiguous():
    """Brand-only evidence never forces an assignment."""
    definition = _definition(shelves=3)
    slots = [_slot("img0", 0, idx) for idx in range(1, 5)]
    idents = [_ident(s, product=None, brand="Alpha") for s in slots]
    reg = register_image("img0", slots, idents, definition)
    assert reg.ambiguous is True and reg.assignments == {}


def test_more_rows_than_shelves_is_ambiguous():
    definition = _definition(shelves=2)
    slots, idents = _rows("img0", (1, 2, 1))
    reg = register_image("img0", slots, idents, definition)
    assert reg.ambiguous is True and reg.row_to_shelf == {}


def test_other_image_inputs_are_ignored():
    definition = _definition(shelves=3)
    slots, idents = _rows("img0", (1, 2, 3))
    other_slots, other_idents = _rows("img1", (3, 2, 1))
    reg = register_image("img0", slots + other_slots, idents + other_idents, definition)
    assert reg.row_to_shelf == {0: "shelf_1", 1: "shelf_2", 2: "shelf_3"}
    assert all(key.startswith("img0:") for key in reg.assignments)
    empty = register_image("img9", slots, idents, definition)
    assert empty.ambiguous is False and empty.assignments == {}


def test_gap_in_row_keeps_neighbours_aligned():
    """A missing observed slot does not shift its neighbours onto the wrong facings."""
    definition = _definition(shelves=2, per_shelf=5)
    slots, idents = _rows("img0", (1, 2), per_shelf=5, skip={(0, 3)})
    reg = register_image("img0", slots, idents, definition)
    assert reg.assignments["img0:t0:2"] == "s1_f2"
    assert reg.assignments["img0:t0:4"] == "s1_f4"
    assert "img0:t0:3" not in reg.assignments


def test_uncertain_identification_scores_neutral_but_occupies_position():
    definition = _definition(shelves=2)
    slots, idents = _rows("img0", (1, 2))
    idents[1] = idents[1].model_copy(update={"uncertain": True, "product": "P2-4"})
    reg = register_image("img0", slots, idents, definition)
    assert reg.ambiguous is False
    assert reg.assignments["img0:t0:2"] == "s1_f2"  # position kept, evidence ignored


def test_register_image_is_deterministic():
    definition = _definition(shelves=6)
    slots, idents = _rows("img0", (2, 3, 4))
    first = register_image("img0", slots, idents, definition)
    for _ in range(3):
        assert register_image("img0", list(reversed(slots)), list(reversed(idents)), definition) == first
