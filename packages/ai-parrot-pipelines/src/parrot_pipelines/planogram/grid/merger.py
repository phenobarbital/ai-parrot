"""Bounding-box overlap helper shared by the identification stage.

Only ``_compute_iou`` survives the removal of the grid execution classes (FEAT-612): the identify stage uses it
to reject model-added shapes that duplicate an existing area.
"""

from parrot.models.detections import DetectionBox


def _compute_iou(box_a: DetectionBox, box_b: DetectionBox) -> float:
    """Compute Intersection over Union (IoU) between two DetectionBox instances.

    Args:
        box_a: First bounding box.
        box_b: Second bounding box.

    Returns:
        IoU score in [0.0, 1.0]. Returns 0.0 if union area is zero.
    """
    # Intersection coordinates
    ix1 = max(box_a.x1, box_b.x1)
    iy1 = max(box_a.y1, box_b.y1)
    ix2 = min(box_a.x2, box_b.x2)
    iy2 = min(box_a.y2, box_b.y2)

    inter_w = max(0, ix2 - ix1)
    inter_h = max(0, iy2 - iy1)
    intersection = inter_w * inter_h

    if intersection == 0:
        return 0.0

    area_a = max(0, box_a.x2 - box_a.x1) * max(0, box_a.y2 - box_a.y1)
    area_b = max(0, box_b.x2 - box_b.x1) * max(0, box_b.y2 - box_b.y1)
    union = area_a + area_b - intersection

    if union <= 0:
        return 0.0

    return intersection / union
