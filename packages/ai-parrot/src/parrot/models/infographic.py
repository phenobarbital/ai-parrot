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
    Annotated,
    Dict,
    Literal,
    Union,
)
import json
from enum import Enum
from pydantic import BaseModel, Discriminator, Field, field_validator, model_validator


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

    @field_validator("trend", mode="before")
    @classmethod
    def _coerce_trend(cls, v: Any) -> Optional[TrendDirection]:
        """Coerce freeform LLM trend text to the TrendDirection enum."""
        if v is None or isinstance(v, TrendDirection):
            return v
        if isinstance(v, str):
            low = v.lower().strip()
            # Exact match
            try:
                return TrendDirection(low)
            except ValueError:
                pass
            # Keyword mapping
            if any(kw in low for kw in ("positive", "increase", "growth", "up", "rise")):
                return TrendDirection.UP
            if any(kw in low for kw in ("negative", "decrease", "decline", "down", "drop")):
                return TrendDirection.DOWN
            if any(kw in low for kw in ("flat", "stable", "neutral", "unchanged", "steady")):
                return TrendDirection.FLAT
            # Unrecognisable — discard rather than fail
            return None
        return None

    @model_validator(mode="before")
    @classmethod
    def _extract_from_items(cls, values: Any) -> Any:
        """Handle LLM returning items list instead of flat label/value."""
        if not isinstance(values, dict):
            return values
        if "label" not in values and "items" in values:
            items = values.get("items")
            if isinstance(items, list) and items:
                first = items[0] if isinstance(items[0], dict) else {}
                values["label"] = first.get("label", first.get("title", "Metric"))
                values["value"] = str(first.get("value", ""))
                if not values.get("icon") and first.get("icon"):
                    values["icon"] = first["icon"]
        return values


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

    @model_validator(mode="before")
    @classmethod
    def _normalize_table_data(cls, values: Any) -> Any:
        """Normalize LLM output that sends columns as dicts and rows as dicts.

        The LLM sometimes returns:
          columns: [{"key": "col1", "label": "Col 1"}, ...]
          rows: [{"col1": "val1", "col2": "val2"}, ...]
        instead of:
          columns: ["Col 1", ...]
          rows: [["val1", "val2"], ...]
        """
        if isinstance(values, BaseModel):
            return values
        if not isinstance(values, dict):
            return values
        cols = values.get("columns", [])
        rows = values.get("rows", [])
        # Normalize columns: list of dicts → list of strings
        col_keys: List[str] = []
        if cols and isinstance(cols[0], dict):
            col_keys = [c.get("key", "") for c in cols]
            values["columns"] = [
                c.get("label", c.get("key", str(c))) for c in cols
            ]
        # Normalize rows: list of dicts → list of lists (ordered by column keys)
        if rows and isinstance(rows[0], dict):
            if not col_keys:
                # columns were already strings; use them as keys
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
                pass  # fall back to default INFO
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
        """
        if not isinstance(values, dict):
            return values
        # layout → template alias
        if "layout" in values and "template" not in values:
            values["template"] = values.pop("layout")
        # Normalise blocks
        raw_blocks = values.get("blocks")
        if isinstance(raw_blocks, list):
            # Deserialize any stringified JSON blocks
            parsed_blocks: list = []
            for block in raw_blocks:
                if isinstance(block, str):
                    try:
                        block = json.loads(block)
                    except (json.JSONDecodeError, TypeError):
                        pass
                parsed_blocks.append(block)
            # Expand hero_card items into individual blocks
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
                expanded.append(block)
            values["blocks"] = expanded
        return values


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
