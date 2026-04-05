from typing import Optional, Dict, List, Any, Union
from pathlib import Path
from enum import Enum
from PIL import Image
from pydantic import BaseModel, Field
from parrot.models.detections import (
    PlanogramDescription,
    PlanogramDescriptionFactory,
)
from parrot_pipelines.planogram.grid.models import DetectionGridConfig

class EndcapGeometry(BaseModel):
    """Configurable endcap geometry parameters"""
    aspect_ratio: float = Field(default=1.35, description="Endcap width/height ratio")
    left_margin_ratio: float = Field(default=0.01, description="Left margin as ratio of panel width")
    right_margin_ratio: float = Field(default=0.03, description="Right margin as ratio of panel width")
    top_margin_ratio: float = Field(default=0.02, description="Top margin as ratio of panel height")

    # NEW: Additional margin controls for better shelf separation
    bottom_margin_ratio: float = Field(default=0.05, description="Bottom margin as ratio of panel height")
    inter_shelf_padding: float = Field(default=0.02, description="Padding between shelves as ratio of ROI height")

    # ROI detection specific margins
    width_margin_percent: float = Field(default=0.25, description="Panel width margin percentage")
    height_margin_percent: float = Field(default=0.30, description="Panel height margin percentage")
    top_margin_percent: float = Field(default=0.05, description="Panel top margin percentage")
    side_margin_percent: float = Field(default=0.05, description="Panel side margin percentage")

class PlanogramConfig(BaseModel):
    """
    Complete configuration for planogram analysis pipeline.
    Contains planogram description, prompts, and reference images.
    """
    planogram_id: Optional[int] = Field(
        default=None,
        description="Optional unique identifier for the planogram (if any)"
    )

    config_name: str = Field(
        default="default_planogram_config",
        description="Name of the planogram configuration"
    )

    planogram_type: str = Field(
        default="product_on_shelves",
        description="Type of planogram composable to use (e.g. product_on_shelves, ink_wall, tv_wall)"
    )

    # Core planogram configuration
    planogram_config: Dict[str, Any] = Field(
        description="Planogram configuration dictionary (gets converted to PlanogramDescription)"
    )

    # ROI Detection prompt
    roi_detection_prompt: str = Field(
        description="Prompt for ROI detection phase (used by _find_poster method)"
    )

    # Object identification prompt
    object_identification_prompt: str = Field(
        description="Prompt for Phase 2 object identification (used by _identify_objects method)"
    )

    # Reference images — supports single image or list of images per product
    reference_images: Dict[str, Union[str, Path, List[str], List[Path], Image.Image]] = Field(
        default_factory=dict,
        description=(
            "Reference images for object identification. "
            "Supports a single image path/object or a list of images per product key."
        )
    )

    # Optional: Additional detection parameters
    confidence_threshold: float = Field(
        default=0.25,
        description="YOLO detection confidence threshold"
    )

    detection_model: str = Field(
        default="yolo11l.pt",
        description="YOLO model to use for detection"
    )

    endcap_geometry: EndcapGeometry = Field(
        default_factory=EndcapGeometry,
        description="Endcap geometry and margin configuration"
    )

    # Detection grid configuration (optional)
    detection_grid: Optional[DetectionGridConfig] = Field(
        default=None,
        description=(
            "Detection grid configuration. "
            "When None or grid_type='no_grid', pipeline uses current single-image behavior."
        )
    )

    class Config:
        """Pydantic configuration."""
        arbitrary_types_allowed = True

    def get_planogram_description(self) -> PlanogramDescription:
        """
        Load and validate a planogram description from a configuration dictionary.
        Uses PlanogramDescriptionFactory to parse and validate the config.
        """
        factory = PlanogramDescriptionFactory()
        return factory.create_planogram_description(self.planogram_config)
