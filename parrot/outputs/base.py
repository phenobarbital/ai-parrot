
from typing import Any, List, Optional, Dict
from enum import Enum
from dataclasses import dataclass

try:
    import panel as pn
    PANEL_AVAILABLE = True
except ImportError:
    PANEL_AVAILABLE = False

# Visualization library imports
try:
    import folium
    FOLIUM_AVAILABLE = True
except ImportError:
    FOLIUM_AVAILABLE = False

try:
    import plotly.graph_objects as go
    import plotly.io as pio
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

try:
    import matplotlib as mp
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

try:
    import bokeh as bk
    BOKEH_AVAILABLE = True
except ImportError:
    BOKEH_AVAILABLE = False

try:
    import altair as alt
    ALTAIR_AVAILABLE = True
except ImportError:
    ALTAIR_AVAILABLE = False


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
    DEFAULT = "default"
    TERMINAL = "terminal"
    HTML = "html"
    JUPYTER = "jupyter"
    NOTEBOOK = "notebook"
    JSON = "json"


@dataclass
class RenderableOutput:
    """Container for a renderable output with metadata"""
    obj: Any
    output_type: OutputType
    title: Optional[str] = None
    description: Optional[str] = None
    metadata: Optional[Dict] = None


class OutputDetector:
    """Detects the type of output object"""

    @staticmethod
    def detect(obj: Any) -> OutputType:
        """Detect the output type of an object"""

        # Folium Map
        if FOLIUM_AVAILABLE and isinstance(obj, folium.Map):
            return OutputType.FOLIUM_MAP

        # Plotly Figure
        if PLOTLY_AVAILABLE and isinstance(obj, (go.Figure, dict)):
            if isinstance(obj, dict) and 'data' in obj and 'layout' in obj:
                return OutputType.PLOTLY_CHART
            elif isinstance(obj, go.Figure):
                return OutputType.PLOTLY_CHART

        # Matplotlib Figure
        if MATPLOTLIB_AVAILABLE and isinstance(obj, mp.figure.Figure):
            return OutputType.MATPLOTLIB_FIGURE

        # DataFrame
        if PANDAS_AVAILABLE and isinstance(obj, pd.DataFrame):
            return OutputType.DATAFRAME

        # Bokeh Plot
        if BOKEH_AVAILABLE and hasattr(obj, 'output_backend'):
            return OutputType.BOKEH_PLOT

        # Altair Chart
        if ALTAIR_AVAILABLE and isinstance(obj, alt.Chart):
            return OutputType.ALTAIR_CHART

        # Panel Dashboard
        if PANEL_AVAILABLE and isinstance(obj, (pn.layout.Panel, pn.pane.PaneBase)):
            return OutputType.PANEL_DASHBOARD

        # HTML (has _repr_html_)
        if hasattr(obj, '_repr_html_'):
            return OutputType.HTML_WIDGET

        # Image (PIL, bytes)
        if hasattr(obj, 'save') and hasattr(obj, 'format'):  # PIL Image
            return OutputType.IMAGE

        # Check for markdown indicators
        if isinstance(obj, str):
            if any(marker in obj for marker in ['#', '```', '**', '*', '-', '>']):
                return OutputType.MARKDOWN
            return OutputType.TEXT

        # JSON-like
        if isinstance(obj, (dict, list)):
            return OutputType.JSON_DATA

        # Default to text
        return OutputType.TEXT

    @staticmethod
    def detect_multiple(obj: Any) -> Optional[List[RenderableOutput]]:
        """
        Detect if object contains renderable visualizations.

        Returns:
            List of RenderableOutput if visualizations found, None otherwise
        """
        renderables = []

        # Check if it's a container with multiple outputs
        if isinstance(obj, (list, tuple)):
            for item in obj:
                output_type = OutputDetector.detect(item)
                # Only include if it's a visualization type
                if output_type in [
                    OutputType.FOLIUM_MAP,
                    OutputType.PLOTLY_CHART,
                    OutputType.MATPLOTLIB_FIGURE,
                    OutputType.DATAFRAME,
                    OutputType.ALTAIR_CHART,
                    OutputType.BOKEH_PLOT,
                    OutputType.PANEL_DASHBOARD,
                    OutputType.HTML_WIDGET,
                    OutputType.IMAGE
                ]:
                    renderables.append(RenderableOutput(obj=item, output_type=output_type))

        # Check if it's a dict with named outputs
        elif isinstance(obj, dict):
            # Check if this looks like a response dict vs visualization dict
            is_visualization_dict = False

            # Plotly figure dict check
            if 'data' in obj and 'layout' in obj:
                is_visualization_dict = True
                output_type = OutputDetector.detect(obj)
                if output_type != OutputType.TEXT:
                    renderables.append(
                        RenderableOutput(obj=obj, output_type=output_type)
                    )
            else:
                # Check if values are visualizations
                for key, value in obj.items():
                    output_type = OutputDetector.detect(value)
                    if output_type in [
                        OutputType.FOLIUM_MAP,
                        OutputType.PLOTLY_CHART,
                        OutputType.MATPLOTLIB_FIGURE,
                        OutputType.DATAFRAME,
                        OutputType.ALTAIR_CHART,
                        OutputType.BOKEH_PLOT,
                        OutputType.PANEL_DASHBOARD,
                        OutputType.HTML_WIDGET,
                        OutputType.IMAGE
                    ]:
                        is_visualization_dict = True
                        renderables.append(
                            RenderableOutput(
                                obj=value,
                                output_type=output_type,
                                title=str(key)
                            )
                        )

        # Single object - check if it's a visualization type
        else:
            output_type = OutputDetector.detect(obj)
            if output_type in [
                OutputType.FOLIUM_MAP,
                OutputType.PLOTLY_CHART,
                OutputType.MATPLOTLIB_FIGURE,
                OutputType.DATAFRAME,
                OutputType.ALTAIR_CHART,
                OutputType.BOKEH_PLOT,
                OutputType.PANEL_DASHBOARD,
                OutputType.HTML_WIDGET,
                OutputType.IMAGE
            ]:
                renderables.append(RenderableOutput(obj=obj, output_type=output_type))

        # Return None if no visualizations found (just text/markdown)
        return renderables if renderables else None


class BaseRenderer:
    """Base class for output renderers"""

    def render_terminal(self, obj: Any, **kwargs) -> str:
        """Render for terminal display"""
        raise NotImplementedError

    def render_html(self, obj: Any, **kwargs) -> str:
        """Render as embeddable HTML"""
        raise NotImplementedError

    def render_jupyter(self, obj: Any, **kwargs) -> Any:
        """Render for Jupyter notebook"""
        raise NotImplementedError
