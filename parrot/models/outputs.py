from datetime import datetime
from typing import (
    List,
    Optional,
    Any,
    Union,
    Callable,
    Literal,
    get_type_hints,
    get_origin,
    get_args
)
from enum import Enum
from dataclasses import dataclass, fields, is_dataclass, MISSING
import json
from pydantic import BaseModel, Field
from .basic import OutputFormat


class OutputType(str, Enum):
    """Types of outputs that can be rendered"""
    TEXT = "text"
    MARKDOWN = "markdown"
    DATAFRAME = "dataframe"
    FOLIUM_MAP = "folium_map"
    PLOTLY_CHART = "plotly_chart"
    MATPLOTLIB_FIGURE = "matplotlib_figure"
    BOKEH_PLOT = "bokeh_plot"
    ALTAIR_CHART = "altair_chart"
    PANEL_DASHBOARD = "panel_dashboard"
    HTML_WIDGET = "html_widget"
    IMAGE = "image"
    JSON_DATA = "json_data"
    MIXED = "mixed"  # Multiple output types


class OutputMode(str, Enum):
    """Output mode enumeration"""
    DEFAULT = "default"          # Keep as-is (BaseModel/dataclass)
    JSON = "json"               # Serialize to JSON (using orjson)
    TERMINAL = "terminal"       # Render for terminal display (using Rich)
    MARKDOWN = "markdown"       # Convert to markdown
    YAML = "yaml"               # Serialize to YAML (using yaml-rs)
    HTML = "html"               # Convert to HTML elements (using Panel)
    JINJA2 = "jinja2"           # Pass to Jinja2 template (using jinja2 templates)
    JUPYTER = "jupyter"         # Render for Jupyter notebook
    NOTEBOOK = "notebook"       # Render for Jupyter notebook
    TEMPLATE_REPORT = "template_report"  # Pass to Jinja2 template (using jinja2 templates)
    APPLICATION = "application"  # Wrap in app (Streamlit/React/Svelte/HTML+TS)
    CHART = "chart"               # Generate chart visualization
    ALTAIR = "altair"           # Generate Altair chart visualization
    PLOTLY = "plotly"
    MATPLOTLIB = "matplotlib"
    BOKEH = "bokeh"
    SEABORN = "seaborn"
    CODE = "code"
    MAP = "map"                   # Generate map visualization
    IMAGE = "image"             # render the image as a base64 embed into HTML <img>
    D3 = "d3"                   # Generate D3.js visualization
    ECHARTS = "echarts"         # Generate ECharts visualization
    TABLE = "table"             # Generate table visualization

@dataclass
class StructuredOutputConfig:
    """Configuration for structured output parsing."""
    output_type: type
    format: OutputFormat = OutputFormat.JSON
    custom_parser: Optional[Callable[[str], Any]] = None

    def get_schema(self) -> dict[str, Any]:
        """
        Extract JSON schema from output_type.
        Supports both Pydantic models and dataclasses.
        """
        # Check if it's a Pydantic model
        if hasattr(self.output_type, 'model_json_schema'):
            # Pydantic v2
            return self.output_type.model_json_schema()
        elif hasattr(self.output_type, 'schema'):
            # Pydantic v1
            return self.output_type.schema()

        # Check if it's a dataclass
        elif is_dataclass(self.output_type):
            return self._dataclass_to_schema(self.output_type)

        else:
            raise ValueError(
                f"output_type must be a Pydantic model or dataclass, "
                f"got {type(self.output_type)}"
            )

    def _dataclass_to_schema(self, dc: type) -> dict[str, Any]:
        """Convert a dataclass to JSON schema."""
        type_hints = get_type_hints(dc)
        properties = {}
        required = []

        for field in fields(dc):
            field_type = type_hints.get(field.name, Any)
            field_schema = self._python_type_to_json_schema(field_type)

            # Add description from field metadata if available
            if field.metadata:
                field_schema["description"] = field.metadata.get("description", "")

            properties[field.name] = field_schema

            # Check if field is required (no default value)
            if field.default == field.default_factory == MISSING:
                required.append(field.name)

        schema = {
            "type": "object",
            "properties": properties,
            "required": required,
            "title": dc.__name__
        }

        # Add docstring as description if available
        if dc.__doc__:
            schema["description"] = dc.__doc__.strip()

        return schema

    def _python_type_to_json_schema(self, py_type: Any) -> dict[str, Any]:
        """Convert Python type hints to JSON schema types."""
        origin = get_origin(py_type)

        # Handle Optional types
        if origin is Union:
            args = get_args(py_type)
            if type(None) in args:
                # It's Optional[T]
                non_none_types = [t for t in args if t is not type(None)]
                if len(non_none_types) == 1:
                    return self._python_type_to_json_schema(non_none_types[0])

        # Handle List types
        if origin is list:
            item_type = get_args(py_type)[0] if get_args(py_type) else Any
            return {
                "type": "array",
                "items": self._python_type_to_json_schema(item_type)
            }

        # Handle Dict types
        if origin is dict:
            return {"type": "object"}

        # Basic type mappings
        type_map = {
            str: {"type": "string"},
            int: {"type": "integer"},
            float: {"type": "number"},
            bool: {"type": "boolean"},
            list: {"type": "array"},
            dict: {"type": "object"},
        }

        return type_map.get(py_type, {"type": "string"})

    def format_schema_instruction(self) -> str:
        """
        Format the schema as an instruction for the system prompt.
        """
        schema = self.get_schema()
        return f"""Respond with a valid JSON object that strictly matches the requested schema.

Schema:
```json
{json.dumps(schema, indent=2)}
```

Rules:
- Output ONLY valid JSON matching this schema
- Do not include any explanatory text before or after the JSON
- All required fields must be present
- Field types must match exactly"""


