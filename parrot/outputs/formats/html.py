# parrot/outputs/formats/html.py
from typing import Any, List
import tempfile
import os
from . import register_renderer
from .base import BaseRenderer
from ...models.outputs import OutputMode

# Check Panel availability
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

    @staticmethod
    def render(response: Any, **kwargs) -> Any:
        """
        Render response as HTML.

        Args:
            response: AIMessage response object
            **kwargs: Additional rendering options
                - show_metadata: Show metadata section (default: True)
                - show_sources: Show sources section (default: True)
                - show_tools: Show tool calls section (default: False)
                - return_html: Return HTML string instead of Panel object (default: False)
                - use_panel: Force Panel usage if available (default: True)

        Returns:
            Panel dashboard object or HTML string
        """
        use_panel = kwargs.get('use_panel', True) and PANEL_AVAILABLE

        if use_panel:
            return HTMLRenderer._render_with_panel(response, **kwargs)
        else:
            return HTMLRenderer._render_simple_html(response, **kwargs)

    @staticmethod
    def _render_with_panel(response: Any, **kwargs) -> Any:
        """
        Format output as HTML using Panel for rich interactive dashboards.

        Args:
            response: AIMessage response object
            **kwargs: Additional options

        Returns:
            Panel dashboard or HTML string
        """
        show_metadata = kwargs.get('show_metadata', True)
        show_sources = kwargs.get('show_sources', True)
        show_tools = kwargs.get('show_tools', False)
        return_html = kwargs.get('return_html', False)

        components = []

        # Main response section
        content = HTMLRenderer._get_content(response)
        if content:
            response_md = PanelMarkdown(
                content,
                sizing_mode='stretch_width',
                styles={
                    'background': '#f0f8ff',
                    'padding': '20px',
                    'border-radius': '5px',
                    'box-shadow': '0 2px 4px rgba(0,0,0,0.1)'
                }
            )
            components.append(pn.pane.HTML("<h2>🤖 Response</h2>"))
            components.append(response_md)

        # Tool calls section
        if show_tools and hasattr(response, 'tool_calls') and response.tool_calls:
            tools_df = HTMLRenderer._create_tools_dataframe(response.tool_calls)
            components.append(pn.pane.HTML("<h3>🔧 Tool Calls</h3>"))
            components.append(
                pn.widgets.Tabulator(
                    tools_df,
                    sizing_mode='stretch_width',
                    theme='modern',
                    show_index=False
                )
            )

        # Metadata section
        if show_metadata:
            metadata_html = HTMLRenderer._create_metadata_panel(response)
            components.append(pn.pane.HTML("<h3>📊 Metadata</h3>"))
            components.append(pn.pane.HTML(metadata_html))

        # Sources section
        if show_sources and hasattr(response, 'source_documents') and response.source_documents:
            sources_df = HTMLRenderer._create_sources_dataframe(response.source_documents)
            components.append(pn.pane.HTML("<h3>📄 Sources</h3>"))
            components.append(
                pn.widgets.Tabulator(
                    sources_df,
                    sizing_mode='stretch_width',
                    theme='modern',
                    show_index=False
                )
            )

        # Create dashboard
        dashboard = Column(
            *components,
            sizing_mode='stretch_width',
            styles={'background': '#ffffff', 'padding': '20px'}
        )

        # Convert to HTML string if requested
        if return_html:
            return HTMLRenderer._panel_to_html(dashboard)

        # Return Panel object for interactive use
        return dashboard

    @staticmethod
    def _panel_to_html(dashboard: Any) -> str:
        """Convert Panel dashboard to HTML string."""
        # Create temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as tmp:
            tmp_path = tmp.name

        try:
            # Save Panel dashboard to HTML file
            dashboard.save(tmp_path, embed=True)

            # Read the HTML content
            with open(tmp_path, 'r', encoding='utf-8') as f:
                html_content = f.read()

            return html_content
        finally:
            # Clean up temporary file
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    @staticmethod
    def _create_tools_dataframe(tool_calls: List[Any]):
        """Create pandas DataFrame for tool calls."""
        try:
            import pandas as pd

            tools_data = []
            for idx, tool in enumerate(tool_calls, 1):
                name = getattr(tool, 'name', 'Unknown')
                status = getattr(tool, 'status', 'completed')
                tools_data.append({
                    '#': idx,
                    'Tool Name': name,
                    'Status': status
                })

            return pd.DataFrame(tools_data)
        except ImportError:
            # Fallback to dict if pandas not available
            return HTMLRenderer._create_tools_list(tool_calls)

    @staticmethod
    def _create_sources_dataframe(sources: List[Any]):
        """Create pandas DataFrame for sources."""
        try:
            import pandas as pd

            sources_data = []
            for idx, source in enumerate(sources, 1):
                # Handle both SourceDocument objects and dict-like sources
                if hasattr(source, 'source'):
                    source_name = source.source
                elif isinstance(source, dict):
                    source_name = source.get('source', 'Unknown')
                else:
                    source_name = str(source)

                if hasattr(source, 'score'):
                    score = source.score
                elif isinstance(source, dict):
                    score = source.get('score', 'N/A')
                else:
                    score = 'N/A'

                sources_data.append({
                    '#': idx,
                    'Source': source_name,
                    'Score': f"{score:.4f}" if isinstance(score, float) else str(score)
                })

            return pd.DataFrame(sources_data)
        except ImportError:
            return HTMLRenderer._create_sources_list(sources)

    @staticmethod
    def _create_metadata_panel(response: Any) -> str:
        """Create HTML for metadata with modern styling."""
        metadata_items = []

        if hasattr(response, 'model'):
            metadata_items.append(
                f"<div class='metadata-item'><span class='key'>Model:</span> <span class='value'>{response.model}</span></div>"
            )
        if hasattr(response, 'provider'):
            metadata_items.append(
                f"<div class='metadata-item'><span class='key'>Provider:</span> <span class='value'>{response.provider}</span></div>"
            )
        if hasattr(response, 'session_id') and response.session_id:
            session_short = str(response.session_id)[:16] + "..."
            metadata_items.append(
                f"<div class='metadata-item'><span class='key'>Session ID:</span> <span class='value'>{session_short}</span></div>"
            )
        if hasattr(response, 'turn_id') and response.turn_id:
            turn_short = str(response.turn_id)[:16] + "..."
            metadata_items.append(
                f"<div class='metadata-item'><span class='key'>Turn ID:</span> <span class='value'>{turn_short}</span></div>"
            )
        if hasattr(response, 'usage') and response.usage:
            usage = response.usage
            if hasattr(usage, 'total_tokens'):
                metadata_items.append(
                    f"<div class='metadata-item'><span class='key'>Total Tokens:</span> <span class='value'>{usage.total_tokens}</span></div>"
                )
            if hasattr(usage, 'prompt_tokens'):
                metadata_items.append(
                    f"<div class='metadata-item'><span class='key'>Prompt Tokens:</span> <span class='value'>{usage.prompt_tokens}</span></div>"
                )
            if hasattr(usage, 'completion_tokens'):
                metadata_items.append(
                    f"<div class='metadata-item'><span class='key'>Completion Tokens:</span> <span class='value'>{usage.completion_tokens}</span></div>"
                )
        if hasattr(response, 'response_time') and response.response_time:
            metadata_items.append(
                f"<div class='metadata-item'><span class='key'>Response Time:</span> <span class='value'>{response.response_time:.2f}s</span></div>"
            )

        html = f"""
        <div class='metadata-container'>
            <style>
                .metadata-container {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                    gap: 10px;
                    padding: 15px;
                    background: #f9f9f9;
                    border-radius: 5px;
                }}
                .metadata-item {{
                    padding: 8px;
                    background: white;
                    border-radius: 3px;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                }}
                .metadata-item .key {{
                    font-weight: bold;
                    color: #555;
                }}
                .metadata-item .value {{
                    color: #2c5aa0;
                }}
            </style>
            {''.join(metadata_items)}
        </div>
        """
        return html

    @staticmethod
    def _render_simple_html(response: Any, **kwargs) -> str:
        """
        Format output as HTML without Panel (manual construction).
        Faster and simpler for basic HTML export.

        Args:
            response: AIMessage response object
            **kwargs: Additional options

        Returns:
            HTML string
        """
        show_metadata = kwargs.get('show_metadata', True)
        show_sources = kwargs.get('show_sources', True)
        show_tools = kwargs.get('show_tools', False)

        html_parts = [HTMLRenderer._get_html_header()]

        # Main response
        if content := HTMLRenderer._get_content(response):
            html_content = HTMLRenderer._markdown_to_html(content)
            html_parts.append(f'''
            <div class="response-container">
                <h2>🤖 Response</h2>
                <div class="content">{html_content}</div>
            </div>
            ''')

        # Tool calls section
        if show_tools and hasattr(response, 'tool_calls') and response.tool_calls:
            tools_html = HTMLRenderer._create_tools_html(response.tool_calls)
            html_parts.append(f'''
            <div class="section">
                <h3>🔧 Tool Calls</h3>
                {tools_html}
            </div>
            ''')

        # Metadata section
        if show_metadata:
            metadata_html = HTMLRenderer._create_metadata_html(response)
            html_parts.append(f'''
            <div class="section">
                <h3>📊 Metadata</h3>
                {metadata_html}
            </div>
            ''')

        # Sources section
        if show_sources and hasattr(response, 'source_documents') and response.source_documents:
            sources_html = HTMLRenderer._create_sources_html(response.source_documents)
            html_parts.append(f'''
            <div class="section">
                <h3>📄 Sources</h3>
                {sources_html}
            </div>
            ''')

        html_parts.append('</body></html>')
        return '\n'.join(html_parts)

    @staticmethod
    def _get_html_header() -> str:
        """Get HTML header with CSS styling."""
        return '''
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>AI Response</title>
            <style>
                * {
                    box-sizing: border-box;
                    margin: 0;
                    padding: 0;
                }
                body {
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    max-width: 1200px;
                    margin: 0 auto;
                    padding: 20px;
                    background-color: #f5f5f5;
                }
                h2, h3 {
                    margin-bottom: 15px;
                    color: #2c3e50;
                }
                h2 { font-size: 1.8em; }
                h3 { font-size: 1.4em; }
                .response-container {
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    padding: 30px;
                    border-radius: 8px;
                    margin-bottom: 20px;
                    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
                }
                .response-container h2 {
                    color: white;
                    margin-top: 0;
                }
                .response-container .content {
                    background: white;
                    padding: 20px;
                    border-radius: 5px;
                    margin-top: 15px;
                }
                .section {
                    background-color: white;
                    padding: 20px;
                    border-radius: 8px;
                    margin-bottom: 20px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }
                .section h3 {
                    margin-top: 0;
                    padding-bottom: 10px;
                    border-bottom: 2px solid #667eea;
                }
                table {
                    width: 100%;
                    border-collapse: collapse;
                    margin-top: 15px;
                }
                th, td {
                    padding: 12px;
                    text-align: left;
                    border-bottom: 1px solid #e0e0e0;
                }
                th {
                    background-color: #667eea;
                    color: white;
                    font-weight: 600;
                    text-transform: uppercase;
                    font-size: 0.85em;
                    letter-spacing: 0.5px;
                }
                tr:hover {
                    background-color: #f8f9fa;
                }
                tr:nth-child(even) {
                    background-color: #f9f9f9;
                }
                code {
                    background-color: #f4f4f4;
                    padding: 2px 6px;
                    border-radius: 3px;
                    font-family: 'Courier New', monospace;
                    font-size: 0.9em;
                }
                pre {
                    background-color: #2d2d2d;
                    color: #f8f8f2;
                    padding: 15px;
                    border-radius: 5px;
                    overflow-x: auto;
                    margin: 10px 0;
                }
                pre code {
                    background-color: transparent;
                    color: inherit;
                    padding: 0;
                }
                blockquote {
                    border-left: 4px solid #667eea;
                    margin: 10px 0;
                    padding-left: 15px;
                    color: #666;
                    font-style: italic;
                }
                .badge {
                    display: inline-block;
                    padding: 4px 8px;
                    border-radius: 12px;
                    font-size: 0.85em;
                    font-weight: 600;
                }
                .badge-success {
                    background-color: #d4edda;
                    color: #155724;
                }
                .badge-info {
                    background-color: #d1ecf1;
                    color: #0c5460;
                }
            </style>
        </head>
        <body>
        '''

    @staticmethod
    def _markdown_to_html(content: str) -> str:
        """Convert markdown content to HTML."""
        try:
            import markdown
            return markdown.markdown(
                content,
                extensions=['fenced_code', 'tables', 'nl2br']
            )
        except ImportError:
            # Basic fallback: just convert newlines and wrap in paragraph
            paragraphs = content.split('\n\n')
            html_paragraphs = [f'<p>{p.replace(chr(10), "<br>")}</p>' for p in paragraphs if p.strip()]
            return '\n'.join(html_paragraphs)

    @staticmethod
    def _create_tools_html(tool_calls: List[Any]) -> str:
        """Create HTML table for tool calls."""
        html = "<table>"
        html += "<thead><tr><th>#</th><th>Tool Name</th><th>Status</th></tr></thead>"
        html += "<tbody>"

        for idx, tool in enumerate(tool_calls, 1):
            name = getattr(tool, 'name', 'Unknown')
            status = getattr(tool, 'status', 'completed')

            badge_class = 'badge-success' if status == 'completed' else 'badge-info'
            status_badge = f"<span class='badge {badge_class}'>{status}</span>"

            html += f"<tr>"
            html += f"<td><strong>{idx}</strong></td>"
            html += f"<td>{name}</td>"
            html += f"<td>{status_badge}</td>"
            html += "</tr>"

        html += "</tbody></table>"
        return html

    @staticmethod
    def _create_metadata_html(response: Any) -> str:
        """Create HTML table for metadata."""
        html = "<table>"
        html += "<thead><tr><th>Property</th><th>Value</th></tr></thead>"
        html += "<tbody>"

        if hasattr(response, 'model'):
            html += f"<tr><td><strong>Model</strong></td><td><code>{response.model}</code></td></tr>"
        if hasattr(response, 'provider'):
            html += f"<tr><td><strong>Provider</strong></td><td><code>{response.provider}</code></td></tr>"
        if hasattr(response, 'session_id') and response.session_id:
            session_id = str(response.session_id)[:16] + "..."
            html += f"<tr><td><strong>Session ID</strong></td><td><code>{session_id}</code></td></tr>"
        if hasattr(response, 'turn_id') and response.turn_id:
            turn_id = str(response.turn_id)[:16] + "..."
            html += f"<tr><td><strong>Turn ID</strong></td><td><code>{turn_id}</code></td></tr>"

        if hasattr(response, 'usage') and response.usage:
            usage = response.usage
            if hasattr(usage, 'total_tokens'):
                html += f"<tr><td><strong>Total Tokens</strong></td><td>{usage.total_tokens:,}</td></tr>"
            if hasattr(usage, 'prompt_tokens'):
                html += f"<tr><td><strong>Prompt Tokens</strong></td><td>{usage.prompt_tokens:,}</td></tr>"
            if hasattr(usage, 'completion_tokens'):
                html += f"<tr><td><strong>Completion Tokens</strong></td><td>{usage.completion_tokens:,}</td></tr>"

        if hasattr(response, 'response_time') and response.response_time:
            html += f"<tr><td><strong>Response Time</strong></td><td>{response.response_time:.3f}s</td></tr>"

        html += "</tbody></table>"
        return html

    @staticmethod
    def _create_sources_html(sources: List[Any]) -> str:
        """Create HTML table for sources."""
        html = "<table>"
        html += "<thead><tr><th>#</th><th>Source</th><th>Score</th></tr></thead>"
        html += "<tbody>"

        for idx, source in enumerate(sources, 1):
            # Handle both SourceDocument objects and dict-like sources
            if hasattr(source, 'source'):
                source_name = source.source
            elif isinstance(source, dict):
                source_name = source.get('source', 'Unknown')
            else:
                source_name = str(source)

            if hasattr(source, 'score'):
                score = source.score
            elif isinstance(source, dict):
                score = source.get('score', 'N/A')
            else:
                score = 'N/A'

            score_str = f"{score:.4f}" if isinstance(score, float) else str(score)

            html += f"<tr>"
            html += f"<td><strong>{idx}</strong></td>"
            html += f"<td>{source_name}</td>"
            html += f"<td><code>{score_str}</code></td>"
            html += "</tr>"

        html += "</tbody></table>"
        return html
