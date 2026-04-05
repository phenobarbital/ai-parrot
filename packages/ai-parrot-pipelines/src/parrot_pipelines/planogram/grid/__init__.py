"""Grid detection package for adaptive planogram compliance.

Provides the infrastructure to decompose an ROI into independent grid cells
before LLM detection, improving accuracy on dense or large planograms.
"""
from parrot_pipelines.planogram.grid.models import (
    DetectionGridConfig,
    GridCell,
    GridType,
)
from parrot_pipelines.planogram.grid.merger import CellResultMerger
from parrot_pipelines.planogram.grid.strategy import (
    AbstractGridStrategy,
    NoGrid,
    get_strategy,
)

__all__ = [
    "AbstractGridStrategy",
    "CellResultMerger",
    "DetectionGridConfig",
    "GridCell",
    "GridType",
    "NoGrid",
    "get_strategy",
]
