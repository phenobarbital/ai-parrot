from typing import List, Dict, Optional
from pydantic import BaseModel, Field

class DetectionBox(BaseModel):
    """Bounding box from object detection"""
    x1: int = Field(description="Left x coordinate")
    y1: int = Field(description="Top y coordinate")
    x2: int = Field(description="Right x coordinate")
    y2: int = Field(description="Bottom y coordinate")
    confidence: float = Field(ge=0.0, le=1.0, description="Detection confidence")
    class_id: int = Field(description="Detected class ID")
    class_name: str = Field(description="Detected class name")
    area: int = Field(description="Bounding box area in pixels")


class ShelfRegion(BaseModel):
    """Detected shelf region"""
    shelf_id: str = Field(description="Unique shelf identifier")
    bbox: DetectionBox = Field(description="Shelf bounding box")
    level: str = Field(description="Shelf level (top, middle, bottom)")
    objects: List[DetectionBox] = Field(default_factory=list, description="Objects on this shelf")


class IdentifiedProduct(BaseModel):
    """Product identified by LLM using reference images"""
    detection_box: Optional[DetectionBox] = Field(None, description="Detection box information")
    product_type: str = Field(description="Type of product")
    product_model: Optional[str] = Field(None, description="Specific product model")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score")
    visual_features: List[str] = Field(default_factory=list, description="Visual features")
    reference_match: Optional[str] = Field(None, description="Reference image match")
    shelf_location: str = Field(description="Shelf location")
    position_on_shelf: str = Field(description="Position on shelf")
    detection_id: Optional[int] = Field(None, description="Detection ID from annotated image")


class PlanogramDescription(BaseModel):
    """Expected planogram layout

    Example structure:
    {
        "top": ["ET-2980 demo", "ET-3950 demo", "ET-4950 demo"],
        "middle": ["fact_tag_2980", "fact_tag_3950", "fact_tag_4950"],
        "bottom": ["ET-2980 box", "ET-3950 box", "ET-4950 box"],
        "header": ["backlit_graphic"]
    }
    """
    shelves: Dict[str, List[str]] = Field(description="Expected products per shelf level")
