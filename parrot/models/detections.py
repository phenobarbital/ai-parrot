from typing import List, Dict, Optional, Literal, Any, Mapping
import uuid
from pydantic import BaseModel, Field, field_validator

class BoundingBox(BaseModel):
    """Normalized bounding box coordinates"""
    x1: float = Field(..., description="The leftmost x-coordinate (normalized)", ge=0, le=1)
    y1: float = Field(..., description="The topmost y-coordinate (normalized)", ge=0, le=1)
    x2: float = Field(..., description="The rightmost x-coordinate (normalized)", ge=0, le=1)
    y2: float = Field(..., description="The bottommost y-coordinate (normalized)", ge=0, le=1)

    def get_coordinates(self) -> tuple[float, float, float, float]:
        """Return bounding box as (x1, y1, x2, y2)"""
        return (self.x1, self.y1, self.x2, self.y2)

    def get_pixel_coordinates(self, width: int, height: int) -> tuple[int, int, int, int]:
        """Return bounding box as (x1, y1, x2, y2) absolute integer pixels."""
        px1 = int(self.x1 * width)
        py1 = int(self.y1 * height)
        px2 = int(self.x2 * width)
        py2 = int(self.y2 * height)
        return (px1, py1, px2, py2)

class Detection(BaseModel):
    """Generic detection result"""
    label: Optional[str] = Field(None, description="Optional label for the detection")
    confidence: float = Field(ge=0.0, le=1.0, description="Detection confidence")
    content: Optional[str] = Field(None, description="The recognized text content within the bounding box, if any.")
    bbox: BoundingBox


class Detections(BaseModel):
    """Collection of detections in an image"""
    detections: List[Detection] = Field(default_factory=list, description="List of detected bounding boxes")


class DetectionBox(BaseModel):
    """Bounding box from object detection"""
    x1: int = Field(description="Left x coordinate")
    y1: int = Field(description="Top y coordinate")
    x2: int = Field(description="Right x coordinate")
    y2: int = Field(description="Bottom y coordinate")
    confidence: float = Field(ge=0.0, le=1.0, description="Detection confidence")
    class_id: int = Field(default=None, description="Detected class ID")
    class_name: str = Field(default=None, description="Detected class name")
    area: int = Field(default=None, description="Bounding box area in pixels")
    label: Optional[str] = Field(None, description="Optional label for the detection")
    ocr_text: Optional[str] = Field(
        None,
        description="OCR text within the bounding box, if any"
    )

class ShelfRegion(BaseModel):
    """Detected shelf region"""
    shelf_id: str = Field(description="Unique shelf identifier")
    bbox: DetectionBox = Field(description="Shelf bounding box")
    level: str = Field(description="Shelf level (top, middle, bottom)")
    objects: List[DetectionBox] = Field(default_factory=list, description="Objects on this shelf")


