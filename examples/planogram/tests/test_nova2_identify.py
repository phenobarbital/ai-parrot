"""Unit tests for the flattening join (FEAT-592, TASK-3642)."""

from __future__ import annotations

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.contracts import (
    Identification,
    IdentificationResult,
    ObservationSource,
    PerceptionResult,
    Shape,
    Slot,
)

from identify import flatten


def _box(x1: int, y1: int, x2: int, y2: int) -> DetectionBox:
    return DetectionBox(x1=x1, y1=y1, x2=x2, y2=y2, confidence=1.0)


def _perception() -> PerceptionResult:
    """Build one image with two slots, including a gap-filled slot."""
    return PerceptionResult(
        image_id="img0",
        image_size=(1000, 800),
        slots=[
            Slot(
                slot_id="img0:r0:s1",
                image_id="img0",
                row_index=0,
                slot_index=1,
                box=_box(10, 20, 110, 220),
                inferred=False,
            ),
            Slot(
                slot_id="img0:r0:s2",
                image_id="img0",
                row_index=0,
                slot_index=2,
                box=_box(120, 20, 220, 220),
                inferred=True,
            ),
        ],
    )


def _identification(shape_id: str, **values: object) -> Identification:
    return Identification(shape_id=shape_id, raw_confidence=0.9, **values)


def test_flatten_joins_slot_ids_to_source_pixels() -> None:
    """A slot identification gets that slot's source-pixel box."""
    result = IdentificationResult(
        image_id="img0",
        identifications=[
            _identification("img0:r0:s1", product="9C228AN", brand="HP", occupancy="occupied"),
        ],
    )

    rows = flatten(result, _perception())

    assert [row.bbox for row in rows] == [[10, 20, 110, 220]]
    assert rows[0].brand == "HP"
    assert rows[0].occupancy == "occupied"


def test_flatten_marks_inferred_slots() -> None:
    """A gap-filled slot carries its inferred flag into the flat row."""
    result = IdentificationResult(
        image_id="img0",
        identifications=[_identification("img0:r0:s2", occupancy="empty")],
    )

    rows = flatten(result, _perception())

    assert rows[0].inferred is True


def test_flatten_joins_added_shapes() -> None:
    """An LLM-added shape uses its own box and llm_added source."""
    added = Shape(
        shape_id="img0:added:1",
        image_id="img0",
        box=_box(300, 20, 400, 220),
        source=ObservationSource.LLM_ADDED,
    )
    result = IdentificationResult(
        image_id="img0",
        identifications=[_identification("img0:added:1", occupancy="occupied")],
        added=[added],
    )

    rows = flatten(result, _perception())

    assert rows[0].bbox == [300, 20, 400, 220]
    assert rows[0].source == "llm_added"


def test_flatten_skips_unmatched_ids() -> None:
    """An id without a source box is omitted rather than emitted with a null box."""
    result = IdentificationResult(
        image_id="img0",
        identifications=[_identification("img0:r9:s9")],
    )

    assert flatten(result, _perception()) == []


def test_flatten_never_emits_normalised_coordinates() -> None:
    """Every flattened coordinate remains in the source image's pixel bounds."""
    result = IdentificationResult(
        image_id="img0",
        identifications=[
            _identification("img0:r0:s1"),
            _identification("img0:r0:s2"),
        ],
    )

    rows = flatten(result, _perception())

    assert all(0 <= coordinate <= bound for row in rows for coordinate, bound in zip(row.bbox, (1000, 800, 1000, 800)))
