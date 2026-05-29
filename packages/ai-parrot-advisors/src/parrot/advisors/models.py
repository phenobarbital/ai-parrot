# parrot/advisors/models.py
from pydantic import BaseModel, Field, computed_field
from typing import List, Dict, Any, Optional, Literal
from datetime import datetime
from enum import Enum


class FeatureType(str, Enum):
    """Types of product features for filtering logic."""
    NUMERIC = "numeric"      # Can compare: >, <, =
    CATEGORICAL = "categorical"  # Exact match or in list
    BOOLEAN = "boolean"      # Yes/No
    RANGE = "range"          # Min-max range
    TEXT = "text"            # Free text (for RAG, not filtering)


class ProductFeature(BaseModel):
    """A single product feature/specification."""
    name: str
    value: Any
    feature_type: FeatureType = FeatureType.TEXT
    unit: Optional[str] = None
    display_name: Optional[str] = None  # Human-readable
    is_filterable: bool = True  # Can be used for filtering
    filter_priority: int = 0    # Higher = asked earlier
    
    # For categorical features
    valid_values: Optional[List[str]] = None


class ProductDimensions(BaseModel):
    """Physical dimensions (for space-based filtering)."""
    width: float
    depth: float
    height: float
    unit: Literal["ft", "m", "in", "cm"] = "ft"
    
    @computed_field
    @property
    def footprint(self) -> float:
        """Calculate floor space needed."""
        return self.width * self.depth
    
    def fits_in(self, available_width: float, available_depth: float) -> bool:
        """Check if product fits in available space."""
        # Check both orientations
        return (
            (self.width <= available_width and self.depth <= available_depth) or
            (self.depth <= available_width and self.width <= available_depth)
        )


class ProductSpec(BaseModel):
    """
    Complete product specification.
    
    This is the canonical model for any product in the catalog.
    The markdown_content is vectorized; features are used for filtering.
    """
    product_id: str
    name: str
    category: str
    subcategory: Optional[str] = None  # e.g., "commercial", "home", "pool", "farm", "backyard"
    
    # Structured data
    dimensions: Optional[ProductDimensions] = None
    features: List[ProductFeature] = Field(default_factory=list)
    use_cases: List[str] = Field(default_factory=list)
    price: Optional[float] = None
    price_range: Optional[str] = None  # "budget", "mid-range", "premium"
    
    # Short description (distinct from markdown_content)
    description: Optional[str] = None
    
    # URLs and media
    url: Optional[str] = None
    image_url: Optional[str] = None
    brochure_url: Optional[str] = None
    
    # For RAG - the full text content (markdown version of product brochure)
    markdown_content: str = ""
    
    # For comparisons
    unique_selling_points: List[str] = Field(default_factory=list)
    
    # New JSONB fields for extended product data
    faqs: List[Dict[str, Any]] = Field(default_factory=list)  # FAQ list [{question, answer}]
    product_variants: List[Dict[str, Any]] = Field(default_factory=list)  # Variant options
    product_json: Dict[str, Any] = Field(default_factory=dict)  # Raw source JSON
    product_data: Dict[str, Any] = Field(default_factory=dict)  # Additional metadata
    specs: Dict[str, Any] = Field(default_factory=dict)  # Structured specs: misc, roof, floor, wall, door
    
    # Metadata
    catalog_id: str = "default"  # Multi-tenant support
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    def get_feature(self, name: str) -> Optional[ProductFeature]:
        """Get a feature by name."""
        for f in self.features:
            if f.name == name:
                return f
        return None
    
    def matches_criteria(self, criteria: Dict[str, Any]) -> bool:
        """Check if product matches all criteria."""
        for key, value in criteria.items():
            if key == "max_footprint" and self.dimensions:
                if self.dimensions.footprint > value:
                    return False
            elif key == "use_case":
                if value not in self.use_cases:
                    return False
            else:
                feature = self.get_feature(key)
                if feature:
                    if feature.feature_type == FeatureType.NUMERIC:
                        # Handle numeric comparisons
                        if isinstance(value, dict):
                            if "min" in value and feature.value < value["min"]:
                                return False
                            if "max" in value and feature.value > value["max"]:
                                return False
                        elif feature.value != value:
                            return False
                    elif feature.feature_type == FeatureType.CATEGORICAL:
                        if isinstance(value, list):
                            if feature.value not in value:
                                return False
                        elif feature.value != value:
                            return False
        return True