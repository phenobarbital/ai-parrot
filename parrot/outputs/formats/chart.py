from typing import Any, Optional
from abc import abstractmethod
import re
import html
import uuid
from pathlib import Path
from pygments import highlight
from pygments.lexers.python import PythonLexer
from pygments.formatters.html import HtmlFormatter

try:
    from ipywidgets import HTML as IPyHTML
    IPYWIDGETS_AVAILABLE = True
except ImportError:
    IPYWIDGETS_AVAILABLE = False

from .base import BaseRenderer


class BaseChart(BaseRenderer):
    """Base class for chart renderers - extends BaseRenderer with chart-specific methods"""

    @staticmethod
    def _extract_code(content: str) -> Optional[str]:
        """Extract Python code from markdown blocks."""
        pattern = r'```(?:python)?\n(.*?)```'
        matches = re.findall(pattern, content, re.DOTALL)
        return matches[0].strip() if matches else None

    @staticmethod
    def _highlight_code(code: str, theme: str = 'monokai') -> str:
        """Apply syntax highlighting to code."""
        try:
            formatter = HtmlFormatter(style=theme, noclasses=True, cssclass='code')
            return highlight(code, PythonLexer(), formatter)
        except ImportError:
            escaped = html.escape(code)
            return f'<pre class="code"><code>{escaped}</code></pre>'

    @staticmethod
    def _wrap_for_environment(content: Any, environment: str) -> Any:
        """Wrap content based on environment."""
        if isinstance(content, str) and environment in {'jupyter', 'ipython', 'colab'} and IPYWIDGETS_AVAILABLE:
                return IPyHTML(value=content)
        return content

    @staticmethod
    def _build_code_section(code: str, theme: str, icon: str = "📊") -> str:
        """Build collapsible code section."""
        highlighted = BaseChart._highlight_code(code, theme)
        return f'''
        <details class="ap-code-accordion">
            <summary class="ap-code-header">
                <span>{icon} View Code</span>
                <span class="ap-toggle-icon">▶</span>
            </summary>
            <div class="ap-code-content">
                {highlighted}
            </div>
        </details>
        '''

    @staticmethod
    def _render_error(error: str, code: str, theme: str) -> str:
        """Render error message with code."""
        highlighted = BaseChart._highlight_code(code, theme)
        return f'''
        {BaseChart._get_chart_styles()}
        <div class="ap-error-container">
            <h3>⚠️ Chart Generation Error</h3>
            <p class="ap-error-message">{error}</p>
            <details class="ap-code-accordion" open>
                <summary class="ap-code-header">Code with Error</summary>
                <div class="ap-code-content">{highlighted}</div>
            </details>
        </div>
        '''

    @staticmethod
    def _get_chart_styles() -> str:
        """CSS styles specific to charts."""
        return '''
        <style>
            .ap-chart-container {
                background: white;
                border-radius: 8px;
            }
            .ap-chart-wrapper {
                min-height: 400px;
                justify-content: center;
                align-items: center;
            }
            .ap-chart-guidance {
                background: #f0f4ff;
                border-left: 4px solid #667eea;
                padding: 16px 20px;
                border-radius: 6px;
            }
            .ap-chart-guidance h3 {
                font-size: 16px;
                font-weight: 600;
                color: #364152;
            }
            .ap-chart-guidance ol {
                margin: 0 0 0 20px;
                padding: 0;
            }
            .ap-chart-guidance li {
                margin-bottom: 6px;
                line-height: 1.4;
            }
            .ap-chart-note {
                background: #fffaf0;
                border-left: 4px solid #f6ad55;
                padding: 2px 4px;
                border-radius: 6px;
                margin-bottom: 2px;
                color: #744210;
                font-size: 14px;
            }
            .ap-code-accordion {
                margin-top: 20px;
                border: 1px solid #e0e0e0;
                border-radius: 6px;
                overflow: hidden;
            }
            .ap-code-header {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 12px 20px;
                cursor: pointer;
                display: flex;
                justify-content: space-between;
                align-items: center;
                font-weight: 600;
                user-select: none;
            }
            .ap-code-header:hover {
                background: linear-gradient(135deg, #5568d3 0%, #653a8e 100%);
            }
            .ap-toggle-icon {
                transition: transform 0.3s ease;
            }
            details[open] .ap-toggle-icon {
                transform: rotate(90deg);
            }
            .ap-code-content {
                background: #272822;
                padding: 15px;
                overflow-x: auto;
            }
            .ap-code-content pre {
                margin: 0;
                font-family: 'Monaco', 'Menlo', 'Consolas', monospace;
                font-size: 13px;
                line-height: 1.5;
            }
            .ap-error-container {
                background: #fff3cd;
                border: 1px solid #ffc107;
                border-radius: 8px;
                padding: 20px;
                margin: 20px 0;
            }
            .ap-error-message {
                color: #856404;
                font-weight: 500;
                margin: 10px 0;
            }
        </style>
        '''

    def _save_to_disk(self, chart_obj: Any, filename: str = None) -> str:
        """Save chart to disk for terminal viewing."""
        if not filename:
            filename = f"chart_{uuid.uuid4().hex[:8]}.png"

        # Ensure we have a directory
        # TODO: using a fixed path for now; ideally this should be configurable
        output_dir = Path("outputs/charts")
        output_dir.mkdir(parents=True, exist_ok=True)

        filepath = output_dir / filename
        chart_obj.savefig(str(filepath), bbox_inches='tight', dpi=100)
        return str(filepath)

    @staticmethod
    def _build_html_document(
        chart_content: str,
        code_section: str = '',
        title: str = 'AI-Parrot Chart',
        extra_head: str = '',
        mode: str = 'partial'
    ) -> str:
        """Build HTML document wrapper for charts."""
        if mode == 'partial':
            return f'''
            {BaseChart._get_chart_styles()}
            <div class="ap-chart-container">
                <div class="ap-chart-wrapper">
                    {chart_content}
                </div>
            </div>
            {code_section}
            '''

        elif mode == 'complete':
            # Generate unique ID for the container
            container_id = f"container-{uuid.uuid4().hex[:8]}"

            return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>

    {extra_head}

    <style>
        .ap-chart-wrapper {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
                         'Helvetica Neue', Arial, sans-serif;
            padding: 5px;
            line-height: 1.6;
            box-sizing: border-box;
        }}

        .ap-chart-wrapper * {{
            box-sizing: border-box;
        }}

        .ap-media-container {{
            max-width: 1200px;
            margin: 0 auto;
        }}

        .ap-chart-container {{
            border-radius: 12px;
            padding: 5px;
        }}

        .ap-chart-wrapper {{
            min-height: 400px;
            display: flex;
            justify-content: center;
            align-items: center;
        }}

        .ap-code-accordion {{
            margin-top: 20px;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            overflow: hidden;
            background: white;
        }}

        .ap-code-header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 14px 20px;
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-weight: 600;
            user-select: none;
            transition: all 0.3s ease;
        }}

        .ap-code-header:hover {{
            background: linear-gradient(135deg, #5568d3 0%, #653a8e 100%);
        }}

        .ap-toggle-icon {{
            transition: transform 0.3s ease;
            font-size: 12px;
        }}

        details[open] .ap-toggle-icon {{
            transform: rotate(90deg);
        }}

        .ap-code-content {{
            background: #272822;
            padding: 20px;
            overflow-x: auto;
        }}

        .ap-code-content pre {{
            margin: 0;
            font-family: 'Monaco', 'Menlo', 'Consolas', 'Courier New', monospace;
            font-size: 14px;
            line-height: 1.6;
        }}

        .ap-error-container {{
            background: #fff3cd;
            border: 2px solid #ffc107;
            border-radius: 8px;
            padding: 20px;
            margin: 20px 0;
        }}

        .ap-error-container h3 {{
            color: #856404;
            margin-bottom: 10px;
        }}

        .ap-error-message {{
            color: #856404;
            font-weight: 500;
            margin: 10px 0;
        }}

        @media (max-width: 768px) {{
            .ap-chart-wrapper {{
                padding: 1px;
            }}

            .ap-chart-container {{
                padding: 2px;
            }}
        }}
    </style>
</head>
<body>
    <div class="ap-chart-wrapper">
        <div class="ap-media-container" id="{container_id}">
            <div class="ap-chart-container">
                <div class="ap-chart-wrapper">
                    {chart_content}
                </div>
            </div>

            {code_section}
        </div>
    </div>

    <script>
        (function() {{
            function sendSize() {{
                const width = document.documentElement.scrollWidth || window.innerWidth;
                const height = document.documentElement.scrollHeight || window.innerHeight;

                parent.postMessage(
                    {{
                        type: "iframe_resize",
                        width: width,
                        height: height,
                        containerId: "{container_id}"
                    }},
                    "*"
                );
            }}

            // Send initial size
            sendSize();

            // Detect viewport resize
            window.addEventListener("resize", sendSize);

            // Detect content changes (e.g., height changes from DOM mutations)
            const observer = new ResizeObserver(sendSize);
            observer.observe(document.body);

            // Also observe the container for more precise tracking
            const container = document.getElementById("{container_id}");
            if (container) {{
                observer.observe(container);
            }}
        }})();
    </script>
</body>
</html>'''

        else:
            raise ValueError(f"Invalid mode: {mode}. Must be 'partial' or 'complete'")

    @abstractmethod
    def _render_chart_content(self, chart_obj: Any, **kwargs) -> str:
        """
        Render the chart-specific content (to be embedded in HTML).
        This should return just the chart div/script, not the full HTML document.

        Each chart renderer must implement this method to generate their
        specific chart content (Altair vega-embed, Plotly div, etc.)
        """
        pass

    def to_html(
        self,
        chart_obj: Any,
        mode: str = 'partial',
        include_code: bool = False,
        code: Optional[str] = None,
        theme: str = 'monokai',
        title: str = 'AI-Parrot Chart',
        **kwargs
    ) -> str:
        """
        Convert chart object to HTML.

        Args:
            chart_obj: Chart object to render
            mode: 'partial' for embeddable HTML or 'complete' for full document
            include_code: Whether to include code section
            code: Python code to display
            theme: Code highlighting theme
            title: Document title (for complete mode)
            **kwargs: Additional parameters passed to _render_chart_content

        Returns:
            HTML string based on mode
        """
        # Get chart-specific content from subclass
        chart_content = self._render_chart_content(chart_obj, **kwargs)

        # Build code section if requested
        code_section = ''
        if include_code and code:
            code_section = self._build_code_section(
                code, theme, kwargs.get('icon', '📊')
            )

        # Get extra head content if provided by subclass
        extra_head = kwargs.get('extra_head', '')

        # Build final HTML
        return self._build_html_document(
            chart_content=chart_content,
            code_section=code_section,
            title=title,
            extra_head=extra_head,
            mode=mode
        )