class IdentifiedProduct(BaseModel):
    """Product identified by LLM using reference images"""
    detection_id: int = Field(None, description="The unique ID of the corresponding detection box.")
    product_type: str = Field(description="Type of product")
    product_model: Optional[str] = Field(None, description="Specific product model")
    brand: Optional[str] = Field(None, description="Brand on the item (e.g., Epson)")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score")
    visual_features: List[str] = Field(default_factory=list, description="List of key visual identifiers.")
    reference_match: Optional[str] = Field(None, description="Which reference image was matched, or 'none'.")
    shelf_location: Optional[str] = Field(
        None, description="The shelf level where the product is located: 'header', 'top', 'middle', 'bottom'."
    )
    position_on_shelf: Optional[str] = Field(
        None, description="Position on the shelf: 'left', 'center', 'right'."
    )
    advertisement_type: Optional[str] = Field(
        None, description="Ad type if promotional (backlit_graphic, endcap_poster, shelf_talker, banner, digital_display)"
    )
    detection_box: Optional[DetectionBox] = Field(None, description="Detection box information")
    extra: Dict[str, str] = Field(default_factory=dict, description="Any Extra descriptive tags")

    @field_validator('confidence', mode='before')
    @classmethod
    def validate_confidence(cls, v: Any) -> float:
        """Ensure confidence is between 0 and 1."""
        if isinstance(v, str):
            if v.lower() == 'high':
                return 0.9
            elif v.lower() == 'medium':
                return 0.6
            elif v.lower() == 'low':
                return 0.3
            else:
                return 0.5  # Default for unrecognized strings
        if not (0 <= v <= 1):
            raise ValueError(f"confidence must be between 0 and 1, got {v}")
        return v

    @field_validator('position_on_shelf', mode='before')
    @classmethod
    def validate_position_on_shelf(cls, v: Any) -> Optional[str]:
        """Ensure position_on_shelf is one of the accepted values."""
        if isinstance(v, int):
            mapping = {0: "left", 1: "center", 2: "right"}
            return mapping.get(v, None)
        valid_positions = {"left", "center", "right"}
        if v is not None and v.lower() not in valid_positions:
            raise ValueError(f"position_on_shelf must be one of {valid_positions}, got '{v}'")
        return v.lower() if v else v

    @field_validator('detection_id', mode='before')
    @classmethod
    def set_id_for_llm_found_items(cls, v: Any) -> int:
        """If detection_id is null, generate a unique negative ID."""
        if v is None:
            # Generate a unique integer to avoid collisions. Negative values clearly
            # indicate that this item was found by the LLM, not YOLO.
            return -int(str(uuid.uuid4().int)[:8])
        return v

    # VALIDATOR 2: Converts a coordinate list into a DetectionBox object.
    @field_validator('detection_box', mode='before')
    @classmethod
    def convert_list_to_detection_box(cls, v: Any, values: Any) -> Any:
        """If detection_box is a list [x1,y1,x2,y2], convert it to a DetectionBox object."""
        # The 'v' is the value of the 'detection_box' field itself.
        if isinstance(v, list) and len(v) == 4:
            x1, y1, x2, y2 = v

            # We need the confidence to create a valid DetectionBox.
            # 'values.data' gives us access to the other raw data in the JSON object.
            confidence = values.data.get('confidence', 0.95) # Default to 0.95 if not found

            return DetectionBox(
                x1=int(x1),
                y1=int(y1),
                x2=int(x2),
                y2=int(y2),
                confidence=float(confidence),
                class_id=0,  # Placeholder ID for LLM-found items
                class_name='llm_detected',
                area=abs(int(x2) - int(x1)) * abs(int(y2) - int(y1))
            )
        # If it's already a dict or a DetectionBox object, pass it through.
        return v

class IdentificationResponse(BaseModel):
    """Response from product identification"""
    identified_products: List[IdentifiedProduct] = Field(
        alias="detections",
        description="List of identified products from the image"
    )

# Enhanced models for pipeline planogram description
class BrandDetectionConfig(BaseModel):
    """Configuration for brand detection parameters"""
    enabled: bool = Field(default=True, description="Enable brand detection")
    target_brands: List[str] = Field(default_factory=list, description="List of brands to detect")
    confidence_threshold: float = Field(default=0.7, description="Minimum confidence for brand detection")
    ocr_enabled: bool = Field(default=True, description="Use OCR for brand text detection")
    case_sensitive: bool = Field(default=False, description="Case-sensitive brand matching")

class CategoryDetectionConfig(BaseModel):
    """Configuration for product category detection"""
    enabled: bool = Field(default=True, description="Enable category detection")
    target_categories: List[str] = Field(default_factory=list, description="Categories to detect (printers, boxes, etc.)")
    size_based_classification: bool = Field(default=True, description="Use size for category classification")
    visual_features_weight: float = Field(default=0.6, description="Weight of visual features in classification")
    confidence_threshold: float = Field(default=0.6, description="Minimum confidence for category detection")

class ShelfProduct(BaseModel):
    """Configuration for products expected on a shelf"""
    name: str = Field(description="Product name/model")
    product_type: str = Field(description="Type: printer, product_box, promotional_graphic, etc.")
    quantity_range: tuple[int, int] = Field(default=(1, 1), description="Min and max quantity expected")
    position_preference: Optional[Literal["left", "center", "right"]] = Field(default=None, description="Preferred position on shelf")
    mandatory: bool = Field(default=True, description="Whether this product is required")
    visual_features: Optional[List[str]] = Field(default=None, description="Expected key visual identifiers and features for this product")

class ShelfConfig(BaseModel):
    """Configuration for a single shelf"""
    level: str = Field(description="Shelf level: header, top, middle, bottom")
    products: List[ShelfProduct] = Field(description="Expected products on this shelf")
    compliance_threshold: float = Field(default=0.8, description="Compliance threshold for this shelf")
    allow_extra_products: bool = Field(default=False, description="Allow products not in the specification")
    position_strict: bool = Field(default=False, description="Enforce strict positioning")
    height_ratio: Optional[float] = Field(default=0.30)  # Add this field: 0.30 = 30% of ROI height

