from typing import Any
import base64
from io import BytesIO

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
    from bokeh.plotting import figure
    BOKEH_AVAILABLE = True
except ImportError:
    BOKEH_AVAILABLE = False

try:
    import altair as alt
    ALTAIR_AVAILABLE = True
except ImportError:
    ALTAIR_AVAILABLE = False

try:
    from rich.table import Table as RichTable
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

from .base import (
    BaseRenderer
)

class FoliumRenderer(BaseRenderer):
    """Renderer for Folium maps"""

    def render_terminal(self, obj: folium.Map, **kwargs) -> str:
        """Terminal representation"""
        center = obj.location
        zoom = obj.options.get('zoom', 'auto')
        return f"🗺️  Folium Map (center: {center}, zoom: {zoom})\n[View in HTML/Jupyter mode]"

    def render_html(self, obj: folium.Map, **kwargs) -> str:
        """Embeddable HTML with iframe"""
        width = kwargs.get('width', '100%')
        height = kwargs.get('height', '600px')

        # Get the map HTML
        map_html = obj._repr_html_()

        # Option 1: Direct embed (best for most use cases)
        if kwargs.get('use_iframe', False):
            # Escape quotes for srcdoc
            escaped_html = map_html.replace('"', '&quot;')
            return f'''
            <div style="width: {width}; height: {height};">
                <iframe srcdoc="{escaped_html}"
                        width="100%"
                        height="100%"
                        frameborder="0"
                        style="border: 1px solid #ddd; border-radius: 4px;">
                </iframe>
            </div>
            '''
        else:
            # Option 2: Direct HTML (better for embedding)
            return f'<div style="width: {width}; height: {height};">{map_html}</div>'

    def render_jupyter(self, obj: folium.Map, **kwargs) -> Any:
        """Native Jupyter display"""
        return obj  # Folium maps display natively in Jupyter


class PlotlyRenderer(BaseRenderer):
    """Renderer for Plotly charts"""

    def render_terminal(self, obj: go.Figure, **kwargs) -> str:
        """Terminal representation"""
        return f"📊 Plotly Chart (traces: {len(obj.data)})\n[View in HTML/Jupyter mode]"

    def render_html(self, obj: go.Figure, **kwargs) -> str:
        """Embeddable HTML"""
        include_plotlyjs = kwargs.get('include_plotlyjs', 'cdn')
        config = kwargs.get('config', {'responsive': True})

        # Generate HTML
        html = pio.to_html(
            obj,
            include_plotlyjs=include_plotlyjs,
            config=config,
            div_id=kwargs.get('div_id'),
            full_html=False  # Just the div, not full HTML doc
        )
        return html

    def render_jupyter(self, obj: go.Figure, **kwargs) -> Any:
        """Native Jupyter display"""
        return obj


class MatplotlibRenderer(BaseRenderer):
    """Renderer for Matplotlib figures"""

    def render_terminal(self, obj: mp.figure.Figure, **kwargs) -> str:
        """Terminal representation"""
        return f"📈 Matplotlib Figure\n[View in HTML/Jupyter mode]"

    def render_html(self, obj: mp.figure.Figure, **kwargs) -> str:
        """Convert to base64 embedded image"""
        format = kwargs.get('format', 'png')
        dpi = kwargs.get('dpi', 100)

        buf = BytesIO()
        obj.savefig(buf, format=format, dpi=dpi, bbox_inches='tight')
        buf.seek(0)
        img_base64 = base64.b64encode(buf.read()).decode('utf-8')
        buf.close()

        width = kwargs.get('width', '100%')
        return f'<img src="data:image/{format};base64,{img_base64}" style="width: {width}; max-width: 100%;">'

    def render_jupyter(self, obj: mp.figure.Figure, **kwargs) -> Any:
        """Native Jupyter display"""
        return obj


class DataFrameRenderer(BaseRenderer):
    """Renderer for Pandas DataFrames"""

    def render_terminal(self, obj: pd.DataFrame, **kwargs) -> str:
        """Rich table for terminal"""
        max_rows = kwargs.get('max_rows', 10)

        if not RICH_AVAILABLE:
            return str(obj.head(max_rows))

        # Create Rich table
        table = RichTable(
            title=f"DataFrame ({len(obj)} rows × {len(obj.columns)} columns)"
        )

        # Add columns
        for col in obj.columns:
            table.add_column(str(col), style="cyan")

        # Add rows (limited)
        for _, row in obj.head(max_rows).iterrows():
            table.add_row(*[str(val) for val in row])

        if len(obj) > max_rows:
            table.add_row(*["..." for _ in obj.columns])

        return table

    def render_html(self, obj: pd.DataFrame, **kwargs) -> str:
        """Styled HTML table"""
        max_rows = kwargs.get('max_rows', 100)

        # Limit rows
        df_display = obj.head(max_rows) if len(obj) > max_rows else obj

        # Generate styled HTML
        styler = df_display.style.set_table_attributes(
            'class="dataframe" style="border-collapse: collapse; width: 100%;"'
        ).set_properties(**{
            'text-align': 'left',
            'padding': '8px',
            'border': '1px solid #ddd'
        }).set_table_styles([
            {'selector': 'thead th', 'props': [
                ('background-color', '#f0f0f0'),
                ('font-weight', 'bold'),
                ('border', '1px solid #ddd')
            ]},
            {'selector': 'tbody tr:nth-child(even)', 'props': [
                ('background-color', '#f9f9f9')
            ]}
        ])

        html = styler.to_html()

        if len(obj) > max_rows:
            html += f'<p style="color: #666; font-style: italic;">Showing {max_rows} of {len(obj)} rows</p>'

        return html

    def render_jupyter(self, obj: pd.DataFrame, **kwargs) -> Any:
        """Native Jupyter display with styling"""
        max_rows = kwargs.get('max_rows', 100)
        return obj.head(max_rows) if len(obj) > max_rows else obj


class AltairRenderer(BaseRenderer):
    """Renderer for Altair charts"""

    def render_terminal(self, obj: alt.Chart, **kwargs) -> str:
        return "📊 Altair Chart\n[View in HTML/Jupyter mode]"

    def render_html(self, obj: alt.Chart, **kwargs) -> str:
        """Embeddable Vega-Lite JSON"""
        return obj.to_html()

    def render_jupyter(self, obj: alt.Chart, **kwargs) -> Any:
        return obj


class HTMLWidgetRenderer(BaseRenderer):
    """Renderer for generic HTML widgets"""

    def render_terminal(self, obj: Any, **kwargs) -> str:
        return "🌐 HTML Widget\n[View in HTML/Jupyter mode]"

    def render_html(self, obj: Any, **kwargs) -> str:
        return obj._repr_html_()

    def render_jupyter(self, obj: Any, **kwargs) -> Any:
        return obj
