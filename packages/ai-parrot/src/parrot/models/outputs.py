from typing import (
    List,
    Optional,
    Any,
    Tuple,
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
from pydantic import BaseModel, Field, ConfigDict, model_validator, field_validator
from .basic import OutputFormat


class OutputType(str, Enum):
    """Types of outputs that can be rendered"""
    TEXT = "text"
    MARKDOWN = "markdown"
    DATAFRAME = "dataframe"
    FOLIUM_MAP = "folium_map"
    PANEL_DASHBOARD = "panel_dashboard"
    HTML_WIDGET = "html_widget"
    IMAGE = "image"
    JSON_DATA = "json_data"
    MIXED = "mixed"  # Multiple output types


class OutputMode(str, Enum):
    """Output mode enumeration"""
    DEFAULT = "default"          # Keep as-is (BaseModel/dataclass)
    TEXT = "text"               # Plain conversational text — markdown-free (A2A/Copilot)
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
    CODE = "code"
    MAP = "map"                   # Generate map visualization
    IMAGE = "image"             # render the image as a base64 embed into HTML <img>
    ECHARTS = "echarts"         # Generate ECharts visualization
    TABLE = "table"             # Generate table visualization
    CARD = "card"
    TELEGRAM = "telegram"
    MSTEAMS = "msteams"
    WHATSAPP = "whatsapp"
    SLACK = "slack"
    INFOGRAPHIC = "infographic"
    INTERACTIVE = "interactive"  # Tool-driven interactive HTML artifact (canvas); finalized to OutputMode.HTML
    SQL_ANALYSIS = "sql_analysis"  # DBA helper: QueryResponse with explanation + SQL artifact
    STRUCTURED_CHART = "structured_chart"  # Library-agnostic chart config (AppChartConfig mirror)
    STRUCTURED_TABLE = "structured_table"  # Framework-agnostic table config (FEAT-218)
    STRUCTURED_MAP = "structured_map"      # Framework-agnostic map config (FEAT-221)
    A2UI = "a2ui"                          # A2UI v1.0 declarative envelope (FEAT-273)

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
    """Input schema for generating an image.

    Carries the full homologated attribute surface shared by both the Gemini
    (``generate_image``) and Imagen (``generate_images``) backends. Individual
    method kwargs always take precedence over the fields set here.
    """
    prompt: str = Field(..., description="The main text prompt describing the desired image.")
    styles: Optional[List[str]] = Field(default_factory=list, description="Optional list of styles to apply (e.g., 'photorealistic', 'cinematic', 'anime').")
    model: str = Field(description="The image generation model to use.")
    negative_prompt: Optional[str] = Field(None, description="A description of what to avoid in the image (Imagen only).")
    aspect_ratio: str = Field(default="1:1", description="The desired aspect ratio (e.g., '1:1', '16:9', '9:16').")
    resolution: Optional[str] = Field(default="1K", description="The desired resolution / image size (e.g., '1K', '2K', '4K').")
    auto_upscale: Optional[bool] = Field(default=False, description="Whether to automatically upscale the generated image.")
    number_of_images: int = Field(default=1, ge=1, le=8, description="How many images to generate per request.")
    person_generation: str = Field(default="allow_adult", description="Person generation policy: 'allow_all', 'allow_adult', or 'dont_allow' (Imagen only).")
    safety_filter_level: str = Field(default="BLOCK_ONLY_HIGH", description="Safety filter threshold (e.g., 'BLOCK_ONLY_HIGH', 'BLOCK_MEDIUM_AND_ABOVE', 'BLOCK_LOW_AND_ABOVE').")
    seed: Optional[int] = Field(default=None, description="Optional seed for reproducible generation.")
    add_watermark: bool = Field(default=False, description="Whether to add a SynthID watermark (Imagen only).")
    output_mime_type: str = Field(default="image/png", description="Output image MIME type (e.g., 'image/png', 'image/jpeg').")
    service_tier: Optional[str] = Field(default=None, description="Optional service tier (e.g., 'flex'); applies to the Gemini backend.")


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
    resolution: Optional[str] = Field(default="1080p", description="The desired resolution (e.g., '1080p', '2K').")
    smoothing: Optional[bool] = Field(default=False, description="Whether to apply frame rate smoothing to the generated video.")
    seed: Optional[int] = Field(default=None, description="Optional seed for reproducible generation.")
    include_audio: bool = Field(default=True, description="Whether to include generated audio.")

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


# ── FEAT-215: Structured Chart Output ────────────────────────────────────────

ChartType = Literal[
    "bar", "horizontalBar", "line", "area", "scatter",
    "pie", "donut", "radar", "map"
]
"""Supported chart types for StructuredChartConfig."""

XAxisMode = Literal["category", "time"]
"""X-axis mode: 'category' for categorical labels, 'time' for ISO 8601 date strings."""


class StructuredChartConfig(BaseModel):
    """Library-agnostic chart configuration mirroring the frontend AppChartConfig.

    Accepts data rows on input (for column validation), but the renderer excludes
    the ``data`` field from the serialized output — rows are routed to
    ``response.data`` instead (see StructuredChartRenderer).

    Attributes:
        type: Chart type (e.g. "bar", "line", "map").
        x: Categorical/label column name.
        y: One or more value column names (multi-series).
        stacked: Whether to stack series (bar/area/line).
        trendline: Whether to render a trend line.
        split_series: Render each y series as a separate chart.
        show_legend: Whether to display the chart legend.
        x_axis_mode: Axis scale — "category" or "time" (ISO 8601 strings required).
        palette: Optional list of hex colour strings.
        color_by_sign: Colour bars/points by positive/negative value.
        negative_color: Hex colour for negative values when colorBySign is True.
        map_name: GeoJSON map identifier (required when type="map").
        data: Flat row list — INPUT-ONLY; excluded from output by the renderer.
    """

    model_config = ConfigDict(populate_by_name=True)

    type: ChartType = Field(..., description="Chart type")
    x: str = Field(..., description="Categorical/label column name")
    y: List[str] = Field(..., description="One or more value column names (multi-series)")
    stacked: Optional[bool] = Field(default=None, description="Stack series")
    trendline: Optional[bool] = Field(default=None, description="Show trend line")
    split_series: Optional[bool] = Field(
        default=None, alias="splitSeries",
        description="Render each y series as a separate chart",
    )
    show_legend: Optional[bool] = Field(
        default=None, alias="showLegend",
        description="Display chart legend",
    )
    x_axis_mode: Optional[XAxisMode] = Field(
        default=None, alias="xAxisMode",
        description="Axis scale: 'category' or 'time'",
    )
    palette: Optional[List[str]] = Field(
        default=None, description="Optional list of hex colour strings",
    )
    color_by_sign: Optional[bool] = Field(
        default=None, alias="colorBySign",
        description="Colour bars/points by positive/negative value",
    )
    negative_color: Optional[str] = Field(
        default=None, alias="negativeColor",
        description="Hex colour for negative values when colorBySign is True",
    )
    positive_color: Optional[str] = Field(
        default=None, alias="positiveColor",
        description="Hex colour for positive values when colorBySign is True",
    )
    x_axis_label: Optional[str] = Field(
        default=None, alias="xAxisLabel",
        description="Human-readable x-axis display label (overrides column name)",
    )
    y_axis_label: Optional[str] = Field(
        default=None, alias="yAxisLabel",
        description="Human-readable y-axis display label",
    )
    map_name: Optional[str] = Field(
        default=None, alias="mapName",
        description="GeoJSON map name (frontend-validated, free-form; required for type='map')",
    )
    title: Optional[str] = Field(
        default=None,
        description="Short chart title (≤1 line) shown as the card header.",
    )
    description: Optional[str] = Field(
        default=None,
        description=(
            "One short paragraph (natural language) summarizing the chart's key "
            "takeaway; shown as the message text alongside the chart."
        ),
    )
    data: List[dict] = Field(
        default_factory=list,
        description=(
            "Optional: the rows to chart, as a list of flat dicts whose keys "
            "include the x and y column names. When omitted, the renderer uses "
            "the DataFrame the agent computed (injected into response.data) as "
            "the data source instead — see StructuredChartRenderer."
        ),
    )
    data_variable: Optional[str] = Field(
        default=None,
        alias="dataVariable",
        description=(
            "The name of the pandas DataFrame variable you created in a tool "
            "(e.g. 'expense_breakdown') that holds the rows to chart. ALWAYS set "
            "this to the variable that contains the chart data. It is REQUIRED "
            "when the turn produced more than one DataFrame, so the system knows "
            "which one to use; x and y must be columns of that DataFrame."
        ),
    )

    @field_validator("data", mode="before")
    @classmethod
    def _normalize_data_orientation(cls, v):
        """Accept any pandas-style orientation for ``data`` and coerce to records.

        The LLM serializes the DataFrame inconsistently — sometimes as a list of
        row dicts (``records``), sometimes as ``split`` orientation
        ``{"columns": [...], "data": [[...], ...]}``, sometimes as the default
        ``{col: {idx: val}}``. Only ``records`` matches ``List[dict]``; the others
        used to fail validation and trigger a slow (~13s) reformat call. Normalize
        them here so the chart pipeline is resilient to the serialization shape.

        Args:
            v: The raw ``data`` value from the LLM (list or dict orientation).

        Returns:
            A list of row dicts, or the value unchanged when already a list / not
            a recognized orientation (lets normal validation handle it).
        """
        if not isinstance(v, dict):
            return v
        # 'split'/'tight' orientation: {"columns": [...], "data"|"rows"|"values": [[...]]}.
        # The values key varies by serializer/LLM ('data' is pandas-canonical, but
        # models also emit 'rows' or 'values'); accept any of them.
        cols = v.get("columns")
        rows = v.get("data")
        if rows is None:
            rows = v.get("rows")
        if rows is None:
            rows = v.get("values")
        if isinstance(cols, list) and isinstance(rows, list):
            return [
                dict(zip(cols, r)) if isinstance(r, (list, tuple)) else r
                for r in rows
            ]
        # pandas default 'dict' orientation: {col: {row_idx: value}}
        if v and all(isinstance(col_vals, dict) for col_vals in v.values()):
            indices = list(next(iter(v.values())).keys())
            return [
                {col: col_vals.get(idx) for col, col_vals in v.items()}
                for idx in indices
            ]
        # A single row dict → wrap as one-row list
        return [v]

    @model_validator(mode="after")
    def _validate_chart_constraints(self) -> "StructuredChartConfig":
        """Validate the map-name requirement only.

        We deliberately do NOT reject configs whose ``x``/``y`` don't match the
        embedded data columns. The LLM frequently names semantic axes
        (``x="expense_category"``) that differ from the keys it actually embeds,
        and it delivers data through several paths (embedded rows, a python
        variable, or a materialized dataset). Raising here forced a slow
        reformat call and — worse — pre-empted ``StructuredChartRenderer``, which
        is responsible for reconciling x/y against whatever rows are available.
        So the only hard constraint left is the map-name requirement; column
        alignment is handled downstream by the renderer.

        Returns:
            The validated StructuredChartConfig instance.

        Raises:
            ValueError: When type='map' and mapName is absent.
        """
        if self.type == "map" and not self.map_name:
            raise ValueError("type='map' requires 'mapName'")
        return self


# ── FEAT-218: Structured Table Output Mode ─────────────────────────────────────


class TableColumn(BaseModel):
    """Per-column contract for a structured table output.

    Carries the minimum information a frontend grid library needs to
    render a column correctly: the key name, its storage type, a human
    label, and an optional display-format hint.

    Attributes:
        name: Column key — must match a key in every data row dict.
        type: Storage type vocabulary: ``string`` | ``integer`` | ``number`` |
            ``boolean`` | ``date`` | ``datetime`` | ``time`` | ``duration`` | ``any``.
        title: Human-readable column label (defaults to ``name`` as-is; the
            renderer may refine it via a narrow LLM pass).
        format: Optional display hint for ambiguous columns:
            ``currency`` | ``percent`` | ``email`` | ``uri`` | ``enum`` |
            ``id`` | ``code``.
            This is a *hint* for the frontend — it does NOT change the base
            storage type.
    """

    name: str = Field(..., description="Column key (matches a key in data rows)")
    type: str = Field(
        ...,
        description=(
            "Storage type: string | integer | number | boolean"
            " | date | datetime | time | duration | any"
        ),
    )
    title: str = Field(..., description="Human-readable column label")
    format: Optional[str] = Field(
        default=None,
        description=(
            "Optional display hint: currency | percent | email | uri | enum | id | code"
        ),
    )


class StructuredTableConfig(BaseModel):
    """Framework-agnostic table configuration for FEAT-218.

    Accepts data rows on input (for column-name validation), but the renderer
    excludes the ``data`` field from the serialized output — rows are routed
    to ``response.data`` instead (mirroring ``StructuredChartConfig``).

    Attributes:
        columns: Per-column contract list (name / type / title / optional format).
        data: Flat row list — INPUT-ONLY; excluded from ``output``,
            routed to ``response.data`` by the renderer.
        explanation: Optional prose description of how the table was derived
            (reused from the producing agent; absent → omitted).
        total_rows: Total number of rows before truncation (set when data
            originates from a larger dataset).
        truncated: ``True`` when the dataset was capped at ``row_limit``
            and rows were dropped.
    """

    model_config = ConfigDict(populate_by_name=True)

    columns: List[TableColumn] = Field(
        ..., description="Per-column contract (name / type / title / format)"
    )
    data: List[dict] = Field(
        default_factory=list,
        description=(
            "Flat data rows; INPUT-ONLY — excluded from ``output``, "
            "routed to response.data by the renderer."
        ),
    )
    explanation: Optional[str] = Field(
        default=None,
        description="Prose description of how the table was derived (best-effort).",
    )
    total_rows: Optional[int] = Field(
        default=None,
        description="Total row count before any truncation.",
    )
    truncated: bool = Field(
        default=False,
        description="True when the dataset was capped at row_limit.",
    )

    @model_validator(mode="after")
    def _validate_column_names(self) -> "StructuredTableConfig":
        """Validate that every declared column name exists in the data rows.

        When ``data`` is non-empty, every ``column.name`` must appear as a key
        in ``data[0]``.  This mirrors the ``StructuredChartConfig`` x/y column
        presence check.

        Returns:
            The validated ``StructuredTableConfig`` instance.

        Raises:
            ValueError: When a ``column.name`` is absent from ``data[0].keys()``
                and ``data`` is non-empty.
        """
        if self.data:
            cols = set(self.data[0].keys())
            missing = [c.name for c in self.columns if c.name not in cols]
            if missing:
                raise ValueError(
                    f"column names not present in data rows: {missing}"
                )
        return self


# ── FEAT-221: Structured Map Output Mode ──────────────────────────────────────


class MapColumn(BaseModel):
    """Per-column contract for a map layer (same vocabulary as TableColumn).

    Carries the minimum information a frontend map library needs to
    render a column correctly: the key name, its storage type, a human
    label, and an optional display-format hint.

    Attributes:
        name: Column key — must match a key in every data row dict /
            feature.properties.
        type: Storage type vocabulary: ``string`` | ``integer`` | ``number`` |
            ``boolean`` | ``date`` | ``datetime`` | ``time`` | ``duration`` | ``any``.
        title: Human-readable column label (defaults to ``name`` as-is; the
            renderer may refine it via a narrow LLM pass).
        format: Optional display hint for ambiguous columns:
            ``currency`` | ``percent`` | ``email`` | ``uri`` | ``enum`` |
            ``id`` | ``code``.
            This is a *hint* for the frontend — it does NOT change the base
            storage type.
    """

    name: str = Field(..., description="Column key (matches a key in data rows / feature.properties)")
    type: str = Field(
        ...,
        description=(
            "Storage type: string | integer | number | boolean"
            " | date | datetime | time | duration | any"
        ),
    )
    title: str = Field(..., description="Human-readable column label")
    format: Optional[str] = Field(
        default=None,
        description=(
            "Optional display hint: currency | percent | email | uri | enum | id | code"
        ),
    )


class MapLayer(BaseModel):
    """One layer per dataset — data schema + presentation schema (FEAT-221).

    Attributes:
        layer: Leaflet layer id / GeoJSON source discriminator.
        columns: Per-column contract for this layer (name / type / title / format).
        tooltip_template: Python ``str.format_map`` template applied client-side
            over ``feature.properties`` (compact, G8 — no per-element strings).
        label_field: Property key used for the marker label.
        data_shape: Per-layer data payload shape: ``"geojson"`` passes features
            through; ``"rows"`` flattens to canonical row dicts (G6).
        total_count: Per-dataset true count before capping (G10).
        capped: True when the per-dataset result was truncated at the hard cap.
        geodesic: Whether the executed path was geodesic (True) or
            spherical-approximate (False). Sourced from ``SpatialLayerResult``.
        marker_color: Optional marker/pin color for every feature in this layer,
            derived from the user's request (piggyback — no extra LLM call). A
            canonical CSS color name (e.g. ``"red"``, ``"blue"``) or a hex string
            (e.g. ``"#1f77b4"``). ``None`` = the frontend uses its default marker
            color.
    """

    model_config = ConfigDict(populate_by_name=True)

    layer: str = Field(..., description="Leaflet layer id / GeoJSON source discriminator.")
    columns: List[MapColumn] = Field(
        ..., description="Per-column contract (name / type / title / format)"
    )
    tooltip_template: Optional[str] = Field(
        default=None,
        alias="tooltipTemplate",
        description="str.format_map template for client-side tooltip rendering.",
    )
    label_field: Optional[str] = Field(
        default=None,
        alias="labelField",
        description="Property key used for the marker label.",
    )
    data_shape: Literal["geojson", "rows"] = Field(
        default="geojson",
        alias="dataShape",
        description="Per-layer data payload shape: geojson or rows.",
    )
    total_count: int = Field(
        default=0,
        alias="totalCount",
        description="Per-dataset true count before capping.",
    )
    capped: bool = Field(
        default=False,
        description="True when the per-dataset result was truncated at the hard cap.",
    )
    geodesic: Optional[bool] = Field(
        default=None,
        description="True = geodesic path; False = spherical-approx. From SpatialLayerResult.",
    )
    marker_color: Optional[str] = Field(
        default=None,
        alias="markerColor",
        description=(
            "Optional marker/pin color for this layer (CSS color name or hex). "
            "Derived from the user's request; None = frontend default."
        ),
    )


class MapViewport(BaseModel):
    """Map viewport hints — computed from feature bounds (FEAT-221).

    Attributes:
        bbox: [min_lng, min_lat, max_lng, max_lat] bounding box.
        center: (lat, lng) optional center — frontend may derive from bbox.
        zoom: Optional zoom-level hint.
    """

    bbox: Optional[List[float]] = Field(
        default=None,
        description="[min_lng, min_lat, max_lng, max_lat] bounding box.",
    )
    center: Optional[Tuple[float, float]] = Field(
        default=None,
        description="(lat, lng) optional center — frontend may derive from bbox.",
    )
    zoom: Optional[int] = Field(
        default=None,
        description="Optional zoom-level hint.",
    )


class MapQuery(BaseModel):
    """Echoed spatial filter query — carries the originating search parameters (FEAT-221).

    Attributes:
        point: (lat, lng) echoed from ``SpatialFilterSpec.point``.
        radius: Search radius.
        unit: Distance unit.
    """

    point: Tuple[float, float] = Field(
        ...,
        description="(lat, lng) in decimal degrees — echoed from SpatialFilterSpec.",
    )
    radius: float = Field(..., description="Search radius.")
    unit: Literal["mi", "km", "m"] = Field(..., description="Distance unit: mi, km, or m.")


class StructuredMapConfig(BaseModel):
    """Framework-agnostic map configuration for FEAT-221.

    Mirrors ``StructuredTableConfig``/``StructuredChartConfig`` — accepts data
    on input (for column-name validation), but the renderer excludes the ``data``
    field from the serialized output and routes per-layer payloads to
    ``response.data`` instead.

    Attributes:
        layers: One ``MapLayer`` per dataset with data-schema + presentation hints.
        data: Flat tabular rows — INPUT-ONLY; excluded from ``output``,
            routed to ``response.data`` by the renderer.
        datasets: Per-layer GeoJSON/rows payloads — INCLUDED in ``output``
            (unlike ``data``); stripped from the FEAT-224 artifact definition
            to keep chat storage lean.
        viewport: Viewport hints (bbox + optional center/zoom).
        query: Echoed ``SpatialFilterSpec`` parameters (point / radius / unit).
        base_layer: Optional base-tile/style hint for the frontend (e.g. an OSM
            tile URL template or a Mapbox style id).
        title: Short map title.
        description: Short prose description.
        explanation: Longer LLM-authored prose explanation of the spatial result.
    """

    model_config = ConfigDict(populate_by_name=True)

    layers: List[MapLayer] = Field(
        ..., description="One MapLayer per dataset."
    )
    data: List[dict] = Field(
        default_factory=list,
        description=(
            "Flat tabular rows; INPUT-ONLY — excluded from ``output``, "
            "routed to response.data by the renderer."
        ),
    )
    datasets: List[dict] = Field(
        default_factory=list,
        description=(
            "Per-layer GeoJSON/rows payloads [{dataset, layer, data_shape, payload}]; "
            "INCLUDED in output (unlike ``data``). Stripped from the FEAT-224 "
            "artifact definition to keep chat storage lean."
        ),
    )
    viewport: Optional[MapViewport] = Field(
        default=None,
        description="Viewport hints (bbox + optional center/zoom).",
    )
    query: Optional[MapQuery] = Field(
        default=None,
        description="Echoed SpatialFilterSpec parameters.",
    )
    base_layer: Optional[str] = Field(
        default=None,
        alias="baseLayer",
        description="Optional base-tile/style hint (e.g. OSM tile URL or Mapbox style id).",
    )
    title: Optional[str] = Field(
        default=None,
        description="Short map title.",
    )
    description: Optional[str] = Field(
        default=None,
        description="Short prose description of the map.",
    )
    explanation: Optional[str] = Field(
        default=None,
        description="Longer LLM-authored prose explanation of the spatial result.",
    )

    @model_validator(mode="after")
    def _validate_column_names(self) -> "StructuredMapConfig":
        """Validate that every declared column name exists in the data rows.

        When ``data`` is non-empty, every ``layer.columns[*].name`` must appear
        as a key in ``data[0]``.  This mirrors the ``StructuredTableConfig``
        column-name check.

        MULTI-LAYER LIMITATION:
        ``data`` in this context is expected to be a *flat union* of all layer
        columns (or left empty, which is the normal renderer path).  For
        multi-layer configs where each layer has distinct property columns, the
        check against a single ``data[0]`` row is a footgun: a column present
        only in layer B will appear missing when ``data[0]`` is a row from
        layer A.

        **The renderer always passes ``data=[]``** (see ``StructuredMapRenderer``),
        which skips this validator entirely.  The validator only fires when a
        caller constructs ``StructuredMapConfig`` directly with non-empty ``data``
        rows — in that case, ``data`` MUST be a flat union of all layer columns,
        or the caller should omit ``data`` altogether.

        Returns:
            The validated ``StructuredMapConfig`` instance.

        Raises:
            ValueError: When a ``column.name`` is absent from ``data[0].keys()``
                and ``data`` is non-empty.
        """
        if self.data:
            cols = set(self.data[0].keys())
            for layer in self.layers:
                missing = [c.name for c in layer.columns if c.name not in cols]
                if missing:
                    raise ValueError(
                        f"column names not present in data rows: {missing}"
                    )
        return self
