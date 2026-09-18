"""Offline tests for fixture membership (pure geometry — no images needed)."""

import copy
import inspect

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.contracts import FixtureMembership, Shape, ShapeKind
from parrot_pipelines.planogram.perception.membership import assign_membership, usable_shapes

SIZE = (2000, 1500)
ON, OFF, UNC = FixtureMembership.ON_FIXTURE, FixtureMembership.OFF_FIXTURE, FixtureMembership.UNCERTAIN


def _shape(
    shape_id: str, x: int, y: int, w: int = 120, h: int = 120, *, kind=ShapeKind.PRODUCT, row_index=None
) -> Shape:
    """Local factory."""
    return Shape(
        shape_id=shape_id,
        image_id="img0",
        kind=kind,
        profile="test",
        box=DetectionBox(x1=x, y1=y, x2=x + w, y2=y + h, confidence=1.0),
        row_index=row_index,
    )


def _by_id(shapes):
    return {s.shape_id: s for s in shapes}


def _header(x1: int = 600, x2: int = 1400, y1: int = 50) -> Shape:
    return _shape("zone_header", x1, y1, w=x2 - x1, h=150, kind=ShapeKind.ZONE)


def _tag_rows(start_x: int = 100, count: int = 8, pitch: int = 150, rows: int = 3, prefix: str = "t"):
    return [
        _shape(
            f"{prefix}{r}_{i}", start_x + i * pitch, 400 + r * 300, w=100, h=40, kind=ShapeKind.PRICE_TAG, row_index=r
        )
        for r in range(rows)
        for i in range(count)
    ]


def test_anchor_column_separates_adjacent_fixture():  # AC-1
    """Shapes under the header are on; shapes on the adjacent fixture far left are off."""
    shapes = [_shape("p1", 700, 400), _shape("p2", 900, 400), _shape("p3", 1100, 400)]
    shapes += [_shape("d1", 50, 400), _shape("d2", 200, 400)]
    got = _by_id(assign_membership(shapes, [_header()], SIZE))
    for sid in ("p1", "p2", "p3"):
        assert got[sid].membership == ON and "anchor_column" in got[sid].membership_evidence
    for sid in ("d1", "d2"):
        assert got[sid].membership == OFF and "outside_anchor_column" in got[sid].membership_evidence


def test_membership_ignores_expected_sku_and_handles_missing_anchors():  # AC-2 + AC-7 (spec §4 name)
    """No zones and no rows ⇒ uncertain everywhere; the signature carries no expected products."""
    assert list(inspect.signature(assign_membership).parameters) == ["shapes", "zones", "image_size", "llm_hints"]
    shapes = [_shape("a", 100, 100), _shape("b", 900, 100)]
    got = assign_membership(shapes, [], SIZE)
    assert [s.membership for s in got] == [UNC, UNC]
    assert all(s.membership_evidence == ["no_anchor_evidence"] for s in got)


def test_row_block_is_evidence_without_zones():  # AC-3
    """A coherent 3x8 tag block is on; a separated group of 3 tags on the same rows is off."""
    block = _tag_rows()  # x centres 150 .. 1200, pitch 150
    far = [
        _shape(f"far{r}_{i}", 1600 + i * 130, 400 + r * 300, w=100, h=40, kind=ShapeKind.PRICE_TAG, row_index=r)
        for r in range(3)
        for i in range(1)
    ]
    far += [_shape("far0_1", 1730, 400, w=100, h=40, kind=ShapeKind.PRICE_TAG, row_index=0)]
    far += [_shape("far0_2", 1860, 400, w=100, h=40, kind=ShapeKind.PRICE_TAG, row_index=0)]
    got = _by_id(assign_membership(block + far, [], SIZE))
    assert all(got[s.shape_id].membership == ON for s in block)
    assert all("row_block" in got[s.shape_id].membership_evidence for s in block)
    assert all(got[s.shape_id].membership == OFF for s in far)
    assert all(got[s.shape_id].membership_evidence == ["row_gap"] for s in far)


