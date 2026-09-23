"""Unit tests for the --boxes override validation (FEAT-592, TASK-3643)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.contracts import PerceptionResult, Slot

from nova2 import load_perception


def _image(width: int = 100, height: int = 80) -> np.ndarray:
    """Return a blank BGR image of the given size."""
    return np.zeros((height, width, 3), dtype=np.uint8)


def _perception(width: int = 100, height: int = 80, box: tuple = (10, 10, 40, 40)) -> PerceptionResult:
    """Return a minimally valid perception result for a single slot."""
    x1, y1, x2, y2 = box
    return PerceptionResult(
        image_id="img0",
        image_size=(width, height),
        slots=[
            Slot(
                slot_id="img0:r0:s1",
                image_id="img0",
                row_index=0,
                slot_index=1,
                box=DetectionBox(x1=x1, y1=y1, x2=x2, y2=y2, confidence=1.0),
            )
        ],
    )


def _write(tmp_path: Path, perception: PerceptionResult) -> Path:
    """Write a perception override and return its path.

    ``exclude_none=True`` works around a pre-existing quirk in
    ``parrot.models.detections.DetectionBox`` (outside this feature's scope,
    G3/AC6): ``class_id``/``class_name``/``area`` are typed non-Optional but
    default to ``None``, so a round-trip through a plain ``model_dump_json()``
    writes an explicit ``null`` that then fails re-validation on load.
    Omitting ``None``-valued fields lets ``model_validate_json`` fall back to
    the (unvalidated) declared defaults instead.
    """
    path = tmp_path / "boxes.json"
    path.write_text(perception.model_dump_json(exclude_none=True), encoding="utf-8")
    return path


def test_load_perception_accepts_a_matching_override(tmp_path: Path) -> None:
    """A consistent override round-trips unchanged."""
    loaded = load_perception(_write(tmp_path, _perception()), _image())
    assert tuple(loaded.image_size) == (100, 80)
    assert len(loaded.slots) == 1


def test_load_perception_rejects_stale_image_size(tmp_path: Path) -> None:
    """An override recorded against a different photo is refused."""
    with pytest.raises(ValueError, match="does not match"):
        load_perception(_write(tmp_path, _perception(width=200, height=160)), _image(100, 80))


def test_load_perception_rejects_out_of_bounds_box(tmp_path: Path) -> None:
    """A box outside the image is refused rather than silently clipped."""
    with pytest.raises(ValueError, match="outside"):
        load_perception(_write(tmp_path, _perception(box=(10, 10, 500, 40))), _image())


def test_load_perception_rejects_dangling_anchor(tmp_path: Path) -> None:
    """A slot whose anchor_shape_id names no shape is refused."""
    perception = _perception()
    perception.slots[0].anchor_shape_id = "img0:missing"
    with pytest.raises(ValueError, match="names no shape"):
        load_perception(_write(tmp_path, perception), _image())


def test_load_perception_rejects_malformed_json(tmp_path: Path) -> None:
    """A file that is not a PerceptionResult fails validation, not silently."""
    path = tmp_path / "boxes.json"
    path.write_text('{"nope": 1}', encoding="utf-8")
    with pytest.raises(ValueError):
        load_perception(path, _image())
