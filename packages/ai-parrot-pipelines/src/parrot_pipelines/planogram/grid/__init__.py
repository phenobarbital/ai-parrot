"""Grid detection package for adaptive planogram compliance.

Provides the infrastructure to decompose an ROI into independent grid cells
before LLM detection, improving accuracy on dense or large planograms.
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
