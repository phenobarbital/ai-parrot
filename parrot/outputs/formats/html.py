from typing import Any, List, Tuple, Optional
import tempfile
import os
from . import register_renderer
from .base import BaseRenderer
from ...models.outputs import OutputMode

try:
    import panel as pn
    from panel.pane import Markdown as PanelMarkdown
    from panel.layout import Column
    pn.extension('tabulator')
    PANEL_AVAILABLE = True
except ImportError:
    PANEL_AVAILABLE = False


@register_renderer(OutputMode.HTML)
class HTMLRenderer(BaseRenderer):
    """Renderer for HTML output using Panel or simple HTML fallback"""

    async def render(
        self,
        response: Any,
        **kwargs,
    ) -> Tuple[Any, Optional[str]]:
        """
        Render response as HTML, returning a primary content object and a wrapped HTML string.
        """
        use_panel = kwargs.get('use_panel', True) and PANEL_AVAILABLE

        if use_panel:
            dashboard = self._render_with_panel(response, **kwargs)
            html_string = self._panel_to_html(dashboard)
            content = dashboard
            wrapped = html_string
        else:
            html_string = self._render_simple_html(response, **kwargs)
            content = html_string
            wrapped = html_string

        return content, wrapped

    def _render_with_panel(self, response: Any, **kwargs) -> Any:
        """
        Format output as an interactive Panel dashboard.
        """
        components = self._build_panel_components(response, **kwargs)
        return Column(*components, sizing_mode='stretch_width', styles={'background': '#ffffff', 'padding': '20px'})

    def _build_panel_components(self, response: Any, **kwargs) -> list:
        show_metadata = kwargs.get('show_metadata', True)
        show_sources = kwargs.get('show_sources', True)
        show_tools = kwargs.get('show_tools', False)
        components = []

        if content := self._get_content(response):
            components.extend([
                pn.pane.HTML("<h2>🤖 Response</h2>"),
                PanelMarkdown(
                    content, sizing_mode='stretch_width',
                    styles={'background': '#f0f8ff', 'padding': '20px', 'border-radius': '5px'}
                )
            ])
        if show_tools and hasattr(response, 'tool_calls') and response.tool_calls:
            tools_df = self._create_tools_dataframe(response.tool_calls)
            components.extend([
                pn.pane.HTML("<h3>🔧 Tool Calls</h3>"),
                pn.widgets.Tabulator(tools_df, sizing_mode='stretch_width', theme='modern', show_index=False)
            ])
        if show_metadata:
            metadata_html = self._create_metadata_panel(response)
            components.extend([pn.pane.HTML("<h3>📊 Metadata</h3>"), pn.pane.HTML(metadata_html)])
        if show_sources and hasattr(response, 'source_documents') and response.source_documents:
            sources_df = self._create_sources_dataframe(response.source_documents)
            components.extend([
                pn.pane.HTML("<h3>📄 Sources</h3>"),
                pn.widgets.Tabulator(sources_df, sizing_mode='stretch_width', theme='modern', show_index=False)
            ])
        return components

    def _panel_to_html(self, dashboard: Any) -> str:
        """Convert Panel dashboard to an HTML string."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as tmp:
            tmp_path = tmp.name
        try:
            dashboard.save(tmp_path, embed=True)
            with open(tmp_path, 'r', encoding='utf-8') as f:
                return f.read()
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def _create_tools_dataframe(self, tool_calls: List[Any]):
        import pandas as pd
        return pd.DataFrame([
            {'#': idx, 'Tool Name': getattr(tool, 'name', 'Unknown'), 'Status': getattr(tool, 'status', 'completed')}
            for idx, tool in enumerate(tool_calls, 1)
        ])

    def _create_sources_dataframe(self, sources: List[Any]):
        import pandas as pd
        return pd.DataFrame([
            {
                '#': idx,
                'Source': getattr(source, 'source', source.get('source', 'Unknown')),
                'Score': f"{getattr(source, 'score', source.get('score', 'N/A')):.4f}"
            }
            for idx, source in enumerate(sources, 1)
        ])

    def _create_metadata_panel(self, response: Any) -> str:
        items = []
        if hasattr(response, 'model'):
            items.append(f"<div class='metadata-item'><span class='key'>Model:</span> <span class='value'>{response.model}</span></div>")
        return f"<div class='metadata-container'>{''.join(items)}</div>"

    def _render_simple_html(self, response: Any, **kwargs) -> str:
        """Format output as a simple HTML string."""
        html_parts = [self._get_html_header()]
        if content := self._get_content(response):
            html_parts.append(f"<div class='response-container'><h2>🤖 Response</h2><div class='content'>{self._markdown_to_html(content)}</div></div>")
        if kwargs.get('show_tools', False) and hasattr(response, 'tool_calls') and response.tool_calls:
            html_parts.append(f"<div class='section'><h3>🔧 Tool Calls</h3>{self._create_tools_html(response.tool_calls)}</div>")
        html_parts.append('</body></html>')
        return '\n'.join(html_parts)

    def _get_html_header(self) -> str:
        return '''
        <!DOCTYPE html><html><head><title>AI Response</title>
        <style>body { font-family: sans-serif; } .response-container { background: #f0f8ff; }</style>
        </head><body>
        '''

    def _markdown_to_html(self, content: str) -> str:
        try:
            import markdown
            return markdown.markdown(content, extensions=['fenced_code', 'tables', 'nl2br'])
        except ImportError:
            return f"<p>{content.replace(chr(10), '<br>')}</p>"

    def _create_tools_html(self, tool_calls: List[Any]) -> str:
        rows = "".join(
            f"<tr><td><strong>{idx}</strong></td><td>{getattr(tool, 'name', 'Unknown')}</td><td><span class='badge'>completed</span></td></tr>"
            for idx, tool in enumerate(tool_calls, 1)
        )
        return f"<table><thead><tr><th>#</th><th>Tool Name</th><th>Status</th></tr></thead><tbody>{rows}</tbody></table>"
