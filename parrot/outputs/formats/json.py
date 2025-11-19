from typing import Any, Tuple, Optional
from . import register_renderer
from .base import BaseRenderer
from ...models.outputs import OutputMode


@register_renderer(OutputMode.JSON)
class JSONRenderer(BaseRenderer):
    """
    Renderer for JSON output.
    Handles PandasAgentResponse, DataFrames, Pydantic models, and generic content.
    Adapts output format to Terminal (Rich), HTML (Pygments), and Jupyter (Widgets).
    """
    async def render(
        self,
        response: Any,
        environment: str = 'terminal',
        **kwargs,
    ) -> Tuple[Any, Optional[Any]]:
        """
        Render response as JSON.

        Returns:
            Tuple[str, Any]: (json_string, wrapped_content)
        """
        indent = kwargs.get('indent')
        # include_metadata = kwargs.get('include_metadata', False)
        # data = self._prepare_data(response, include_metadata)

        output_format = kwargs.get('output_format', environment)

        # 1. Extract Data
        data = self._extract_data(response)

        # 2. Serialize to content string
        json_string = self._serialize(data, indent=indent)

        # 3. Wrap content based on environment
        wrapped_output = self._wrap_output(json_string, data, output_format)

        return json_string, wrapped_output

    def _wrap_output(self, json_string: str, data: Any, environment: str) -> Any:
        """
        Wrap the JSON string into an environment-specific container.
        """
        if environment == 'terminal':
            try:
                from rich.panel import Panel
                from rich.syntax import Syntax
                from rich.json import JSON as RichJSON

                # Use Rich's native JSON rendering if possible for better formatting
                return Panel(
                    RichJSON(json_string),
                    title="JSON Output",
                    border_style="green"
                )
            except ImportError:
                return json_string

        elif environment in {'jupyter', 'notebook'}:
            try:
                # For Jupyter, we try to return a Widget or specialized display object
                # Method A: ipywidgets (Interactive)
                from ipywidgets import HTML

                # Create formatted HTML for the JSON
                from pygments import highlight
                from pygments.lexers import JsonLexer
                from pygments.formatters import HtmlFormatter

                formatter = HtmlFormatter(style='colorful', noclasses=True)
                highlighted_html = highlight(json_string, JsonLexer(), formatter)

                # Wrap in a widget
                widget = HTML(
                    value=f'<div style="max-height: 500px; overflow-y: auto; background-color: #f8f8f8; padding: 10px;">{highlighted_html}</div>'
                )
                return widget

            except ImportError:
                # Fallback to HTML representation if widgets not available
                return self._wrap_html(json_string)

        elif environment == 'html':
            return self._wrap_html(json_string)

        # Default / Text
        return json_string