class BoundingBox(BaseModel):
    """Represents a detected object with its location and details."""
    object_id: str = Field(..., description="Unique identifier for this detection")
    brand: str = Field(..., description="Product brand (Epson, HP, Canon, etc.)")
    model: Optional[str] = Field(None, description="Product model if identifiable")
    product_type: str = Field(
        ..., description="Type of product (printer, scanner, ink cartridge, etc.)"
    )
    description: str = Field(..., description="Brief description of the product")
    confidence: float = Field(..., description="Confidence level (0.0 to 1.0)")
    # Simple bounding box as [x1, y1, x2, y2] normalized coordinates (0.0 to 1.0)
    bbox: List[float] = Field(
        ..., description="Bounding box coordinates [x1, y1, x2, y2] as normalized values (0.0-1.0)"
    )


class ObjectDetectionResult(BaseModel):
    """A list of all prominent items detected in the image."""
    analysis: str = Field(
        ...,
        description="A detailed text analysis of the image that answers the user's prompt."
    )
    total_count: int = Field(..., description="Total number of products detected")
    detections: List[BoundingBox] = Field(
        default_factory=list,
        description="A list of bounding boxes for all prominent detected objects."
    )

class ImageGenerationPrompt(BaseModel):
    """Input schema for generating an image."""
    prompt: str = Field(..., description="The main text prompt describing the desired image.")
    styles: Optional[List[str]] = Field(default_factory=list, description="Optional list of styles to apply (e.g., 'photorealistic', 'cinematic', 'anime').")
    model: str = Field(description="The image generation model to use.")
    negative_prompt: Optional[str] = Field(None, description="A description of what to avoid in the image.")
    aspect_ratio: str = Field(default="1:1", description="The desired aspect ratio (e.g., '1:1', '16:9', '9:16').")


class SpeakerConfig(BaseModel):
    """Configuration for a single speaker in speech generation."""
    name: str = Field(..., description="The name of the speaker in the script (e.g., 'Joe', 'Narrator').")
    voice: str = Field(..., description="The pre-built voice name to use (e.g., 'Kore', 'Puck', 'Chitose').")
    # Gender is often inferred from the voice, but can be included for clarity
    gender: Optional[str] = Field(None, description="The gender associated with the voice (e.g., 'Male', 'Female').")


class SpeechGenerationPrompt(BaseModel):
    """Input schema for generating speech from text."""
    prompt: str = Field(
        ...,
        description="The text to be converted to speech. For multiple speakers, use their names (e.g., 'Joe: Hello. Jane: Hi there.')."
    )
    speakers: List[SpeakerConfig] = Field(
        ...,
        description="A list of speaker configurations. Use one for a single voice, multiple for a conversation."
    )
    model: Optional[str] = Field(default=None, description="The text-to-speech model to use.")
    language: Optional[str] = Field("en-US", description="Language code for the conversation.")


class VideoGenerationPrompt(BaseModel):
    """Input schema for generating video content."""
    prompt: str = Field(..., description="The text prompt describing the desired video content.")
    number_of_videos: int = Field(
        default=1, description="The number of videos to generated per request."
    )
    model: str = Field(..., description="The video generation model to use.")
    aspect_ratio: str = Field(
        default="16:9", description="The desired aspect ratio (e.g., '16:9', '9:16')."
    )
    duration: Optional[int] = Field(None, description="Optional duration in seconds for the video.")
    negative_prompt: Optional[str] = Field(
        default='',
        description="A description of what to avoid in the video."
    )

class SentimentAnalysis(BaseModel):
    """Structured sentiment analysis response."""
    sentiment: Literal["positive", "negative", "neutral", "mixed"] = Field(
        description="Overall sentiment classification"
    )
    confidence_level: float = Field(
        ge=0.0, le=1.0,
        description="Confidence level as decimal between 0 and 1"
    )
    emotional_indicators: List[str] = Field(
        description="List of words/phrases that indicate emotional content"
    )
    reason: str = Field(
        description="Explanation of the sentiment analysis"
    )


class ProductReview(BaseModel):
    """Structured product review response."""
    product_id: str = Field(..., description="Unique identifier for the product being reviewed")
    product_name: str = Field(..., description="Name of the product being reviewed")
    review_text: str = Field(..., description="The text of the product review")
    rating: float = Field(..., description="Rating given to the product")
    sentiment: Literal["positive", "negative", "neutral"] = Field(
        ..., description="Sentiment of the review"
    )
    key_features: list[str] = Field(..., description="Key features highlighted in the review")
