"""HorizontalBands grid strategy for product-on-shelves planograms.

Splits the ROI into N horizontal bands based on shelf height_ratios from
the planogram description. Each band becomes an independent detection cell
with focused product hints for that shelf level.
"""
from typing import Any, List

from parrot_pipelines.planogram.grid.models import DetectionGridConfig, GridCell, GridType
from parrot_pipelines.planogram.grid.strategy import AbstractGridStrategy, _GRID_STRATEGIES


class HorizontalBands(AbstractGridStrategy):
    """Grid strategy that decomposes the ROI into horizontal shelf bands.

    Reads shelf configurations from PlanogramDescription to determine:
    - The number of bands (N = number of configured shelves)
    - Each band's vertical extent (proportional to shelf.height_ratio)
    - Expected products per band (from shelf.products[].name)

    An overlap margin is applied to extend each band's top/bottom boundary
    so that products near cell boundaries are captured by both adjacent cells
    and later deduplicated by CellResultMerger.
    """

    def compute_cells(
        self,
        roi_bbox: tuple,
        image_size: tuple,
        planogram_description: Any,
        grid_config: DetectionGridConfig,
    ) -> List[GridCell]:
        """Decompose the ROI into horizontal shelf bands.

        Args:
            roi_bbox: ROI coordinates (x1, y1, x2, y2) in absolute pixels.
            image_size: Full image dimensions (width, height).
            planogram_description: PlanogramDescription with shelf config.
            grid_config: Grid configuration — uses overlap_margin.

        Returns:
            List of GridCell, one per shelf, with absolute pixel coords.
            Falls back to a single full-ROI cell if shelves is empty.
        """
        x1, y1, x2, y2 = roi_bbox
        roi_height = y2 - y1

        shelves = getattr(planogram_description, "shelves", []) if planogram_description else []

        if not shelves:
            # Fallback: single cell covering entire ROI (NoGrid behavior)
            return [
                GridCell(
                    cell_id="full_roi",
                    bbox=roi_bbox,
                    expected_products=[],
                    reference_image_keys=[],
                    level=None,
                )
            ]

        overlap_px = int(roi_height * grid_config.overlap_margin)
        cells: List[GridCell] = []
        current_y = y1

        for shelf in shelves:
            level = getattr(shelf, "level", f"band_{len(cells)}")
            height_ratio = getattr(shelf, "height_ratio", None)

            if height_ratio is not None:
                band_height = int(roi_height * float(height_ratio))
            else:
                # Default: equal division
                band_height = roi_height // max(len(shelves), 1)

            # Apply overlap — extend each band beyond its nominal extent,
            # clamped to ROI bounds
            band_y1 = max(y1, current_y - overlap_px)
            band_y2 = min(y2, current_y + band_height + overlap_px)

            # Extract expected products from this shelf's config
            products: List[str] = []
            for product in getattr(shelf, "products", []):
                name = getattr(product, "name", None)
                if name:
                    products.append(name)

            cells.append(
                GridCell(
                    cell_id=level,
                    bbox=(x1, band_y1, x2, band_y2),
                    expected_products=products,
                    reference_image_keys=products,
                    level=level,
                )
            )

            current_y += band_height

            # Stop if we've exhausted the ROI height
            if current_y >= y2:
                break

        return cells


# Register HorizontalBands in the global strategy registry
_GRID_STRATEGIES[GridType.HORIZONTAL_BANDS] = HorizontalBands
