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
    - AccordionBlock: Collapsible sections with nested content
    - ChecklistBlock: Visual checkbox-style list
    - TabViewBlock: Tabbed navigation with nested content panes
"""
from typing import (
    List,
    Optional,
    Any,
    Annotated,
    ClassVar,
    Dict,
    Literal,
    Tuple,
    Union,
)
import json
import re
from enum import Enum
from pydantic import BaseModel, Discriminator, Field, field_validator, model_validator


# ──────────────────────────────────────────────
# CSS color validator (reusable)
# ──────────────────────────────────────────────

_CSS_COLOR_RE = re.compile(
    r'^(#[0-9a-fA-F]{3,8}|rgba?\(\s*[\d.]+\s*,\s*[\d.]+\s*,\s*[\d.]+(?:\s*,\s*[\d.]+)?\s*\)'
    r'|hsla?\(\s*[\d.]+\s*,\s*[\d.%]+\s*,\s*[\d.%]+(?:\s*,\s*[\d.]+)?\s*\)'
    r'|[a-zA-Z][-a-zA-Z]*|var\(--[-\w]+\))$'
)


def _validate_css_color(v: Any) -> Any:
    """Validator for CSS color fields — silently drops invalid values.

    Args:
        v: Value to validate.

    Returns:
        The original value if valid, ``None`` otherwise.
    """
    if v is not None and not _CSS_COLOR_RE.match(str(v).strip()):
        return None
    return v


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
    ACCORDION = "accordion"
    CHECKLIST = "checklist"
    TAB_VIEW = "tab_view"


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


class TableStyle(str, Enum):
    """Visual style variants for TableBlock."""
    DEFAULT = "default"
    STRIPED = "striped"
    BORDERED = "bordered"
    COMPACT = "compact"
    COMPARISON = "comparison"


class BulletListStyle(str, Enum):
    """Visual style variants for BulletListBlock."""
    DEFAULT = "default"
    TITLED = "titled"
    COMPACT = "compact"


# ──────────────────────────────────────────────
# Supporting Models (defined before block models
# so forward references can be resolved)
# ──────────────────────────────────────────────

class ColumnDef(BaseModel):
    """Column definition for TableBlock with optional styling."""
    header: str = Field(..., description="Column header text")
    width: Optional[str] = Field(None, description="CSS width (e.g., '200px', '30%')")
    align: Optional[Literal["left", "center", "right"]] = Field(
        None, description="Text alignment for this column"
    )
    color: Optional[str] = Field(
        None, description="Accent color for the column header"
    )

    @field_validator("color", mode="before")
    @classmethod
    def _validate_color(cls, v: Any) -> Any:
        """Validate CSS color value — silently drops invalid values."""
        return _validate_css_color(v)


class AccordionItem(BaseModel):
    """A single collapsible item within an AccordionBlock."""
    id: Optional[str] = Field(None, description="Unique ID; auto-generated if None")
    title: str = Field(..., description="Accordion section title")
    subtitle: Optional[str] = Field(None, description="Optional subtitle below title")
    badge: Optional[str] = Field(None, description="Badge label (e.g., 'Weeks 1-2')")
    badge_color: Optional[str] = Field(None, description="Badge background color")
    number: Optional[int] = Field(None, description="Step number indicator")
    number_color: Optional[str] = Field(None, description="Step number background color")
    content_blocks: List[Any] = Field(
        default_factory=list,
        description="Nested InfographicBlock items. Takes priority over html_content.",
    )
    html_content: Optional[str] = Field(
        None,
        description="Raw HTML content (escape hatch). Sanitized via nh3 before render.",
    )
    expanded: bool = Field(False, description="Whether the section is expanded by default")

    @field_validator("badge_color", "number_color", mode="before")
    @classmethod
    def _validate_colors(cls, v: Any) -> Any:
        """Validate CSS color values — silently drops invalid values."""
        return _validate_css_color(v)


class ChecklistItem(BaseModel):
    """A single item in a ChecklistBlock."""
    text: str = Field(..., description="Checklist item text")
    checked: bool = Field(False, description="Whether the item is checked")
    description: Optional[str] = Field(
        None, description="Optional description below the item text"
    )


class TabPane(BaseModel):
    """A single tab pane within a TabViewBlock."""
    id: str = Field(..., description="Unique slug identifier for this tab")
    label: str = Field(..., description="Tab button label text")
    icon: Optional[str] = Field(
        None, description="Emoji or CSS icon class for the tab button"
    )
    blocks: List[Any] = Field(
        default_factory=list,
        description="InfographicBlock items inside this tab pane.",
    )


# ──────────────────────────────────────────────
# Block Models
# ──────────────────────────────────────────────

class TitleBlock(BaseModel):
    """Main title/subtitle header block."""
    type: Literal["title"] = "title"
    title: str = Field(..., max_length=200, description="Main heading text")
    subtitle: Optional[str] = Field(None, description="Secondary heading or tagline")
    author: Optional[str] = Field(None, description="Author or source attribution")
    date: Optional[str] = Field(None, description="Date or time period covered")
    logo_url: Optional[str] = Field(None, description="URL to logo image")


class HeroCardBlock(BaseModel):
    """Key metric card with value, label, and optional trend indicator."""
    type: Literal["hero_card"] = "hero_card"
    label: str = Field(
        "",
        description="Metric label (e.g., 'Total Revenue')",
    )
    value: str = Field(
        "",
        description="Formatted metric value (e.g., '$1.2M', '98%')",
    )
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

    @field_validator("color", mode="before")
    @classmethod
    def _validate_color(cls, v: Any) -> Any:
        """Validate CSS color value — silently drops invalid values."""
        return _validate_css_color(v)

    @field_validator("trend", mode="before")
    @classmethod
    def _coerce_trend(cls, v: Any) -> Optional[TrendDirection]:
        """Coerce freeform LLM trend text to the TrendDirection enum."""
        if v is None or isinstance(v, TrendDirection):
            return v
        if isinstance(v, str):
            low = v.lower().strip()
            try:
                return TrendDirection(low)
            except ValueError:
                pass
            if any(kw in low for kw in ("positive", "increase", "growth", "up", "rise")):
                return TrendDirection.UP
            if any(kw in low for kw in ("negative", "decrease", "decline", "down", "drop")):
                return TrendDirection.DOWN
            if any(kw in low for kw in ("flat", "stable", "neutral", "unchanged", "steady")):
                return TrendDirection.FLAT
            return None
        return None

    _LABEL_ALIASES: ClassVar[Tuple[str, ...]] = (
        "label", "title", "name", "metric", "metric_name",
        "caption", "heading", "header", "key",
    )
    _VALUE_ALIASES: ClassVar[Tuple[str, ...]] = (
        "value", "number", "text", "content", "figure",
        "count", "total", "amount", "kpi_value", "metric_value",
    )
    _NESTED_WRAPPERS: ClassVar[Tuple[str, ...]] = (
        "card", "card_data", "data", "metric", "kpi",
        "content", "callout", "hero_card", "details",
    )

    @model_validator(mode="before")
    @classmethod
    def _extract_from_items(cls, values: Any) -> Any:
        """Recover label/value from common LLM hallucinations.

        Handles three flavours of malformed hero_card payloads:
        * ``items=[{...}]`` instead of flat label/value
        * Alternative key names (``title``, ``number``, ``text``, ...)
        * Nested wrapper dicts (``card``, ``callout``, ``data``, ...)

        Falls back to empty strings so a single bad card never crashes
        the whole infographic render.
        """
        if not isinstance(values, dict):
            return values

        # 1) items list → flatten first item into label/value
        if "label" not in values and "items" in values:
            items = values.get("items")
            if isinstance(items, list) and items:
                first = items[0] if isinstance(items[0], dict) else {}
                values["label"] = first.get("label", first.get("title", "Metric"))
                values["value"] = str(first.get("value", ""))
                if not values.get("icon") and first.get("icon"):
                    values["icon"] = first["icon"]

        # 2) Alternative key names at the top level
        if "label" not in values:
            for alt in cls._LABEL_ALIASES:
                if alt == "label":
                    continue
                v = values.get(alt)
                if isinstance(v, str) and v:
                    values["label"] = v
                    break
        if "value" not in values:
            for alt in cls._VALUE_ALIASES:
                if alt == "value":
                    continue
                v = values.get(alt)
                if isinstance(v, (str, int, float)) and not isinstance(v, bool):
                    values["value"] = str(v)
                    break

        # 3) Nested wrapper dicts
        if "label" not in values or "value" not in values:
            for wrapper_key in cls._NESTED_WRAPPERS:
                nested = values.get(wrapper_key)
                if not isinstance(nested, dict):
                    continue
                if "label" not in values:
                    for k in cls._LABEL_ALIASES:
                        nv = nested.get(k)
                        if isinstance(nv, str) and nv:
                            values["label"] = nv
                            break
                if "value" not in values:
                    for k in cls._VALUE_ALIASES:
                        nv = nested.get(k)
                        if isinstance(nv, (str, int, float)) and not isinstance(nv, bool):
                            values["value"] = str(nv)
                            break
                if not values.get("icon") and isinstance(nested.get("icon"), str):
                    values["icon"] = nested["icon"]
                if "label" in values and "value" in values:
                    break

        # 4) Final safety net — never block validation on these fields
        values.setdefault("label", "")
        values.setdefault("value", "")
        return values


class SummaryBlock(BaseModel):
    """Rich text summary paragraph."""
    type: Literal["summary"] = "summary"
    title: Optional[str] = Field(None, description="Section heading")
    content: str = Field(
        ...,
        max_length=2000,
        description="Summary text content. Supports markdown formatting."
    )
    highlight: Optional[bool] = Field(
        False,
        description="Whether to visually emphasize this block"
    )

    @model_validator(mode="before")
    @classmethod
    def _text_to_content(cls, values: Any) -> Any:
        """Accept ``text`` as an alias for ``content``."""
        if isinstance(values, dict) and "content" not in values and "text" in values:
            values["content"] = values.pop("text")
        return values


class ChartDataSeries(BaseModel):
    """A single data series for chart rendering."""
    name: str = Field(..., description="Series name/label")
    values: List[Union[int, float, None]] = Field(
        ...,
        description="Data values corresponding to labels"
    )
    color: Optional[str] = Field(None, description="Series color")

    @field_validator("color", mode="before")
    @classmethod
    def _validate_color(cls, v: Any) -> Any:
        """Validate CSS color value — silently drops invalid values."""
        return _validate_css_color(v)


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
    layout: Optional[Literal["full", "half"]] = Field(
        None,
        description=(
            "Layout hint for the frontend renderer. 'half' marks the chart as "
            "half-width so consecutive half-width charts render side-by-side in "
            "a 2-column grid. Omit or set to 'full' for full-width rendering."
        ),
    )
    color_by_sign: Optional[bool] = Field(
        False,
        description=(
            "When True, the frontend colors each data point by the sign of its "
            "value (positive vs negative) instead of by series. Intended for "
            "variance/delta charts (e.g. bar or waterfall) where positive and "
            "negative figures should read differently. The actual colors come "
            "from the frontend theme unless overridden via 'positive_color' / "
            "'negative_color'."
        ),
    )
    positive_color: Optional[str] = Field(
        None,
        description=(
            "Optional override color for positive values when 'color_by_sign' is "
            "enabled. CSS color value. When omitted, the frontend falls back to "
            "its theme's positive/success color."
        ),
    )
    negative_color: Optional[str] = Field(
        None,
        description=(
            "Optional override color for negative values when 'color_by_sign' is "
            "enabled. CSS color value. When omitted, the frontend falls back to "
            "its theme's negative/danger color."
        ),
    )

    @field_validator("positive_color", "negative_color", mode="before")
    @classmethod
    def _validate_sign_colors(cls, v: Any) -> Any:
        """Validate CSS color value — silently drops invalid values."""
        return _validate_css_color(v)

    def to_chart_config(self) -> Any:
        """Convert to the agnostic StructuredChartConfig shape.

        Translates the infographic ``labels`` / ``series`` representation to
        the ``x`` / ``y`` / ``data`` column-oriented format used by the
        frontend-agnostic config.

        Returns:
            A :class:`~parrot.models.outputs.StructuredChartConfig` instance.
        """
        from parrot.models.outputs import StructuredChartConfig as _SCC

        x_col: str = self.x_axis_label or "category"
        y_cols: List[str] = [s.name for s in self.series]
        rows: List[dict] = [
            {x_col: label, **{
                s.name: s.values[i] if i < len(s.values) else None
                for s in self.series
            }}
            for i, label in enumerate(self.labels)
        ]

        return _SCC(
            type=self.chart_type.value,
            x=x_col,
            y=y_cols,
            title=self.title,
            description=self.description,
            stacked=self.stacked,
            show_legend=self.show_legend,
            color_by_sign=self.color_by_sign,
            positive_color=self.positive_color,
            negative_color=self.negative_color,
            x_axis_label=self.x_axis_label,
            y_axis_label=self.y_axis_label,
            data=rows,
        )

    @classmethod
    def from_chart_config(cls, cfg: Any, **kwargs: Any) -> "ChartBlock":
        """Create a ChartBlock from an agnostic StructuredChartConfig.

        Translates the ``x`` / ``y`` / ``data`` column-oriented format back
        to the ``labels`` / ``series`` representation.

        Args:
            cfg: A :class:`~parrot.models.outputs.StructuredChartConfig` instance.
            **kwargs: Additional fields to pass to the ChartBlock constructor
                (e.g. ``layout``).

        Returns:
            A :class:`ChartBlock` instance.
        """
        rows: List[dict] = cfg.data or []
        labels: List[str] = [str(row.get(cfg.x, "")) for row in rows]
        series: List[ChartDataSeries] = [
            ChartDataSeries(name=col, values=[row.get(col) for row in rows])
            for col in cfg.y
        ]

        try:
            chart_type = ChartType(cfg.type)
        except ValueError:
            chart_type = ChartType.BAR

        return cls(
            chart_type=chart_type,
            title=cfg.title,
            description=cfg.description,
            labels=labels,
            series=series,
            stacked=cfg.stacked,
            show_legend=cfg.show_legend,
            color_by_sign=cfg.color_by_sign,
            positive_color=getattr(cfg, "positive_color", None),
            negative_color=cfg.negative_color,
            x_axis_label=getattr(cfg, "x_axis_label", None),
            y_axis_label=getattr(cfg, "y_axis_label", None),
            **kwargs,
        )


class BulletListBlock(BaseModel):
    """Ordered or unordered list of items."""
    type: Literal["bullet_list"] = "bullet_list"
    title: Optional[str] = Field(None, description="List heading")
    items: List[Annotated[str, Field(max_length=500)]] = Field(
        ...,
        description="List items (max 500 chars each). Each item supports markdown formatting."
    )
    ordered: Optional[bool] = Field(False, description="Numbered list if True")
    icon: Optional[str] = Field(
        None,
        description="Custom icon for list items (e.g., 'check', 'arrow', 'star')"
    )
    # New styling fields (backward compatible — all default to None)
    color: Optional[str] = Field(
        None,
        description="Dot indicator color as CSS hex value (e.g., '#534AB7')"
    )
    columns: Optional[int] = Field(
        None,
        ge=1,
        le=4,
        description="Number of grid columns for multi-column layout (1-4)"
    )
    style: Optional[BulletListStyle] = Field(
        None,
        description="Visual style variant for the list"
    )

    @field_validator("color", mode="before")
    @classmethod
    def _validate_color(cls, v: Any) -> Any:
        """Validate CSS color value — silently drops invalid values."""
        return _validate_css_color(v)


class TableBlock(BaseModel):
    """Tabular data block."""
    type: Literal["table"] = "table"
    title: Optional[str] = Field(None, description="Table caption/title")
    columns: Union[List[str], List[ColumnDef]] = Field(
        ...,
        description="Column header names (str) or ColumnDef objects with styling"
    )
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
    # New styling fields (backward compatible — all default to None/True)
    style: Optional[TableStyle] = Field(
        None,
        description="Visual style variant for the table"
    )
    responsive: Optional[bool] = Field(
        True,
        description="Wrap table in a responsive scroll container"
    )
    caption: Optional[str] = Field(
        None,
        description="HTML caption element text"
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_table_data(cls, values: Any) -> Any:
        """Normalize LLM output that sends columns as dicts and rows as dicts.

        Handles:
        - Legacy format: [{"key": "col1", "label": "Col 1"}, ...]
        - ColumnDef format: [{"header": "Col 1", "width": "200px"}, ...]
        - Dict rows: [{"col1": "val1"}, ...] → [["val1"], ...]
        """
        if isinstance(values, BaseModel):
            return values
        if not isinstance(values, dict):
            return values
        cols = values.get("columns", [])
        rows = values.get("rows", [])
        col_keys: List[str] = []
        if cols and isinstance(cols[0], dict):
            if "header" in cols[0]:
                # ColumnDef format — leave columns as-is, normalize rows only if needed
                if rows and isinstance(rows[0], dict):
                    col_keys = [c.get("header", "") for c in cols]
                    values["rows"] = [
                        [row.get(k, "") for k in col_keys] for row in rows
                    ]
            else:
                # Legacy format: {"key": ..., "label": ...}
                col_keys = [c.get("key", "") for c in cols]
                values["columns"] = [
                    c.get("label", c.get("key", str(c))) for c in cols
                ]
                if rows and isinstance(rows[0], dict):
                    if not col_keys:
                        col_keys = list(cols) if cols else list(rows[0].keys())
                    values["rows"] = [
                        [row.get(k, "") for k in col_keys] for row in rows
                    ]
        elif rows and isinstance(rows[0], dict):
            if not col_keys:
                col_keys = list(cols) if cols else list(rows[0].keys())
            values["rows"] = [
                [row.get(k, "") for k in col_keys] for row in rows
            ]
        return values


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

    @model_validator(mode="before")
    @classmethod
    def _normalise_fields(cls, values: Any) -> Any:
        """Accept ``text`` as alias for ``content`` and ``color`` as alias for ``level``."""
        if not isinstance(values, dict):
            return values
        if "content" not in values and "text" in values:
            values["content"] = values.pop("text")
        if "level" not in values and "color" in values:
            raw = values.pop("color")
            try:
                values["level"] = CalloutLevel(raw)
            except ValueError:
                pass
        return values


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

    @field_validator("color", mode="before")
    @classmethod
    def _validate_color(cls, v: Any) -> Any:
        """Validate CSS color value — silently drops invalid values."""
        return _validate_css_color(v)


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

    @field_validator("color", mode="before")
    @classmethod
    def _validate_color(cls, v: Any) -> Any:
        """Validate CSS color value — silently drops invalid values."""
        return _validate_css_color(v)


class ProgressBlock(BaseModel):
    """Progress/completion indicators."""
    type: Literal["progress"] = "progress"
    title: Optional[str] = Field(None, description="Section heading")
    items: List[ProgressItem] = Field(
        ...,
        description="List of progress indicators"
    )


class AccordionBlock(BaseModel):
    """Collapsible accordion sections with optional nested block content."""
    type: Literal["accordion"] = "accordion"
    title: Optional[str] = Field(None, description="Accordion group title")
    items: List[AccordionItem] = Field(
        ...,
        description="List of collapsible accordion sections"
    )
    allow_multiple: bool = Field(
        True,
        description="Whether multiple sections can be expanded simultaneously"
    )


class ChecklistBlock(BaseModel):
    """Visual checkbox-style list with optional checked/unchecked state."""
    type: Literal["checklist"] = "checklist"
    title: Optional[str] = Field(None, description="Checklist heading")
    items: List[ChecklistItem] = Field(
        ...,
        description="List of checklist items with checked state"
    )
    style: Optional[Literal["default", "acceptance", "todo", "compact"]] = Field(
        "default",
        description="Visual style variant"
    )


class TabViewBlock(BaseModel):
    """Tabbed navigation block containing multiple content panes."""
    type: Literal["tab_view"] = "tab_view"
    tabs: List[TabPane] = Field(
        ...,
        min_length=2,
        description="List of tab panes (minimum 2 required)"
    )
    active_tab: Optional[str] = Field(
        None,
        description="ID of the default active tab (defaults to first tab)"
    )
    style: Optional[Literal["pills", "underline", "boxed"]] = Field(
        "pills",
        description="Tab navigation visual style"
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
    AccordionBlock,
    ChecklistBlock,
    TabViewBlock,
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
    blocks: List[Annotated[InfographicBlock, Discriminator("type")]] = Field(
        ...,
        description="Ordered list of content blocks forming the infographic"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Extra metadata (data sources, generation params, etc.)"
    )

    @model_validator(mode="before")
    @classmethod
    def _normalise_payload(cls, values: Any) -> Any:
        """Fix common LLM output mismatches before validation.

        * ``layout`` → ``template`` alias.
        * Stringified JSON blocks → deserialize to dicts.
        * ``hero_card`` blocks with ``items`` list → expand to individual cards.
        * ``tab_view`` blocks: ensure tabs is a list.
        * ``accordion`` blocks: ensure items is a list.
        """
        if not isinstance(values, dict):
            return values
        # layout → template alias
        if "layout" in values and "template" not in values:
            values["template"] = values.pop("layout")
        # Normalise blocks
        raw_blocks = values.get("blocks")
        if isinstance(raw_blocks, list):
            parsed_blocks: list = []
            for block in raw_blocks:
                if isinstance(block, str):
                    try:
                        block = json.loads(block)
                    except (json.JSONDecodeError, TypeError):
                        pass
                parsed_blocks.append(block)
            expanded: list = []
            for block in parsed_blocks:
                if (
                    isinstance(block, dict)
                    and block.get("type") == "hero_card"
                    and "items" in block
                    and "label" not in block
                ):
                    items = block["items"]
                    if isinstance(items, list):
                        for item in items:
                            if isinstance(item, dict):
                                card = {"type": "hero_card", **item}
                                expanded.append(card)
                        continue
                # Normalize tab_view: ensure tabs is a list
                if isinstance(block, dict) and block.get("type") == "tab_view":
                    if not isinstance(block.get("tabs"), list):
                        block["tabs"] = block.get("tabs") or []
                # Normalize accordion: ensure items is a list
                if isinstance(block, dict) and block.get("type") == "accordion":
                    if not isinstance(block.get("items"), list):
                        block["items"] = block.get("items") or []
                expanded.append(block)
            values["blocks"] = expanded
        return values


# ──────────────────────────────────────────────
# Resolve forward references for recursive models
# ──────────────────────────────────────────────

# AccordionItem.content_blocks and TabPane.blocks use List[Any] but we
# rebuild models after InfographicBlock is defined so runtime type checking
# is accurate.
AccordionItem.model_rebuild()
TabPane.model_rebuild()
InfographicResponse.model_rebuild()


# ──────────────────────────────────────────────
# Asset Declarations (FEAT-197)
# ──────────────────────────────────────────────


class JSBundle(BaseModel):
    """Declarative JavaScript bundle attached to an InfographicTemplate.

    When ``scope='cdn'``, the ``url`` and ``sri_hash`` fields are required so
    the HTML-serving CSP can whitelist the origin and SRI hash.  When
    ``scope='inline'``, the ``inline`` field must contain the JavaScript
    source verbatim.

    The enhance prompt lists the allowed bundles to the LLM; the
    ``build_csp_headers`` helper (parrot/handlers/csp.py) uses the ``url``
    origins to build the ``script-src`` directive.

    Example (CDN)::

        JSBundle(
            name="echarts",
            scope="cdn",
            url="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js",
            sri_hash="sha384-AAAA...",
        )

    Example (inline)::

        JSBundle(name="sparkline", scope="inline", inline="/* sparkline js */")
    """

    name: str = Field(
        ..., description="Stable bundle identifier (e.g. 'echarts')."
    )
    url: Optional[str] = Field(
        default=None,
        description="CDN URL — required when scope='cdn'.",
    )
    inline: Optional[str] = Field(
        default=None,
        description="Inline JavaScript source — required when scope='inline'.",
    )
    sri_hash: Optional[str] = Field(
        default=None,
        description="'sha384-…' integrity hash — required when scope='cdn'.",
    )
    scope: Literal["inline", "cdn"] = Field(
        default="inline",
        description="Delivery mechanism: 'inline' (embedded) or 'cdn' (external URL).",
    )

    @field_validator("sri_hash", mode="before")
    @classmethod
    def _validate_sri_format(cls, v: Any) -> Any:
        """Validate SRI hash format (sha256/384/512-<base64>).

        Args:
            v: Incoming value for ``sri_hash``.

        Returns:
            The value unchanged if valid or ``None``.

        Raises:
            ValueError: When the value is present but not a valid SRI hash.
        """
        if v is not None and not re.match(r'^sha(256|384|512)-[A-Za-z0-9+/]+=*$', str(v)):
            raise ValueError(
                f"sri_hash must be a valid SRI hash (sha256/384/512-<base64>), got: {v!r}"
            )
        return v

    @model_validator(mode="after")
    def _validate_scope_consistency(self) -> "JSBundle":
        """Enforce cross-field consistency based on ``scope``."""
        if self.scope == "cdn":
            if not self.url or not self.sri_hash:
                raise ValueError(
                    "scope='cdn' requires both 'url' and 'sri_hash'"
                )
            if self.inline is not None:
                raise ValueError("scope='cdn' must not set 'inline'")
        else:  # inline
            if self.inline is None:
                raise ValueError("scope='inline' requires 'inline' source")
            if self.url is not None or self.sri_hash is not None:
                raise ValueError(
                    "scope='inline' must not set 'url' or 'sri_hash'"
                )
        return self


# ──────────────────────────────────────────────
# Theme System
# ──────────────────────────────────────────────

class ThemeConfig(BaseModel):
    """CSS variable configuration for infographic HTML themes.

    Each theme defines color tokens and font settings that map to
    CSS custom properties on :root. The ``to_css_variables()`` method
    generates the CSS block consumed by ``InfographicHTMLRenderer``.
    """
    name: str = Field(..., description="Theme identifier")
    primary: str = Field("#6366f1", description="Primary brand color")
    primary_dark: str = Field("#4f46e5", description="Darker primary shade")
    primary_light: str = Field("#818cf8", description="Lighter primary shade")
    accent_green: str = Field("#10b981", description="Success / positive accent")
    accent_amber: str = Field("#f59e0b", description="Warning / attention accent")
    accent_red: str = Field("#ef4444", description="Error / negative accent")
    neutral_bg: str = Field("#f8fafc", description="Card / section background")
    neutral_border: str = Field("#e2e8f0", description="Border color")
    neutral_muted: str = Field("#64748b", description="Muted / secondary text")
    neutral_text: str = Field("#0f172a", description="Primary text color")
    body_bg: str = Field("#f1f5f9", description="Page background color")
    font_family: str = Field(
        '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, '
        'Helvetica, Arial, sans-serif',
        description="CSS font-family stack",
    )

    @field_validator(
        "primary", "primary_dark", "primary_light",
        "accent_green", "accent_amber", "accent_red",
        "neutral_bg", "neutral_border", "neutral_muted",
        "neutral_text", "body_bg",
        mode="before",
    )
    @classmethod
    def _validate_color_fields(cls, v: Any) -> Any:
        """Validate CSS color values — raises ValueError on invalid input."""
        if v is not None and not _CSS_COLOR_RE.match(str(v).strip()):
            raise ValueError(
                f"Invalid CSS color value: {v!r}. "
                "Expected a hex, rgb(), rgba(), hsl(), hsla(), or named color."
            )
        return v

    def to_css_variables(self) -> str:
        """Generate a CSS ``:root`` block with custom properties.

        Returns:
            A string like ``:root { --primary: #6366f1; ... }``
        """
        props = [
            f"    --primary: {self.primary};",
            f"    --primary-dark: {self.primary_dark};",
            f"    --primary-light: {self.primary_light};",
            f"    --accent-green: {self.accent_green};",
            f"    --accent-amber: {self.accent_amber};",
            f"    --accent-red: {self.accent_red};",
            f"    --neutral-bg: {self.neutral_bg};",
            f"    --neutral-border: {self.neutral_border};",
            f"    --neutral-muted: {self.neutral_muted};",
            f"    --neutral-text: {self.neutral_text};",
            f"    --body-bg: {self.body_bg};",
            f"    --font-family: {self.font_family};",
        ]
        return ":root {\n" + "\n".join(props) + "\n}"


class ThemeRegistry:
    """Registry for infographic HTML themes.

    Provides ``register``, ``get``, and ``list_themes`` following the
    same pattern as ``InfographicTemplateRegistry``.
    """

    def __init__(self) -> None:
        self._themes: Dict[str, ThemeConfig] = {}

    def register(self, theme: ThemeConfig) -> None:
        """Register a theme configuration.

        Args:
            theme: ThemeConfig instance to register.
        """
        self._themes[theme.name] = theme

    def get(self, name: str) -> ThemeConfig:
        """Retrieve a theme by name.

        Args:
            name: Theme identifier.

        Returns:
            The matching ThemeConfig.

        Raises:
            KeyError: If the theme name is not registered.
        """
        try:
            return self._themes[name]
        except KeyError:
            raise KeyError(
                f"Theme '{name}' not found. Available: {self.list_themes()}"
            )

    def list_themes(self) -> List[str]:
        """Return names of all registered themes.

        Returns:
            Sorted list of theme names.
        """
        return sorted(self._themes.keys())

    def list_themes_detailed(self) -> List[Dict[str, str]]:
        """Return theme summaries with key colour tokens.

        Returns:
            List of dicts containing name, primary, neutral_bg, body_bg,
            sorted by name.
        """
        return [
            {
                "name": t.name,
                "primary": t.primary,
                "neutral_bg": t.neutral_bg,
                "body_bg": t.body_bg,
            }
            for t in sorted(self._themes.values(), key=lambda x: x.name)
        ]


# Module-level singleton
theme_registry = ThemeRegistry()

# ── Built-in themes ──────────────────────────

theme_registry.register(ThemeConfig(
    name="light",
    primary="#6366f1",
    primary_dark="#4f46e5",
    primary_light="#818cf8",
    accent_green="#10b981",
    accent_amber="#f59e0b",
    accent_red="#ef4444",
    neutral_bg="#f8fafc",
    neutral_border="#e2e8f0",
    neutral_muted="#64748b",
    neutral_text="#0f172a",
    body_bg="#f1f5f9",
))

theme_registry.register(ThemeConfig(
    name="dark",
    primary="#818cf8",
    primary_dark="#6366f1",
    primary_light="#a5b4fc",
    accent_green="#34d399",
    accent_amber="#fbbf24",
    accent_red="#f87171",
    neutral_bg="#1e293b",
    neutral_border="#334155",
    neutral_muted="#94a3b8",
    neutral_text="#f1f5f9",
    body_bg="#0f172a",
))

theme_registry.register(ThemeConfig(
    name="corporate",
    primary="#1e40af",
    primary_dark="#1e3a8a",
    primary_light="#3b82f6",
    accent_green="#059669",
    accent_amber="#d97706",
    accent_red="#dc2626",
    neutral_bg="#f9fafb",
    neutral_border="#d1d5db",
    neutral_muted="#6b7280",
    neutral_text="#111827",
    body_bg="#f3f4f6",
))

theme_registry.register(ThemeConfig(
    name="midnight",
    primary="#60a5fa",        # blue-400 — links, KPIs, accents
    primary_dark="#3b82f6",   # blue-500 — hover states, borders
    primary_light="#93c5fd",  # blue-300 — subtle highlights
    accent_green="#4ade80",   # green-400 — success, running, in-progress
    accent_amber="#f59e0b",   # amber-500 — warnings, notices
    accent_red="#f87171",     # red-400 — errors, blockers, critical
    neutral_bg="#1e293b",     # slate-800 — cards, sections
    neutral_border="#334155",  # slate-700 — borders, dividers
    neutral_muted="#64748b",  # slate-500 — labels, secondary text
    neutral_text="#e2e8f0",   # slate-200 — primary text
    body_bg="#0f172a",        # slate-900 — page background
    font_family=(
        '-apple-system, BlinkMacSystemFont, "Segoe UI", '
        'sans-serif'
    ),
))
