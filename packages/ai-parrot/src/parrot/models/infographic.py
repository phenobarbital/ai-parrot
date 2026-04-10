"""
Structured Infographic Output Models.

Defines block-based Pydantic models for infographic generation.
The LLM returns structured JSON using these models, and the frontend
is responsible for rendering each block type appropriately.

Block Types:
    - TitleBlock: Main title/subtitle header
    - HeroCardBlock: Key metric card with optional trend
    - SummaryBlock: Rich text summary paragraph
    - ChartBlock: Chart specification (bar, line, pie, etc.)
    - BulletListBlock: Ordered/unordered list of items
    - TableBlock: Tabular data with headers and rows
    - ImageBlock: Image reference with alt text
    - QuoteBlock: Highlighted quote or callout
    - CalloutBlock: Alert/info/warning box
    - DividerBlock: Visual separator
    - TimelineBlock: Chronological sequence of events
    - ProgressBlock: Progress/completion indicators
"""
from typing import (
    List,
    Optional,
    Any,
    Dict,
    Literal,
    Union,
)
from enum import Enum
from pydantic import BaseModel, Field


# ──────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────

class BlockType(str, Enum):
    """Available infographic block types."""
    TITLE = "title"
    HERO_CARD = "hero_card"
    SUMMARY = "summary"
    CHART = "chart"
    BULLET_LIST = "bullet_list"
    TABLE = "table"
    IMAGE = "image"
    QUOTE = "quote"
    CALLOUT = "callout"
    DIVIDER = "divider"
    TIMELINE = "timeline"
    PROGRESS = "progress"


class ChartType(str, Enum):
    """Supported chart types for ChartBlock."""
    BAR = "bar"
    LINE = "line"
    PIE = "pie"
    DONUT = "donut"
    AREA = "area"
    SCATTER = "scatter"
    RADAR = "radar"
    HEATMAP = "heatmap"
    TREEMAP = "treemap"
    FUNNEL = "funnel"
    GAUGE = "gauge"
    WATERFALL = "waterfall"


class TrendDirection(str, Enum):
    """Trend direction for hero card metrics."""
    UP = "up"
    DOWN = "down"
    FLAT = "flat"


class CalloutLevel(str, Enum):
    """Severity/type for callout blocks."""
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    TIP = "tip"


# ──────────────────────────────────────────────
# Block Models
# ──────────────────────────────────────────────

class TitleBlock(BaseModel):
    """Main title/subtitle header block."""
    type: Literal["title"] = "title"
    title: str = Field(..., description="Main heading text")
    subtitle: Optional[str] = Field(None, description="Secondary heading or tagline")
    author: Optional[str] = Field(None, description="Author or source attribution")
    date: Optional[str] = Field(None, description="Date or time period covered")
    logo_url: Optional[str] = Field(None, description="URL to logo image")


class HeroCardBlock(BaseModel):
    """Key metric card with value, label, and optional trend indicator."""
    type: Literal["hero_card"] = "hero_card"
    label: str = Field(..., description="Metric label (e.g., 'Total Revenue')")
    value: str = Field(..., description="Formatted metric value (e.g., '$1.2M', '98%')")
    icon: Optional[str] = Field(
        None,
        description="Icon identifier (e.g., 'money', 'users', 'chart', 'time', 'target')"
    )
    trend: Optional[TrendDirection] = Field(None, description="Trend direction")
    trend_value: Optional[str] = Field(
        None,
        description="Trend change text (e.g., '+12.5%', '-3 pts')"
    )
    comparison_period: Optional[str] = Field(
        None,
        description="Period for comparison (e.g., 'vs last month')"
    )
    color: Optional[str] = Field(
        None,
        description="Accent color for this card (CSS color value)"
    )


class SummaryBlock(BaseModel):
    """Rich text summary paragraph."""
    type: Literal["summary"] = "summary"
    title: Optional[str] = Field(None, description="Section heading")
    content: str = Field(
        ...,
        description="Summary text content. Supports markdown formatting."
    )
    highlight: Optional[bool] = Field(
        False,
        description="Whether to visually emphasize this block"
    )


class ChartDataSeries(BaseModel):
    """A single data series for chart rendering."""
    name: str = Field(..., description="Series name/label")
    values: List[Union[int, float, None]] = Field(
        ...,
        description="Data values corresponding to labels"
    )
    color: Optional[str] = Field(None, description="Series color")


class ChartBlock(BaseModel):
    """Chart specification block. Frontend renders using its preferred library."""
    type: Literal["chart"] = "chart"
    chart_type: ChartType = Field(..., description="Type of chart to render")
    title: Optional[str] = Field(None, description="Chart title")
    description: Optional[str] = Field(None, description="Caption or description")
    labels: List[str] = Field(
        ...,
        description="Category/axis labels (x-axis for bar/line, slices for pie)"
    )
    series: List[ChartDataSeries] = Field(
        ...,
        description="One or more data series"
    )
    x_axis_label: Optional[str] = Field(None, description="X-axis label")
    y_axis_label: Optional[str] = Field(None, description="Y-axis label")
    stacked: Optional[bool] = Field(False, description="Whether series are stacked")
    show_legend: Optional[bool] = Field(True, description="Whether to show the legend")


