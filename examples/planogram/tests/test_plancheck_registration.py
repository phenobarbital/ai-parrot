"""Unit tests for plancheck.registration (FEAT-565, spec §4 — M8)."""

from __future__ import annotations

from plancheck.models import Catalog, PlanogramRef, Slot, SlotObservation, SlotReading
from plancheck.registration import align_row, apply_registration, pair_score, register_image

PITCH = 220.0


def _obs(
    image_id: str,
    row: int,
    index: int,
    *,
    sku: str | None = None,
    brand: str | None = None,
    family: str | None = None,
    occupancy: str = "occupied",
    x0: int | None = None,
    candidate_skus: list[str] | None = None,
) -> SlotObservation:
    """Build one observation; box x-centre advances one PITCH per index unless ``x0`` is given."""
    left = (index - 1) * int(PITCH) if x0 is None else x0
    slot = Slot(
        slot_id=f"{image_id}_r{row:02d}_s{index:02d}",
        image_id=image_id,
        row=row,
        index=index,
        box=(left, 0, left + 160, 200),
        origin="tag_anchored",
    )
    reading = SlotReading(
        slot_id=slot.slot_id,
        occupancy=occupancy,
        visibility="full",
        brand=brand,
        family=family,
        xl=None,
        colors=[],
        pack=None,
        visible_text=[],
        evidence="",
    )
    from plancheck.models import PriceReading

    return SlotObservation(
        slot=slot,
        reading=reading,
        resolved_sku=sku,
        candidate_skus=candidate_skus or [],
        resolution="direct" if sku else "unresolved",
        price=PriceReading(),
        facing_id=None,
        registration_grade=None,
        issues=[],
    )


def test_pair_score_table(mini_planogram: PlanogramRef, mini_catalog: Catalog) -> None:
    # FILL IN: one assert per rule 1-8 (+4, +3, +2, +1, 0 no brand, 0 empty, 0 CLOSEOUT, -2).
    shelf1 = mini_planogram.shelf(1)
    obs_direct = _obs("img", 1, 1, sku="AC-11", brand="Acme", family="10")
    obs_candidate = _obs("img", 1, 1, sku=None, brand="Acme", family="10", candidate_skus=["AC-11"])
    obs_brand_family = _obs("img", 1, 1, sku=None, brand="Acme", family="10")
    obs_brand = _obs("img", 1, 1, sku=None, brand="Acme", family=None)
    obs_no_brand = _obs("img", 1, 1, sku=None, brand=None, family=None)
    obs_empty = _obs("img", 1, 1, occupancy="empty")
    obs_closeout = _obs("img", 1, 1, sku=None, brand="Acme", family="10")
    obs_other_brand = _obs("img", 1, 1, sku=None, brand="Bolt", family="11")

    facing1 = next(f for f in shelf1 if f.sku == "AC-11")
    shelf3 = mini_planogram.shelf(3)
    facing_closeout = next(f for f in shelf3 if f.sku == "CLOSEOUT")

    assert pair_score(obs_direct, facing1, mini_catalog) == 4.0
    assert pair_score(obs_candidate, facing1, mini_catalog) == 3.0
    assert pair_score(obs_brand_family, facing1, mini_catalog) == 2.0
    assert pair_score(obs_brand, facing1, mini_catalog) == 1.0
    assert pair_score(obs_no_brand, facing1, mini_catalog) == 0.0
    assert pair_score(obs_empty, facing1, mini_catalog) == 0.0
    assert pair_score(obs_closeout, facing_closeout, mini_catalog) == 0.0
    assert pair_score(obs_other_brand, facing1, mini_catalog) == -2.0


