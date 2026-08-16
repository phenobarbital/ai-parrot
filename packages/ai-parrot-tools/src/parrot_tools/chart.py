"""
Chart Generation Tool for AI-Parrot Agents.

Generates visualizations (bar charts, line charts, pie charts, etc.)
from structured data returned by agents.

Supports multiple backends:
- altair (default): Vega-Lite JSON output — the frontend renders it
  natively (no extra deps); PNG/SVG export is available via the optional
  `vl-convert-python` dependency (falls back to JSON if not installed).
- plotly (interactive HTML exports)

Example usage:
    from parrot_tools.chart import ChartTool

    chart_tool = ChartTool(backend="altair")
    agent.add_tool(chart_tool)

    # Agent can then use:
    # generate_chart(chart_type="bar", title="Revenue", data={...})
"""
from typing import Dict, Any, List, Optional, Literal
from pathlib import Path
from dataclasses import dataclass, field
import tempfile
import contextlib
import json
import uuid
import base64
from enum import Enum
from pydantic import BaseModel, Field, model_validator
from datamodel.parsers.json import json_decoder  # pylint: disable=E0611 # noqa


try:
    from navconfig.logging import logging
except ImportError:
    import logging

from .abstract import AbstractTool, ToolResult
from .decorators import tool_schema


class ChartType(str, Enum):
    """Supported chart types."""
    BAR = "bar"
    LINE = "line"
    PIE = "pie"
    SCATTER = "scatter"
    HEATMAP = "heatmap"
    HISTOGRAM = "histogram"
    AREA = "area"
    HORIZONTAL_BAR = "horizontal_bar"


class ChartFormat(str, Enum):
    """Output format for charts."""
    PNG = "png"  # altair: requires vl-convert-python; falls back to VEGALITE_JSON
    SVG = "svg"  # altair: requires vl-convert-python; falls back to VEGALITE_JSON
    PDF = "pdf"
    HTML = "html"  # For plotly interactive
    VEGALITE_JSON = "vegalite"  # altair default — pure-JSON Vega-Lite spec


@dataclass
class ChartStyle:
    """Visual styling configuration for charts."""
    # Colors
    primary_color: str = "#4A90D9"
    secondary_colors: List[str] = field(default_factory=lambda: [
        "#50C878", "#FFB347", "#FF6B6B", "#9B59B6",
        "#3498DB", "#1ABC9C", "#F39C12", "#E74C3C"
    ])
    background_color: str = "#FFFFFF"
    text_color: str = "#333333"
    grid_color: str = "#E0E0E0"

    # Typography
    title_font_size: int = 14
    label_font_size: int = 11
    tick_font_size: int = 10
    font_family: str = "sans-serif"

    # Layout
    figure_width: float = 10.0
    figure_height: float = 6.0
    dpi: int = 150

    # Grid
    show_grid: bool = True
    grid_alpha: float = 0.3


class GenerateChartInput(BaseModel):
    """Input schema for chart generation."""
    chart_type: str = Field(
        description="Type of chart: bar, line, pie, scatter, histogram, area, horizontal_bar, heatmap"
    )
    title: str = Field(
        description="Title of the chart"
    )
    data: Any = Field(
        description="""Data for the chart. Can be a dict or JSON string. Format depends on chart type:
        - bar/line/area: {"categories": ["A","B"], "values": [10,20]} or {"x": [...], "y": [...]}
        - pie: {"labels": ["A","B"], "values": [30,70]}
        - scatter: {"x": [1,2,3], "y": [4,5,6]}
        - histogram: {"values": [1,2,2,3,3,3,4]}
        - heatmap: {"data": [[1,2],[3,4]], "x_labels": [...], "y_labels": [...]}
        """
    )
    x_label: Optional[str] = Field(
        default=None,
        description="Label for X axis"
    )
    y_label: Optional[str] = Field(
        default=None,
        description="Label for Y axis"
    )
    legend_title: Optional[str] = Field(
        default=None,
        description="Title for the legend (if applicable)"
    )
    output_format: str = Field(
        default="png",
        description=(
            "Output format: vegalite (default Vega-Lite JSON spec, no extra "
            "deps — recommended when the frontend renders charts natively), "
            "png/svg (recommended for Teams/Telegram; requires the optional "
            "vl-convert-python dependency, falls back to vegalite if absent), "
            "html (plotly backend only)"
        )
    )
    style: Optional[str] = Field(
        default="default",
        description="Visual style: default, dark, minimal, corporate"
    )

    @model_validator(mode='before')
    @classmethod
    def parse_data_string(cls, values):
        """Parse data if it's a JSON string."""
        if isinstance(values, dict) and 'data' in values:
            data = values.get('data')
            if isinstance(data, str):
                with contextlib.suppress(Exception):
                    values['data'] = json_decoder(data)
        return values


