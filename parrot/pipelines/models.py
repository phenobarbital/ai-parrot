from typing import Optional
from enum import Enum
from pydantic import BaseModel, Field


PROMO_NAMES = {"promotional_candidate", "promotional_graphic"}

class ObjectType(str, Enum):
    """Enumeration of object types."""
    PRODUCT_CANDIDATE = "product_candidate"
    BOX_CANDIDATE = "box_candidate"
    IMAGE_CANDIDATE = "image_candidate"
    PROMOTIONAL_CANDIDATE = "promotional_candidate"
    UNCLEAR = "unclear"


class VerificationResult(BaseModel):
    """The result of verifying a single cropped object image."""
    object_type: ObjectType = Field(
        ...,
        description="The classification of the object in the image."
    )
    visible_text: Optional[str] = Field(
        None,
        description="Any clearly visible text extracted from the image, cleaned up. Null if no legible text is found."
    )
