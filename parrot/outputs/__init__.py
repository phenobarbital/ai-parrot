"""
Output formatters for AI-Parrot using Rich (terminal) and Panel (HTML) with Jupyter support.
- Interactive widgets and controls
- Rich markdown rendering
- Collapsible sections
- Inline visualizations
- Syntax highlighting
- Tables and structured data

Automatically detects and renders:
- Folium maps
- Plotly charts
- Matplotlib figures
- DataFrames
- Bokeh plots
- Altair charts
- Panel dashboards
- HTML widgets
- Images

Each output type is rendered appropriately based on the output mode (Terminal, HTML, Jupyter).
HTML mode generates embeddable widgets for integration with Streamlit, Gradio, web apps, etc.
"""
from ..models.outputs import OutputMode, OutputType
from .formatter import OutputFormatter


__all__ = (
    'OutputMode',
    'OutputType',
    'OutputFormatter',
)