class TextRequirement(BaseModel):
    """Text requirement for promotional materials"""
    required_text: str = Field(description="Text that must be present")
    match_type: Literal["exact", "contains", "regex"] = Field(default="contains", description="Type of text matching")
    case_sensitive: bool = Field(default=False, description="Case-sensitive matching")
    confidence_threshold: float = Field(default=0.7, description="OCR confidence threshold")
    mandatory: bool = Field(default=True, description="Whether this text is required")


class AdvertisementEndcap(BaseModel):
    """Configuration for advertisement endcap"""
    enabled: bool = Field(default=True, description="Whether endcap advertisement is present")
    promotional_type: Literal["backlit_graphic", "endcap_poster", "shelf_talker", "banner", "digital_display", "integrated_display", "promotional_base"] = Field(
        default="backlit_graphic", description="Type of promotional display"
    )
    position: Literal["header", "top", "middle", "bottom", "side"] = Field(default="header", description="Position of endcap")
    product_weight: float = Field(default=0.8, description="Weight of product compliance in overall score")
    text_weight: float = Field(default=0.2, description="Weight of text compliance in overall score")
    top_margin_percent: float = Field(default=0.02, description="Top margin percent of image for panel detection")
    width_margin_percent: float = Field(default=0.45, description="Width percent of image for panel detection")
    height_margin_percent: float = Field(default=0.33, description="Height percent of image for panel detection")
    side_margin_percent: float = Field(default=0.05, description="Side margin percent for panel detection")
    brand_requirements: List[str] = Field(default_factory=list, description="Required brand elements")
    text_requirements: List[TextRequirement] = Field(default_factory=list, description="Required text elements")
    reference_image_path: Optional[str] = Field(default=None, description="Path to reference image for comparison")
    allow_additional_text: bool = Field(default=True, description="Allow additional text beyond requirements")

class AisleConfig(BaseModel):
    """Configuration for aisle-specific settings"""
    name: str = Field(description="Aisle name (electronics, furniture, etc.)")
    category_hints: List[str] = Field(default_factory=list, description="Product category hints for this aisle")
    lighting_conditions: Literal["bright", "normal", "dim", "retail_standard"] = Field(default="normal", description="Expected lighting")
    shelf_spacing: Optional[float] = Field(default=None, description="Expected spacing between shelves")


class PlanogramDescription(BaseModel):
    """
    Comprehensive, configurable planogram description
    """
    # Basic identification
    brand: str = Field(description="Primary brand for this planogram")
    category: str = Field(description="Product category")
    aisle: AisleConfig = Field(description="Aisle configuration")
    tags: List[str] = Field(default_factory=list, description="Tags for special features or promotions")
    advertisement: Dict[str, Any] = Field(default_factory=dict, description="Advertisement sizing and positioning")
    text_tokens: List[str] = Field(default_factory=list, description="Additional text tokens for detection")
    # Detection configuration
    brand_detection: BrandDetectionConfig = Field(default_factory=BrandDetectionConfig, description="Brand detection settings")
    category_detection: CategoryDetectionConfig = Field(default_factory=CategoryDetectionConfig, description="Category detection settings")

    # Shelf layout
    shelves: List[ShelfConfig] = Field(description="Configuration for each shelf level")

    # Advertisement configuration
    advertisement_endcap: Optional[AdvertisementEndcap] = Field(default=None, description="Advertisement endcap configuration")

    # Global compliance settings
    global_compliance_threshold: float = Field(default=0.8, description="Default compliance threshold")
    weighted_scoring: Dict[str, float] = Field(
        default_factory=lambda: {"product_compliance": 0.7, "text_compliance": 0.3},
        description="Weights for different compliance aspects"
    )

    # Additional metadata
    planogram_id: Optional[str] = Field(default=None, description="Unique identifier for this planogram")
    created_date: Optional[str] = Field(default=None, description="Creation date")
    version: str = Field(default="1.0", description="Planogram version")
    notes: Optional[str] = Field(default=None, description="Additional notes or instructions")