def test_conflicting_votes_stay_uncertain_with_both_reasons():  # AC-4
    """Inside the anchor column but across a row gap ⇒ uncertain with both reasons."""
    block = _tag_rows(count=6)  # x 100 .. 950
    stray = _shape("stray", 1500, 400, w=100, h=40, kind=ShapeKind.PRICE_TAG, row_index=0)
    wide_header = _header(x1=100, x2=1700)
    got = _by_id(assign_membership(block + [stray], [wide_header], SIZE))
    assert got["stray"].membership == UNC
    assert set(got["stray"].membership_evidence) >= {"anchor_column", "row_gap"}


def test_containment_marks_tag_on_product():
    """A tag whose centre lies inside an on product gets an on vote naming the container."""
    product = _shape("p1", 700, 400, w=300, h=300)
    tag = _shape("tag", 800, 650, w=80, h=30, kind=ShapeKind.PRICE_TAG)
    zone = _header(x1=650, x2=1050)
    got = _by_id(assign_membership([product, tag], [zone], SIZE))
    assert got["tag"].membership == ON
    assert "contained_in:p1" in got["tag"].membership_evidence


def test_llm_hint_resolves_uncertain_but_never_flips():  # AC-5
    """A hint resolves an uncertain shape but never flips a deterministic decision."""
    shapes = [_shape("p1", 700, 400), _shape("d1", 50, 400), _shape("mid", 400, 400)]
    hints = {"mid": ON, "d1": ON}
    got = _by_id(assign_membership(shapes, [_header()], SIZE, llm_hints=hints))
    # "mid": centre 460 is between the widened column (520) and the off margin (400) ⇒ no vote ⇒ uncertain.
    assert got["mid"].membership == ON
    assert "llm_hint:on_fixture" in got["mid"].membership_evidence
    assert "resolved_by:llm_hint" in got["mid"].membership_evidence
    assert got["d1"].membership == OFF
    assert "llm_hint:on_fixture" in got["d1"].membership_evidence
    assert "resolved_by:llm_hint" not in got["d1"].membership_evidence


def test_inputs_not_mutated_and_order_preserved():  # AC-6
    """Copies, same order and length; [] in ⇒ [] out."""
    shapes = [_shape("b", 900, 400), _shape("a", 700, 400), _shape("z", 50, 400)]
    snapshot = copy.deepcopy(shapes)
    got = assign_membership(shapes, [_header()], SIZE)
    assert [s.shape_id for s in got] == ["b", "a", "z"]
    assert shapes == snapshot
    assert all(s.membership == UNC and s.membership_evidence == [] for s in shapes)
    assert all(g is not s for g, s in zip(got, shapes, strict=True))
    assert assign_membership([], [_header()], SIZE) == []
    degenerate = _shape("flat", 700, 400, w=0)
    assert assign_membership([degenerate], [_header()], SIZE)[0].membership_evidence == ["degenerate_box"]


def test_usable_shapes_counts_only_on_fixture():  # AC-8
    """Adding off/uncertain shapes never changes the usable count."""
    base = assign_membership([_shape("p1", 700, 400), _shape("p2", 900, 400)], [_header()], SIZE)
    assert len(usable_shapes(base)) == 2
    noisy = base + assign_membership([_shape(f"d{i}", 20 + i, 400) for i in range(10)], [_header()], SIZE)
    noisy += assign_membership([_shape("u", 100, 100)], [], SIZE)
    assert len(usable_shapes(noisy)) == 2


def test_partial_view_header_cut_off():  # AC-9
    """A header cut off at the top edge still anchors the visible column."""
    cut_header = _shape("zone_header", 600, 0, w=800, h=40, kind=ShapeKind.ZONE)
    got = _by_id(assign_membership([_shape("p1", 700, 400), _shape("p2", 1200, 400)], [cut_header], SIZE))
    assert got["p1"].membership == ON and got["p2"].membership == ON
