"""
Chart Generation Tool for AI-Parrot Agents.

Generates visualizations (bar charts, line charts, pie charts, etc.)
from structured data returned by agents.

Supports multiple backends:
- matplotlib (default, most compatible)
- plotly (interactive HTML exports)

Example usage:
    from parrot.tools.chart import ChartTool

    chart_tool = ChartTool(backend="matplotlib")
    agent.add_tool(chart_tool)

    # Agent can then use:
    # generate_chart(chart_type="bar", title="Revenue", data={...})
"""
from typing import Dict, Any, List, Optional, Literal
from pathlib import Path
from dataclasses import dataclass, field
import tempfile
import contextlib
import uuid
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
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
    PNG = "png"
    SVG = "svg"
    PDF = "pdf"
    HTML = "html"  # For plotly interactive


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
        description="Output format: png (recommended for Teams/Telegram), svg, pdf"
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
        backend: Chart generation library (matplotlib, plotly)
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

    # Thread pool for blocking matplotlib operations
    _executor: ThreadPoolExecutor = None

    def __init__(
        self,
        backend: Literal["matplotlib", "plotly"] = "matplotlib",
        output_dir: Optional[Path] = None,
        style: Optional[ChartStyle] = None,
        auto_cleanup: bool = True,
        cleanup_age_hours: int = 24,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.backend = backend
        self.output_dir = output_dir or Path(tempfile.gettempdir()) / "parrot_charts"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.style = style or ChartStyle()
        self.auto_cleanup = auto_cleanup
        self.cleanup_age_hours = cleanup_age_hours
        self.logger = logging.getLogger("ChartTool")

        # Initialize executor for thread-safe matplotlib
        if ChartTool._executor is None:
            ChartTool._executor = ThreadPoolExecutor(max_workers=2)

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
            if self.backend == "matplotlib":
                path = await self._generate_matplotlib(
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

            # Read image and encode as base64 for inline rendering
            image_base64 = None
            if format_enum in (ChartFormat.PNG, ChartFormat.SVG):
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
                    "format": format_enum.value,
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

    async def _generate_matplotlib(
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
        """Generate chart using matplotlib (thread-safe)."""
        # Run matplotlib in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor,
            self._matplotlib_render,
            chart_type, title, data, x_label, y_label,
            legend_title, output_format, style_name
        )

    def _matplotlib_render(
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
        """Synchronous matplotlib rendering (runs in thread pool)."""
        import matplotlib
        matplotlib.use('Agg')  # Non-GUI backend
        import matplotlib.pyplot as plt
        import numpy as np

        # Apply style
        style_map = {
            "default": "seaborn-v0_8-whitegrid",
            "dark": "dark_background",
            "minimal": "seaborn-v0_8-white",
            "corporate": "seaborn-v0_8-paper"
        }
        try:
            plt.style.use(style_map.get(style_name, "seaborn-v0_8-whitegrid"))
        except OSError:
            # Fallback if style not available
            plt.style.use('default')

        # Create figure
        fig, ax = plt.subplots(
            figsize=(self.style.figure_width, self.style.figure_height)
        )

        # Extract data based on chart type
        if chart_type == ChartType.BAR:
            categories = data.get("categories", data.get("labels", data.get("x", [])))
            values = data.get("values", data.get("y", []))
            colors = self._get_colors(len(values))
            ax.bar(categories, values, color=colors)

        elif chart_type == ChartType.HORIZONTAL_BAR:
            categories = data.get("categories", data.get("labels", data.get("y", [])))
            values = data.get("values", data.get("x", []))
            colors = self._get_colors(len(values))
            ax.barh(categories, values, color=colors)

        elif chart_type == ChartType.LINE:
            x = data.get("x", list(range(len(data.get("y", data.get("values", []))))))
            y = data.get("y", data.get("values", []))

            # Support multiple series
            if isinstance(y[0], list) if y else False:
                labels = data.get("series_labels", [f"Series {i+1}" for i in range(len(y))])
                colors = self._get_colors(len(y))
                for i, (series, label, color) in enumerate(zip(y, labels, colors)):
                    ax.plot(x, series, marker='o', label=label, color=color, linewidth=2)
                ax.legend(title=legend_title)
            else:
                ax.plot(x, y, marker='o', color=self.style.primary_color, linewidth=2)

        elif chart_type == ChartType.AREA:
            x = data.get("x", list(range(len(data.get("y", data.get("values", []))))))
            y = data.get("y", data.get("values", []))
            ax.fill_between(x, y, alpha=0.4, color=self.style.primary_color)
            ax.plot(x, y, color=self.style.primary_color, linewidth=2)

        elif chart_type == ChartType.PIE:
            labels = data.get("labels", [])
            values = data.get("values", [])
            colors = self._get_colors(len(values))
            explode = data.get("explode", [0.02] * len(values))

            wedges, texts, autotexts = ax.pie(
                values,
                labels=labels,
                colors=colors,
                autopct='%1.1f%%',
                explode=explode,
                startangle=90
            )
            for autotext in autotexts:
                autotext.set_fontsize(self.style.tick_font_size)

        elif chart_type == ChartType.SCATTER:
            x = data.get("x", [])
            y = data.get("y", [])
            sizes = data.get("sizes", 50)
            colors = data.get("colors", self.style.primary_color)
            ax.scatter(x, y, s=sizes, c=colors, alpha=0.7)

        elif chart_type == ChartType.HISTOGRAM:
            values = data.get("values", [])
            bins = data.get("bins", "auto")
            ax.hist(values, bins=bins, color=self.style.primary_color,
                   edgecolor='white', alpha=0.7)

        elif chart_type == ChartType.HEATMAP:
            matrix = np.array(data.get("data", data.get("matrix", [[]])))
            x_labels = data.get("x_labels", [])
            y_labels = data.get("y_labels", [])

            im = ax.imshow(matrix, cmap='YlOrRd', aspect='auto')
            fig.colorbar(im, ax=ax)

            if x_labels:
                ax.set_xticks(range(len(x_labels)))
                ax.set_xticklabels(x_labels, rotation=45, ha='right')
            if y_labels:
                ax.set_yticks(range(len(y_labels)))
                ax.set_yticklabels(y_labels)

        # Set labels and title
        ax.set_title(title, fontsize=self.style.title_font_size, fontweight='bold', pad=15)

        if x_label and chart_type != ChartType.PIE:
            ax.set_xlabel(x_label, fontsize=self.style.label_font_size)
        if y_label and chart_type != ChartType.PIE:
            ax.set_ylabel(y_label, fontsize=self.style.label_font_size)

        # Grid
        if self.style.show_grid and chart_type not in (ChartType.PIE, ChartType.HEATMAP):
            ax.grid(True, alpha=self.style.grid_alpha, color=self.style.grid_color)

        # Generate filename
        filename = f"chart_{uuid.uuid4().hex[:8]}.{output_format.value}"
        output_path = self.output_dir / filename

        plt.tight_layout()
        plt.savefig(
            output_path,
            format=output_format.value,
            dpi=self.style.dpi,
            bbox_inches='tight',
            facecolor=self.style.background_color
        )
        plt.close(fig)

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