class BulletListBlock(BaseModel):
    """Ordered or unordered list of items."""
    type: Literal["bullet_list"] = "bullet_list"
    title: Optional[str] = Field(None, description="List heading")
    items: List[str] = Field(
        ...,
        description="List items. Each item supports markdown formatting."
    )
    ordered: Optional[bool] = Field(False, description="Numbered list if True")
    icon: Optional[str] = Field(
        None,
        description="Custom icon for list items (e.g., 'check', 'arrow', 'star')"
    )


class TableBlock(BaseModel):
    """Tabular data block."""
    type: Literal["table"] = "table"
    title: Optional[str] = Field(None, description="Table caption/title")
    columns: List[str] = Field(..., description="Column header names")
    rows: List[List[Any]] = Field(
        ...,
        description="Row data, each row is a list of cell values"
    )
    highlight_first_column: Optional[bool] = Field(
        False,
        description="Visually emphasize the first column as row headers"
    )
    sortable: Optional[bool] = Field(
        False,
        description="Whether the frontend should allow column sorting"
    )


class ImageBlock(BaseModel):
    """Image reference block."""
    type: Literal["image"] = "image"
    url: Optional[str] = Field(None, description="Image URL")
    base64: Optional[str] = Field(None, description="Base64-encoded image data")
    alt: str = Field(..., description="Alt text description")
    caption: Optional[str] = Field(None, description="Image caption")
    width: Optional[str] = Field(None, description="CSS width (e.g., '100%', '400px')")


class QuoteBlock(BaseModel):
    """Highlighted quote or testimonial."""
    type: Literal["quote"] = "quote"
    text: str = Field(..., description="Quote text")
    author: Optional[str] = Field(None, description="Attribution")
    source: Optional[str] = Field(None, description="Source reference")


class CalloutBlock(BaseModel):
    """Alert/info/warning box."""
    type: Literal["callout"] = "callout"
    level: CalloutLevel = Field(
        CalloutLevel.INFO,
        description="Callout type: info, success, warning, error, tip"
    )
    title: Optional[str] = Field(None, description="Callout heading")
    content: str = Field(..., description="Callout body text")


class DividerBlock(BaseModel):
    """Visual separator between sections."""
    type: Literal["divider"] = "divider"
    style: Optional[Literal["solid", "dashed", "dotted", "gradient"]] = Field(
        "solid",
        description="Divider visual style"
    )


class TimelineEvent(BaseModel):
    """A single event in a timeline."""
    date: str = Field(..., description="Date or time label")
    title: str = Field(..., description="Event title")
    description: Optional[str] = Field(None, description="Event details")
    icon: Optional[str] = Field(None, description="Event icon")
    color: Optional[str] = Field(None, description="Event accent color")


class TimelineBlock(BaseModel):
    """Chronological sequence of events."""
    type: Literal["timeline"] = "timeline"
    title: Optional[str] = Field(None, description="Timeline heading")
    events: List[TimelineEvent] = Field(
        ...,
        description="Ordered list of timeline events"
    )


class ProgressItem(BaseModel):
    """A single progress indicator."""
    label: str = Field(..., description="Progress item label")
    value: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Completion percentage (0-100)"
    )
    color: Optional[str] = Field(None, description="Progress bar color")
    target: Optional[float] = Field(
        None,
        ge=0.0,
        le=100.0,
        description="Target value to display as reference"
    )


class ProgressBlock(BaseModel):
    """Progress/completion indicators."""
    type: Literal["progress"] = "progress"
    title: Optional[str] = Field(None, description="Section heading")
    items: List[ProgressItem] = Field(
        ...,
        description="List of progress indicators"
    )


# ──────────────────────────────────────────────
# Union type for all blocks
# ──────────────────────────────────────────────

InfographicBlock = Union[
    TitleBlock,
    HeroCardBlock,
    SummaryBlock,
    ChartBlock,
    BulletListBlock,
    TableBlock,
    ImageBlock,
    QuoteBlock,
    CalloutBlock,
    DividerBlock,
    TimelineBlock,
    ProgressBlock,
]


# ──────────────────────────────────────────────
# Infographic Response
# ──────────────────────────────────────────────

class InfographicResponse(BaseModel):
    """Structured infographic output returned by get_infographic().

    Contains an ordered list of typed blocks that the frontend
    renders according to its own design system.
    """
    template: Optional[str] = Field(
        None,
        description="Template name used to generate this infographic"
    )
    theme: Optional[str] = Field(
        None,
        description="Color theme hint (e.g., 'light', 'dark', 'corporate', 'vibrant')"
    )
    blocks: List[InfographicBlock] = Field(
        ...,
        description="Ordered list of content blocks forming the infographic"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Extra metadata (data sources, generation params, etc.)"
    )
