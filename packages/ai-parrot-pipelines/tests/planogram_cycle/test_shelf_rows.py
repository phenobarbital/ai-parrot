"""Offline tests for shelf rows of ``SHAPE_IS_SLOT`` fixtures (pure geometry — no images needed)."""

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.contracts import Shape, ShapeKind
from parrot_pipelines.planogram.perception.shelf_rows import centre_bands, dedupe_anchors, fit_rows


def _shape(
    shape_id: str, x: int, y: int, w: int = 200, h: int = 200, *, kind=ShapeKind.PRODUCT, confidence: float = 1.0
) -> Shape:
    """Local factory."""
    return Shape(
        shape_id=shape_id,
        image_id="img0",
        kind=kind,
        profile="test",
        box=DetectionBox(x1=x, y1=y, x2=x + w, y2=y + h, confidence=confidence),
    )


def _ids(shapes):
    return [shape.shape_id for shape in shapes]


def _printers():
    return [_shape(f"p{i}", 100 + i * 300, 400) for i in range(3)]


def _cartons(y: int = 700, prefix: str = "c", count: int = 3):
    return [_shape(f"{prefix}{i}", 100 + i * 300, y, h=120, kind=ShapeKind.BOX) for i in range(count)]


# ── dedupe_anchors ────────────────────────────────────────────────────────────


def test_dedupe_keeps_one_of_two_profiles_proposing_the_same_box():
    body = _shape("body", 100, 400, kind=ShapeKind.PRODUCT, confidence=0.6)
    box = _shape("box", 100, 400, kind=ShapeKind.BOX, confidence=0.9)
    assert _ids(dedupe_anchors([box, body], [box, body])) == ["body"]


def test_dedupe_prefers_higher_confidence_within_one_kind():
    low = _shape("low", 100, 400, confidence=0.4)
    high = _shape("high", 102, 400, confidence=0.8)
    assert _ids(dedupe_anchors([low, high], [low, high])) == ["high"]


def test_dedupe_drops_an_anchor_that_is_really_a_tag():
    tag = _shape("tag", 100, 620, w=100, h=40, kind=ShapeKind.PRICE_TAG)
    as_box = _shape("as_box", 100, 620, w=104, h=42, kind=ShapeKind.BOX)
    printer = _shape("p0", 100, 400)
    assert _ids(dedupe_anchors([as_box, printer], [tag, as_box, printer])) == ["p0"]


def test_dedupe_keeps_distinct_neighbours_in_original_order():
    anchors = [_shape("right", 400, 400, kind=ShapeKind.BOX), _shape("left", 100, 400)]
    assert _ids(dedupe_anchors(anchors, anchors)) == ["right", "left"]


def test_dedupe_of_nothing_is_nothing():
    assert dedupe_anchors([], []) == []


# ── centre_bands ──────────────────────────────────────────────────────────────


def test_centre_bands_of_nothing_is_nothing():
    assert centre_bands([]) == []


def test_centre_bands_separates_two_shelves_top_to_bottom():
    bands = centre_bands([*_cartons(), *_printers()])
    assert [_ids(band) for band in bands] == [["p0", "p1", "p2"], ["c0", "c1", "c2"]]


def test_centre_bands_tolerates_vertical_jitter_inside_a_shelf():
    jittered = [_shape("a", 100, 400), _shape("b", 400, 430), _shape("c", 700, 390)]
    assert len(centre_bands(jittered)) == 1


# ── fit_rows ──────────────────────────────────────────────────────────────────


def test_fit_rows_leaves_bands_alone_when_the_shelf_count_is_unknown():
    bands = centre_bands([*_printers(), *_cartons(), *_cartons(830, "s", 1)])
    assert len(fit_rows(bands, None)) == 3


def test_fit_rows_leaves_bands_alone_when_they_already_fit():
    card = _shape("card", 900, 100, w=60, h=60, kind=ShapeKind.BOX)
    rows = fit_rows(centre_bands([*_printers(), card]), 2)
    assert [[shape.shape_id for shape, _ in row] for row in rows] == [["card"], ["p0", "p1", "p2"]]


def test_fit_rows_drops_strays_and_stacks_cartons_into_the_known_shelves():
    card = _shape("card", 900, 100, w=60, h=60, kind=ShapeKind.BOX)
    stacked = _cartons(830, "s", 1)
    bands = centre_bands([card, *_printers(), *_cartons(), *stacked])
    assert len(bands) == 4

    rows = fit_rows(bands, 2)

    assert [[shape.shape_id for shape, _ in row] for row in rows] == [["p0", "p1", "p2"], ["c0", "c1", "c2"]]
    # The stacked column is one slot covering both cartons; its anchor is the top one.
    assert rows[1][0][1] == (100, 700, 300, 950)
    assert rows[1][1][1] == (400, 700, 600, 820)


def test_fit_rows_orders_slots_left_to_right():
    band = [_shape("right", 700, 400), _shape("left", 100, 400), _shape("mid", 400, 400)]
    rows = fit_rows([band], 2)
    assert [[shape.shape_id for shape, _ in row] for row in rows] == [["left", "mid", "right"]]


def test_fit_rows_skips_empty_bands():
    assert fit_rows([[], _printers()], 2) == fit_rows([_printers()], 2)