class PlanogramDescriptionFactory:
    """Factory class for creating PlanogramDescription objects from dictionaries"""

    @staticmethod
    def create_planogram_description(config_dict: Dict[str, Any]) -> PlanogramDescription:
        """
        Create a PlanogramDescription object from a dictionary configuration.

        Args:
            config_dict: Dictionary containing all planogram configuration

        Returns:
            PlanogramDescription object ready for compliance checking

        Example config_dict structure:
        {
            "brand": "Epson",
            "category": "Printers",
            "aisle": {
                "name": "Electronics",
                "category_hints": ["printers", "ink", "paper"],
                "lighting_conditions": "normal"
            },
            "tags": ["goodbye", "hello", "savings", "cartridges"],
            # Advertisement sizing and positioning
            "advertisement": {
                "width_percent": 0.45,      # 45% of image width
                "height_percent": 0.25,     # 25% of image height
                "top_margin_percent": 0.02, # 2% margin above detected brand
                "side_margin_percent": 0.05 # 5% margin on sides
            },
            "brand_detection": {
                "enabled": True,
                "target_brands": ["Epson", "Canon", "HP"],
                "confidence_threshold": 0.8
            },
            "category_detection": {
                "enabled": True,
                "target_categories": ["printer", "product_box", "promotional_graphic"],
                "confidence_threshold": 0.7
            },
            "shelves": [
                {
                    "level": "header",
                    "products": [
                        {
                            "name": "Epson EcoTank Advertisement",
                            "product_type": "promotional_graphic",
                            "mandatory": True
                        }
                    ],
                    "compliance_threshold": 0.9
                },
                {
                    "level": "top",
                    "products": [
                        {
                            "name": "ET-2980",
                            "product_type": "printer",
                            "quantity_range": [1, 2],
                            "position_preference": "left"
                        },
                        {
                            "name": "ET-3950",
                            "product_type": "printer",
                            "quantity_range": [1, 1],
                            "position_preference": "center"
                        }
                    ],
                    "compliance_threshold": 0.8
                }
            ],
            "advertisement_endcap": {
                "enabled": True,
                "promotional_type": "backlit_graphic",
                "position": "header",
                "brand_requirements": ["Epson"],
                "text_requirements": [
                    {
                        "required_text": "Goodbye Cartridges",
                        "match_type": "contains",
                        "mandatory": True
                    },
                    {
                        "required_text": "Hello Savings",
                        "match_type": "contains",
                        "mandatory": True
                    }
                ]
            }
        }
        """

        # Process aisle configuration
        aisle_data = config_dict.get("aisle", {})
        if isinstance(aisle_data, str):
            # Simple string aisle name
            aisle_config = AisleConfig(name=aisle_data)
        else:
            # Full aisle configuration
            aisle_config = AisleConfig(**aisle_data)

        # Process brand detection configuration
        brand_detection_data = config_dict.get("brand_detection", {})
        brand_detection_config = BrandDetectionConfig(**brand_detection_data)

        # Process category detection configuration
        category_detection_data = config_dict.get("category_detection", {})
        category_detection_config = CategoryDetectionConfig(**category_detection_data)

        # Process shelves configuration
        shelves_data = config_dict.get("shelves", [])
        shelf_configs = []

        for shelf_data in shelves_data:
            # Process products for this shelf
            products_data = shelf_data.get("products", [])
            shelf_products = []

            for product_data in products_data:
                shelf_product = ShelfProduct(**product_data)
                shelf_products.append(shelf_product)

            # Create shelf config
            shelf_config = ShelfConfig(
                level=shelf_data["level"],
                products=shelf_products,
                compliance_threshold=shelf_data.get("compliance_threshold", 0.8),
                allow_extra_products=shelf_data.get("allow_extra_products", False),
                position_strict=shelf_data.get("position_strict", False)
            )
            shelf_configs.append(shelf_config)

        # Process advertisement endcap configuration
        advertisement_endcap = None
        endcap_data = config_dict.get("advertisement_endcap")
        if endcap_data:
            # Process text requirements
            text_requirements = []
            for text_req_data in endcap_data.get("text_requirements", []):
                text_req = TextRequirement(**text_req_data)
                text_requirements.append(text_req)

            # Update endcap data with processed text requirements
            endcap_data = endcap_data.copy()
            endcap_data["text_requirements"] = text_requirements

            advertisement_endcap = AdvertisementEndcap(**endcap_data)

        # Create the main PlanogramDescription object
        planogram_description = PlanogramDescription(
            brand=config_dict["brand"],
            category=config_dict["category"],
            aisle=aisle_config,
            text_tokens=config_dict.get("text_tokens", []),
            advertisement=config_dict.get("advertisement", {}),
            tags=config_dict.get("tags", []),
            brand_detection=brand_detection_config,
            category_detection=category_detection_config,
            shelves=shelf_configs,
            advertisement_endcap=advertisement_endcap,
            global_compliance_threshold=config_dict.get("global_compliance_threshold", 0.8),
            weighted_scoring=config_dict.get("weighted_scoring", {"product_compliance": 0.7, "text_compliance": 0.3}),
            planogram_id=config_dict.get("planogram_id"),
            created_date=config_dict.get("created_date"),
            version=config_dict.get("version", "1.0"),
            notes=config_dict.get("notes")
        )

        return planogram_description

