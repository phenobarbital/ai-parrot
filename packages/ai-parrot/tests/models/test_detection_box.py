"""Tests for :class:`parrot.models.detections.DetectionBox` serialization."""
from parrot.models.detections import DetectionBox


def test_optional_fields_round_trip_through_json() -> None:
    """A box without class_id/class_name/area survives dump -> validate."""
    box = DetectionBox(x1=1, y1=2, x2=30, y2=40, confidence=0.9)
    restored = DetectionBox.model_validate_json(box.model_dump_json())
    assert restored == box
    assert restored.class_id is None
    assert restored.class_name is None
    assert restored.area is None


def test_explicit_null_is_accepted() -> None:
    """Explicit JSON nulls validate instead of raising 'valid integer'."""
    payload = '{"x1": 0, "y1": 0, "x2": 5, "y2": 5, "confidence": 0.5,' \
        ' "class_id": null, "class_name": null, "area": null}'
    box = DetectionBox.model_validate_json(payload)
    assert box.class_id is None and box.class_name is None and box.area is None


def test_populated_fields_round_trip() -> None:
    """Populated optional fields keep their values across a round-trip."""
    box = DetectionBox(x1=1, y1=2, x2=30, y2=40, confidence=0.9, class_id=3, class_name="tv", area=1064)
    restored = DetectionBox.model_validate_json(box.model_dump_json())
    assert (restored.class_id, restored.class_name, restored.area) == (3, "tv", 1064)
