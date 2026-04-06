"""Cell Result Merger for grid-based detection.

Merges per-cell detection results from parallel LLM calls into a
unified product list. Handles:
- Coordinate offset correction: cell-relative coords -> absolute image coords
- IoU-based boundary deduplication: removes duplicates at cell boundaries
- Out-of-place tagging: flags products detected in the wrong cell
"""
import logging
from typing import List, Optional, Tuple

from parrot_pipelines.planogram.grid.models import GridCell
from parrot.models.detections import DetectionBox, IdentifiedProduct


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


class CellResultMerger:
    """Merges per-cell detection results into a unified product list.

    Applies per-cell coordinate offsets to convert cell-relative detections
    to absolute image coordinates. Deduplicates boundary objects using IoU.
    Tags objects not in any cell's expected_products as out_of_place.
    """

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)

    def merge(
        self,
        cell_results: List[Tuple[GridCell, List[IdentifiedProduct]]],
        iou_threshold: float = 0.5,
    ) -> List[IdentifiedProduct]:
        """Merge detection results from multiple grid cells.

        Args:
            cell_results: List of (cell, products) tuples from parallel detection.
                Each product's detection_box coordinates are relative to the
                cell's crop origin (cell.bbox[0], cell.bbox[1]).
            iou_threshold: IoU threshold for boundary deduplication. Detections
                above this threshold are considered duplicates; the one with
                higher confidence is kept.

        Returns:
            Unified list of IdentifiedProduct with absolute image coordinates.
        """
        all_products: List[IdentifiedProduct] = []

        for cell, products in cell_results:
            for product in products:
                # 1. Apply coordinate offset: cell-relative -> absolute
                self._apply_offset(product, cell.bbox)

                # 2. Tag out-of-place products
                if (
                    product.product_model
                    and cell.expected_products
                    and product.product_model not in cell.expected_products
                ):
                    if hasattr(product, "out_of_place"):
                        product.out_of_place = True
                    else:
                        extra = dict(product.extra)
                        extra["out_of_place"] = "true"
                        product.extra = extra

                all_products.append(product)

        # 3. Deduplicate boundary objects
        return self._deduplicate(all_products, iou_threshold)

    def _apply_offset(
        self,
        product: IdentifiedProduct,
        cell_bbox: Tuple[int, int, int, int],
    ) -> None:
        """Apply cell origin offset to product detection_box in-place.

        Converts cell-relative coordinates to absolute image coordinates
        by adding the cell's top-left corner (x1, y1).

        Args:
            product: IdentifiedProduct to update (mutated in-place).
            cell_bbox: Cell bounding box (x1, y1, x2, y2) in absolute pixels.
        """
        if product.detection_box is None:
            return

        offset_x, offset_y = cell_bbox[0], cell_bbox[1]
        product.detection_box.x1 += offset_x
        product.detection_box.y1 += offset_y
        product.detection_box.x2 += offset_x
        product.detection_box.y2 += offset_y

    def _deduplicate(
        self,
        products: List[IdentifiedProduct],
        iou_threshold: float,
    ) -> List[IdentifiedProduct]:
        """Remove duplicate detections at cell boundaries using IoU.

        When two detections have overlapping boxes above iou_threshold,
        the one with the lower confidence is discarded.

        Args:
            products: Full list of products after offset correction.
            iou_threshold: IoU threshold for duplicate detection.

        Returns:
            Deduplicated list with higher-confidence detections retained.
        """
        if not products:
            return []

        # Sort by confidence descending so higher-confidence detections win
        sorted_products = sorted(products, key=lambda p: p.confidence, reverse=True)
        kept: List[IdentifiedProduct] = []

        for candidate in sorted_products:
            if candidate.detection_box is None:
                # No bbox to compare — always keep
                kept.append(candidate)
                continue

            is_duplicate = False
            for existing in kept:
                if existing.detection_box is None:
                    continue
                iou = _compute_iou(candidate.detection_box, existing.detection_box)
                if iou >= iou_threshold:
                    is_duplicate = True
                    self.logger.debug(
                        "Deduplicating: '%s' (conf=%.2f) overlaps with '%s' "
                        "(conf=%.2f, IoU=%.3f)",
                        candidate.product_model,
                        candidate.confidence,
                        existing.product_model,
                        existing.confidence,
                        iou,
                    )
                    break

            if not is_duplicate:
                kept.append(candidate)

        return kept