class PlanogramConfigBuilder:
    """Builder class for easier construction of planogram configurations"""

    def __init__(self):
        self.config = {
            "brand": "",
            "category": "",
            "aisle": {},
            "shelves": [],
            "global_compliance_threshold": 0.8
        }

    def set_basic_info(self, brand: str, category: str, aisle: str) -> "PlanogramConfigBuilder":
        """Set basic planogram information"""
        self.config["brand"] = brand
        self.config["category"] = category
        self.config["aisle"] = {"name": aisle}
        return self

    def add_shelf(
        self,
        level: str,
        products: List[Dict[str, Any]],
        compliance_threshold: float = 0.8
    ) -> "PlanogramConfigBuilder":
        """Add a shelf configuration"""
        shelf_config = {
            "level": level,
            "products": products,
            "compliance_threshold": compliance_threshold
        }
        self.config["shelves"].append(shelf_config)
        return self

    def add_product_to_shelf(
        self,
        shelf_level: str,
        name: str,
        product_type: str,
        quantity_range: tuple = (1, 1),
        mandatory: bool = True
    ) -> "PlanogramConfigBuilder":
        """Add a product to an existing shelf"""
        # Find the shelf
        for shelf in self.config["shelves"]:
            if shelf["level"] == shelf_level:
                product = {
                    "name": name,
                    "product_type": product_type,
                    "quantity_range": quantity_range,
                    "mandatory": mandatory
                }
                shelf["products"].append(product)
                break
        return self

    def set_advertisement_endcap(
        self,
        promotional_type: str,
        position: str = "header",
        brand_requirements: List[str] = None,
        text_requirements: List[Dict[str, Any]] = None
    ) -> "PlanogramConfigBuilder":
        """Configure advertisement endcap"""
        endcap_config = {
            "enabled": True,
            "promotional_type": promotional_type,
            "position": position,
            "brand_requirements": brand_requirements or [],
            "text_requirements": text_requirements or []
        }
        self.config["advertisement_endcap"] = endcap_config
        return self

    def set_brand_detection(
        self,
        target_brands: List[str],
        confidence_threshold: float = 0.7
    ) -> "PlanogramConfigBuilder":
        """Configure brand detection"""
        self.config["brand_detection"] = {
            "enabled": True,
            "target_brands": target_brands,
            "confidence_threshold": confidence_threshold
        }
        return self

    def build(self) -> Dict[str, Any]:
        """Build the final configuration dictionary"""
        return self.config


def _dump(obj) -> Dict[str, Any]:
    """Works with Pydantic v1/v2 or plain dicts."""
    if obj is None:
        return {}
    if hasattr(obj, "model_dump"):
        return obj.model_dump(exclude_none=True)
    if hasattr(obj, "dict"):
        return obj.dict(exclude_none=True)
    if isinstance(obj, dict):
        return obj
    # Fallback: shallow attr dump
    return {
        k: getattr(obj, k) for k in dir(obj) if not k.startswith("_") and not callable(getattr(obj, k))
    }

def _product_label(p) -> str:
    # ShelfProduct may be a pydantic model or dict
    if p is None:
        return "UNKNOWN"
    if isinstance(p, dict):
        name = p.get("name") or p.get("product_type") or "UNKNOWN"
        return str(name)
    name = getattr(p, "name", None) or getattr(p, "product_type", None) or "UNKNOWN"
    return str(name)