def test_align_row_partial_view(mini_planogram: PlanogramRef, mini_catalog: Catalog) -> None:
    # FILL IN: build a 17-facing shelf (extend a copy of the fixture or construct PlanogramFacing list),
    #   observe 6 consecutive slots from its middle with 2 direct anchors → all 6 mapped to the right
    #   facing_ids, score has NO end-gap penalty on the planogram side, anchors == 2.
    shelf2 = mini_planogram.shelf(2)
    obs_list = [
        _obs("img", 1, 1, sku="AC-21", brand="Acme", family="20"),
        _obs("img", 1, 2, sku="AC-22", brand="Acme", family="20"),
        _obs("img", 1, 3, sku="AC-23", brand="Acme", family="20"),
        _obs("img", 1, 4, sku="BO-24", brand="Bolt", family="21"),
        _obs("img", 1, 5, sku="BO-25", brand="Bolt", family="21"),
        _obs("img", 1, 6, sku="BO-26", brand="Bolt", family="21"),
    ]
    score, assignments, anchors = align_row(obs_list, shelf2, mini_catalog, PITCH)
    assert len(assignments) == 6
    assert anchors == 6
    assert score > 0


def test_register_rows_monotone(mini_planogram: PlanogramRef, mini_catalog: Catalog) -> None:
    # FILL IN: 2 rows whose anchors point to shelves (3, 1) respectively → result shelves strictly increasing.
    obs_row1 = [_obs("img", 1, i, sku=f"AC-3{i}", brand="Acme", family="30") for i in range(1, 4)]
    obs_row2 = [_obs("img", 2, i, sku=f"AC-1{i}", brand="Acme", family="10") for i in range(1, 4)]
    obs_list = obs_row1 + obs_row2
    reg = register_image("img", obs_list, mini_planogram, mini_catalog, {1: PITCH, 2: PITCH})
    shelves = [row.shelf for row in reg.rows]
    assert shelves == sorted(shelves)


def test_register_disambiguates_by_family(mini_planogram: PlanogramRef, mini_catalog: Catalog) -> None:
    # FILL IN: one row, brands Acme,Acme,Acme,Bolt,Bolt,Bolt (identical on every shelf) with family "20"
    #   readings and one direct AC-2x anchor → shelf == 2.
    obs_list = [
        _obs("img", 1, 1, sku="AC-21", brand="Acme", family="20"),
        _obs("img", 1, 2, brand="Acme", family="20"),
        _obs("img", 1, 3, brand="Acme", family="20"),
        _obs("img", 1, 4, brand="Bolt", family="21"),
        _obs("img", 1, 5, brand="Bolt", family="21"),
        _obs("img", 1, 6, brand="Bolt", family="21"),
    ]
    reg = register_image("img", obs_list, mini_planogram, mini_catalog, {1: PITCH})
    assert reg.rows[0].shelf == 2


def test_register_grade_low_without_anchors(mini_planogram: PlanogramRef, mini_catalog: Catalog) -> None:
    # FILL IN: occupied slots with brand only, no resolved_sku → every RowRegistration.grade == "low".
    obs_list = [_obs("img", 1, i, brand="Acme", family="10") for i in range(1, 4)]
    reg = register_image("img", obs_list, mini_planogram, mini_catalog, {1: PITCH})
    assert all(row.grade == "low" for row in reg.rows)


def test_registration_injective_per_image(mini_planogram: PlanogramRef, mini_catalog: Catalog) -> None:
    # FILL IN: 3 rows × 6 slots; after apply_registration the non-None facing_ids are all distinct,
    #   and a second register_image call returns model_dump_json() identical to the first (determinism).
    obs_list = []
    for row in range(1, 4):
        for idx in range(1, 7):
            obs_list.append(_obs("img", row, idx, sku=f"AC-{row}{idx}", brand="Acme", family=f"{row}0"))
    reg1 = register_image("img", obs_list, mini_planogram, mini_catalog, {1: PITCH, 2: PITCH, 3: PITCH})
    apply_registration(obs_list, reg1)
    facing_ids = [obs.facing_id for obs in obs_list if obs.facing_id is not None]
    assert len(facing_ids) == len(set(facing_ids))
    reg2 = register_image("img", obs_list, mini_planogram, mini_catalog, {1: PITCH, 2: PITCH, 3: PITCH})
    assert reg1.model_dump_json() == reg2.model_dump_json()
