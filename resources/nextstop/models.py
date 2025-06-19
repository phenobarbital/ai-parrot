# Pydantic:
from pydantic import BaseModel, Field, ConfigDict

class StoreInfoInput(BaseModel):
    """Input schema for store-related operations requiring a Store ID."""
    store_id: str = Field(
        ...,
        description="The unique identifier of the store you want to visit or know about.",
        example="BBY123",
        title="Store ID",
        min_length=1,
        max_length=50
    )
    # Add a model_config to prevent additional properties
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        json_schema_extra={
            "required": ["store_id"]
        }
    )