def build_planogram_json_diagram(planogram) -> Dict[str, Any]:
    """
    Produce a compact, human-friendly JSON 'diagram' of a PlanogramDescription.
    Keys/shape kept simple for rendering and reporting.
    """
    shelves: List[Dict[str, Any]] = []
    for s in getattr(planogram, "shelves", []):
        # Accept model or dict
        s_d = _dump(s)
        level = s_d.get("level") or s_d.get("name") or s_d.get("label") or "unknown"
        products = s_d.get("products", [])
        expected = [_product_label(p) for p in products]
        shelves.append({
            "shelf": str(level),
            "slots": len(products),
            "expected_left_to_right": expected,
            "compliance_threshold": s_d.get(
                "compliance_threshold", getattr(planogram, "global_compliance_threshold", 0.8)
            ),
            "allow_extra_products": s_d.get("allow_extra_products", False),
            "position_strict": s_d.get("position_strict", False),
            "notes": s_d.get("notes"),
        })

    ad = _dump(getattr(planogram, "advertisement_endcap", None)) or None
    aisle = _dump(getattr(planogram, "aisle", None))

    diagram: Dict[str, Any] = {
        "brand": getattr(planogram, "brand", ""),
        "category": getattr(planogram, "category", ""),
        "aisle": aisle,
        "advertisement_endcap": ad,  # will be None if not configured
        "shelves": shelves,
        "global_compliance_threshold": getattr(planogram, "global_compliance_threshold", 0.8),
        "weighted_scoring": dict(getattr(planogram, "weighted_scoring", {"product_compliance": 0.7, "text_compliance": 0.3})),
        "metadata": {
            "planogram_id": getattr(planogram, "planogram_id", None),
            "created_date": getattr(planogram, "created_date", None),
            "version": getattr(planogram, "version", "1.0"),
            "notes": getattr(planogram, "notes", None),
        },
    }
    return diagram

def planogram_diagram_to_markdown(diagram: Mapping[str, Any]) -> str:
    """Render the JSON diagram as Markdown ready for reports."""
    brand = diagram.get("brand", "")
    category = diagram.get("category", "")
    gthr = diagram.get("global_compliance_threshold", "")
    weights = diagram.get("weighted_scoring", {})
    meta = diagram.get("metadata", {})
    aisle = diagram.get("aisle", {})
    ad = diagram.get("advertisement_endcap", None)
    shelves = diagram.get("shelves", [])

    def _fmt_dict(d: Mapping[str, Any]) -> str:
        if not d:
            return "-"
        # compact key: value list
        parts = []
        for k, v in d.items():
            if isinstance(v, (list, dict)):
                parts.append(f"**{k}**: `{str(v)}`")
            else:
                parts.append(f"**{k}**: {v}")
        return "<br>".join(parts)

    # Header table
    md = []
    md.append("| Field | Value |")
    md.append("|---|---|")
    md.append(f"| **Brand** | {brand} |")
    md.append(f"| **Category** | {category} |")
    md.append(f"| **Global Threshold** | {gthr} |")
    md.append(f"| **Weighted Scoring** | product: {weights.get('product_compliance', '-')}, text: {weights.get('text_compliance', '-')} |")
    md.append(f"| **Planogram ID** | {meta.get('planogram_id','-')} |")
    md.append(f"| **Version** | {meta.get('version','-')} |")
    md.append(f"| **Created** | {meta.get('created_date','-')} |")
    md.append(f"| **Notes** | {meta.get('notes','-')} |")
    md.append("")
    # Aisle block
    md.append("**Aisle**")
    md.append("")
    md.append(_fmt_dict(aisle))
    md.append("")
    # Advertisement block
    md.append("**Advertisement Endcap**")
    md.append("")
    if ad:
        md.append(_fmt_dict(ad))
    else:
        md.append("_None_")
    md.append("")
    # Shelves table
    if shelves:
        md.append("**Shelves**")
        md.append("")
        md.append("| Shelf | Slots | Expected (L→R) | Threshold | Allow Extra | Position Strict | Notes |")
        md.append("|---:|---:|---|---:|:---:|:---:|---|")
        for s in shelves:
            exp = ", ".join(str(x) for x in s.get("expected_left_to_right", []))
            md.append(
                f"| {s.get('shelf','-')} | {s.get('slots','-')} | `{exp}` | "
                f"{s.get('compliance_threshold','-')} | {s.get('allow_extra_products', False)} | "
                f"{s.get('position_strict', False)} | {s.get('notes','-')} |"
            )
        md.append("")
    return "\n".join(md)
