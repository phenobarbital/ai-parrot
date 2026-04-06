"""Detection grid data models.

Provides Pydantic models for the adaptive grid detection system:
- GridType: supported decomposition strategies
- DetectionGridConfig: configuration for grid decomposition
- GridCell: a single cell in the detection grid
"""
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field


class GridType(str, Enum):
    """Supported grid decomposition strategies.

    Determines how the ROI is split into detection cells before LLM calls.
    """

    NO_GRID = "no_grid"
    HORIZONTAL_BANDS = "horizontal_bands"
    MATRIX_GRID = "matrix_grid"
    ZONE_GRID = "zone_grid"
    FLAT_GRID = "flat_grid"


class DetectionGridConfig(BaseModel):
    """Configuration for detection grid decomposition.

    Added as an optional field to PlanogramConfig.
    When None or grid_type='no_grid', pipeline uses current single-image behavior.
    """

    grid_type: GridType = Field(
        default=GridType.NO_GRID,
        description="Grid decomposition strategy",
    )
    overlap_margin: float = Field(
        default=0.05,
        ge=0.0,
        le=0.20,
        description="Overlap between adjacent cells as ratio of cell dimension",
    )
    max_image_size: int = Field(
        default=1024,
        description="Max pixel dimension for each cell image sent to LLM",
    )
    # For MATRIX_GRID
    rows: Optional[int] = Field(
        default=None,
        description="Number of rows (matrix grid)",
    )
    cols: Optional[int] = Field(
        default=None,
        description="Number of columns (matrix grid)",
    )
    # For FLAT_GRID
    flat_divisions: Optional[int] = Field(
        default=None,
        description="NxN divisions for flat grid (e.g., 2 = 2x2, 3 = 3x3)",
    )
    # For ZONE_GRID
    zones: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description=(
            "Named zone definitions "
            "[{name, y_start_ratio, y_end_ratio, x_start_ratio, x_end_ratio}]"
        ),
    )


class GridCell(BaseModel):
    """A single cell in the detection grid.

    Each cell represents an independent region of the ROI that will be
    sent to the LLM as a separate detection call.
    """

    cell_id: str = Field(
        description="Unique identifier (e.g., 'shelf_top', 'matrix_1_2')",
    )
    bbox: Tuple[int, int, int, int] = Field(
        description="Absolute pixel coordinates (x1, y1, x2, y2) within the full image",
    )
    expected_products: List[str] = Field(
        default_factory=list,
        description="Product names expected in this cell (from planogram config)",
    )
    reference_image_keys: List[str] = Field(
        default_factory=list,
        description="Keys into reference_images dict for products in this cell",
    )
    level: Optional[str] = Field(
        default=None,
        description="Shelf level or zone name, if applicable",
    )