class ChartTool(AbstractTool):
    """
    Tool for generating charts from structured data.

    Designed to work with integration wrappers (Teams, Telegram) that can
    send images inline in messages.

    Attributes:
        backend: Chart generation library (altair, plotly)
        output_dir: Directory for saving generated charts
        style: Default visual styling
        auto_cleanup: Whether to cleanup old charts
    """

    name: str = "generate_chart"
    description: str = """
    Generates data visualizations (charts) from structured data.

    Use this tool when the user asks for visual representations of data,
    such as bar charts, line graphs, pie charts, etc.

    The tool returns the path to the generated image which will be
    automatically displayed in the chat.

    Supported chart types:
    - bar: Vertical bar chart for comparing categories
    - horizontal_bar: Horizontal bar chart
    - line: Line chart for trends over time
    - area: Filled area chart
    - pie: Pie chart for proportions
    - scatter: Scatter plot for relationships
    - histogram: Distribution of values
    - heatmap: 2D data matrix visualization
    """

    args_schema = GenerateChartInput

    def __init__(
        self,
        backend: Literal["altair", "plotly"] = "altair",
        output_dir: Optional[Path] = None,
        style: Optional[ChartStyle] = None,
        auto_cleanup: bool = True,
        cleanup_age_hours: int = 24,
        **kwargs
    ):
        super().__init__(**kwargs)
        if backend not in ("altair", "plotly"):
            raise ValueError(
                f"Unsupported backend: {backend!r}. ChartTool supports "
                "'altair' (default) or 'plotly'."
            )
        self.backend = backend
        self.output_dir = output_dir or Path(tempfile.gettempdir()) / "parrot_charts"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.style = style or ChartStyle()
        self.auto_cleanup = auto_cleanup
        self.cleanup_age_hours = cleanup_age_hours
        self.logger = logging.getLogger("ChartTool")

    @tool_schema(GenerateChartInput)
    async def _execute(
        self,
        chart_type: str,
        title: str,
        data: Dict[str, Any],
        x_label: Optional[str] = None,
        y_label: Optional[str] = None,
        legend_title: Optional[str] = None,
        output_format: str = "png",
        style: str = "default",
        **kwargs
    ) -> ToolResult:
        """Generate a chart from the provided data."""
        try:
            # Parse data if it's a JSON string (LLMs sometimes pass strings)
            if isinstance(data, str):
                try:
                    data = json_decoder(data)
                except Exception as e:
                    return ToolResult(
                        success=False,
                        status="error",
                        result=None,
                        error=f"Invalid JSON in data parameter: {e}"
                    )

            # Validate chart type
            try:
                chart_type_enum = ChartType(chart_type.lower())
            except ValueError:
                return ToolResult(
                    success=False,
                    status="error",
                    result=None,
                    error=f"Unsupported chart type: {chart_type}. "
                          f"Supported: {[t.value for t in ChartType]}"
                )

            # Validate format
            try:
                format_enum = ChartFormat(output_format.lower())
            except ValueError:
                format_enum = ChartFormat.PNG

            # Auto cleanup old charts
            if self.auto_cleanup:
                await self._cleanup_old_charts()


            # Generate chart based on backend
            if self.backend == "altair":
                path = await self._generate_altair(
                    chart_type_enum, title, data,
                    x_label, y_label, legend_title,
                    format_enum, style
                )
            elif self.backend == "plotly":
                path = await self._generate_plotly(
                    chart_type_enum, title, data,
                    x_label, y_label, legend_title,
                    format_enum, style
                )
            else:
                return ToolResult(
                    success=False,
                    status="error",
                    result=None,
                    error=f"Backend '{self.backend}' not supported"
                )

            self.logger.debug(
                f"Generated chart: {path}"
            )

            # Read image and encode as base64 for inline rendering.
            # Check the ACTUAL output suffix, not just the requested
            # format_enum: the altair backend may have fallen back to a
            # Vega-Lite JSON file (e.g. vl-convert-python not installed)
            # when PNG/SVG was requested (see _generate_altair).
            image_base64 = None
            if format_enum in (ChartFormat.PNG, ChartFormat.SVG) and path.suffix.lstrip(".") == format_enum.value:
                try:
                    with open(path, 'rb') as f:
                        image_bytes = f.read()
                    image_base64 = base64.b64encode(image_bytes).decode('utf-8')
                except Exception as e:
                    self.logger.warning(
                        f"Could not encode image to base64: {e}"
                    )

            return ToolResult(
                success=True,
                status="success",
                result=f"Chart '{title}' generated successfully at {path}",
                images=[path],
                metadata={
                    "chart_path": str(path),
                    # Actual output suffix — may differ from the requested
                    # format_enum when the altair backend falls back to
                    # Vega-Lite JSON (see _generate_altair).
                    "format": path.suffix.lstrip("."),
                    "title": title,
                    "chart_type": chart_type,
                    "image_base64": image_base64,
                    "images": [str(path)]
                }
            )

        except Exception as e:
            self.logger.error(
                f"Chart generation failed: {e}", exc_info=True
            )
            return ToolResult(
                success=False,
                status="error",
                result=None,
                error=f"Failed to generate chart: {str(e)}"
            )

    def _data_to_dataframe(self, chart_type: ChartType, data: Dict[str, Any]):
        """Convert the tool's flexible input dict shape into a DataFrame altair can encode.

        Mirrors the same key-name fallbacks (``categories``/``labels``/``x``,
        ``values``/``y``, ``series_labels``, ``data``/``matrix``, ``x_labels``,
        ``y_labels``) the plotly backend already accepts, for a consistent
        input contract across backends.
        """
        import pandas as pd

        if chart_type in (ChartType.BAR, ChartType.HORIZONTAL_BAR):
            categories = data.get("categories", data.get("labels", data.get("x", [])))
            values = data.get("values", data.get("y", []))
            return pd.DataFrame({"category": categories, "value": values})

        if chart_type in (ChartType.LINE, ChartType.AREA):
            y = data.get("y", data.get("values", []))
            x = data.get("x", list(range(len(y))))
            if y and isinstance(y[0], list):
                labels = data.get("series_labels", [f"Series {i + 1}" for i in range(len(y))])
                frames = [
                    pd.DataFrame({"x": x, "y": series, "series": label})
                    for series, label in zip(y, labels)
                ]
                return pd.concat(frames, ignore_index=True)
            return pd.DataFrame({"x": x, "y": y})

        if chart_type == ChartType.PIE:
            labels = data.get("labels", [])
            values = data.get("values", [])
            return pd.DataFrame({"label": labels, "value": values})

        if chart_type == ChartType.SCATTER:
            x = data.get("x", [])
            y = data.get("y", [])
            return pd.DataFrame({"x": x, "y": y})

        if chart_type == ChartType.HISTOGRAM:
            values = data.get("values", [])
            return pd.DataFrame({"value": values})

        if chart_type == ChartType.HEATMAP:
            matrix = data.get("data", data.get("matrix", [[]]))
            x_labels = data.get("x_labels") or [f"X{i}" for i in range(len(matrix[0]) if matrix else 0)]
            y_labels = data.get("y_labels") or [f"Y{i}" for i in range(len(matrix))]
            rows = [
                {"x": x_labels[xi], "y": y_labels[yi], "value": val}
                for yi, row in enumerate(matrix)
                for xi, val in enumerate(row)
            ]
            return pd.DataFrame(rows)

        raise ValueError(f"Unsupported chart type for altair backend: {chart_type}")

    def _build_altair_chart(
        self,
        chart_type: ChartType,
        df,
        x_label: Optional[str],
        y_label: Optional[str],
        legend_title: Optional[str],
    ):
        """Build the altair ``Chart`` object for ``chart_type`` (see spec's Chart Type Mapping)."""
        import altair as alt

        color_scale = alt.Scale(range=[self.style.primary_color, *self.style.secondary_colors])

        if chart_type == ChartType.BAR:
            return alt.Chart(df).mark_bar(color=self.style.primary_color).encode(
                x=alt.X("category:N", title=x_label or "category", sort=None),
                y=alt.Y("value:Q", title=y_label or "value"),
            )

        if chart_type == ChartType.HORIZONTAL_BAR:
            return alt.Chart(df).mark_bar(color=self.style.primary_color).encode(
                y=alt.Y("category:N", title=y_label or "category", sort=None),
                x=alt.X("value:Q", title=x_label or "value"),
            )

        if chart_type == ChartType.LINE:
            chart = alt.Chart(df).mark_line(point=True)
            if "series" in df.columns:
                return chart.encode(
                    x=alt.X("x:Q", title=x_label),
                    y=alt.Y("y:Q", title=y_label),
                    color=alt.Color("series:N", scale=color_scale, legend=alt.Legend(title=legend_title)),
                )
            return chart.encode(
                x=alt.X("x:Q", title=x_label),
                y=alt.Y("y:Q", title=y_label),
                color=alt.value(self.style.primary_color),
            )

        if chart_type == ChartType.AREA:
            return alt.Chart(df).mark_area(color=self.style.primary_color, opacity=0.6).encode(
                x=alt.X("x:Q", title=x_label),
                y=alt.Y("y:Q", title=y_label),
            )

        if chart_type == ChartType.PIE:
            return alt.Chart(df).mark_arc().encode(
                theta=alt.Theta("value:Q"),
                color=alt.Color("label:N", scale=color_scale, legend=alt.Legend(title=legend_title)),
            )

        if chart_type == ChartType.SCATTER:
            return alt.Chart(df).mark_circle(size=80, color=self.style.primary_color, opacity=0.7).encode(
                x=alt.X("x:Q", title=x_label),
                y=alt.Y("y:Q", title=y_label),
            )

        if chart_type == ChartType.HISTOGRAM:
            return alt.Chart(df).mark_bar(color=self.style.primary_color).encode(
                x=alt.X("value:Q", bin=True, title=x_label or "value"),
                y=alt.Y("count()", title=y_label or "count"),
            )

        if chart_type == ChartType.HEATMAP:
            return alt.Chart(df).mark_rect().encode(
                x=alt.X("x:N", title=x_label, sort=None),
                y=alt.Y("y:N", title=y_label, sort=None),
                color=alt.Color("value:Q", scale=alt.Scale(scheme="yelloworangered")),
            )

        raise ValueError(f"Unsupported chart type for altair backend: {chart_type}")

    async def _generate_altair(
        self,
        chart_type: ChartType,
        title: str,
        data: Dict[str, Any],
        x_label: Optional[str],
        y_label: Optional[str],
        legend_title: Optional[str],
        output_format: ChartFormat,
        style_name: str
    ) -> Path:
        """Generate chart using altair (Vega-Lite JSON spec by default).

        PNG/SVG export requires the optional ``vl-convert-python`` dependency
        (``ai-parrot-tools[charts]``) — falls back to a Vega-Lite JSON spec
        when it is not installed (spec Key Constraint).
        """
        df = self._data_to_dataframe(chart_type, data)
        chart = self._build_altair_chart(chart_type, df, x_label, y_label, legend_title)

        chart = chart.properties(
            title=title,
            width=int(self.style.figure_width * 80),
            height=int(self.style.figure_height * 80),
        )
        if style_name == "dark":
            chart = (
                chart.configure(background="#1a1a2e")
                .configure_title(color="#FFFFFF")
                .configure_axis(labelColor="#FFFFFF", titleColor="#FFFFFF")
            )

        filename = f"chart_{uuid.uuid4().hex[:8]}"

        if output_format == ChartFormat.VEGALITE_JSON:
            output_path = self.output_dir / f"{filename}.json"
            output_path.write_text(json.dumps(chart.to_dict(), indent=2))
            return output_path

        if output_format in (ChartFormat.PNG, ChartFormat.SVG):
            output_path = self.output_dir / f"{filename}.{output_format.value}"
            try:
                chart.save(str(output_path))
            except (ImportError, ValueError) as exc:
                # altair raises ImportError OR a ValueError whose message
                # names vl-convert-python (see
                # altair.utils.mimebundle._validate_normalize_engine) when
                # the optional PNG/SVG export engine isn't installed. Only
                # that specific case falls back — re-raise anything else so
                # real chart-spec errors aren't masked.
                if "vl-convert" not in str(exc) and "vl_convert" not in str(exc):
                    raise
                self.logger.warning(
                    "vl-convert-python not available (%s) — falling back to "
                    "Vega-Lite JSON for chart '%s'. Install "
                    "ai-parrot-tools[charts] for PNG/SVG export.",
                    exc, title,
                )
                output_path = self.output_dir / f"{filename}.json"
                output_path.write_text(json.dumps(chart.to_dict(), indent=2))
            return output_path

        # HTML (and anything else not natively supported by altair without
        # vl-convert, e.g. PDF) — pure-python, no extra deps.
        output_path = self.output_dir / f"{filename}.html"
        chart.save(str(output_path), format="html")
        return output_path

    async def _generate_plotly(
        self,
        chart_type: ChartType,
        title: str,
        data: Dict[str, Any],
        x_label: Optional[str],
        y_label: Optional[str],
        legend_title: Optional[str],
        output_format: ChartFormat,
        style_name: str
    ) -> Path:
        """Generate chart using plotly."""
        import plotly.graph_objects as go

        fig = None

        if chart_type == ChartType.BAR:
            categories = data.get("categories", data.get("labels", data.get("x", [])))
            values = data.get("values", data.get("y", []))
            fig = go.Figure(data=[go.Bar(x=categories, y=values)])

        elif chart_type == ChartType.LINE:
            x = data.get("x", list(range(len(data.get("y", [])))))
            y = data.get("y", data.get("values", []))
            fig = go.Figure(data=[go.Scatter(x=x, y=y, mode='lines+markers')])

        elif chart_type == ChartType.PIE:
            labels = data.get("labels", [])
            values = data.get("values", [])
            fig = go.Figure(data=[go.Pie(labels=labels, values=values)])

        elif chart_type == ChartType.SCATTER:
            x = data.get("x", [])
            y = data.get("y", [])
            fig = go.Figure(data=[go.Scatter(x=x, y=y, mode='markers')])

        elif chart_type == ChartType.HISTOGRAM:
            values = data.get("values", [])
            fig = go.Figure(data=[go.Histogram(x=values)])

        elif chart_type == ChartType.AREA:
            x = data.get("x", list(range(len(data.get("y", [])))))
            y = data.get("y", data.get("values", []))
            fig = go.Figure(data=[go.Scatter(x=x, y=y, fill='tozeroy', mode='lines')])

        elif chart_type == ChartType.HORIZONTAL_BAR:
            categories = data.get("categories", data.get("labels", data.get("y", [])))
            values = data.get("values", data.get("x", []))
            fig = go.Figure(data=[go.Bar(y=categories, x=values, orientation='h')])

        elif chart_type == ChartType.HEATMAP:
            matrix = data.get("data", data.get("matrix", [[]]))
            x_labels = data.get("x_labels", None)
            y_labels = data.get("y_labels", None)
            fig = go.Figure(data=[go.Heatmap(z=matrix, x=x_labels, y=y_labels)])

        if fig is None:
            # Fallback to bar chart
            categories = data.get("categories", data.get("labels", data.get("x", [])))
            values = data.get("values", data.get("y", []))
            fig = go.Figure(data=[go.Bar(x=categories, y=values)])

        # Update layout
        fig.update_layout(
            title=dict(text=title, font=dict(size=self.style.title_font_size)),
            xaxis_title=x_label,
            yaxis_title=y_label,
            template="plotly_white" if style_name != "dark" else "plotly_dark"
        )

        # Save
        filename = f"chart_{uuid.uuid4().hex[:8]}.{output_format.value}"
        output_path = self.output_dir / filename

        if output_format == ChartFormat.HTML:
            fig.write_html(str(output_path))
        else:
            fig.write_image(str(output_path), width=int(self.style.figure_width * 100),
                          height=int(self.style.figure_height * 100))

        return output_path

    def _get_colors(self, n: int) -> List[str]:
        """Get n colors from the palette."""
        if n == 1:
            return [self.style.primary_color]

        colors = [self.style.primary_color] + self.style.secondary_colors
        if n <= len(colors):
            return colors[:n]

        # Repeat colors if needed
        return (colors * (n // len(colors) + 1))[:n]

    async def _cleanup_old_charts(self):
        """Remove charts older than cleanup_age_hours."""
        import time

        try:
            cutoff = time.time() - (self.cleanup_age_hours * 3600)

            for file_path in self.output_dir.glob("chart_*"):
                if file_path.stat().st_mtime < cutoff:
                    file_path.unlink()
                    self.logger.debug(f"Cleaned up old chart: {file_path.name}")

        except Exception as e:
            self.logger.warning(f"Chart cleanup failed: {e}")


# Convenience function for direct usage
async def generate_chart(
    chart_type: str,
    title: str,
    data: Dict[str, Any],
    **kwargs
) -> Path:
    """
    Convenience function to generate a chart without instantiating the tool.

    Args:
        chart_type: Type of chart (bar, line, pie, etc.)
        title: Chart title
        data: Chart data
        **kwargs: Additional options (x_label, y_label, output_format, etc.)

    Returns:
        Path to the generated chart image
    """
    tool = ChartTool()
    result = await tool._execute(chart_type=chart_type, title=title, data=data, **kwargs)

    if not result.success:
        raise ValueError(result.error)

    return result.images[0] if result.images else Path(result.metadata.get('chart_path', ''))
