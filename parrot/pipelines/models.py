from typing import Optional, Dict, List, Any, Union
from pathlib import Path
from enum import Enum
from PIL import Image
from pydantic import BaseModel, Field
from ..models.detections import (
    PlanogramDescription,
    PlanogramDescriptionFactory,
)

class PlanogramConfig(BaseModel):
    """
    Complete configuration for planogram analysis pipeline.
    Contains planogram description, prompts, and reference images.
    """

    # Core planogram configuration
    planogram_config: Dict[str, Any] = Field(
        description="Planogram configuration dictionary (gets converted to PlanogramDescription)"
    )

    # ROI Detection prompt
    roi_detection_prompt: str = Field(
        description="Prompt for ROI detection phase (_find_poster method)"
    )

    # Object identification prompt
    object_identification_prompt: str = Field(
        description="Prompt for Phase 2 object identification"
    )

    # Reference images
    reference_images: Dict[str, Union[str, Path, Image.Image]] = Field(
        default_factory=dict,
        description="Reference images for object identification"
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
