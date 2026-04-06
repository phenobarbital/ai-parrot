"""Abstract Grid Strategy and NoGrid default implementation.

Defines the ABC that all grid decomposition strategies implement,
plus NoGrid which preserves the current single-image detection behavior.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Type

from parrot_pipelines.planogram.grid.models import DetectionGridConfig, GridCell, GridType


class AbstractGridStrategy(ABC):
    """Base class for grid decomposition strategies.

    Concrete strategies implement compute_cells() to split an ROI into
    independent detection cells based on planogram configuration.

    All strategies must be stateless — configuration is passed via
    DetectionGridConfig at call time.
    """

    @abstractmethod
    def compute_cells(
        self,
        roi_bbox: tuple,
        image_size: tuple,
        planogram_description: Any,
        grid_config: DetectionGridConfig,
    ) -> List[GridCell]:
        """Decompose the ROI into grid cells for detection.

        Args:
            roi_bbox: ROI coordinates (x1, y1, x2, y2) in absolute pixels.
            image_size: Full image (width, height).
            planogram_description: PlanogramDescription with shelf/product info.
            grid_config: Grid configuration parameters.

        Returns:
            List of GridCell, each defining a region to detect independently.
        """


class NoGrid(AbstractGridStrategy):
    """Default grid strategy — no decomposition.

    Returns a single GridCell covering the entire ROI with all expected
    products from all shelves. Preserves current single-image behavior.
    """

    def compute_cells(
        self,
        roi_bbox: tuple,
        image_size: tuple,
        planogram_description: Any,
        grid_config: DetectionGridConfig,
    ) -> List[GridCell]:
        """Return a single cell covering the full ROI.

        Args:
            roi_bbox: ROI coordinates (x1, y1, x2, y2).
            image_size: Full image dimensions (width, height).
            planogram_description: PlanogramDescription — used to collect all
                expected product names across all shelves.
            grid_config: Grid configuration (overlap_margin etc.).

        Returns:
            List with exactly one GridCell covering roi_bbox.
        """
        # Collect all product names from all shelves
        all_products: List[str] = []
        if planogram_description is not None:
            for shelf in getattr(planogram_description, "shelves", []):
                for product in getattr(shelf, "products", []):
                    name = getattr(product, "name", None)
                    if name:
                        all_products.append(name)

        return [
            GridCell(
                cell_id="full_roi",
                bbox=roi_bbox,
                expected_products=all_products,
                reference_image_keys=all_products,
                level=None,
            )
        ]


# ---------------------------------------------------------------------------
# Strategy registry
# ---------------------------------------------------------------------------

_GRID_STRATEGIES: Dict[GridType, Type[AbstractGridStrategy]] = {
    GridType.NO_GRID: NoGrid,
}


def get_strategy(grid_type: GridType) -> AbstractGridStrategy:
    """Instantiate and return the grid strategy for the given GridType.

    Args:
        grid_type: The desired grid strategy type.

    Returns:
        An instance of the corresponding AbstractGridStrategy subclass.

    Raises:
        ValueError: If grid_type is not registered in the strategy registry.
    """
    cls = _GRID_STRATEGIES.get(grid_type)
    if cls is None:
        raise ValueError(
            f"Unknown grid type: {grid_type!r}. "
            f"Registered types: {list(_GRID_STRATEGIES.keys())}"
        )
    return cls()
