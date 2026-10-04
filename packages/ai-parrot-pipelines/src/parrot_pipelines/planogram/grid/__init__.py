"""Detection-grid configuration models (accepted, not executed).

The grid execution classes were removed with the legacy pipeline (FEAT-612). ``DetectionGridConfig`` is kept
because ``PlanogramConfig.detection_grid`` is still accepted — and ignored — for one release.
"""

from parrot_pipelines.planogram.grid.models import (
    DetectionGridConfig,
    GridCell,
    GridType,
)

__all__ = [
    "DetectionGridConfig",
    "GridCell",
    "GridType",
]
